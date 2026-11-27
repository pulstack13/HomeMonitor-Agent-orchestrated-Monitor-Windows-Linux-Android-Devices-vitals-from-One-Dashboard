"""Tests for the standalone Android/Termux agent helpers.

These do not touch /proc, so they also run on the Windows development machine.
"""

from __future__ import annotations

import unittest
from unittest import mock

from agent.android_agent import _clamp_interval, _normalise_url, _read_battery


class AndroidAgentTests(unittest.TestCase):
    def test_normalise_url_adds_http(self) -> None:
        self.assertEqual(_normalise_url("192.0.2.34:8787"), "http://192.0.2.34:8787")

    def test_normalise_url_keeps_scheme_and_strips_slash(self) -> None:
        self.assertEqual(_normalise_url(" http://firetv:8787/ "), "http://firetv:8787")

    def test_clamp_interval_uses_default_for_garbage(self) -> None:
        self.assertEqual(_clamp_interval("not-a-number", 5.0), 5.0)

    def test_clamp_interval_bounds(self) -> None:
        self.assertEqual(_clamp_interval(1, 5.0), 2.0)
        self.assertEqual(_clamp_interval(999, 5.0), 60.0)
        self.assertEqual(_clamp_interval(10, 5.0), 10.0)

    def test_tv_devices_report_no_battery(self) -> None:
        with mock.patch("agent.android_agent._getprop", return_value="tv"):
            self.assertEqual(_read_battery(), {})


if __name__ == "__main__":
    unittest.main()
