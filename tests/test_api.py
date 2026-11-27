from __future__ import annotations

import http.client
import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from agent.transport import ApiError, ControllerClient
from server.controller.server import Controller


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.controller = Controller(
            data_dir=Path(cls.tmp.name),
            host="127.0.0.1",
            port=0,
            admin_token="test-admin-token",
            discovery=False,
        )
        cls.controller.start()
        cls.base = f"http://127.0.0.1:{cls.controller.port}"
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.controller.stop()
        cls.tmp.cleanup()

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        token: str | None = None,
        include_auth: bool = True,
    ) -> tuple[int, dict, dict]:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if include_auth and token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=10) as response:
                body = response.read()
                return response.status, json.loads(body or b"{}"), dict(response.headers)
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read()
                return exc.code, json.loads(body or b"{}"), dict(exc.headers)
            finally:
                exc.close()

    def test_full_pairing_flow(self) -> None:
        device_id = str(uuid.uuid4())
        client = ControllerClient(self.base)
        device = {
            "id": device_id,
            "name": "API Test Laptop",
            "hostname": "apitest",
            "os": "Windows 11",
            "os_version": "26H2",
            "arch": "AMD64",
            "model": "Test",
            "category": "windows",
            "agent_version": "1.0.0",
        }

        with self.assertRaises(ApiError) as denied:
            client.register("WRONG-CODE", device)
        self.assertEqual(denied.exception.status, 403)

        registration = client.register(self.controller.pairing_code, device)
        self.assertIn("token", registration)
        token = registration["token"]
        self.assertFalse(registration["approved"])

        heartbeat = client.heartbeat(device_id, token, {"uptime_s": 10})
        self.assertFalse(heartbeat["approved"])

        with self.assertRaises(ApiError) as pending:
            client.send_metrics(device_id, token, self.metrics())
        self.assertEqual(pending.exception.code, "pending_approval")

        status, approved, _ = self.request(
            "POST",
            f"/api/v1/devices/{device_id}/approve",
            {},
            token="test-admin-token",
        )
        self.assertEqual(status, 200)
        self.assertTrue(approved["device"]["approved"])

        heartbeat = client.heartbeat(device_id, token, {"uptime_s": 20})
        self.assertTrue(heartbeat["approved"])
        client.send_metrics(device_id, token, self.metrics())
        time.sleep(0.1)

        status, overview, _ = self.request(
            "GET", "/api/v1/overview", token="test-admin-token"
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(overview["counts"]["total"], 1)
        self.assertGreaterEqual(overview["counts"]["online"], 1)
        matching = [d for d in overview["devices"] if d["id"] == device_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["status"], "online")
        self.assertEqual(matching[0]["latest"]["cpu_pct"], 12.5)

        status, detail, _ = self.request(
            "GET",
            f"/api/v1/devices/{device_id}?minutes=15",
            token="test-admin-token",
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(detail["history"]), 1)
        self.assertEqual(detail["device"]["name"], "API Test Laptop")
        self.assertTrue(any(e["kind"] == "approved" for e in detail["events"]))

    def test_keep_alive_after_bodyless_handler(self) -> None:
        """A POST body must be consumed even when the route ignores it."""
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.controller.port, timeout=10
        )
        try:
            headers = {
                "Authorization": "Bearer test-admin-token",
                "Content-Type": "application/json",
            }
            connection.request("POST", "/api/v1/pairing/regenerate", body=b"{}", headers=headers)
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 200)

            connection.request("GET", "/api/v1/settings", headers=headers)
            response = connection.getresponse()
            body = response.read()
            self.assertEqual(response.status, 200)
            self.assertIn(b"heartbeat_interval", body)
        finally:
            connection.close()

    def test_admin_auth_and_login(self) -> None:
        status, _, _ = self.request(
            "GET", "/api/v1/overview", token="wrong-token"
        )
        self.assertEqual(status, 401)

        status, body, headers = self.request(
            "POST",
            "/api/v1/session",
            {"token": "test-admin-token"},
            include_auth=False,
        )
        self.assertEqual(status, 200)
        self.assertIn("hm_session=", headers.get("Set-Cookie", ""))

        status, body, _ = self.request(
            "POST",
            "/api/v1/session",
            {"token": "wrong"},
            include_auth=False,
        )
        self.assertEqual(status, 401)

    def test_settings_update(self) -> None:
        status, body, _ = self.request(
            "GET", "/api/v1/settings", token="test-admin-token"
        )
        self.assertEqual(status, 200)
        self.assertIn("pairing_code", body)

        status, body, _ = self.request(
            "PUT",
            "/api/v1/settings",
            {"heartbeat_interval": 4, "offline_after": 20},
            token="test-admin-token",
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["settings"]["heartbeat_interval"], 4)
        self.assertEqual(body["settings"]["offline_after"], 20)

        status, body, _ = self.request(
            "PUT",
            "/api/v1/settings",
            {"offline_after": 2},
            token="test-admin-token",
        )
        self.assertEqual(status, 400)

    def test_ping_is_public(self) -> None:
        status, body, _ = self.request(
            "GET", "/api/v1/ping", include_auth=False
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["service"], "homemonitor")

    @staticmethod
    def metrics() -> dict:
        return {
            "schema_version": 1,
            "ts": time.time(),
            "cpu": {"percent": 12.5, "cores": 8, "freq_mhz": 2400},
            "memory": {"percent": 45, "used_mb": 7000, "total_mb": 16000},
            "disk_pct": 51,
            "network": {"up_bps": 100, "down_bps": 200},
            "system": {"uptime_s": 100},
            "processes": [{"pid": 1, "name": "p", "cpu": 1, "mem_mb": 2}],
        }


if __name__ == "__main__":
    unittest.main()
