from __future__ import annotations

import unittest

from common.protocol import (
    ProtocolError,
    json_loads,
    validate_heartbeat,
    validate_metrics,
    validate_registration,
)


def sample_metrics() -> dict:
    return {
        "schema_version": 1,
        "ts": 1700000000.0,
        "cpu": {
            "percent": 12.5,
            "cores": 8,
            "freq_mhz": 2400,
            "temp_c": 55.0,
            "load": [0.5, 0.4, 0.3],
        },
        "memory": {
            "percent": 48.0,
            "used_mb": 8000,
            "total_mb": 16000,
            "swap_percent": 2.0,
        },
        "gpu": {"percent": 33.0, "temp_c": 61.0, "name": "Test GPU"},
        "disks": [{"mount": "C:\\", "percent": 51.0, "used_gb": 500, "total_gb": 1000}],
        "disk_io": {"read_bps": 100, "write_bps": 200},
        "network": {"up_bps": 1000, "down_bps": 2000, "rx_bytes": 10, "tx_bytes": 20},
        "battery": {"percent": 90, "plugged": True},
        "system": {"uptime_s": 3600, "hostname": "box"},
        "processes": [{"pid": 10, "name": "proc", "cpu": 1.5, "mem_mb": 20.0}],
    }


class ProtocolTests(unittest.TestCase):
    def test_metrics_round_trip(self) -> None:
        result = validate_metrics(sample_metrics())
        self.assertEqual(result["cpu_pct"], 12.5)
        self.assertEqual(result["ram_pct"], 48.0)
        self.assertEqual(result["gpu_name"], "Test GPU")
        self.assertEqual(result["load1"], 0.5)
        self.assertEqual(len(result["processes"]), 1)
        self.assertTrue(result["battery_charging"])

    def test_metrics_reject_out_of_range(self) -> None:
        payload = sample_metrics()
        payload["cpu"]["percent"] = 150
        with self.assertRaises(ProtocolError):
            validate_metrics(payload)

    def test_metrics_allow_missing_cpu_percent(self) -> None:
        payload = sample_metrics()
        del payload["cpu"]["percent"]
        result = validate_metrics(payload)
        self.assertIsNone(result["cpu_pct"])
        self.assertEqual(result["cpu_cores"], 8)

    def test_metrics_require_cpu_and_memory(self) -> None:
        payload = sample_metrics()
        del payload["cpu"]
        with self.assertRaises(ProtocolError):
            validate_metrics(payload)

    def test_metrics_limits_process_list(self) -> None:
        payload = sample_metrics()
        payload["processes"] = [
            {"pid": i, "name": f"p{i}", "cpu": 0.1, "mem_mb": 1.0} for i in range(50)
        ]
        result = validate_metrics(payload)
        self.assertEqual(len(result["processes"]), 15)

    def test_registration(self) -> None:
        code, info = validate_registration(
            {
                "pairing_code": "K7M4-P2QX",
                "device": {
                    "id": "123e4567-e89b-42d3-a456-426614174000",
                    "name": "Laptop",
                    "category": "windows",
                    "os": "Windows 11",
                },
            }
        )
        self.assertEqual(code, "K7M4-P2QX")
        self.assertEqual(info["name"], "Laptop")
        self.assertEqual(info["category"], "windows")

    def test_registration_rejects_bad_id(self) -> None:
        with self.assertRaises(ProtocolError):
            validate_registration(
                {
                    "pairing_code": "K7M4-P2QX",
                    "device": {"id": "../../etc/passwd", "name": "bad"},
                }
            )

    def test_json_rejects_nan(self) -> None:
        with self.assertRaises(ProtocolError):
            json_loads(b'{"cpu": NaN}')

    def test_text_is_sanitized(self) -> None:
        _, info = validate_registration(
            {
                "pairing_code": "K7M4-P2QX",
                "device": {
                    "id": "123e4567-e89b-42d3-a456-426614174000",
                    "name": "Bad\x00Name",
                },
            }
        )
        self.assertNotIn("\x00", info["name"])

    def test_heartbeat_accepts_network_details(self) -> None:
        result = validate_heartbeat(
            {
                "uptime_s": 120,
                "network": {
                    "ssid": "Home Wi-Fi",
                    "ip": "192.0.2.40",
                    "gateway": "192.0.2.1",
                    "dns": "192.0.2.1",
                    "interface": "wlan0",
                    "signal_pct": 87.5,
                    "link_mbps": 144,
                    "ignored": "value",
                },
            }
        )
        network = result["network"]
        self.assertEqual(network["ssid"], "Home Wi-Fi")
        self.assertEqual(network["signal_pct"], 87.5)
        self.assertEqual(network["link_mbps"], 144.0)
        self.assertNotIn("ignored", network)

    def test_heartbeat_drops_unknown_ssid(self) -> None:
        result = validate_heartbeat(
            {"network": {"ssid": "<unknown ssid>", "ip": "192.0.2.40"}}
        )
        network = result["network"]
        self.assertNotIn("ssid", network)
        self.assertEqual(network["ip"], "192.0.2.40")

    def test_heartbeat_rejects_bad_signal(self) -> None:
        with self.assertRaises(ProtocolError):
            validate_heartbeat({"network": {"signal_pct": 140}})


if __name__ == "__main__":
    unittest.main()
