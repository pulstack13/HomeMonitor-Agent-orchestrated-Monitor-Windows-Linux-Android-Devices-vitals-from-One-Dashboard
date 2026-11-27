"""Check the public tree for required files, broken local links, and unsafe artifacts."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md",
    ".gitignore", ".env.example", "docs/COMPLETE_SETUP_GUIDE.md",
    "server/controller/server.py", "dashboard/index.html", "agent/__main__.py",
    "agents/windows/install.ps1", "agents/linux/ubuntu/install.sh",
    "agents/linux/debian/install.sh", "agents/linux/linuxmint/install.sh",
    "agents/android/setup.sh", "scripts/scan_personal_data.py",
    "scripts/package_release.py", ".github/workflows/tests.yml",
)
FORBIDDEN_NAMES = {"keystore.jks", "keystore.password", "agent.json", "android_agent.json", "pairing_code.txt"}
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archives", type=Path, help="also inspect archives in this directory")
    args = parser.parse_args()
    errors: list[str] = []

    for name in REQUIRED:
        if not (ROOT / name).is_file():
            errors.append(f"missing required file: {name}")

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in {".git", ".venv", "venv", "__pycache__", "build"} for part in rel.parts):
            continue
        if path.name.lower() in FORBIDDEN_NAMES or path.suffix.lower() in {".jks", ".keystore", ".p12", ".pfx", ".apk", ".aab", ".idsig"}:
            errors.append(f"generated or secret artifact present: {rel.as_posix()}")
        if path.suffix.lower() in {".sh", ".service"}:
            data = path.read_bytes()
            if b"\r\n" in data:
                errors.append(f"expected LF line endings: {rel.as_posix()}")
            if not data.strip():
                errors.append(f"empty script/unit: {rel.as_posix()}")

    for path in ROOT.rglob("*.md"):
        rel = path.relative_to(ROOT)
        if any(part in {".git", "dist"} for part in rel.parts):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read {rel.as_posix()}: {exc}")
            continue
        for target in LINK_RE.findall(content):
            target = target.strip().split("#", 1)[0]
            if not target or re.match(r"^[a-z]+://", target, re.I) or target.startswith(("mailto:", "#")):
                continue
            target = target.split(" ", 1)[0].strip("<>")
            if not (path.parent / target).exists():
                errors.append(f"broken local Markdown link in {rel.as_posix()}: {target}")

    if args.archives:
        try:
            from package_release import validate_archives
            errors.extend(validate_archives(args.archives))
        except ImportError as exc:
            errors.append(f"cannot load archive validator: {exc}")

    if errors:
        print("Repository validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
