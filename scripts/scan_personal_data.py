"""Conservative pre-release scan for private network addresses, credentials, and artifacts."""

from __future__ import annotations

import ipaddress
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", "build", "dist"}
EXAMPLE_NETWORKS = (ipaddress.ip_network("192.0.2.0/24"), ipaddress.ip_network("198.51.100.0/24"), ipaddress.ip_network("203.0.113.0/24"))
SAFE_TEST_ADDRESSES = {"172.20.10.1", "172.20.10.3"}
IP_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
PRIVATE_PATH_RE = re.compile(r"(?i)(?:[A-Z]:\\Users\\(?!<|YOUR|USERNAME)[^\\\s]+|(?<![\w/])/home/(?!<|YOU(?:/|\\b)|YOUR|username)[^/\s]+)")
SECRET_RE = re.compile(r"(?i)(?:gh[pousr]_[A-Za-z0-9]{25,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
TOKEN_ASSIGN_RE = re.compile(r"(?i)\b(?:bot_token|telegram_token|admin_token|api_key)\s*[:=]\s*['\"]?([A-Za-z0-9_./+=:-]{24,})")


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        # The scanner necessarily contains patterns describing what it scans for.
        if rel.as_posix() == "scripts/scan_personal_data.py":
            continue
        if path.suffix.lower() in {".jks", ".keystore", ".p12", ".pfx", ".pem", ".key", ".apk", ".aab", ".idsig"}:
            findings.append(f"sensitive/generated artifact: {rel.as_posix()}")
            continue
        if path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for match in IP_RE.finditer(text):
            try:
                address = ipaddress.ip_address(match.group())
            except ValueError:
                continue
            if (address.is_private and not any(address in net for net in EXAMPLE_NETWORKS)
                    and str(address) not in SAFE_TEST_ADDRESSES
                    and not address.is_loopback and not address.is_unspecified and not address.is_link_local
                    and address not in ipaddress.ip_network("255.0.0.0/8")):
                findings.append(f"private IPv4 address in {rel.as_posix()}: {address}")
                break
        if PRIVATE_PATH_RE.search(text):
            findings.append(f"personal home-directory path in {rel.as_posix()}")
        if SECRET_RE.search(text) or TOKEN_ASSIGN_RE.search(text):
            findings.append(f"token or private-key pattern in {rel.as_posix()}")

    if findings:
        print("Personal-data scan failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Personal-data scan passed. No likely private data or signing artifacts found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
