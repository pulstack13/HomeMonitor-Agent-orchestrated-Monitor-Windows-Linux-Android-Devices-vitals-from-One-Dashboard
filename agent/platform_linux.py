"""Linux distribution and service-manager detection.

The desktop collector is shared with Windows, but installation and diagnostics
are platform-specific. This module keeps Linux detection in one place so the
agent and the installers can report a precise, testable result.

It uses only the Python standard library and never shells out.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
from pathlib import Path
from typing import Any

SUPPORTED_DISTRIBUTIONS = {
    "ubuntu": "Ubuntu",
    "debian": "Debian",
    "linuxmint": "Linux Mint",
}
SUPPORTED_VERSIONS = {
    "ubuntu": {"22.04", "24.04", "24.10", "25.04"},
    "debian": {"12", "13"},
    "linuxmint": {"21", "21.1", "21.2", "21.3", "22", "22.1"},
}


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def read_os_release(path: str | Path = "/etc/os-release") -> dict[str, str]:
    """Parse a freedesktop ``os-release`` file without executing it."""
    result: dict[str, str] = {}
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            result[key] = _unquote(value)
    return result


def distribution(path: str | Path = "/etc/os-release") -> dict[str, Any]:
    """Return ID, display name, version and support state for this Linux host."""
    data = read_os_release(path)
    distro_id = (data.get("ID") or "").strip().lower()
    like = data.get("ID_LIKE", "").lower().split()
    display = data.get("PRETTY_NAME") or data.get("NAME") or "Linux"
    version = data.get("VERSION_ID", "")
    supported = distro_id in SUPPORTED_DISTRIBUTIONS
    if not supported:
        # Derivatives may identify as Ubuntu or Debian through ID_LIKE. They
        # are reported, but not claimed as an officially validated target.
        supported = any(item in SUPPORTED_DISTRIBUTIONS for item in like)
    tested_version = version in SUPPORTED_VERSIONS.get(distro_id, set())
    return {
        "id": distro_id or "unknown",
        "name": display,
        "version": version,
        "version_codename": data.get("VERSION_CODENAME", ""),
        "id_like": like,
        "supported": supported,
        "validated_version": tested_version,
        "kernel": platform.release(),
        "arch": platform.machine() or "unknown",
    }


def init_system() -> str:
    """Return ``systemd`` when systemd is actually running, else ``other``."""
    if Path("/run/systemd/system").is_dir() and shutil.which("systemctl"):
        return "systemd"
    if shutil.which("rc-service"):
        return "openrc"
    if Path("/etc/init.d").is_dir():
        return "sysvinit"
    return "unknown"


def package_manager() -> str:
    for name in ("apt-get", "dnf", "pacman", "zypper", "apk"):
        if shutil.which(name):
            return name
    return "unknown"


def is_android() -> bool:
    return bool(os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"))


def snapshot() -> dict[str, Any]:
    distro = distribution()
    return {
        "platform": "linux",
        "android_runtime": is_android(),
        "distribution": distro,
        "init": init_system(),
        "package_manager": package_manager(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show HomeMonitor Linux platform details")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    data = snapshot()
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        distro = data["distribution"]
        print(f"Distribution : {distro['name']} ({distro['id']} {distro['version']})")
        print(f"Kernel       : {distro['kernel']} / {distro['arch']}")
        print(f"Init system  : {data['init']}")
        print(f"Package mgr  : {data['package_manager']}")
        print(f"Support      : {'yes' if distro['supported'] else 'not validated'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
