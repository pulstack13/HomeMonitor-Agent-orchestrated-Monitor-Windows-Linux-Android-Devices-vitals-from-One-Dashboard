"""Cross-platform system metric collection for HomeMonitor agents.

Windows and Debian share one collector. Optional extras:
  * NVIDIA GPU metrics via ``pynvml`` (pip install nvidia-ml-py)
  * Windows CPU temperature via ``wmi`` + LibreHardwareMonitor (optional)
"""

from __future__ import annotations

import logging
import os
import platform
import socket
import time
from pathlib import Path
from typing import Any

import psutil

from common.netinfo import collect_network
from common.protocol import SCHEMA_VERSION, VERSION

logger = logging.getLogger("homemonitor.agent.collector")

_PREFERRED_TEMP_GROUPS = (
    "coretemp",
    "k10temp",
    "zenpower",
    "cpu_thermal",
    "soc_thermal",
    "cpu-thermal",
    "thermal",
)


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


class GpuReader:
    """NVIDIA metrics through NVML; silently disabled when unavailable."""

    def __init__(self) -> None:
        self.enabled = False
        self._nvml = None
        self._handle = None
        self.name = ""
        try:
            import pynvml

            pynvml.nvmlInit()
            if pynvml.nvmlDeviceGetCount() > 0:
                self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                raw_name = pynvml.nvmlDeviceGetName(self._handle)
                self.name = raw_name.decode("utf-8", "replace") if isinstance(raw_name, bytes) else str(raw_name)
                self._nvml = pynvml
                self.enabled = True
        except Exception:
            self.enabled = False
            self._nvml = None
            self._handle = None

    def read(self) -> dict[str, Any] | None:
        if not self.enabled or self._nvml is None or self._handle is None:
            return None
        nvml = self._nvml
        data: dict[str, Any] = {"name": self.name}
        try:
            utilization = nvml.nvmlDeviceGetUtilizationRates(self._handle)
            data["percent"] = float(utilization.gpu)
        except Exception:
            pass
        try:
            temperature = nvml.nvmlDeviceGetTemperature(self._handle, nvml.NVML_TEMPERATURE_GPU)
            data["temp_c"] = float(temperature)
        except Exception:
            pass
        try:
            memory = nvml.nvmlDeviceGetMemoryInfo(self._handle)
            data["mem_used_mb"] = round(memory.used / 1048576, 1)
            data["mem_total_mb"] = round(memory.total / 1048576, 1)
        except Exception:
            pass
        return data if len(data) > 1 else None


class WindowsTempReader:
    """Optional Windows CPU temperature support.

    Requires the ``wmi`` package and usually LibreHardwareMonitor or an
    exposed ACPI thermal zone. Any failure permanently disables the reader.
    """

    def __init__(self) -> None:
        self._sensor_client = None
        self._acpi_client = None
        self._last_read = 0.0
        self._cached: float | None = None
        self._tried = False

    def _initialize(self) -> None:
        if self._tried:
            return
        self._tried = True
        if os.name != "nt":
            return
        try:
            import wmi

            try:
                client = wmi.WMI(namespace=r"root\LibreHardwareMonitor")
                if client.Sensor():
                    self._sensor_client = client
            except Exception:
                pass
            try:
                self._acpi_client = wmi.WMI(namespace=r"root\wmi")
            except Exception:
                pass
        except Exception:
            self._sensor_client = None
            self._acpi_client = None

    def read(self) -> float | None:
        now = time.monotonic()
        if now - self._last_read < 25:
            return self._cached
        self._last_read = now
        self._initialize()
        value: float | None = None
        if self._sensor_client is not None:
            try:
                temperatures = [
                    float(sensor.Value)
                    for sensor in self._sensor_client.Sensor()
                    if getattr(sensor, "SensorType", "") == "Temperature"
                    and "cpu" in (getattr(sensor, "Name", "") or "").lower()
                    and sensor.Value is not None
                ]
                if temperatures:
                    value = max(temperatures)
            except Exception:
                self._sensor_client = None
        if value is None and self._acpi_client is not None:
            try:
                zones = self._acpi_client.MSAcpi_ThermalZoneTemperature()
                readings = []
                for zone in zones:
                    raw = _safe_float(getattr(zone, "CurrentTemperature", None))
                    if raw is not None and raw > 0:
                        readings.append(raw / 10.0 - 273.15)
                if readings:
                    value = max(readings)
            except Exception:
                self._acpi_client = None
        self._cached = round(value, 1) if value is not None and -20 < value < 200 else None
        return self._cached


def _linux_cpu_temperature() -> float | None:
    try:
        groups = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None
    if not groups:
        return None
    for name in _PREFERRED_TEMP_GROUPS:
        entries = groups.get(name)
        if entries:
            values = [
                entry.current
                for entry in entries
                if entry.current is not None and -20 < entry.current < 200
            ]
            if values:
                return round(max(values), 1)
    filtered: list[float] = []
    for entries in groups.values():
        for entry in entries:
            label = (entry.label or "").lower()
            if entry.current is not None and any(k in label for k in ("cpu", "soc", "package")):
                if -20 < entry.current < 200:
                    filtered.append(entry.current)
    return round(max(filtered), 1) if filtered else None


