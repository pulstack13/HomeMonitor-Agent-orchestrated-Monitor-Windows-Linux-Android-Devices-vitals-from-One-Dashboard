"""Linux distribution detection tests (run on every platform)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.platform_linux import distribution, read_os_release


class PlatformLinuxTests(unittest.TestCase):
    def write_release(self, content: str) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        return Path(tmp.name)

    def test_parses_quoted_os_release(self) -> None:
        path = self.write_release(
            'NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="24.04"\n'
            "PRETTY_NAME=\"Ubuntu 24.04.1 LTS\"\nVERSION_CODENAME=noble\n"
        )
        data = read_os_release(path)
        self.assertEqual(data["ID"], "ubuntu")
        self.assertEqual(data["PRETTY_NAME"], "Ubuntu 24.04.1 LTS")

    def test_ubuntu_is_validated(self) -> None:
        path = self.write_release('ID=ubuntu\nVERSION_ID="24.04"\nPRETTY_NAME="Ubuntu 24.04 LTS"\n')
        info = distribution(path)
        self.assertTrue(info["supported"])
        self.assertTrue(info["validated_version"])
        self.assertEqual(info["id"], "ubuntu")

    def test_debian_is_supported(self) -> None:
        path = self.write_release('ID=debian\nVERSION_ID="12"\nPRETTY_NAME="Debian GNU/Linux 12"\n')
        info = distribution(path)
        self.assertTrue(info["supported"])
        self.assertTrue(info["validated_version"])

    def test_linux_mint_is_supported(self) -> None:
        path = self.write_release(
            'ID=linuxmint\nID_LIKE="ubuntu debian"\nVERSION_ID="22"\n'
            'PRETTY_NAME="Linux Mint 22"\n'
        )
        info = distribution(path)
        self.assertTrue(info["supported"])
        self.assertTrue(info["validated_version"])
        self.assertIn("ubuntu", info["id_like"])

    def test_unknown_distribution_is_not_claimed(self) -> None:
        path = self.write_release('ID=alpine\nVERSION_ID="3.20"\nPRETTY_NAME="Alpine"\n')
        info = distribution(path)
        self.assertFalse(info["supported"])
        self.assertFalse(info["validated_version"])

    def test_missing_file_is_safe(self) -> None:
        info = distribution("/nonexistent/os-release")
        self.assertEqual(info["id"], "unknown")
        self.assertFalse(info["supported"])


if __name__ == "__main__":
    unittest.main()
