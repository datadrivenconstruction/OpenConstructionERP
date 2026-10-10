# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Symmetric encryption for at-rest secrets (API keys, OAuth tokens).

Uses Fernet (cryptography lib, already in deps via python-jose). The key
is derived from settings.jwt_secret + a fixed app salt so existing
deployments do not need a new env var. New values are always encrypted
with the current JWT_SECRET; decryption also tries every secret listed in
JWT_PREVIOUS_SECRETS, so a rotation does not make stored secrets unreadable
(see docs/jwt-key-rotation.md).
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import get_settings

_SALT = b"oe-ai-keys-v1"


def _key_for(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8") + _SALT).digest()
    return base64.urlsafe_b64encode(digest)


def _key() -> bytes:
    return _key_for(get_settings().jwt_secret)


def _decrypting_fernet() -> MultiFernet:
    settings = get_settings()
    previous = [p.strip() for p in (getattr(settings, "jwt_previous_secrets", "") or "").split(",") if p.strip()]
    return MultiFernet([Fernet(_key_for(s)) for s in [settings.jwt_secret, *previous]])


def encrypt_secret(plaintext: str | None) -> str | None:
    if not plaintext:
        return plaintext
    return Fernet(_key()).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return ciphertext
    try:
        return _decrypting_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        # If the value looks like a Fernet token (``gAAAAA…``) but the
        # current key can't open it, the encryption key has rotated -
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
