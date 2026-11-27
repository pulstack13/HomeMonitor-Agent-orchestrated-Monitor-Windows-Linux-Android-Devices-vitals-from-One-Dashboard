"""Best-effort Wi-Fi and link information, using only the standard library.

The controller and the desktop agents both call :func:`collect_network`. Every
probe is optional: a missing command, permission denial or unusual ROM simply
produces fewer fields instead of an error. Results are cached briefly because
starting ``ip``/``netsh`` on every heartbeat is wasteful.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

CACHE_SECONDS = 15.0

_lock = threading.Lock()
_cache: dict[str, Any] = {}
_cache_at = 0.0

_IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_HEX_RE = re.compile(r"^[0-9A-Fa-f]{8}$")


def _run(args: list[str], timeout: float = 3.0) -> str:
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    try:
        return subprocess.check_output(
            args,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=flags,
        ).decode("utf-8", "replace")
    except Exception:
        return ""


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"unknown", "<unknown>", "null", "none", "0.0.0.0"}:
        return None
    return text


def _clamp_pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(100.0, value)), 1)


def _dns_from_resolv_conf() -> str | None:
    try:
        for line in Path("/etc/resolv.conf").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("nameserver"):
                value = line.split(None, 1)[-1].strip()
                if value:
                    return value
    except OSError:
        pass
    return None


def _is_android() -> bool:
    prefix = os.environ.get("PREFIX", "")
    return bool(os.environ.get("ANDROID_ROOT")) or "com.termux" in prefix


def parse_ip_addr(text: str, prefer: str | None = None) -> tuple[str | None, str | None]:
    """Return (interface, IPv4) from ``ip -4 addr show`` output."""
    current = None
    found: list[tuple[str, str]] = []
    for line in text.splitlines():
        match = re.match(r"^\d+:\s+([^:@\s]+)", line)
        if match:
            current = match.group(1)
            continue
        inet = re.search(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/", line)
        if inet and current:
            found.append((current, inet.group(1)))
    for iface, address in found:
        if prefer and iface == prefer:
            return iface, address
    for iface, address in found:
        if iface != "lo" and not iface.startswith("lo"):
            return iface, address
    return (found[0] if found else (None, None))


def parse_default_route(text: str) -> tuple[str | None, str | None]:
    """Return (gateway, interface) from ``ip route`` output."""
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0] != "default":
            continue
        gateway = None
        iface = None
        if "via" in parts:
            index = parts.index("via")
            if index + 1 < len(parts):
                gateway = parts[index + 1]
        if "dev" in parts:
            index = parts.index("dev")
            if index + 1 < len(parts):
                iface = parts[index + 1]
        return gateway, iface
    return None, None


def parse_wireless(text: str, prefer: str | None = None, prefer_level: bool = False) -> float | None:
    """Parse link quality from /proc/net/wireless into a percentage.

    Some Android drivers report an unusable ``quality`` (for example 14/70 at
    -50 dBm), so callers can ask for the RSSI-derived value instead.
    """
    candidates: list[tuple[str, float | None, float | None]] = []
    for line in text.splitlines():
        if ":" not in line or line.lstrip().startswith("Inter-"):
            continue
        iface, rest = line.split(":", 1)
        fields = rest.split()
        if len(fields) < 3:
            continue
        try:
            quality = float(fields[1].rstrip("."))
            level = float(fields[2].rstrip("."))
        except ValueError:
            continue
        from_quality: float | None = None
        if quality > 0:
            from_quality = quality / 70.0 * 100.0 if quality <= 70 else quality
        from_level: float | None = None
        if -100 <= level <= 0:
            from_level = (level + 100.0) * 2.0
        percent = from_level if prefer_level and from_level is not None else from_quality
        if percent is None:
            percent = from_level
        candidates.append((iface.strip(), _clamp_pct(percent), _clamp_pct(from_level)))
    if prefer:
        for iface, percent, _ in candidates:
            if iface == prefer:
                return percent
    return candidates[0][1] if candidates else None


def parse_netsh(text: str) -> dict[str, Any]:
    """Parse ``netsh wlan show interfaces`` (English output).

    Some Windows builds keep an SSID, signal and rate on a disconnected
    adapter, so Wi-Fi details are only returned while ``State`` is connected.
    """
    data: dict[str, Any] = {}
    state = ""
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "name" and "interface" not in data:
            data["interface"] = value
        elif key == "state":
            state = value.lower()
        elif key == "ssid" and "ssid" not in data:
            data["ssid"] = value
        elif key == "signal":
            match = re.search(r"(\d+)", value)
            if match:
                data["signal_pct"] = _clamp_pct(float(match.group(1)))
        elif key == "receive rate (mbps)":
            try:
                data["link_mbps"] = float(value)
            except ValueError:
                pass
        elif key == "transmit rate (mbps)":
            try:
                data["link_mbps"] = max(float(data.get("link_mbps") or 0), float(value))
            except ValueError:
                pass
    if state and state != "connected":
        for key in ("ssid", "signal_pct", "link_mbps"):
            data.pop(key, None)
    if state:
        data["state"] = state
    return {key: value for key, value in data.items() if value not in (None, "")}


def _adapter_label(name: str) -> str:
    label = name.strip()
    for prefix in (
        "Wireless LAN adapter ",
        "Ethernet adapter ",
        "Unknown adapter ",
        "Tunnel adapter ",
    ):
        if label.lower().startswith(prefix.lower()):
            label = label[len(prefix):]
            break
    return label.strip()


def parse_ipconfig(text: str, prefer: str | None = None) -> dict[str, Any]:
    """Parse IPv4/gateway/DNS from English ``ipconfig`` output.

    ``prefer`` is only honoured when that adapter has an address; a
    disconnected Wi-Fi section must not hide the adapter that is actually
    carrying traffic (for example a USB-tethered phone). ``interface`` carries
    the adapter label so callers can tell which section was chosen.
    """
    sections: list[tuple[str, list[str]]] = []
    current_name = ""
    current: list[str] = []
    for line in text.splitlines():
        if line and not line.startswith((" ", "\t")) and line.rstrip().endswith(":"):
            if current:
                sections.append((current_name, current))
            current_name = line.strip().rstrip(":")
            current = []
        else:
            current.append(line)
    if current:
        sections.append((current_name, current))

    def parse_section(lines: list[str]) -> dict[str, Any]:
        data: dict[str, Any] = {}
        dns: list[str] = []
        current_key = ""
        for line in lines:
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip().lower()
                value = value.strip()
                current_key = key
            elif line.strip():
                key, value = current_key, line.strip()
            else:
                continue
            if key.startswith("ipv4 address"):
                match = _IPV4_RE.search(value)
                if match:
                    data["ip"] = match.group(1)
            elif key.startswith("default gateway"):
                match = _IPV4_RE.search(value)
                if match:
                    data["gateway"] = match.group(1)
            elif key.startswith("dns servers"):
                dns.extend(_IPV4_RE.findall(value))
        if dns:
            data["dns"] = dns[0]
        return data

    parsed = [(name, parse_section(lines)) for name, lines in sections]
    matching = [
        (name, data)
        for name, data in parsed
        if prefer and prefer.lower() in name.lower()
    ]

    chosen: dict[str, Any] = {}
    chosen_name = ""
    for name, data in matching:
        if data.get("ip") and data.get("gateway"):
            chosen_name, chosen = name, data
            break
    if not chosen:
        for name, data in matching:
            if data.get("ip"):
                chosen_name, chosen = name, data
                break
    if not chosen:
        for name, data in parsed:
            if data.get("ip") and data.get("gateway"):
                chosen_name, chosen = name, data
                break
    if not chosen:
        for name, data in parsed:
            if data.get("ip"):
                chosen_name, chosen = name, data
                break
    if not chosen and matching:
        chosen_name, chosen = matching[0]
    if not chosen and parsed:
        chosen_name, chosen = parsed[0]
    if chosen_name:
        chosen["interface"] = _adapter_label(chosen_name)
    return {key: value for key, value in chosen.items() if value not in (None, "")}


def parse_nmcli(text: str) -> dict[str, Any]:
    """Parse ``nmcli -t -f ACTIVE,SSID,SIGNAL dev wifi`` output."""
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        active, ssid, signal = parts[0], ":".join(parts[1:-1]), parts[-1]
        if active.strip().lower() in {"yes", "*"} and ssid.strip():
            data: dict[str, Any] = {"ssid": ssid.strip()}
            try:
                data["signal_pct"] = _clamp_pct(float(signal.strip()))
            except ValueError:
                pass
            return data
    return {}


def parse_proc_route(text: str, prefer: str | None = None) -> tuple[str | None, str | None]:
    """Return (gateway, interface) from /proc/net/route."""
    rows: list[tuple[str, str]] = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3 or parts[1] != "00000000":
            continue
        if not _HEX_RE.match(parts[2]):
            continue
        raw = bytes.fromhex(parts[2])
        gateway = socket.inet_ntoa(bytes(reversed(raw)))
        rows.append((parts[0], gateway))
    if prefer:
        for iface, gateway in rows:
            if iface == prefer:
                return gateway, iface
    return (rows[0][1], rows[0][0]) if rows else (None, None)


def _termux_wifi() -> dict[str, Any]:
    """Return SSID/RSSI via Termux:API when the helper is installed."""
    prefix = os.environ.get("PREFIX") or "/data/data/com.termux/files/usr"
    candidate = Path(prefix) / "bin" / "termux-wifi-connectioninfo"
    command = str(candidate) if candidate.exists() else shutil.which("termux-wifi-connectioninfo")
    if not command:
        return {}
    try:
        raw = _run([command], timeout=4.0)
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    ssid = _clean(payload.get("SSID") or payload.get("ssid"))
    rssi = payload.get("rssi", payload.get("signal_strength"))
    signal = None
    try:
        if rssi is not None:
            signal = _clamp_pct((float(rssi) + 100.0) * 2.0)
    except (TypeError, ValueError):
        pass
    data: dict[str, Any] = {
        "ssid": ssid,
        "ip": _clean(payload.get("ip")),
        "signal_pct": signal,
    }
    for key in ("link_speed_mbps", "tx_link_speed_mbps", "rx_link_speed_mbps"):
        try:
            value = float(payload.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            data["link_mbps"] = value
            break
    return {key: value for key, value in data.items() if value not in (None, "")}


def _android() -> dict[str, Any]:
    termux = _termux_wifi()
    props: dict[str, str] = {}
    for line in _run(["getprop"]).splitlines():
        match = re.match(r"\[([^\]]+)\]:\s*\[([^\]]*)\]", line)
        if match:
            props[match.group(1)] = match.group(2)
    iface = _clean(props.get("wifi.interface")) or "wlan0"

    ip_text = _run(["ip", "-4", "addr", "show"])
    found_iface, address = parse_ip_addr(ip_text, iface)
    iface = found_iface or iface
    gateway, route_iface = parse_default_route(_run(["ip", "route", "show", "table", "all"]))
    if not gateway:
        gateway, route_iface = parse_default_route(_run(["ip", "route"]))
    # Android often reports the radio under an alias such as "if30" in route
    # tables while ``ip addr`` and getprop use "wlan0". Keep the friendly name.
    iface = iface or route_iface

    ssid = termux.get("ssid") or _clean(props.get(f"dhcp.{iface}.ssid"))
    gateway = _clean(props.get(f"dhcp.{iface}.gateway")) or gateway
    dns = _clean(props.get(f"dhcp.{iface}.dns1")) or _clean(props.get(f"dhcp.{iface}.dns2"))

    signal = termux.get("signal_pct")
    if signal is None:
        try:
            signal = parse_wireless(
                Path("/proc/net/wireless").read_text(errors="replace"),
                iface,
                prefer_level=True,
            )
        except OSError:
            pass

    data: dict[str, Any] = {
        "interface": iface,
        "ip": address or termux.get("ip"),
        "gateway": gateway,
        "dns": dns,
        "ssid": ssid,
        "signal_pct": signal,
        "link_mbps": termux.get("link_mbps"),
    }
    return {key: value for key, value in data.items() if value is not None}


def _linux() -> dict[str, Any]:
    gateway, iface = parse_default_route(_run(["ip", "route"]))
    if not iface:
        gateway, iface = parse_proc_route(
            Path("/proc/net/route").read_text(errors="replace") if Path("/proc/net/route").exists() else ""
        )
    found_iface, address = parse_ip_addr(_run(["ip", "-4", "addr", "show"]), iface)
    iface = iface or found_iface

    ssid = None
    signal = None
    nmcli = _run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"])
    parsed = parse_nmcli(nmcli)
    if parsed:
        ssid = parsed.get("ssid")
        signal = parsed.get("signal_pct")
    if not ssid:
        ssid = _clean(_run(["iwgetid", "-r"]))
    if signal is None and iface:
        try:
            signal = parse_wireless(Path("/proc/net/wireless").read_text(errors="replace"), iface)
        except OSError:
            pass

    link_mbps = None
    if iface:
        try:
            raw = Path(f"/sys/class/net/{iface}/speed").read_text().strip()
            speed = float(raw)
            if 0 < speed < 100000:
                link_mbps = speed
        except (OSError, ValueError):
            pass

    data: dict[str, Any] = {
        "interface": iface,
        "ip": address,
        "gateway": gateway,
        "dns": _dns_from_resolv_conf(),
        "ssid": ssid,
        "signal_pct": signal,
        "link_mbps": link_mbps,
    }
    return {key: value for key, value in data.items() if value is not None}


def _windows() -> dict[str, Any]:
    wifi = parse_netsh(_run(["netsh", "wlan", "show", "interfaces"]))
    connected = wifi.pop("state", "") == "connected"
    wifi_iface = wifi.get("interface")
    ipconfig = parse_ipconfig(
        _run(["ipconfig", "/all"]),
        wifi_iface if connected else None,
    )
    adapter = ipconfig.pop("interface", None)
    data: dict[str, Any] = {
        key: value for key, value in ipconfig.items() if value not in (None, "")
    }
    if adapter:
        data["interface"] = adapter
    # Only report Wi-Fi details when the radio is connected and it owns the
    # active address. A USB/ethernet tether must not inherit stale Wi-Fi data.
    if connected and (not adapter or adapter.lower() == (wifi_iface or "").lower()):
        data.update(wifi)
        if not adapter and wifi_iface:
            data["interface"] = wifi_iface
    if not data.get("ip"):
        try:
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                address = item[4][0]
                if not address.startswith("127."):
                    data["ip"] = address
                    break
        except OSError:
            pass
    return {key: value for key, value in data.items() if value not in (None, "")}


def collect_network(force: bool = False) -> dict[str, Any]:
    """Return cached Wi-Fi/link details for this machine (possibly empty)."""
    global _cache, _cache_at
    with _lock:
        now = time.monotonic()
        if not force and _cache and now - _cache_at < CACHE_SECONDS:
            return dict(_cache)
        try:
            if _is_android():
                data = _android()
            elif os.name == "nt":
                data = _windows()
            elif sys.platform.startswith("linux"):
                data = _linux()
            else:
                data = {}
        except Exception:
            data = {}
        _cache = data
        _cache_at = now
        return dict(data)
