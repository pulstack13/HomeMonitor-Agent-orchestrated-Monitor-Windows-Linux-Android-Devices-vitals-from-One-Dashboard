"""Build reproducible-scope public archives and SHA-256 manifests."""

from __future__ import annotations

import argparse
import hashlib
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common.protocol import VERSION  # noqa: E402

EXCLUDED_PARTS = {".git", ".venv", "venv", "__pycache__", "build", "dist", "wheels"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".log", ".jks", ".keystore", ".p12", ".pfx", ".apk", ".aab", ".idsig", ".zip", ".tar", ".gz"}
EXCLUDED_NAMES = {"keystore.password", "agent.json", "android_agent.json", "pairing_code.txt"}


def files_for(paths: tuple[str, ...]) -> list[Path]:
    found: set[Path] = set()
    for item in paths:
        path = ROOT / item
        if path.is_file():
            found.add(path)
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    rel = child.relative_to(ROOT)
                    if not any(part in EXCLUDED_PARTS for part in rel.parts) and child.name not in EXCLUDED_NAMES and child.suffix.lower() not in EXCLUDED_SUFFIXES:
                        found.add(child)
    return sorted(found)


def add_zip(output: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, Path("HomeMonitor") / path.relative_to(ROOT))


def add_tar(output: Path, files: list[Path]) -> None:
    with tarfile.open(output, "w:gz") as archive:
        for path in files:
            info = archive.gettarinfo(str(path), arcname=str(Path("HomeMonitor") / path.relative_to(ROOT)))
            info.mode = 0o755 if path.suffix.lower() == ".sh" else 0o644
            with path.open("rb") as handle:
                archive.addfile(info, handle)


def validate_archives(directory: Path) -> list[str]:
    errors: list[str] = []
    for archive_path in sorted(directory.glob("HomeMonitor-*.*")):
        try:
            if archive_path.suffix == ".zip":
                with zipfile.ZipFile(archive_path) as archive:
                    names = archive.namelist()
            elif archive_path.name.endswith(".tar.gz"):
                with tarfile.open(archive_path, "r:gz") as archive:
                    names = archive.getnames()
            else:
                continue
            for name in names:
                rel = Path(name)
                if any(part in EXCLUDED_PARTS for part in rel.parts) or rel.name in EXCLUDED_NAMES or rel.suffix.lower() in EXCLUDED_SUFFIXES:
                    errors.append(f"forbidden content in archive {archive_path.name}: {name}")
        except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
            errors.append(f"cannot inspect archive {archive_path.name}: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    output = args.output.resolve()

    scan = __import__("subprocess").run([sys.executable, str(ROOT / "scripts/scan_personal_data.py")], cwd=ROOT)
    if scan.returncode:
        return scan.returncode

    specs: list[tuple[str, tuple[str, ...], str]] = [
        (f"HomeMonitor-{VERSION}.zip", ("README.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", ".gitignore", ".gitattributes", ".env.example", "requirements-agent.txt", "requirements-dev.txt", "agent", "agents", "android-lite", "common", "dashboard", "docs", "examples", "scripts", "server", "tests", ".github"), "zip"),
        (f"HomeMonitor-{VERSION}.tar.gz", ("README.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", ".gitignore", ".gitattributes", ".env.example", "requirements-agent.txt", "requirements-dev.txt", "agent", "agents", "android-lite", "common", "dashboard", "docs", "examples", "scripts", "server", "tests", ".github"), "tar"),
        (f"HomeMonitor-Server-{VERSION}.tar.gz", ("LICENSE", "server", "common", "dashboard", "docs/COMPLETE_SETUP_GUIDE.md", "docs/REMOTE-ACCESS.md", "docs/TROUBLESHOOTING.md", "requirements-agent.txt"), "tar"),
        (f"HomeMonitor-Agent-Windows-{VERSION}.zip", ("LICENSE", "agent", "common", "agents/windows", "requirements-agent.txt", "docs/WINDOWS-AGENT.md"), "zip"),
        (f"HomeMonitor-Agent-Linux-{VERSION}.tar.gz", ("LICENSE", "agent", "common", "agents/linux", "requirements-agent.txt", "docs/LINUX-AGENT.md"), "tar"),
        (f"HomeMonitor-Agent-Android-{VERSION}.tar.gz", ("LICENSE", "agent/android_agent.py", "agents/android", "docs/ANDROID-AGENT.md"), "tar"),
    ]
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="homemonitor-release-") as temp:
        staging = Path(temp)
        generated: list[Path] = []
        for filename, paths, kind in specs:
            files = files_for(paths)
            if not files:
                print(f"No files selected for {filename}", file=sys.stderr)
                return 1
            target = staging / filename
            (add_zip if kind == "zip" else add_tar)(target, files)
            generated.append(target)
        failures = validate_archives(staging)
        if failures:
            print("Archive validation failed:\n" + "\n".join(failures), file=sys.stderr)
            return 1
        sums: list[str] = []
        for path in generated:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            sums.append(f"{digest}  {path.name}")
            (output / path.name).write_bytes(path.read_bytes())
            (output / f"{path.name}.sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")
        (output / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(f"Built {len(specs)} clean release archives in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
