"""Security helpers for the HomeMonitor controller."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import string
from pathlib import Path

PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_device_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Device tokens are 256-bit random values, so a fast digest is sufficient."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, expected_hash: str) -> bool:
    return hmac.compare_digest(token_hash(token), expected_hash)


def new_pairing_code() -> str:
    raw = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_pairing_code(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def pairing_code_matches(candidate: str, current: str) -> bool:
    return hmac.compare_digest(normalize_pairing_code(candidate), normalize_pairing_code(current))


def load_or_create_admin_token(path: Path) -> str:
    """Load the dashboard admin token, creating a 256-bit token on first run."""
    env = os.environ.get("HOMEMONITOR_ADMIN_TOKEN", "").strip()
    if env:
        return env

    data: dict[str, str] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("admin_token"), str):
                if len(raw["admin_token"]) >= 20:
                    data = raw
        except (OSError, ValueError):
            data = {}

    if not data:
        data = {"admin_token": secrets.token_urlsafe(32)}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)

    return data["admin_token"]


def generate_admin_token() -> str:
    return secrets.token_urlsafe(32)


def masked(token: str) -> str:
    return f"{token[:4]}...{token[-4:]}" if len(token) > 12 else "***"


def pairing_display(code: str) -> str:
    return code.upper()


# Exposed for tests / diagnostics.
def _alphabet_ok() -> bool:
    return set(PAIRING_ALPHABET) <= set(string.ascii_uppercase + string.digits)
