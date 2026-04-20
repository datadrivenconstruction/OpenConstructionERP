"""Symmetric encryption for at-rest secrets (API keys, OAuth tokens).

Uses Fernet (cryptography lib, already in deps via python-jose). The key
is derived from settings.jwt_secret + a fixed app salt so existing
deployments do not need a new env var. If JWT_SECRET rotates, all
encrypted secrets become unreadable — same threat model as JWTs.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_SALT = b"oe-ai-keys-v1"


def _key() -> bytes:
    secret = get_settings().jwt_secret.encode("utf-8")
    digest = hashlib.sha256(secret + _SALT).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plaintext: str | None) -> str | None:
    if not plaintext:
        return plaintext
    return Fernet(_key()).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return ciphertext
    try:
        return Fernet(_key()).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        # If the value looks like a Fernet token (``gAAAAA…``) but the
        # current key can't open it, the encryption key has rotated —
        # treat it as unusable so callers don't end up shipping
        # encrypted garbage as an API key to a remote provider. Genuine
        # plaintext values (no Fernet prefix) pass through unchanged
        # so legacy rows saved before encryption was introduced still
        # work.
        if ciphertext.startswith("gAAAAA"):
            return None
        return ciphertext


def is_encrypted(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    return value.startswith("gAAAAA")  # Fernet token prefix
