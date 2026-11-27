#!/usr/bin/env python3
"""HomeMonitor agent for Android/Termux devices.

The desktop agent depends on psutil and Python 3.10+. This variant is a single
standard-library file for old Termux installs (Python 3.8+) and Android boxes
such as the Android device. It reads the same HTTP API and sends the metrics that
Android exposes through /proc, /sys and getprop.

Examples
--------
Pair and run:
    python android_agent.py --controller http://192.0.2.10:8787 \
        --pairing-code ABCD-1234 --name "Android device"

Run with the saved configuration:
    python android_agent.py

Print one metrics sample without networking:
    python android_agent.py --once
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VERSION = "1.0.0"
AGENT_VERSION = "1.0.0-android"
SCHEMA_VERSION = 1
DISCOVERY_PORT = 45892
DISCOVERY_MAGIC = b"HOMEMONITOR_DISCOVER_V1"
DEFAULT_HEARTBEAT = 5.0
DEFAULT_METRICS = 5.0
PENDING_LOG_INTERVAL = 60.0

_NET_CACHE: Dict[str, Any] = {}
_NET_CACHE_AT = 0.0

logger = logging.getLogger("homemonitor.android")


class FatalAgentError(Exception):
    pass


class ControllerUnavailable(Exception):
    pass


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        message: str,
        code: str = "error",
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.retry_after = retry_after


def _home() -> Path:
    return Path(os.environ.get("HOME") or "/data/data/com.termux/files/home")


def default_config_path() -> Path:
    return _home() / ".config" / "homemonitor" / "android_agent.json"


def _getprop(key: str, default: str = "") -> str:
    try:
        output = subprocess.check_output(
            ["getprop", key], stderr=subprocess.DEVNULL, timeout=5
        )
        value = output.decode("utf-8", "replace").strip()
        return value or default
    except Exception:
        return default


def _read_text(path: str, limit: int = 65536) -> str:
    with open(path, "r") as handle:
        return handle.read(limit)


def _read_cpu_times() -> Tuple[int, int]:
    parts = _read_text("/proc/stat", 4096).splitlines()[0].split()
    values = [int(item) for item in parts[1:]]
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return total, idle


class CpuSampler:
    def __init__(self) -> None:
        self.available = False
        self.prev_total = 0
        self.prev_idle = 0
        try:
            self.prev_total, self.prev_idle = _read_cpu_times()
            self.available = True
        except Exception:
            # Android 13 / OxygenOS can deny /proc/stat to normal apps.
            logger.info("CPU times unavailable; CPU percentage will be omitted")

    def percent(self) -> Optional[float]:
        if not self.available:
            return None
        try:
            total, idle = _read_cpu_times()
        except Exception:
            self.available = False
            return None
        delta_total = total - self.prev_total
        delta_idle = idle - self.prev_idle
        self.prev_total, self.prev_idle = total, idle
        if delta_total <= 0:
            return None
        value = 100.0 * (delta_total - delta_idle) / delta_total
        return max(0.0, min(100.0, value))


def _read_memory() -> Dict[str, Any]:
    info: Dict[str, int] = {}
    for line in _read_text("/proc/meminfo").splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.split()
        if parts:
            try:
                info[key] = int(parts[0])
            except ValueError:
                pass
    total_kb = info.get("MemTotal", 0)
    if total_kb <= 0:
        return {"percent": 0.0}
    if "MemAvailable" in info:
        available_kb = info["MemAvailable"]
    else:
        available_kb = (
            info.get("MemFree", 0)
            + info.get("Buffers", 0)
            + info.get("Cached", 0)
        )
    used_kb = max(0, total_kb - available_kb)
    result: Dict[str, Any] = {
        "percent": round(100.0 * used_kb / total_kb, 1),
        "used_mb": round(used_kb / 1024.0, 1),
        "total_mb": round(total_kb / 1024.0, 1),
    }
    swap_total = info.get("SwapTotal", 0)
    if swap_total > 0:
        swap_used = max(0, swap_total - info.get("SwapFree", 0))
        result["swap_percent"] = round(100.0 * swap_used / swap_total, 1)
    return result


def _read_load() -> List[float]:
    parts = _read_text("/proc/loadavg", 512).split()
    return [float(item) for item in parts[:3]]


def _read_uptime() -> float:
    return float(_read_text("/proc/uptime", 512).split()[0])


def _safe_uptime() -> float:
    try:
        return _read_uptime()
    except Exception:
        # /proc/uptime is denied on Android 13; CLOCK_MONOTONIC is boot-relative.
        return time.monotonic()


def _read_network_totals() -> Tuple[int, int]:
    rx = 0
    tx = 0
    lines = _read_text("/proc/net/dev").splitlines()[2:]
    for line in lines:
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        name = name.strip()
        if name == "lo" or name.startswith("p2p"):
            continue
        fields = rest.split()
        if len(fields) >= 9:
            rx += int(fields[0])
            tx += int(fields[8])
    return rx, tx


class NetworkSampler:
    def __init__(self) -> None:
        self.available = False
        self.prev_rx = 0
        self.prev_tx = 0
        self.prev_time = time.monotonic()
        try:
            self.prev_rx, self.prev_tx = _read_network_totals()
            self.available = True
        except Exception:
            # Android 13 / OxygenOS can deny /proc/net/dev to normal apps.
            logger.info("Network totals unavailable; throughput will be omitted")

    def sample(self) -> Dict[str, Any]:
        if not self.available:
            return {}
        try:
            rx, tx = _read_network_totals()
        except Exception:
            self.available = False
            return {}
        now = time.monotonic()
        elapsed = max(0.1, now - self.prev_time)
        down = max(0.0, (rx - self.prev_rx) / elapsed)
        up = max(0.0, (tx - self.prev_tx) / elapsed)
        self.prev_rx, self.prev_tx = rx, tx
        self.prev_time = now
        return {
            "rx_bytes": rx,
            "tx_bytes": tx,
            "down_bps": round(down, 1),
            "up_bps": round(up, 1),
        }


def _read_disk() -> Dict[str, Any]:
    try:
        stat = os.statvfs("/data")
    except Exception:
        return {}
    total = stat.f_blocks * stat.f_frsize
    free = stat.f_bavail * stat.f_frsize
    if total <= 0:
        return {}
    used = max(0, total - free)
    return {
        "mount": "/data",
        "percent": round(100.0 * used / total, 1),
        "used_gb": round(used / (1024.0 ** 3), 2),
        "total_gb": round(total / (1024.0 ** 3), 2),
    }


def _termux_command(name: str) -> str:
    prefix = os.environ.get("PREFIX") or "/data/data/com.termux/files/usr"
    candidate = Path(prefix) / "bin" / name
    return str(candidate) if candidate.exists() else name


_BATTERY_CACHE: Dict[str, Any] = {}
_BATTERY_CACHE_AT = 0.0
BATTERY_CACHE_SECONDS = 30.0


def _read_battery() -> Dict[str, Any]:
    # Android TV / Fire TV kernels expose a dummy 100% "battery" node. There is
    # no battery to report, so skip these devices instead of showing fake 100%.
    if "tv" in (_getprop("ro.build.characteristics") or "").lower():
        return {}
    global _BATTERY_CACHE, _BATTERY_CACHE_AT
    now = time.monotonic()
    if _BATTERY_CACHE and now - _BATTERY_CACHE_AT < BATTERY_CACHE_SECONDS:
        return dict(_BATTERY_CACHE)
    result = _read_battery_uncached()
    if result:
        _BATTERY_CACHE = result
        _BATTERY_CACHE_AT = now
    return dict(result)


def _read_battery_uncached() -> Dict[str, Any]:
    # Termux:API can report the battery even when SELinux hides sysfs from apps.
    try:
        raw = subprocess.check_output(
            [_termux_command("termux-battery-status")],
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).decode("utf-8", "replace")
        info = json.loads(raw)
        percent = int(info.get("percentage"))
        plugged = str(info.get("plugged", "")).upper()
        return {
            "percent": max(0, min(100, percent)),
            "plugged": plugged not in ("", "UNPLUGGED"),
        }
    except Exception:
        pass
    for base in (
        "/sys/class/power_supply/battery",
        "/sys/class/power_supply/max170xx_battery",
        "/sys/class/power_supply/bms",
    ):
        try:
            percent = int(_read_text(base + "/capacity", 32).strip())
        except Exception:
            continue
        status = ""
        try:
            status = _read_text(base + "/status", 32).strip().lower()
        except Exception:
            pass
        return {
            "percent": max(0, min(100, percent)),
            "plugged": status in ("charging", "full"),
        }
    return {}


def _read_network() -> Dict[str, Any]:
    """Best-effort Wi-Fi details from Termux:API, ``ip``, ``getprop`` and /proc."""
    global _NET_CACHE, _NET_CACHE_AT
    now = time.monotonic()
    if _NET_CACHE and now - _NET_CACHE_AT < 60.0:
        return dict(_NET_CACHE)

    iface = (_getprop("wifi.interface", "wlan0") or "wlan0").strip()
    info: Dict[str, Any] = {}

    termux: Dict[str, Any] = {}
    try:
        raw = subprocess.check_output(
            [_termux_command("termux-wifi-connectioninfo")],
            stderr=subprocess.DEVNULL,
            timeout=4,
        ).decode("utf-8", "replace")
        payload = json.loads(raw) if raw.strip() else {}
        if isinstance(payload, dict):
            termux = payload
    except Exception:
        termux = {}

    ssid = termux.get("SSID") or termux.get("ssid")
    if isinstance(ssid, str):
        ssid = ssid.strip().strip('"').strip() or None
        if ssid and ssid.lower() in {"<unknown ssid>", "<unknown>", "unknown", "0x", "--", "-"}:
            # Android redacts the SSID unless the Termux:API app has location access.
            ssid = None
    else:
        ssid = None

    try:
        addresses = subprocess.check_output(
            ["ip", "-4", "addr", "show"], stderr=subprocess.DEVNULL, timeout=5
        ).decode("utf-8", "replace")
    except Exception:
        addresses = ""

    current = ""
    found: List[Tuple[str, str]] = []
    for line in addresses.splitlines():
        match = re.match(r"^\d+:\s+([^:@\s]+)", line)
        if match:
            current = match.group(1)
            continue
        inet = re.search(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/", line)
        if inet and current and not current.startswith("lo"):
            found.append((current, inet.group(1)))
    address = next((value for name, value in found if name == iface), None)
    if address is None and found:
        address = found[0][1]
    address = address or termux.get("ip")
    if address:
        info["ip"] = address

    gateway: Optional[str] = None
    route_iface: Optional[str] = None
    for args in (["ip", "route", "show", "table", "all"], ["ip", "route"]):
        try:
            routes = subprocess.check_output(
                args, stderr=subprocess.DEVNULL, timeout=5
            ).decode("utf-8", "replace")
        except Exception:
            continue
        for line in routes.splitlines():
            parts = line.split()
            if not parts or parts[0] != "default":
                continue
            if "via" in parts:
                gateway = parts[parts.index("via") + 1]
            if "dev" in parts:
                route_iface = parts[parts.index("dev") + 1]
            break
        if gateway:
            break
    # Android routing tables sometimes use an alias such as "if30" for the
    # same radio that ``ip addr`` and getprop call "wlan0". Keep the friendly
    # name when we already have it.
    iface = iface or route_iface or ""

    def prop(*keys: str) -> Optional[str]:
        for key in keys:
            value = _getprop(key).strip().strip('"')
            if value and value.lower() not in {"<unknown>", "unknown", "0.0.0.0"}:
                return value
        return None

    ssid = ssid or prop("dhcp.%s.ssid" % iface, "dhcp.wlan0.ssid", "wifi.ssid")
    gateway = prop("dhcp.%s.gateway" % iface, "dhcp.wlan0.gateway") or gateway
    dns = prop("dhcp.%s.dns1" % iface, "dhcp.wlan0.dns1")

    signal: Optional[float] = None
    rssi = termux.get("rssi", termux.get("signal_strength"))
    try:
        if rssi is not None:
            signal = (float(rssi) + 100.0) * 2.0
    except (TypeError, ValueError):
        signal = None
    if signal is None:
        try:
            for line in _read_text("/proc/net/wireless").splitlines():
                if ":" not in line or line.lstrip().startswith("Inter-"):
                    continue
                name, rest = line.split(":", 1)
                fields = rest.split()
                if len(fields) < 3:
                    continue
                try:
                    quality = float(fields[1].rstrip("."))
                    level = float(fields[2].rstrip("."))
                except ValueError:
                    continue
                percent = (level + 100.0) * 2.0 if -100 <= level <= 0 else None
                if percent is None and quality > 0:
                    percent = quality / 70.0 * 100.0 if quality <= 70 else quality
                if percent is None:
                    continue
                if name.strip() == iface:
                    signal = percent
                    break
                if signal is None:
                    signal = percent
        except Exception:
            pass

    link = termux.get("link_speed_mbps") or termux.get("tx_link_speed_mbps")
    try:
        link_value = float(link) if link is not None else None
    except (TypeError, ValueError):
        link_value = None

    if iface:
        info["interface"] = iface
    if ssid:
        info["ssid"] = ssid
    if gateway:
        info["gateway"] = gateway
    if dns:
        info["dns"] = dns
    if signal is not None:
        info["signal_pct"] = round(max(0.0, min(100.0, signal)), 1)
    if link_value and link_value > 0:
        info["link_mbps"] = link_value
    _NET_CACHE = info
    _NET_CACHE_AT = now
    return info


def _read_temperature() -> Optional[float]:
    best: Optional[float] = None
    for path in sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp")):
        try:
            value = float(_read_text(path, 64).strip())
        except Exception:
            continue
        if value > 1000:
            value /= 1000.0
        if -50.0 <= value <= 250.0 and (best is None or value > best):
            best = value
    return round(best, 1) if best is not None else None


def _read_frequency() -> Optional[float]:
    values: List[float] = []
    cores = os.cpu_count() or 4
    for index in range(cores):
        path = "/sys/devices/system/cpu/cpu%d/cpufreq/scaling_cur_freq" % index
        try:
            values.append(float(_read_text(path, 64).strip()) / 1000.0)
        except Exception:
            continue
    if not values:
        return None
    return round(sum(values) / len(values), 0)


def _device_info(name: str) -> Dict[str, Any]:
    model = _getprop("ro.product.model", "Android device")
    manufacturer = _getprop("ro.product.manufacturer", "")
    os_name = "Fire OS" if model.startswith("AFT") or manufacturer == "Amazon" else "Android"
    hostname = _getprop("net.hostname", "") or model
    return {
        "name": name or model,
        "hostname": hostname,
        "os": os_name,
        "os_version": _getprop("ro.build.version.release", "unknown"),
        "arch": _getprop("ro.product.cpu.abi", ""),
        "model": model,
        "category": "android",
        "agent_version": AGENT_VERSION,
    }


def collect_metrics(cpu: CpuSampler, network: NetworkSampler) -> Dict[str, Any]:
    cpu_payload: Dict[str, Any] = {
        "cores": os.cpu_count() or 1,
    }
    cpu_percent = cpu.percent()
    if cpu_percent is not None:
        cpu_payload["percent"] = round(cpu_percent, 1)
    try:
        cpu_payload["load"] = _read_load()
    except Exception:
        pass
    temperature = _read_temperature()
    if temperature is not None:
        cpu_payload["temp_c"] = temperature
    frequency = _read_frequency()
    if frequency is not None:
        cpu_payload["freq_mhz"] = frequency

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ts": round(time.time(), 3),
        "cpu": cpu_payload,
        "memory": _read_memory(),
        "network": network.sample(),
    }
    disk = _read_disk()
    if disk:
        payload["disks"] = [disk]
        payload["disk_pct"] = disk["percent"]
    battery = _read_battery()
    if battery:
        payload["battery"] = battery
        payload["battery_pct"] = battery["percent"]
    payload["system"] = {"uptime_s": round(_safe_uptime(), 1)}
    return payload


def _normalise_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if value and "://" not in value:
        value = "http://" + value
    return value


def _clamp_interval(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(2.0, min(60.0, number))


def discover_controllers(timeout: float = 3.0) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    seen = set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.5)
        sock.sendto(DISCOVERY_MAGIC, ("255.255.255.255", DISCOVERY_PORT))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, peer = sock.recvfrom(2048)
            except socket.timeout:
                continue
            try:
                item = json.loads(data.decode("utf-8", "replace"))
            except ValueError:
                continue
            if not isinstance(item, dict):
                continue
            url = _normalise_url(str(item.get("base_url") or ""))
            if not url or url in seen:
                continue
            seen.add(url)
            item["base_url"] = url
            item["peer"] = peer[0]
            found.append(item)
    finally:
        sock.close()
    return found


class Client:
    def __init__(self, base_url: str, timeout: float = 4.0) -> None:
        self.base_url = _normalise_url(base_url)
        self.timeout = timeout
        self.token = ""

    def request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        auth: bool = True,
    ) -> Dict[str, Any]:
        body = None
        if payload is not None:
            body = json.dumps(
                payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path, data=body, method=method
        )
        request.add_header("Accept", "application/json")
        request.add_header("X-Agent-Version", AGENT_VERSION)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        if auth:
            request.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read()
                message = "HTTP %d" % exc.code
                code = "http_error"
                try:
                    parsed = json.loads(raw.decode("utf-8")) if raw else {}
                    if isinstance(parsed, dict):
                        message = str(parsed.get("error") or message)
                        code = str(parsed.get("code") or code)
                except (ValueError, UnicodeDecodeError):
                    pass
                retry_after = None
                try:
                    header = exc.headers.get("Retry-After") if exc.headers else None
                    if header:
                        retry_after = float(header)
                except (TypeError, ValueError):
                    pass
            finally:
                exc.close()
            raise ApiError(exc.code, message, code, retry_after)
        except urllib.error.URLError as exc:
            raise ControllerUnavailable(str(getattr(exc, "reason", exc)))
        except OSError as exc:
            raise ControllerUnavailable(str(exc))
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ControllerUnavailable("invalid controller response") from exc
        if not isinstance(parsed, dict):
            raise ControllerUnavailable("invalid controller response")
        return parsed

    def register(self, pairing_code: str, device: Dict[str, Any]) -> Dict[str, Any]:
        return self.request(
            "POST",
            "/api/v1/register",
            {"pairing_code": pairing_code, "device": device},
            auth=False,
        )

    def heartbeat(self, device_id: str, uptime: float) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"uptime_s": round(uptime, 1), "status": "ok"}
        network = _read_network()
        if network:
            payload["network"] = network
        return self.request(
            "POST",
            "/api/v1/devices/%s/heartbeat" % device_id,
            payload,
        )

    def metrics(self, device_id: str, payload: Dict[str, Any]) -> None:
        self.request(
            "POST", "/api/v1/devices/%s/metrics" % device_id, payload
        )


def _load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise FatalAgentError("Could not read config %s: %s" % (path, exc))
    if not isinstance(data, dict):
        raise FatalAgentError("Config %s is not an object" % path)
    return data


def _save_config(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(str(temp), str(path))


def _setup_logging(path: Path, verbose: bool) -> None:
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(path), maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        pass


def _run(
    config: Dict[str, Any],
    config_path: Path,
    controller_url: str,
    pairing_code: str,
    name: str,
    cpu: CpuSampler,
    network: NetworkSampler,
    stop: threading.Event,
) -> int:
    client = Client(controller_url)
    client.token = str(config.get("token") or "")
    device_id = str(config.get("device_id") or "")
    if not device_id:
        device_id = str(uuid.uuid4())
        config["device_id"] = device_id
    config["controller_url"] = controller_url
    if name:
        config["name"] = name
    device = _device_info(name or str(config.get("name") or ""))
    device["id"] = device_id

    approved = False
    next_heartbeat = 0.0
    next_metrics = 0.0
    heartbeat_interval = DEFAULT_HEARTBEAT
    metrics_interval = DEFAULT_METRICS
    last_pending_log = 0.0
    token = client.token

    def save() -> None:
        config["controller_url"] = controller_url
        config["token"] = token
        config["device_id"] = device_id
        try:
            _save_config(config_path, config)
        except OSError as exc:
            logger.warning("Could not save config: %s", exc)

    while not stop.is_set():
        try:
            if not token:
                if not pairing_code:
                    raise FatalAgentError(
                        "No device token. Run once with --pairing-code CODE."
                    )
                logger.info("Registering '%s' with %s", device["name"], controller_url)
                response = client.register(pairing_code, device)
                token = str(response.get("token") or "")
                if not token:
                    raise FatalAgentError("Controller did not return a device token")
                device_id = str(response.get("device_id") or device_id)
                device["id"] = device_id
                client.token = token
                approved = bool(response.get("approved", False))
                heartbeat_interval = _clamp_interval(
                    response.get("heartbeat_interval"), DEFAULT_HEARTBEAT
                )
                metrics_interval = _clamp_interval(
                    response.get("metrics_interval"), DEFAULT_METRICS
                )
                logger.info("Registered as device %s", device_id)
                if approved:
                    logger.info("Device already approved; starting metrics upload")
                else:
                    logger.info(
                        "Waiting for approval in the dashboard before metrics are accepted"
                    )
                next_heartbeat = 0.0
                next_metrics = 0.0
                save()

            now = time.monotonic()
            if now >= next_heartbeat:
                was_approved = approved
                response = client.heartbeat(device_id, _safe_uptime())
                approved = bool(response.get("approved", True))
                heartbeat_interval = _clamp_interval(
                    response.get("heartbeat_interval"), heartbeat_interval
                )
                metrics_interval = _clamp_interval(
                    response.get("metrics_interval"), metrics_interval
                )
                next_heartbeat = time.monotonic() + heartbeat_interval
                if approved and not was_approved:
                    logger.info("Device approved; starting metrics upload")
                    next_metrics = 0.0
                elif not approved and time.monotonic() - last_pending_log > PENDING_LOG_INTERVAL:
                    logger.info(
                        "Awaiting approval - open the dashboard and approve '%s' (%s)",
                        device["name"],
                        device_id,
                    )
                    last_pending_log = time.monotonic()

            if approved and time.monotonic() >= next_metrics:
                payload = collect_metrics(cpu, network)
                try:
                    client.metrics(device_id, payload)
                except ApiError as exc:
                    if exc.status == 403 and exc.code == "pending_approval":
                        approved = False
                        logger.info("Device is still awaiting approval")
                    else:
                        raise
                else:
                    next_metrics = time.monotonic() + metrics_interval

            due = next_heartbeat
            if approved:
                due = min(due, next_metrics)
            wait = max(0.2, min(10.0, due - time.monotonic()))
            stop.wait(wait)

        except FatalAgentError:
            raise
        except ApiError as exc:
            if exc.status in (401, 404):
                logger.error(
                    "Controller rejected this device token (%s). Re-pairing is required.",
                    exc.message,
                )
                token = ""
                client.token = ""
                save()
                if not pairing_code:
                    raise FatalAgentError(
                        "Re-pair required: run the agent with --pairing-code CODE."
                    )
                stop.wait(1.0)
            elif exc.status == 403 and exc.code == "revoked":
                raise FatalAgentError("This device was revoked on the controller.")
            elif exc.status == 403 and exc.code == "pairing_denied":
                raise FatalAgentError("The pairing code was rejected by the controller.")
            elif exc.status == 429:
                wait = exc.retry_after or 30.0
                logger.warning("Controller rate limit; retrying in %.0fs", wait)
                stop.wait(wait)
            else:
                logger.warning("Controller error: %s (%s)", exc.message, exc.code)
                stop.wait(5.0)
        except ControllerUnavailable as exc:
            # A short back-off keeps the heartbeat inside the controller's
            # offline window when a Wi-Fi blip or a doze freeze drops one request.
            logger.warning("Controller unavailable: %s. Retrying in 3s.", exc)
            stop.wait(3.0)
        except Exception:
            logger.exception("Unexpected agent error; retrying in 5s")
            stop.wait(5.0)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="android_agent.py", description="HomeMonitor agent for Android/Termux"
    )
    parser.add_argument("--config", default=str(default_config_path()))
    parser.add_argument("--controller", help="controller URL, e.g. http://192.0.2.10:8787")
    parser.add_argument(
        "--pairing-code",
        default=os.environ.get("HOMEMONITOR_PAIRING_CODE", ""),
        help="pairing code shown on the controller (env: HOMEMONITOR_PAIRING_CODE)",
    )
    parser.add_argument("--name", help="friendly name shown in the dashboard")
    parser.add_argument("--discover", action="store_true", help="find controllers and exit")
    parser.add_argument("--once", action="store_true", help="print one metrics sample and exit")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser()
    try:
        config = _load_config(config_path)
    except FatalAgentError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    cpu = CpuSampler()
    network = NetworkSampler()
    if args.once:
        # The first CPU sample only establishes a baseline; wait so the printed
        # value reflects a real interval instead of 0%.
        time.sleep(1.0)
        print(
            json.dumps(
                collect_metrics(cpu, network), indent=2, ensure_ascii=False, allow_nan=False
            )
        )
        return 0

    if args.discover:
        found = discover_controllers()
        if not found:
            print("No HomeMonitor controller answered on UDP %d." % DISCOVERY_PORT)
            return 1
        for item in found:
            print(
                "%s%s"
                % (
                    item["base_url"],
                    " (%s)" % item["hostname"] if item.get("hostname") else "",
                )
            )
        return 0

    controller_url = _normalise_url(
        args.controller or str(config.get("controller_url") or "")
    )
    if not controller_url:
        print("No controller configured; searching the LAN...")
        found = discover_controllers()
        if not found:
            print(
                "No controller found. Pass --controller http://IP:8787.",
                file=sys.stderr,
            )
            return 2
        controller_url = found[0]["base_url"]
        print("Using controller %s" % controller_url)

    name = args.name or str(config.get("name") or "")
    pairing_code = (args.pairing_code or "").strip()
    if not config.get("token") and not pairing_code:
        print(
            "This agent is not paired yet.\n"
            "  1. Start the controller and note its pairing code.\n"
            "  2. Run: python android_agent.py --controller %s --pairing-code CODE"
            % controller_url,
            file=sys.stderr,
        )
        return 2

    _setup_logging(config_path.parent / "android_agent.log", args.verbose)
    logger.info("HomeMonitor Android agent %s starting as '%s'", VERSION, name or "Android device")
    logger.info("Controller: %s", controller_url)

    stop = threading.Event()

    def handle_signal(signum: int, frame: Any) -> None:
        logger.info("Signal %s received; stopping", signum)
        stop.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        return _run(
            config, config_path, controller_url, pairing_code, name, cpu, network, stop
        )
    except FatalAgentError as exc:
        logger.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
