"""Password hashing without plaintext credentials or third-party auth state."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
import json
from pathlib import Path

from dashboard.registry import FACILITIES

ITERATIONS = 600_000


def registered_users(overrides=None) -> dict:
    """Only the approved 19 accounts exist; Secrets may replace their hashes."""
    hashes = json.loads(Path(__file__).with_name("account_hashes.json").read_text(encoding="utf-8"))
    users = {}
    for code, name in FACILITIES.items():
        username = f"Admin{code}"
        encoded = (overrides or {}).get(username, {}).get("password_hash", hashes[username])
        users[username] = {"display_name": name, "facility_code": code, "password_hash": encoded}
    return users


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt, expected = encoded.split("$")
        count = int(iterations)
        if scheme != "pbkdf2_sha256" or not 100_000 <= count <= 2_000_000:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt, validate=True), count)
        return hmac.compare_digest(digest, base64.b64decode(expected, validate=True))
    except (ValueError, TypeError):
        return False


class LoginThrottle:
    """Per-process account throttle, shared by sessions but containing no PHI."""

    def __init__(self):
        self.attempts = {}
        self.lock = threading.Lock()

    def allowed(self, account: str) -> bool:
        with self.lock:
            now = time.monotonic()
            recent = [t for t in self.attempts.get(account, []) if now - t < 300]
            self.attempts[account] = recent
            return len(recent) < 5

    def failed(self, account: str):
        with self.lock:
            self.attempts.setdefault(account, []).append(time.monotonic())

    def reset(self, account: str):
        with self.lock:
            self.attempts.pop(account, None)