def _windows_os_info() -> tuple[str, str]:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        ) as key:
            product = str(winreg.QueryValueEx(key, "ProductName")[0])
            display = str(winreg.QueryValueEx(key, "DisplayVersion")[0])
            build = str(winreg.QueryValueEx(key, "CurrentBuildNumber")[0])
            try:
                if int(build) >= 22000 and product.startswith("Windows 10"):
                    product = product.replace("Windows 10", "Windows 11", 1)
            except ValueError:
                pass
            return product, f"{display} (build {build})"
    except Exception:
        return platform.system(), platform.version()


def _windows_model() -> str:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS"
        ) as key:
            manufacturer = str(winreg.QueryValueEx(key, "SystemManufacturer")[0]).strip()
            product = str(winreg.QueryValueEx(key, "SystemProductName")[0]).strip()
            if product and product.lower() not in {"system product name", "to be filled by o.e.m."}:
                return f"{manufacturer} {product}".strip()
    except Exception:
        pass
    return ""


def _linux_model() -> str:
    device_tree = _read_text("/proc/device-tree/model").replace("\x00", "")
    if device_tree:
        return device_tree
    product = _read_text("/sys/class/dmi/id/product_name")
    vendor = _read_text("/sys/class/dmi/id/sys_vendor")
    if product and product.lower() not in {"system product name", "to be filled by o.e.m."}:
        return f"{vendor} {product}".strip()
    return ""


