"""Agent configuration persisted as JSON (token permissions 0600)."""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


def default_config_path() -> Path:
    env = os.environ.get("HOMEMONITOR_CONFIG", "").strip()
    if env:
        return Path(env).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "HomeMonitor" / "agent.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "homemonitor" / "agent.json"


def default_device_name() -> str:
    env = os.environ.get("HOMEMONITOR_NAME", "").strip()
    if env:
        return env
    try:
        return socket.gethostname() or "HomeMonitor agent"
    except OSError:
        return "HomeMonitor agent"


@dataclass
class AgentConfig:
    controller_url: str = ""
    device_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    token: str = ""
    name: str = field(default_factory=default_device_name)
    heartbeat_interval: int = 5
    metrics_interval: int = 5
    auto_discover: bool = True

    @classmethod
    def load(cls, path: Path) -> "AgentConfig":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("agent config must contain a JSON object")
        config = cls()
        for key in (
            "controller_url",
            "device_id",
            "token",
            "name",
        ):
            value = raw.get(key)
            if isinstance(value, str):
                setattr(config, key, value)
        for key in ("heartbeat_interval", "metrics_interval"):
            value = raw.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                setattr(config, key, value)
        if isinstance(raw.get("auto_discover"), bool):
            config.auto_discover = raw["auto_discover"]
        if not config.device_id:
            config.device_id = str(uuid.uuid4())
        if not config.name:
            config.name = default_device_name()
        return config

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)

    def normalized_controller_url(self) -> str:
        url = self.controller_url.strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            url = "http://" + url
        return url


def config_error(message: str) -> None:
    print(f"Configuration error: {message}", file=sys.stderr)
