"""HTTP transport and LAN discovery for HomeMonitor agents."""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from common.protocol import (
    DISCOVERY_MAGIC,
    DISCOVERY_PORT,
    SERVICE_NAME,
    VERSION,
    json_dumps,
)

logger = logging.getLogger("homemonitor.agent.transport")


class ControllerUnavailable(Exception):
    """The controller could not be reached."""


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        message: str,
        code: str = "error",
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.retry_after = retry_after


class ControllerClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        base_url = base_url.strip().rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            base_url = "http://" + base_url
        self.base_url = base_url
        self.timeout = timeout
        # Do not let a system proxy intercept LAN traffic.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json_dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Accept": "application/json",
            "User-Agent": f"HomeMonitorAgent/{VERSION}",
            "X-Agent-Version": VERSION,
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            try:
                raw = b""
                try:
                    raw = exc.read()
                except OSError:
                    pass
                message = f"HTTP {exc.code}"
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
            raise ApiError(exc.code, message, code, retry_after) from None
        except (urllib.error.URLError, TimeoutError, OSError, socket.timeout) as exc:
            reason = getattr(exc, "reason", exc)
            raise ControllerUnavailable(str(reason)) from None
        if not body:
            return {}
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ControllerUnavailable(f"invalid response (HTTP {status})") from exc
        if not isinstance(parsed, dict):
            raise ControllerUnavailable("unexpected response shape")
        return parsed

    def ping(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/ping")

    def register(self, pairing_code: str, device: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/register",
            {"pairing_code": pairing_code, "device": device},
        )

    def heartbeat(
        self, device_id: str, token: str, status: dict[str, Any]
    ) -> dict[str, Any]:
        device = urllib.parse.quote(device_id, safe="")
        return self._request(
            "POST",
            f"/api/v1/devices/{device}/heartbeat",
            {"ts": time.time(), **status},
            token=token,
        )

    def send_metrics(
        self, device_id: str, token: str, metrics: dict[str, Any]
    ) -> dict[str, Any]:
        device = urllib.parse.quote(device_id, safe="")
        return self._request(
            "POST",
            f"/api/v1/devices/{device}/metrics",
            metrics,
            token=token,
        )


def discover_controllers(timeout: float = 2.5) -> list[dict[str, Any]]:
    """Broadcast a probe and return unique controllers that answer."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.4)
    found: dict[str, dict[str, Any]] = {}
    try:
        sock.bind(("", 0))
        for target in ("255.255.255.255", "127.0.0.1"):
            try:
                sock.sendto(DISCOVERY_MAGIC, (target, DISCOVERY_PORT))
            except OSError:
                continue
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, peer = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                payload = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("service") != SERVICE_NAME:
                continue
            base_url = payload.get("base_url")
            if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
                continue
            found[base_url] = {
                "base_url": base_url.rstrip("/"),
                "version": payload.get("version"),
                "hostname": payload.get("hostname"),
                "peer": peer[0],
            }
    finally:
        sock.close()
    return sorted(found.values(), key=lambda item: item["base_url"])
