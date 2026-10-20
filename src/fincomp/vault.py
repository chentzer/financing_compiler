"""Statement passwords encrypted with the user's PIN, in the same format as
web/src/data/vault.ts (so the CLI and the app read each other's file):

    PBKDF2-HMAC-SHA256(PIN, random 16-byte salt, 600,000 iterations) -> AES-256-GCM key
    each save: fresh random 12-byte IV; data = ciphertext + 16-byte tag

    {"v": 1, "kdf": "PBKDF2-SHA256", "iterations": 600000,
     "salt": b64, "iv": b64, "data": b64}

Only that JSON goes to Drive (App Data folder, passwords.vault.json).
"""

from __future__ import annotations

import base64
import json
import os

ITERATIONS = 600_000
VAULT_FILE = "passwords.vault.json"
LEGACY_FILE = "passwords.json"  # old unencrypted file: converted, then deleted


class WrongPin(Exception):
    pass


def _key(pin: str, salt: bytes, iterations: int) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations).derive(pin.encode())


def seal(passwords: dict[str, str], pin: str, salt: bytes | None = None) -> dict:
    """Encrypt. A new random salt unless `salt` keeps the current PIN's."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = salt or os.urandom(16)
    iv = os.urandom(12)
    data = AESGCM(_key(pin, salt, ITERATIONS)).encrypt(iv, json.dumps(passwords).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iterations": ITERATIONS, "salt": b64(salt), "iv": b64(iv), "data": b64(data)}


def open_vault(blob: dict, pin: str) -> dict[str, str]:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if blob.get("v") != 1 or blob.get("kdf") != "PBKDF2-SHA256":
        raise ValueError("unknown vault format")
    key = _key(pin, base64.b64decode(blob["salt"]), int(blob["iterations"]))
    try:
        plain = AESGCM(key).decrypt(base64.b64decode(blob["iv"]), base64.b64decode(blob["data"]), None)
    except InvalidTag as e:
        raise WrongPin("that PIN didn't unlock the saved passwords") from e
    return json.loads(plain)


def salt_of(blob: dict) -> bytes:
    return base64.b64decode(blob["salt"])
