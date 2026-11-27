"""Server path, environment and pairing-code tests."""

from __future__ import annotations

import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from server.controller import server as server_module
from server.controller.server import Controller


class DashboardTests(unittest.TestCase):
    def test_dashboard_directory_can_be_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"HOMEMONITOR_DASHBOARD_DIR": tmp}):
                self.assertEqual(server_module.dashboard_dir(), Path(tmp).resolve())

    def test_dashboard_is_served(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            controller = Controller(
                data_dir=Path(tmp),
                host="127.0.0.1",
                port=0,
                admin_token="test-admin-token",
                discovery=False,
            )
            controller.start()
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f"http://127.0.0.1:{controller.port}/", timeout=5) as response:
                    body = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("HomeMonitor", body)
                self.assertIn("Content-Security-Policy", response.headers)
            finally:
                controller.stop()


class PairingCodeTests(unittest.TestCase):
    def test_pairing_code_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            controller = Controller(
                data_dir=Path(tmp),
                host="127.0.0.1",
                port=0,
                discovery=False,
                pairing_code="TEST-CODE",
            )
            controller.start()
            try:
                self.assertEqual(controller.pairing_code, "TEST-CODE")
            finally:
                controller.stop()

    def test_invalid_pairing_code_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                Controller(data_dir=Path(tmp), discovery=False, pairing_code="!")


if __name__ == "__main__":
    unittest.main()
