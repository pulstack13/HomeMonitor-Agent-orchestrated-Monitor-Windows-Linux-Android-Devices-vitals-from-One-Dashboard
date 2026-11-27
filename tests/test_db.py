from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from server.controller.db import Database
from server.controller.security import token_hash


def device_info() -> dict:
    return {
        "id": "123e4567-e89b-42d3-a456-426614174000",
        "name": "Test Laptop",
        "hostname": "testbox",
        "os": "Windows 11",
        "os_version": "23H2",
        "arch": "AMD64",
        "model": "Test",
        "category": "windows",
        "agent_version": "1.0.0",
    }


def metric_sample() -> dict:
    return {
        "cpu_pct": 12.0,
        "ram_pct": 45.0,
        "ram_used_mb": 7200.0,
        "ram_total_mb": 16000.0,
        "gpu_pct": 10.0,
        "gpu_temp_c": 50.0,
        "gpu_name": "GPU",
        "cpu_temp_c": 55.0,
        "disk_pct": 51.0,
        "net_up_bps": 100.0,
        "net_down_bps": 200.0,
        "battery_pct": 88.0,
        "battery_charging": True,
        "uptime_s": 3600.0,
        "processes": [{"pid": 1, "name": "proc", "cpu": 1.0, "mem_mb": 10.0}],
        "disks": [{"mount": "C:\\", "percent": 51.0, "used_gb": 10.0, "total_gb": 20.0}],
        "cpu_cores": 8,
        "cpu_freq_mhz": 2400.0,
        "load1": 0.1,
        "load5": 0.2,
        "load15": 0.3,
        "swap_pct": 1.0,
        "gpu_mem_used_mb": 100.0,
        "gpu_mem_total_mb": 4000.0,
        "disk_read_bps": 10.0,
        "disk_write_bps": 20.0,
        "net_rx_bytes": 1.0,
        "net_tx_bytes": 2.0,
    }


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.db.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pairing_and_approval(self) -> None:
        now = time.time()
        self.db.register_device(device_info(), token_hash("secret"), "192.0.2.50", now)
        device = self.db.get_device(device_info()["id"])
        self.assertIsNotNone(device)
        self.assertEqual(device["status"], "pending")

        auth = self.db.device_auth(device_info()["id"])
        self.assertFalse(auth["approved"])
        self.assertEqual(auth["token_hash"], token_hash("secret"))

        self.db.set_approved(device_info()["id"])
        self.db.touch_heartbeat(device_info()["id"], now, "192.0.2.50", "1.0.0")
        device = self.db.get_device(device_info()["id"])
        self.assertEqual(device["status"], "online")

    def test_heartbeat_stores_wifi_details(self) -> None:
        now = time.time()
        self.db.register_device(device_info(), token_hash("secret"), "192.0.2.50", now)
        self.db.set_approved(device_info()["id"])
        self.db.touch_heartbeat(
            device_info()["id"],
            now,
            "192.0.2.50",
            "1.0.0",
            {
                "ssid": "TestNetwork",
                "ip": "192.0.2.34",
                "gateway": "192.0.2.1",
                "signal_pct": 92.0,
                "interface": "wlan0",
            },
        )
        device = self.db.get_device(device_info()["id"])
        self.assertEqual(device["network"]["ssid"], "TestNetwork")
        self.assertEqual(device["network"]["signal_pct"], 92.0)
        self.assertEqual(device["network"]["gateway"], "192.0.2.1")
        self.assertEqual(device["network"]["interface"], "wlan0")

    def test_heartbeat_replaces_stale_network_details(self) -> None:
        now = time.time()
        self.db.register_device(device_info(), token_hash("secret"), "192.0.2.50", now)
        self.db.set_approved(device_info()["id"])
        self.db.touch_heartbeat(
            device_info()["id"],
            now,
            "192.0.2.50",
            "1.0.0",
            {
                "ssid": "TestNetwork",
                "ip": "192.0.2.50",
                "gateway": "192.0.2.1",
                "signal_pct": 92.0,
                "interface": "Wi-Fi",
            },
        )
        self.db.touch_heartbeat(
            device_info()["id"],
            now + 5,
            "172.20.10.3",
            "1.0.0",
            {
                "ip": "172.20.10.3",
                "gateway": "172.20.10.1",
                "dns": "172.20.10.1",
                "interface": "Ethernet 4",
            },
        )
        network = self.db.get_device(device_info()["id"])["network"]
        self.assertEqual(network["ip"], "172.20.10.3")
        self.assertEqual(network["gateway"], "172.20.10.1")
        self.assertEqual(network["interface"], "Ethernet 4")
        self.assertNotIn("ssid", network)
        self.assertNotIn("signal_pct", network)

    def test_ingest_and_history(self) -> None:
        now = time.time()
        self.db.register_device(device_info(), token_hash("secret"), "192.0.2.50", now)
        self.db.set_approved(device_info()["id"])
        for i in range(3):
            self.db.ingest_metrics(device_info()["id"], metric_sample(), now + i)
        device = self.db.get_device(device_info()["id"])
        self.assertEqual(device["status"], "online")
        self.assertAlmostEqual(device["latest"]["cpu_pct"], 12.0)
        self.assertEqual(device["latest"]["processes"][0]["name"], "proc")
        history = self.db.history(device_info()["id"], minutes=15)
        self.assertEqual(len(history), 3)
        self.assertLess(history[0]["ts"], history[-1]["ts"])

    def test_transitions_create_and_resolve_alert(self) -> None:
        now = time.time()
        self.db.register_device(device_info(), token_hash("secret"), "192.0.2.50", now)
        self.db.set_approved(device_info()["id"])
        self.db.touch_heartbeat(device_info()["id"], now, "192.0.2.50")

        events, cache = self.db.apply_status_transitions(
            {device_info()["id"]: "online"}, now=now + 20
        )
        self.assertEqual([event["kind"] for event in events], ["offline"])
        self.assertEqual(cache[device_info()["id"]], "offline")
        alerts = self.db.alerts(10)
        self.assertEqual(len(alerts), 1)
        self.assertIsNone(alerts[0]["resolved_at"])

        later = now + 30
        self.db.touch_heartbeat(device_info()["id"], later, "192.0.2.50")
        events, cache = self.db.apply_status_transitions(
            {device_info()["id"]: "offline"}, now=later + 1
        )
        self.assertEqual([event["kind"] for event in events], ["online"])
        alerts = self.db.alerts(10)
        self.assertIsNotNone(alerts[0]["resolved_at"])

    def test_revoke_blocks_auth_state(self) -> None:
        now = time.time()
        self.db.register_device(device_info(), token_hash("secret"), "192.0.2.50", now)
        self.db.set_approved(device_info()["id"])
        self.db.set_revoked(device_info()["id"])
        auth = self.db.device_auth(device_info()["id"])
        self.assertEqual(auth["revoked"], 1)
        self.assertEqual(self.db.get_device(device_info()["id"])["status"], "revoked")


if __name__ == "__main__":
    unittest.main()
