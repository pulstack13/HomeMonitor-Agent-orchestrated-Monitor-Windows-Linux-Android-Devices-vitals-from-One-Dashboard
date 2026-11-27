"""Agent pairing and configuration tests without real hardware."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agent.config import AgentConfig
from agent.runner import AgentRunner


class FakeCollector:
    def describe(self, name: str, device_id: str) -> dict:
        return {
            "id": device_id,
            "name": name,
            "hostname": "testhost",
            "os": "Test OS",
            "os_version": "1",
            "arch": "test",
            "model": "Test",
            "category": "linux",
            "agent_version": "1.0.0",
        }

    def quick_status(self) -> dict:
        return {"uptime_s": 1}

    def collect(self) -> dict:
        raise AssertionError("pair_only must not collect metrics")


class FakeClient:
    base_url = "http://controller.invalid:8787"

    def __init__(self) -> None:
        self.calls = []

    def register(self, pairing_code: str, device: dict) -> dict:
        self.calls.append((pairing_code, device))
        return {"token": "paired-token", "device_id": device["id"], "approved": False}


class PairOnlyTests(unittest.TestCase):
    def test_pair_only_saves_token_and_exits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent.json"
            config = AgentConfig(
                controller_url="http://controller.invalid:8787",
                name="Test device",
            )
            client = FakeClient()
            runner = AgentRunner(
                config=config,
                config_path=path,
                pairing_code="ABCD-1234",
                collector=FakeCollector(),
                client=client,
            )
            self.assertEqual(runner.pair_once(), 0)
            self.assertEqual(len(client.calls), 1)
            loaded = AgentConfig.load(path)
            self.assertEqual(loaded.token, "paired-token")
            self.assertEqual(loaded.name, "Test device")
            if os.name != "nt":
                self.assertFalse(path.stat().st_mode & 0o077)


if __name__ == "__main__":
    unittest.main()
