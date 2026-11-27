"""Static checks for shell/PowerShell installers.

The shell syntax check runs when bash is available (Linux CI and Git Bash).
Windows PowerShell scripts are checked for here-string/parameter structure by
the CI parser job; this test covers encoding and required safety guards.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL_SCRIPTS = sorted(ROOT.glob("agents/**/*.sh")) + sorted(ROOT.glob("server/**/*.sh"))


class ScriptTests(unittest.TestCase):
    def test_expected_installers_exist(self) -> None:
        required = [
            ROOT / "agents/linux/install.sh",
            ROOT / "agents/linux/ubuntu/install.sh",
            ROOT / "agents/linux/debian/install.sh",
            ROOT / "agents/linux/linuxmint/install.sh",
            ROOT / "agents/windows/install.ps1",
            ROOT / "agents/android/setup.sh",
            ROOT / "server/install-linux.sh",
            ROOT / "server/windows/install-server.ps1",
            ROOT / "server/termux/setup.sh",
        ]
        for path in required:
            self.assertTrue(path.is_file(), str(path))

    def test_shell_scripts_use_lf_and_are_not_empty(self) -> None:
        for path in SHELL_SCRIPTS:
            raw = path.read_bytes()
            self.assertNotIn(b"\r\n", raw, f"{path} contains CRLF line endings")
            self.assertGreater(len(raw), 100, f"{path} is unexpectedly small")

    def test_bash_syntax(self) -> None:
        candidates = [shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe"]
        bash = None
        for candidate in candidates:
            if not candidate or not Path(candidate).is_file():
                continue
            probe = subprocess.run(
                [candidate, "--version"], capture_output=True, text=True, timeout=10
            )
            if probe.returncode == 0:
                bash = candidate
                break
        if not bash:
            self.skipTest("a working bash is not installed")
        for path in SHELL_SCRIPTS:
            result = subprocess.run(
                [bash, "-n", str(path)],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, f"{path}: {result.stderr}")

    def test_linux_installer_has_safety_guards(self) -> None:
        text = (ROOT / "agents/linux/install.sh").read_text(encoding="utf-8")
        for marker in ("set -euo pipefail", "id -u", "systemctl", "pair-only"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
