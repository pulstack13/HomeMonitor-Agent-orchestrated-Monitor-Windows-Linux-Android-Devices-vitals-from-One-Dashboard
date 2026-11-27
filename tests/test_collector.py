from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.collector import Collector
from agent.config import AgentConfig
from common.protocol import validate_metrics


class CollectorTests(unittest.TestCase):
    def test_collect_and_validate(self) -> None:
        collector = Collector()
        metrics = collector.collect()
        validated = validate_metrics(metrics)
        self.assertGreaterEqual(validated["cpu_pct"], 0)
        self.assertLessEqual(validated["cpu_pct"], 100)
        self.assertGreaterEqual(validated["ram_pct"], 0)
        self.assertLessEqual(validated["ram_pct"], 100)
        self.assertIsNotNone(validated["uptime_s"])
        self.assertNotIn(
            "system idle process",
            [process["name"].lower() for process in validated["processes"]],
        )
        info = collector.describe("Test", "123e4567-e89b-42d3-a456-426614174000")
        self.assertEqual(info["name"], "Test")
        self.assertIn(info["category"], {"windows", "linux", "android", "other"})

    def test_config_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent.json"
            config = AgentConfig(controller_url="http://192.0.2.2:8787", token="abc")
            config.save(path)
            loaded = AgentConfig.load(path)
            self.assertEqual(loaded.device_id, config.device_id)
            self.assertEqual(loaded.token, "abc")
            self.assertEqual(loaded.controller_url, config.controller_url)


if __name__ == "__main__":
    unittest.main()