def _linux_os_name() -> tuple[str, str]:
    pretty = ""
    for line in _read_text("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            pretty = line.split("=", 1)[1].strip().strip('"')
            break
    return pretty or "Linux", f"kernel {platform.release()}"


class Collector:
    def __init__(self) -> None:
        self.cpu_count = psutil.cpu_count(logical=True) or 1
        self.gpu = GpuReader()
        self.windows_temps = WindowsTempReader()
        self._prev_net = psutil.net_io_counters()
        self._prev_disk = psutil.disk_io_counters()
        self._prev_mono = time.monotonic()
        self._prev_process_cpu: dict[int, float] = {}
        self._prev_process_mono = self._prev_mono
        self._system = self._describe_system()
        psutil.cpu_percent(interval=None)
        self._prime_processes()

    # ------------------------------------------------------------------ identity
    def _describe_system(self) -> dict[str, str]:
        os_name = platform.system()
        os_version = platform.version()
        model = ""
        if os.name == "nt":
            os_name, os_version = _windows_os_info()
            model = _windows_model()
        elif platform.system() == "Linux":
            os_name, os_version = _linux_os_name()
            model = _linux_model()

        if os.name == "nt":
            category = "windows"
        elif os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
            category = "android"
        elif platform.system() == "Linux":
            category = "linux"
        else:
            category = "other"

        return {
            "hostname": socket.gethostname(),
            "os": os_name,
            "os_version": os_version,
            "arch": platform.machine() or "unknown",
            "model": model,
            "category": category,
        }

    def describe(self, name: str, device_id: str) -> dict[str, Any]:
        return {
            "id": device_id,
            "name": name,
            "hostname": self._system["hostname"],
            "os": self._system["os"],
            "os_version": self._system["os_version"],
            "arch": self._system["arch"],
            "model": self._system["model"],
            "category": self._system["category"],
            "agent_version": VERSION,
        }

    # ------------------------------------------------------------------ sampling
    def _prime_processes(self) -> None:
        now = time.monotonic()
        for process in psutil.process_iter(["pid", "cpu_times"]):
            try:
                times = process.info["cpu_times"]
                self._prev_process_cpu[process.info["pid"]] = times.user + times.system
            except (psutil.Error, TypeError):
                continue
        self._prev_process_mono = now

    def _processes(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        elapsed = max(0.2, now - self._prev_process_mono)
        readings: list[dict[str, Any]] = []
        current: dict[int, float] = {}
        for process in psutil.process_iter(["pid", "name", "cpu_times", "memory_info"]):
            try:
                info = process.info
                pid = int(info["pid"])
                if pid == 0 or (info["name"] or "").lower() == "system idle process":
                    continue
                times = info["cpu_times"]
                total_cpu = float(times.user + times.system)
                current[pid] = total_cpu
                previous = self._prev_process_cpu.get(pid)
                cpu = 0.0
                if previous is not None:
                    cpu = max(0.0, total_cpu - previous) / (elapsed * self.cpu_count) * 100.0
                memory = info["memory_info"]
                readings.append(
                    {
                        "pid": pid,
                        "name": info["name"] or "?",
                        "cpu": round(min(cpu, 100.0), 1),
                        "mem_mb": round(memory.rss / 1048576, 1) if memory else 0.0,
                    }
                )
            except (psutil.Error, KeyError, TypeError):
                continue
        self._prev_process_cpu = current
        self._prev_process_mono = now
        readings.sort(key=lambda item: (item["cpu"], item["mem_mb"]), reverse=True)
        return readings[:10]

    def _disks(self) -> list[dict[str, Any]]:
        disks: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            partitions = psutil.disk_partitions(all=False)
        except (psutil.Error, OSError):
            return disks
        for partition in partitions[:12]:
            mount = partition.mountpoint
            if mount in seen or "cdrom" in (partition.opts or ""):
                continue
            seen.add(mount)
            try:
                usage = psutil.disk_usage(mount)
            except (psutil.Error, OSError):
                continue
            total_gb = usage.total / 1073741824
            if total_gb <= 0:
                continue
            disks.append(
                {
                    "mount": mount,
                    "percent": round(usage.percent, 1),
                    "used_gb": round(usage.used / 1073741824, 2),
                    "total_gb": round(total_gb, 2),
                }
            )
            if len(disks) >= 8:
                break
        return disks

    def _rates(self) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
        now = time.monotonic()
        elapsed = max(0.25, now - self._prev_mono)
        network = psutil.net_io_counters()
        disk = psutil.disk_io_counters()
        previous_net = self._prev_net
        previous_disk = self._prev_disk
        self._prev_net = network
        self._prev_disk = disk
        self._prev_mono = now

        net_rates = {
            "up_bps": 0.0,
            "down_bps": 0.0,
            "rx_bytes": float(network.bytes_recv) if network else 0.0,
            "tx_bytes": float(network.bytes_sent) if network else 0.0,
        }
        if network is not None and previous_net is not None:
            net_rates["down_bps"] = round(
                max(0, network.bytes_recv - previous_net.bytes_recv) / elapsed, 1
            )
            net_rates["up_bps"] = round(
                max(0, network.bytes_sent - previous_net.bytes_sent) / elapsed, 1
            )
        disk_rates = {"read_bps": 0.0, "write_bps": 0.0}
        if disk is not None and previous_disk is not None:
            disk_rates["read_bps"] = round(
                max(0, disk.read_bytes - previous_disk.read_bytes) / elapsed, 1
            )
            disk_rates["write_bps"] = round(
                max(0, disk.write_bytes - previous_disk.write_bytes) / elapsed, 1
            )
        return net_rates, disk_rates, {}

    def _cpu_temperature(self) -> float | None:
        if os.name == "nt":
            return self.windows_temps.read()
        if platform.system() == "Linux":
            return _linux_cpu_temperature()
        return None

    def quick_status(self) -> dict[str, Any]:
        battery = None
        try:
            battery = psutil.sensors_battery()
        except (AttributeError, OSError):
            pass
        try:
            uptime = max(0.0, time.time() - psutil.boot_time())
        except (psutil.Error, OSError):
            uptime = None
        status: dict[str, Any] = {"uptime_s": uptime}
        if battery is not None:
            status["battery_pct"] = round(float(battery.percent), 1)
            status["battery_charging"] = bool(battery.power_plugged)
        network = collect_network()
        if network:
            status["network"] = network
        return status

    def collect(self) -> dict[str, Any]:
        cpu_pct = psutil.cpu_percent(interval=None)
        cpu_freq = None
        try:
            frequency = psutil.cpu_freq()
            if frequency is not None:
                cpu_freq = round(frequency.current, 1) if frequency.current else None
        except (psutil.Error, OSError):
            pass
        try:
            load = list(psutil.getloadavg())
        except (AttributeError, OSError):
            load = []
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disks = self._disks()
        net_rates, disk_rates, _ = self._rates()
        battery_data: dict[str, Any] = {}
        try:
            battery = psutil.sensors_battery()
        except (AttributeError, OSError):
            battery = None
        if battery is not None:
            battery_data = {
                "percent": round(float(battery.percent), 1),
                "plugged": bool(battery.power_plugged),
            }
        gpu_data = self.gpu.read()
        process_data = self._processes()
        disk_pct = max((disk["percent"] for disk in disks), default=None)
        try:
            uptime = max(0.0, time.time() - psutil.boot_time())
        except (psutil.Error, OSError):
            uptime = None

        metrics: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "ts": time.time(),
            "cpu": {
                "percent": round(cpu_pct, 1),
                "cores": self.cpu_count,
                "freq_mhz": cpu_freq,
                "temp_c": self._cpu_temperature(),
                "load": [round(value, 2) for value in load],
            },
            "memory": {
                "percent": round(memory.percent, 1),
                "used_mb": round((memory.total - memory.available) / 1048576, 1),
                "total_mb": round(memory.total / 1048576, 1),
                "swap_percent": round(swap.percent, 1),
            },
            "disks": disks,
            "disk_io": disk_rates,
            "disk_pct": disk_pct,
            "network": net_rates,
            "battery": battery_data,
            "system": {
                "hostname": self._system["hostname"],
                "os": self._system["os"],
                "os_version": self._system["os_version"],
                "arch": self._system["arch"],
                "model": self._system["model"],
                "uptime_s": uptime,
            },
            "processes": process_data,
        }
        if gpu_data:
            metrics["gpu"] = gpu_data
        return metrics
