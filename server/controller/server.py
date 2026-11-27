"""HomeMonitor controller: HTTP API, live events, discovery and monitoring loops.

Standard library only, so this can run inside Termux on an older Android phone.
"""

from __future__ import annotations

import argparse
import hmac
import http.server
import json
import logging
import mimetypes
import os
import platform
import queue
import re
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from common.netinfo import collect_network
from common.protocol import (
    DEFAULT_HTTP_PORT,
    DISCOVERY_MAGIC,
    DISCOVERY_PORT,
    MAX_BODY_BYTES,
    SCHEMA_VERSION,
    SERVICE_NAME,
    VERSION,
    ProtocolError,
    json_dumps,
    json_loads,
    validate_heartbeat,
    validate_metrics,
    validate_registration,
)
from .db import DEFAULT_SETTINGS, Database
from .security import (
    load_or_create_admin_token,
    new_device_token,
    new_pairing_code,
    normalize_pairing_code,
    pairing_code_matches,
    token_hash,
    verify_token,
)

logger = logging.getLogger("homemonitor.controller")


def dashboard_dir() -> Path:
    """Return the dashboard directory.

    ``HOMEMONITOR_DASHBOARD_DIR`` lets packaged installs place the static files
    outside the Python package. The default layout in this repository is
    ``<repo>/dashboard``.
    """
    configured = os.environ.get("HOMEMONITOR_DASHBOARD_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "dashboard"

SETTING_BOUNDS: dict[str, tuple[int, int]] = {
    "heartbeat_interval": (2, 60),
    "metrics_interval": (2, 60),
    "offline_after": (10, 300),
    "retention_days": (1, 90),
    "events_retention_days": (1, 180),
}


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str = "error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 2000:
                self._hits = {
                    k: [t for t in v if now - t < self.window] for k, v in self._hits.items()
                }
                self._hits = {k: v for k, v in self._hits.items() if v}
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True


class Broker:
    """Fan out lightweight refresh events to connected dashboards."""

    def __init__(self) -> None:
        self._subscribers: set[queue.Queue[dict]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[dict]:
        q: queue.Queue[dict] = queue.Queue(maxsize=64)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, payload: dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except (queue.Empty, queue.Full):
                    pass


def local_ipv4_addresses() -> list[str]:
    """Return this host's LAN addresses, primary outbound interface first."""
    addresses: set[str] = set()
    try:
        hostname = socket.gethostname()
        for result in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addresses.add(result[4][0])
    except OSError:
        pass

    primary: list[str] = []
    for target in ("1.1.1.1", "8.8.8.8"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((target, 53))
            address = sock.getsockname()[0]
            addresses.add(address)
            if address not in primary:
                primary.append(address)
        except OSError:
            pass
        finally:
            sock.close()

    candidates = [addr for addr in addresses if not addr.startswith("127.")]
    ordered = [addr for addr in primary if addr in candidates]
    return ordered + sorted(addr for addr in candidates if addr not in ordered)


def address_for_peer(peer_ip: str) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((peer_ip, 9))
        return sock.getsockname()[0]
    except OSError:
        addresses = local_ipv4_addresses()
        return addresses[0] if addresses else "127.0.0.1"
    finally:
        sock.close()


class DiscoveryResponder(threading.Thread):
    """Answer UDP broadcast probes from agents on the LAN."""

    def __init__(self, controller: "Controller"):
        super().__init__(name="homemonitor-discovery", daemon=True)
        self.controller = controller
        self.stop_event = threading.Event()
        self.sock: socket.socket | None = None

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(("", DISCOVERY_PORT))
        except OSError as exc:
            logger.warning("UDP discovery unavailable on port %s: %s", DISCOVERY_PORT, exc)
            sock.close()
            return
        self.sock = sock
        logger.info("UDP discovery listening on port %s", DISCOVERY_PORT)
        while not self.stop_event.is_set():
            try:
                data, peer = sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                break
            if data.strip() != DISCOVERY_MAGIC:
                continue
            ip = address_for_peer(peer[0])
            payload = {
                "service": SERVICE_NAME,
                "version": VERSION,
                "schema": SCHEMA_VERSION,
                "base_url": f"http://{ip}:{self.controller.port}",
                "hostname": socket.gethostname(),
            }
            try:
                sock.sendto(json_dumps(payload).encode("utf-8"), peer)
            except OSError:
                pass

    def stop(self) -> None:
        self.stop_event.set()
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass


class StatusMonitor(threading.Thread):
    def __init__(self, controller: "Controller"):
        super().__init__(name="homemonitor-status", daemon=True)
        self.controller = controller
        self.stop_event = controller.stop_event

    def run(self) -> None:
        previous = {device["id"]: device["status"] for device in self.controller.db.list_devices()}
        while not self.stop_event.wait(4):
            try:
                events, previous = self.controller.db.apply_status_transitions(previous)
                if events:
                    logger.info(
                        "Status changes: %s",
                        ", ".join(f"{event['kind']}:{event['device_id']}" for event in events),
                    )
                    self.controller.broker.publish(
                        {"type": "refresh", "reason": "status", "at": time.time()}
                    )
            except Exception:
                logger.exception("Status monitor pass failed")


class RetentionWorker(threading.Thread):
    def __init__(self, controller: "Controller"):
        super().__init__(name="homemonitor-retention", daemon=True)
        self.controller = controller
        self.stop_event = controller.stop_event

    def run(self) -> None:
        if self.stop_event.wait(300):
            return
        while not self.stop_event.wait(3600):
            try:
                deleted = self.controller.db.prune()
                if any(deleted.values()):
                    logger.info("Retention cleanup: %s", deleted)
            except Exception:
                logger.exception("Retention pass failed")


class InternetMonitor(threading.Thread):
    def __init__(self, controller: "Controller"):
        super().__init__(name="homemonitor-internet", daemon=True)
        self.controller = controller
        self.stop_event = controller.stop_event

    def run(self) -> None:
        while not self.stop_event.is_set():
            reachable = False
            for host in ("1.1.1.1", "8.8.8.8"):
                try:
                    with socket.create_connection((host, 53), timeout=1.5):
                        reachable = True
                        break
                except OSError:
                    continue
            with self.controller.network_lock:
                self.controller.network_state = {
                    "internet": reachable,
                    "checked_at": time.time(),
                }
            self.stop_event.wait(30)


class HomeMonitorHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], controller: "Controller"):
        self.controller = controller
        super().__init__(address, RequestHandler)

    def handle_error(self, request, client_address) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            logger.debug("Client %s disconnected", client_address[0])
            return
        super().handle_error(request, client_address)


class RequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = f"HomeMonitor/{VERSION}"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        try:
            self.connection.settimeout(35)
        except OSError:
            pass

    def log_message(self, fmt: str, *args) -> None:
        logger.debug("%s - %s", self.address_string(), fmt % args)

    @property
    def controller(self) -> "Controller":
        return self.server.controller  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ routing
    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        self._response_started = False
        self._body: bytes | None = None
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if method in {"POST", "PUT", "PATCH"}:
                # Read once up front so keep-alive connections stay in sync even
                # for handlers that do not need a request body.
                try:
                    self._read_body()
                except ApiError:
                    self.close_connection = True
                    raise
            if path in {"/", "/index.html"} and method == "GET":
                self._serve_static("index.html", csp=True)
                return
            if path in {"/lite", "/lite/", "/lite.html"} and method == "GET":
                self._serve_static("lite.html", csp=True)
                return
            if path.startswith("/static/") and method == "GET":
                self._serve_static(path[len("/static/") :])
                return
            if path in {"/healthz", "/api/v1/ping"} and method == "GET":
                self._json(
                    200,
                    {
                        "service": SERVICE_NAME,
                        "version": VERSION,
                        "schema": SCHEMA_VERSION,
                        "time": time.time(),
                    },
                )
                return

            if path == "/api/v1/session" and method == "POST":
                self._handle_login()
                return
            if path == "/api/v1/session" and method == "DELETE":
                self._clear_session()
                return
            if path == "/api/v1/register" and method == "POST":
                self._handle_register()
                return
            if path == "/api/v1/stream" and method == "GET":
                self._handle_stream(query)
                return

            device_route = re.fullmatch(
                r"/api/v1/devices/([A-Za-z0-9_-]{8,64})(?:/(heartbeat|metrics|approve|revoke|history))?",
                path,
            )
            if device_route:
                device_id = device_route.group(1)
                action = device_route.group(2)
                if action == "heartbeat" and method == "POST":
                    self._handle_heartbeat(device_id)
                    return
                if action == "metrics" and method == "POST":
                    self._handle_metrics(device_id)
                    return
                if action == "approve" and method == "POST":
                    self._admin_auth()
                    self._handle_approve(device_id)
                    return
                if action == "revoke" and method == "POST":
                    self._admin_auth()
                    self._handle_revoke(device_id)
                    return
                if action == "history" and method == "GET":
                    self._admin_auth()
                    self._handle_device_history(device_id, query)
                    return
                if action is None and method == "GET":
                    self._admin_auth()
                    self._handle_device_detail(device_id, query)
                    return
                if action is None and method == "DELETE":
                    self._admin_auth()
                    self._handle_device_delete(device_id)
                    return

            if path == "/api/v1/overview" and method == "GET":
                self._admin_auth()
                self._handle_overview()
                return
            if path == "/api/v1/devices" and method == "GET":
                self._admin_auth()
                self._json(200, {"devices": self.controller.db.list_devices()})
                return
            if path == "/api/v1/events" and method == "GET":
                self._admin_auth()
                limit = _int_query(query, "limit", 50, 1, 500)
                device_id = _str_query(query, "device_id")
                self._json(200, {"events": self.controller.db.events(limit, device_id)})
                return
            if path == "/api/v1/alerts" and method == "GET":
                self._admin_auth()
                limit = _int_query(query, "limit", 100, 1, 500)
                self._json(200, {"alerts": self.controller.db.alerts(limit)})
                return
            alert_route = re.fullmatch(r"/api/v1/alerts/(\d+)/ack", path)
            if alert_route and method == "POST":
                self._admin_auth()
                ok = self.controller.db.acknowledge_alert(int(alert_route.group(1)))
                if not ok:
                    raise ApiError(404, "Alert not found", "not_found")
                self.controller.broker.publish({"type": "refresh", "reason": "alert"})
                self._json(200, {"ok": True})
                return
            if path == "/api/v1/settings" and method == "GET":
                self._admin_auth()
                self._json(200, self._settings_payload())
                return
            if path == "/api/v1/settings" and method == "PUT":
                self._admin_auth()
                self._handle_update_settings()
                return
            if path == "/api/v1/pairing/regenerate" and method == "POST":
                self._admin_auth()
                code = self.controller.regenerate_pairing_code()
                logger.info("Pairing code regenerated")
                self._json(200, {"pairing_code": code})
                return
            if path == "/api/v1/network" and method == "GET":
                self._admin_auth()
                self._handle_network()
                return

            raise ApiError(404, "Not found", "not_found")
        except ApiError as exc:
            if not self._response_started:
                self._json(exc.status, {"error": exc.message, "code": exc.code})
        except ProtocolError as exc:
            if not self._response_started:
                self._json(400, {"error": str(exc), "code": "invalid_payload"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            logger.exception("Unhandled request error on %s %s", method, path)
            if not self._response_started:
                self._json(500, {"error": "Internal server error", "code": "internal"})

    # ------------------------------------------------------------------ auth
    def _admin_auth(self, allow_query: bool = False) -> None:
        token = ""
        cookie_header = self.headers.get("Cookie")
        if cookie_header:
            from http.cookies import SimpleCookie

            try:
                cookie = SimpleCookie()
                cookie.load(cookie_header)
                if "hm_session" in cookie:
                    token = cookie["hm_session"].value
            except Exception:
                pass
        if not token:
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                token = auth[7:].strip()
        if not token:
            token = (self.headers.get("X-Admin-Token") or "").strip()
        if not token and allow_query:
            token = (parse_qs(urlsplit(self.path).query).get("token") or [""])[0]
        if not token or not hmac.compare_digest(token, self.controller.admin_token):
            raise ApiError(401, "Authentication required", "auth_required")

    def _device_auth(self, device_id: str) -> dict:
        auth = self.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            raise ApiError(401, "Device token required", "auth_required")
        token = auth[7:].strip()
        record = self.controller.db.device_auth(device_id)
        if record is None or not verify_token(token, record["token_hash"]):
            raise ApiError(401, "Invalid device token", "auth_failed")
        if record["revoked"]:
            raise ApiError(403, "Device access revoked", "revoked")
        return record

    # ------------------------------------------------------------------ agent endpoints
    def _handle_register(self) -> None:
        ip = self.client_address[0]
        if not self.controller.register_limiter.allow(ip):
            raise ApiError(429, "Too many registration attempts", "rate_limited")
        payload = self._read_json()
        pairing_code, info = validate_registration(payload)
        if not pairing_code_matches(pairing_code, self.controller.pairing_code):
            logger.warning("Rejected pairing attempt from %s", ip)
            raise ApiError(403, "Invalid pairing code", "pairing_denied")

        device_token = new_device_token()
        now = time.time()
        device = self.controller.db.register_device(
            info, token_hash(device_token), ip, now
        )
        settings = self.controller.db.get_settings()
        logger.info(
            "Pairing request from %s (%s) at %s", info["name"], info["os"], ip
        )
        self.controller.broker.publish(
            {"type": "refresh", "reason": "pairing", "device_id": info["id"]}
        )
        self._json(
            201,
            {
                "device_id": info["id"],
                "token": device_token,
                "approved": False,
                "heartbeat_interval": settings["heartbeat_interval"],
                "metrics_interval": settings["metrics_interval"],
                "offline_after": settings["offline_after"],
                "server_time": now,
            },
        )

    def _handle_heartbeat(self, device_id: str) -> None:
        auth = self._device_auth(device_id)
        payload = validate_heartbeat(self._read_json())
        now = time.time()
        device = self.controller.db.touch_heartbeat(
            device_id,
            now,
            self.client_address[0],
            self.headers.get("X-Agent-Version"),
            payload.get("network"),
        )
        if device is None:
            raise ApiError(404, "Device not found", "not_found")
        settings = self.controller.db.get_settings()
        self.controller.broker.publish(
            {"type": "refresh", "reason": "heartbeat", "device_id": device_id}
        )
        self._json(
            200,
            {
                "ok": True,
                "approved": bool(auth["approved"]),
                "server_time": now,
                "heartbeat_interval": settings["heartbeat_interval"],
                "metrics_interval": settings["metrics_interval"],
                "offline_after": settings["offline_after"],
            },
        )

    def _handle_metrics(self, device_id: str) -> None:
        auth = self._device_auth(device_id)
        if not auth["approved"]:
            raise ApiError(403, "Device is awaiting approval", "pending_approval")
        payload = self._read_json()
        metrics = validate_metrics(payload)
        now = time.time()
        self.controller.db.ingest_metrics(device_id, metrics, now)
        self.controller.broker.publish(
            {"type": "refresh", "reason": "metrics", "device_id": device_id}
        )
        self._json(202, {"ok": True, "ts": now})

    # ------------------------------------------------------------------ dashboard endpoints
    def _handle_login(self) -> None:
        ip = self.client_address[0]
        if not self.controller.login_limiter.allow(ip):
            raise ApiError(429, "Too many login attempts", "rate_limited")
        payload = self._read_json()
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not hmac.compare_digest(
            token.strip(), self.controller.admin_token
        ):
            logger.warning("Failed dashboard login from %s", ip)
            raise ApiError(401, "Invalid admin token", "auth_failed")
        cookie = (
            "hm_session="
            + token.strip()
            + "; Path=/; HttpOnly; SameSite=Strict; Max-Age=604800"
        )
        self._json(200, {"ok": True}, extra_headers={"Set-Cookie": cookie})

    def _clear_session(self) -> None:
        self._json(
            200,
            {"ok": True},
            extra_headers={
                "Set-Cookie": "hm_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
            },
        )

    def _handle_overview(self) -> None:
        devices = self.controller.db.list_devices()
        counts = {
            "total": len(devices),
            "online": sum(1 for d in devices if d["status"] == "online"),
            "offline": sum(1 for d in devices if d["status"] == "offline"),
            "pending": sum(1 for d in devices if d["status"] == "pending"),
            "revoked": sum(1 for d in devices if d["status"] == "revoked"),
        }
        unresolved = [a for a in self.controller.db.alerts(100) if a["resolved_at"] is None]
        self._json(
            200,
            {
                "controller": self.controller.info(),
                "counts": counts,
                "devices": devices,
                "events": self.controller.db.events(12),
                "alerts": unresolved[:8],
                "alert_count": len(unresolved),
                "network": self.controller.network_snapshot(),
                "settings": {
                    key: value
                    for key, value in self.controller.db.get_settings().items()
                    if key in DEFAULT_SETTINGS
                },
                "pending": [d for d in devices if d["status"] == "pending"],
            },
        )

    def _handle_device_detail(self, device_id: str, query: dict) -> None:
        device = self.controller.db.get_device(device_id)
        if device is None:
            raise ApiError(404, "Device not found", "not_found")
        minutes = _int_query(query, "minutes", 15, 1, 60 * 24 * 7)
        self._json(
            200,
            {
                "device": device,
                "history": self.controller.db.history(device_id, minutes),
                "events": self.controller.db.events(25, device_id),
                "alerts": [
                    a
                    for a in self.controller.db.alerts(100)
                    if a["device_id"] == device_id
                ][:20],
            },
        )

    def _handle_device_history(self, device_id: str, query: dict) -> None:
        device = self.controller.db.get_device(device_id)
        if device is None:
            raise ApiError(404, "Device not found", "not_found")
        minutes = _int_query(query, "minutes", 15, 1, 60 * 24 * 7)
        self._json(
            200,
            {
                "device_id": device_id,
                "minutes": minutes,
                "points": self.controller.db.history(device_id, minutes),
            },
        )

    def _handle_approve(self, device_id: str) -> None:
        device = self.controller.db.set_approved(device_id)
        if device is None:
            raise ApiError(404, "Device not found", "not_found")
        logger.info("Approved device %s (%s)", device["name"], device_id)
        self.controller.broker.publish(
            {"type": "refresh", "reason": "approved", "device_id": device_id}
        )
        self._json(200, {"ok": True, "device": device})

    def _handle_revoke(self, device_id: str) -> None:
        device = self.controller.db.set_revoked(device_id)
        if device is None:
            raise ApiError(404, "Device not found", "not_found")
        logger.info("Revoked device %s (%s)", device["name"], device_id)
        self.controller.broker.publish(
            {"type": "refresh", "reason": "revoked", "device_id": device_id}
        )
        self._json(200, {"ok": True, "device": device})

    def _handle_device_delete(self, device_id: str) -> None:
        device = self.controller.db.get_device(device_id)
        if device is None:
            raise ApiError(404, "Device not found", "not_found")
        self.controller.db.delete_device(device_id)
        logger.info("Deleted device %s (%s)", device["name"], device_id)
        self.controller.broker.publish(
            {"type": "refresh", "reason": "deleted", "device_id": device_id}
        )
        self._json(200, {"ok": True})

    def _settings_payload(self) -> dict:
        return {
            "settings": self.controller.db.get_settings(),
            "pairing_code": self.controller.pairing_code,
            "controller": self.controller.info(),
        }

    def _handle_update_settings(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            raise ApiError(400, "Body must be an object", "invalid_payload")
        updates: dict[str, int] = {}
        for key, value in payload.items():
            if key not in SETTING_BOUNDS:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise ApiError(400, f"{key} must be an integer", "invalid_setting")
            lo, hi = SETTING_BOUNDS[key]
            if not lo <= value <= hi:
                raise ApiError(
                    400, f"{key} must be between {lo} and {hi}", "invalid_setting"
                )
            updates[key] = value
        if not updates:
            raise ApiError(400, "No valid settings supplied", "invalid_setting")
        for key, value in updates.items():
            self.controller.db.set_setting(key, value)
        logger.info("Settings updated: %s", updates)
        self.controller.broker.publish({"type": "refresh", "reason": "settings"})
        self._json(200, {"ok": True, **self._settings_payload()})

    def _handle_network(self) -> None:
        devices = self.controller.db.list_devices()
        self._json(
            200,
            {
                "controller": self.controller.info(),
                "internet": self.controller.network_snapshot(),
                "devices": [
                    {
                        "id": d["id"],
                        "name": d["name"],
                        "category": d["category"],
                        "ip": d["ip"],
                        "network": d.get("network"),
                        "status": d["status"],
                        "last_seen": d["last_seen"],
                    }
                    for d in devices
                ],
                "router": {
                    "status": "not_configured",
                    "note": "Router and LAN latency integration is planned for Phase 8.",
                },
            },
        )

    # ------------------------------------------------------------------ SSE
    def _handle_stream(self, query: dict) -> None:
        self._admin_auth(allow_query=True)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self._response_started = True
        self.close_connection = True
        subscriber = self.controller.broker.subscribe()
        try:
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.write(
                ("data: " + json_dumps({"type": "ready", "version": VERSION}) + "\n\n").encode()
            )
            self.wfile.flush()
            while not self.controller.stop_event.is_set():
                try:
                    event = subscriber.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(("data: " + json_dumps(event) + "\n\n").encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.controller.broker.unsubscribe(subscriber)

    # ------------------------------------------------------------------ plumbing
    def _read_body(self) -> bytes:
        if self._body is not None:
            return self._body
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            self._body = b""
            return self._body
        try:
            length = int(content_length)
        except ValueError:
            raise ApiError(400, "Invalid Content-Length", "invalid_request") from None
        if length < 0:
            raise ApiError(400, "Invalid Content-Length", "invalid_request")
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "Request body too large", "too_large")
        self._body = self.rfile.read(length) if length else b""
        return self._body

    def _read_json(self) -> object:
        body = self._read_body()
        if not body:
            raise ApiError(400, "Empty request body", "invalid_request")
        try:
            return json_loads(body)
        except ProtocolError as exc:
            raise ApiError(400, str(exc), "invalid_json") from exc

    def _json(self, status: int, payload: dict, extra_headers: dict | None = None) -> None:
        if self._response_started:
            return
        body = json_dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self._response_started = True
        self.wfile.write(body)

    def _serve_static(self, name: str, csp: bool = False) -> None:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ApiError(404, "Not found", "not_found")
        static_dir = dashboard_dir()
        path = (static_dir / name).resolve()
        if static_dir not in path.parents or not path.is_file():
            raise ApiError(404, "Not found", "not_found")
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if csp:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; "
                "frame-ancestors 'none'",
            )
        self.end_headers()
        self._response_started = True
        self.wfile.write(body)


def _int_query(query: dict, key: str, default: int, lo: int, hi: int) -> int:
    raw = (query.get(key) or [""])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _str_query(query: dict, key: str) -> str | None:
    raw = (query.get(key) or [""])[0]
    return raw if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", raw) else None


class Controller:
    def __init__(
        self,
        data_dir: Path | str,
        host: str = "0.0.0.0",
        port: int = DEFAULT_HTTP_PORT,
        admin_token: str | None = None,
        discovery: bool = True,
        pairing_code: str | None = None,
    ):
        self.data_dir = Path(data_dir).resolve()
        self.host = host
        self.port = port
        self.admin_token = admin_token or load_or_create_admin_token(
            self.data_dir / "config.json"
        )
        self.discovery_enabled = discovery
        self._pairing_code_override = ""
        if pairing_code:
            normalized = normalize_pairing_code(pairing_code)
            if not 4 <= len(normalized) <= 32:
                raise ValueError("pairing code must contain 4-32 letters or digits")
            self._pairing_code_override = pairing_code.strip().upper()
        self.db = Database(self.data_dir / "homemonitor.db")
        self.broker = Broker()
        self.stop_event = threading.Event()
        self.network_lock = threading.Lock()
        self.network_state: dict = {"internet": None, "checked_at": None}
        self.started_at = time.time()
        self.register_limiter = RateLimiter(12, 60)
        self.login_limiter = RateLimiter(10, 60)
        self.pairing_code = ""
        self.httpd: HomeMonitorHTTPServer | None = None
        self.discovery: DiscoveryResponder | None = None
        self._threads: list[threading.Thread] = []
        self._serve_thread: threading.Thread | None = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db.initialize()
        self.pairing_code = self._load_pairing_code()
        self.httpd = HomeMonitorHTTPServer((self.host, self.port), self)
        self.port = int(self.httpd.server_address[1])
        self._serve_thread = threading.Thread(
            target=self.httpd.serve_forever,
            name="homemonitor-http",
            daemon=True,
        )
        self._serve_thread.start()
        self._threads = [StatusMonitor(self), RetentionWorker(self), InternetMonitor(self)]
        if self.discovery_enabled:
            self.discovery = DiscoveryResponder(self)
            try:
                self.discovery.start()
            except Exception:
                logger.exception("Could not start discovery responder")
                self.discovery = None
        for thread in self._threads:
            thread.start()
        self._started = True
        logger.info(
            "Controller listening on http://%s:%s (data: %s)",
            self.host,
            self.port,
            self.data_dir,
        )

    def serve_forever(self) -> None:
        self.start()
        try:
            while not self.stop_event.wait(1):
                pass
        finally:
            self.stop()

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self.stop_event.set()
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.discovery is not None:
            self.discovery.stop()
        for thread in self._threads:
            thread.join(timeout=3)
        if self._serve_thread is not None:
            self._serve_thread.join(timeout=3)
        logger.info("Controller stopped")

    def info(self) -> dict:
        return {
            "service": SERVICE_NAME,
            "version": VERSION,
            "schema": SCHEMA_VERSION,
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "started_at": self.started_at,
            "uptime_s": max(0.0, time.time() - self.started_at),
            "port": self.port,
            "addresses": local_ipv4_addresses(),
            "network": collect_network(),
            "data_dir": str(self.data_dir),
            "db_bytes": self.db.path.stat().st_size if self.db.path.exists() else 0,
        }

    def network_snapshot(self) -> dict:
        with self.network_lock:
            return dict(self.network_state)

    def _load_pairing_code(self) -> str:
        if self._pairing_code_override:
            return self._pairing_code_override
        path = self.data_dir / "pairing_code.txt"
        try:
            code = path.read_text(encoding="utf-8").strip()
            if 4 <= len(normalize_pairing_code(code)) <= 32:
                return code.upper()
        except OSError:
            pass
        code = new_pairing_code()
        self._write_pairing_code(code)
        return code

    def _write_pairing_code(self, code: str) -> None:
        path = self.data_dir / "pairing_code.txt"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(code + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)

    def regenerate_pairing_code(self) -> str:
        code = new_pairing_code()
        self._write_pairing_code(code)
        self.pairing_code = code
        return code


def setup_logging(data_dir: Path, verbose: bool = False) -> None:
    from logging.handlers import RotatingFileHandler

    data_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)
    try:
        file_handler = RotatingFileHandler(
            data_dir / "controller.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        pass


def _env_port() -> int:
    try:
        value = int(os.environ.get("HOMEMONITOR_PORT", "") or DEFAULT_HTTP_PORT)
    except ValueError:
        return DEFAULT_HTTP_PORT
    return value if 1 <= value <= 65535 else DEFAULT_HTTP_PORT


def _env_discovery() -> bool:
    value = os.environ.get("HOMEMONITOR_DISCOVERY", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HomeMonitor controller")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("HOMEMONITOR_DATA_DIR")
        or str(Path(__file__).resolve().parents[2] / "data"),
        help="directory for SQLite, logs and tokens (env: HOMEMONITOR_DATA_DIR)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HOMEMONITOR_HOST", "0.0.0.0"),
        help="HTTP bind address (env: HOMEMONITOR_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_port(),
        help="HTTP port (env: HOMEMONITOR_PORT)",
    )
    parser.add_argument(
        "--no-discovery",
        action="store_true",
        default=not _env_discovery(),
        help="disable UDP discovery (env: HOMEMONITOR_DISCOVERY=0)",
    )
    parser.add_argument(
        "--pairing-code",
        default=os.environ.get("HOMEMONITOR_PAIRING_CODE", ""),
        help="override the persisted pairing code (env: HOMEMONITOR_PAIRING_CODE)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir).expanduser().resolve()
    setup_logging(data_dir, args.verbose)
    try:
        controller = Controller(
            data_dir=data_dir,
            host=args.host,
            port=args.port,
            discovery=not args.no_discovery,
            pairing_code=args.pairing_code or None,
        )
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    controller.start()

    addresses = local_ipv4_addresses() or ["127.0.0.1"]
    print()
    print("=" * 68)
    print(f"  HomeMonitor v{VERSION} — controller running")
    print("=" * 68)
    for address in addresses:
        print(f"  Dashboard : http://{address}:{controller.port}/")
    print(f"  Local     : http://127.0.0.1:{controller.port}/")
    print(f"  Admin token (paste on login screen): {controller.admin_token}")
    print(f"  Pairing code (enter on new agents): {controller.pairing_code}")
    print(f"  Data dir  : {controller.data_dir}")
    print("  LAN only by default. Do not expose this port to the internet.")
    print("=" * 68)
    print()

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        controller.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
