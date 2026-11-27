"""HomeMonitor wire protocol: constants, JSON helpers and validators.

The protocol is deliberately dependency-free so the same file can run inside
the Windows/Debian agents and on a low-end Android controller.

Conventions
-----------
* All timestamps are Unix epoch seconds (float where useful).
* Throughput fields ending in ``_bps`` are bytes per second, not bits.
* Metric documents are validated on both sides. The controller stores its own
  receive timestamp, but agents still send ``ts`` for clock diagnostics.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

VERSION = "1.0.0"
SCHEMA_VERSION = 1
SERVICE_NAME = "homemonitor"
DEFAULT_HTTP_PORT = 8787
DISCOVERY_PORT = 45892
DISCOVERY_MAGIC = b"HOMEMONITOR_DISCOVER_V1"
MAX_BODY_BYTES = 512 * 1024
MAX_PROCESSES = 15
DEVICE_CATEGORIES = {"windows", "linux", "android", "router", "other"}

_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ProtocolError(ValueError):
    """Raised when an agent sends a malformed or unsafe document."""


def json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def json_loads(data: bytes | str) -> Any:
    """Parse JSON while rejecting NaN/Infinity, which json.loads accepts."""

    def _reject_constant(token: str) -> None:
        raise ProtocolError(f"invalid JSON constant: {token}")

    try:
        return json.loads(data, parse_constant=_reject_constant)
    except ProtocolError:
        raise
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError("invalid JSON body") from exc


def _as_dict(value: Any, field: str, required: bool = True) -> dict[str, Any]:
    if value is None:
        if required:
            raise ProtocolError(f"{field} is required")
        return {}
    if not isinstance(value, dict):
        raise ProtocolError(f"{field} must be an object")
    return value


def _text(
    value: Any,
    field: str,
    max_len: int = 120,
    *,
    required: bool = False,
    default: str | None = None,
) -> str | None:
    if value is None:
        if required:
            raise ProtocolError(f"{field} is required")
        return default
    if not isinstance(value, str):
        raise ProtocolError(f"{field} must be a string")
    cleaned = _CONTROL_RE.sub(" ", value).strip()
    if required and not cleaned:
        raise ProtocolError(f"{field} must not be empty")
    return cleaned[:max_len]


_UNKNOWN_SSIDS = {"<unknown ssid>", "<unknown>", "unknown", "0x", "--", "-"}


def _ssid(value: Any) -> str | None:
    """Normalize an SSID, dropping the placeholders Android returns without location access."""
    text = _text(value, "network.ssid", 64, default=None)
    if text is None:
        return None
    cleaned = text.strip().strip('"').strip()
    if not cleaned or cleaned.lower() in _UNKNOWN_SSIDS:
        return None
    return cleaned


def _num(
    value: Any,
    field: str,
    *,
    lo: float | None = None,
    hi: float | None = None,
    required: bool = False,
    default: float | None = None,
) -> float | None:
    if value is None:
        if required:
            raise ProtocolError(f"{field} is required")
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ProtocolError(f"{field} must be finite")
    if lo is not None and number < lo:
        raise ProtocolError(f"{field} must be >= {lo:g}")
    if hi is not None and number > hi:
        raise ProtocolError(f"{field} must be <= {hi:g}")
    return number


def _int(
    value: Any,
    field: str,
    *,
    lo: int | None = None,
    hi: int | None = None,
    required: bool = False,
    default: int | None = None,
) -> int | None:
    if value is None:
        if required:
            raise ProtocolError(f"{field} is required")
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"{field} must be an integer")
    if lo is not None and value < lo:
        raise ProtocolError(f"{field} must be >= {lo}")
    if hi is not None and value > hi:
        raise ProtocolError(f"{field} must be <= {hi}")
    return value


def _bool(value: Any, field: str, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ProtocolError(f"{field} must be a boolean")
    return value


def validate_device_info(raw: Any) -> dict[str, Any]:
    info = _as_dict(raw, "device")
    device_id = _text(info.get("id"), "device.id", 64, required=True)
    assert device_id is not None
    if not _DEVICE_ID_RE.match(device_id):
        raise ProtocolError("device.id must be 8-64 letters, digits, '-' or '_'")

    category = _text(info.get("category"), "device.category", 20, default="other") or "other"
    category = category.lower()
    if category not in DEVICE_CATEGORIES:
        category = "other"

    return {
        "id": device_id,
        "name": _text(info.get("name"), "device.name", 80, required=True),
        "hostname": _text(info.get("hostname"), "device.hostname", 80, default="") or "",
        "os": _text(info.get("os"), "device.os", 80, default="Unknown") or "Unknown",
        "os_version": _text(info.get("os_version"), "device.os_version", 120, default="") or "",
        "arch": _text(info.get("arch"), "device.arch", 40, default="") or "",
        "model": _text(info.get("model"), "device.model", 120, default="") or "",
        "category": category,
        "agent_version": _text(info.get("agent_version"), "device.agent_version", 40, default="") or "",
    }


def validate_registration(payload: Any) -> tuple[str, dict[str, Any]]:
    body = _as_dict(payload, "body")
    pairing_code = _text(body.get("pairing_code"), "pairing_code", 32, required=True)
    assert pairing_code is not None
    return pairing_code, validate_device_info(body.get("device"))


def validate_heartbeat(payload: Any) -> dict[str, Any]:
    body = _as_dict(payload, "body", required=False)
    network = _as_dict(body.get("network"), "network", required=False)
    network_info: dict[str, Any] | None = None
    if network:
        network_info = {
            "ssid": _ssid(network.get("ssid")),
            "ip": _text(network.get("ip"), "network.ip", 45, default=None),
            "gateway": _text(network.get("gateway"), "network.gateway", 45, default=None),
            "dns": _text(network.get("dns"), "network.dns", 100, default=None),
            "interface": _text(network.get("interface"), "network.interface", 32, default=None),
            "signal_pct": _num(network.get("signal_pct"), "network.signal_pct", lo=0, hi=100),
            "link_mbps": _num(network.get("link_mbps"), "network.link_mbps", lo=0, hi=100000),
        }
        network_info = {
            key: value for key, value in network_info.items() if value not in (None, "")
        }
        if not network_info:
            network_info = None
    return {
        "uptime_s": _num(body.get("uptime_s"), "uptime_s", lo=0, hi=10**10),
        "battery_pct": _num(body.get("battery_pct"), "battery_pct", lo=0, hi=100),
        "status": _text(body.get("status"), "status", 32, default="ok") or "ok",
        "network": network_info,
    }


def validate_metrics(payload: Any) -> dict[str, Any]:
    """Validate and normalize a metrics document.

    Returns a compact dict with a stable shape. Missing optional sections are
    ``None`` so storage code can insert NULLs without branching.
    """
    body = _as_dict(payload, "body")
    cpu = _as_dict(body.get("cpu"), "cpu")
    memory = _as_dict(body.get("memory"), "memory")
    gpu = _as_dict(body.get("gpu"), "gpu", required=False)
    disk_io = _as_dict(body.get("disk_io"), "disk_io", required=False)
    network = _as_dict(body.get("network"), "network", required=False)
    battery = _as_dict(body.get("battery"), "battery", required=False)
    system = _as_dict(body.get("system"), "system", required=False)

    load = cpu.get("load")
    load_values: list[float] = []
    if isinstance(load, (list, tuple)):
        for i, item in enumerate(load[:3]):
            value = _num(item, f"cpu.load[{i}]", lo=0, hi=100000)
            if value is not None:
                load_values.append(value)

    disks: list[dict[str, Any]] = []
    raw_disks = body.get("disks")
    if isinstance(raw_disks, list):
        for i, item in enumerate(raw_disks[:16]):
            disk = _as_dict(item, f"disks[{i}]")
            disks.append(
                {
                    "mount": _text(disk.get("mount"), f"disks[{i}].mount", 100, default="?") or "?",
                    "percent": _num(disk.get("percent"), f"disks[{i}].percent", lo=0, hi=100),
                    "used_gb": _num(disk.get("used_gb"), f"disks[{i}].used_gb", lo=0, hi=10**9),
                    "total_gb": _num(disk.get("total_gb"), f"disks[{i}].total_gb", lo=0, hi=10**9),
                }
            )

    processes: list[dict[str, Any]] = []
    raw_processes = body.get("processes")
    if isinstance(raw_processes, list):
        for i, item in enumerate(raw_processes[:MAX_PROCESSES]):
            proc = _as_dict(item, f"processes[{i}]")
            processes.append(
                {
                    "pid": _int(proc.get("pid"), f"processes[{i}].pid", lo=0, hi=2**31 - 1),
                    "name": _text(proc.get("name"), f"processes[{i}].name", 120, default="?") or "?",
                    "cpu": _num(proc.get("cpu"), f"processes[{i}].cpu", lo=0, hi=100000),
                    "mem_mb": _num(proc.get("mem_mb"), f"processes[{i}].mem_mb", lo=0, hi=10**9),
                }
            )

    return {
        "schema_version": _int(body.get("schema_version"), "schema_version", lo=0, hi=1000),
        "ts": _num(body.get("ts"), "ts", lo=0),
        "cpu_pct": _num(cpu.get("percent"), "cpu.percent", lo=0, hi=100),
        "cpu_cores": _int(cpu.get("cores"), "cpu.cores", lo=1, hi=1024),
        "cpu_freq_mhz": _num(cpu.get("freq_mhz"), "cpu.freq_mhz", lo=0, hi=100000),
        "cpu_temp_c": _num(cpu.get("temp_c"), "cpu.temp_c", lo=-50, hi=250),
        "load1": load_values[0] if load_values else None,
        "load5": load_values[1] if len(load_values) > 1 else None,
        "load15": load_values[2] if len(load_values) > 2 else None,
        "ram_pct": _num(memory.get("percent"), "memory.percent", lo=0, hi=100, required=True),
        "ram_used_mb": _num(memory.get("used_mb"), "memory.used_mb", lo=0, hi=10**9),
        "ram_total_mb": _num(memory.get("total_mb"), "memory.total_mb", lo=0, hi=10**9),
        "swap_pct": _num(memory.get("swap_percent"), "memory.swap_percent", lo=0, hi=100),
        "gpu_pct": _num(gpu.get("percent"), "gpu.percent", lo=0, hi=100),
        "gpu_temp_c": _num(gpu.get("temp_c"), "gpu.temp_c", lo=-50, hi=250),
        "gpu_name": _text(gpu.get("name"), "gpu.name", 120, default=None),
        "gpu_mem_used_mb": _num(gpu.get("mem_used_mb"), "gpu.mem_used_mb", lo=0, hi=10**9),
        "gpu_mem_total_mb": _num(gpu.get("mem_total_mb"), "gpu.mem_total_mb", lo=0, hi=10**9),
        "disk_pct": _num(body.get("disk_pct"), "disk_pct", lo=0, hi=100),
        "disk_read_bps": _num(disk_io.get("read_bps"), "disk_io.read_bps", lo=0, hi=10**15),
        "disk_write_bps": _num(disk_io.get("write_bps"), "disk_io.write_bps", lo=0, hi=10**15),
        "net_up_bps": _num(network.get("up_bps"), "network.up_bps", lo=0, hi=10**15),
        "net_down_bps": _num(network.get("down_bps"), "network.down_bps", lo=0, hi=10**15),
        "net_rx_bytes": _num(network.get("rx_bytes"), "network.rx_bytes", lo=0, hi=10**18),
        "net_tx_bytes": _num(network.get("tx_bytes"), "network.tx_bytes", lo=0, hi=10**18),
        "battery_pct": _num(battery.get("percent"), "battery.percent", lo=0, hi=100),
        "battery_charging": _bool(battery.get("plugged"), "battery.plugged"),
        "uptime_s": _num(system.get("uptime_s"), "system.uptime_s", lo=0, hi=10**10),
        "processes": processes,
        "disks": disks,
    }
