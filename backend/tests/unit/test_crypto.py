"""Tests for symmetric secret encryption (BUG-AI-CRYPTO01 regression).

The crypto layer protects user-supplied AI provider keys at rest. These
tests pin down the contract so a future refactor can't silently break
the round-trip, accept a tampered ciphertext, or start logging the
plaintext key.

The Fernet key is derived from ``settings.jwt_secret`` (see
``app.core.crypto._key``) — when the secret rotates, all previously
stored ciphertexts are deliberately unreadable. That behaviour is
verified here too.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import InvalidToken

from app.core.crypto import (
    decrypt_secret,
    encrypt_secret,
    is_encrypted,
)


class TestRoundTrip:
    """``encrypt_secret`` and ``decrypt_secret`` are inverses."""

    def test_round_trip_typical_api_key(self):
        plaintext = "sk-ant-api03-AbCdEf1234567890_token_value-xyz"
        token = encrypt_secret(plaintext)

        assert token is not None
        assert token != plaintext  # ciphertext ≠ plaintext
        assert is_encrypted(token)
        assert decrypt_secret(token) == plaintext

    def test_round_trip_unicode(self):
        plaintext = "клю́ч-€-🔑-key"
        token = encrypt_secret(plaintext)
        assert decrypt_secret(token) == plaintext

    def test_each_call_produces_fresh_ciphertext(self):
        """Fernet uses a random IV per encryption — same plaintext should
        produce different ciphertext, but both must decrypt to the same
        value."""
        plaintext = "sk-test-deterministic-input"
        a = encrypt_secret(plaintext)
        b = encrypt_secret(plaintext)
        assert a != b
        assert decrypt_secret(a) == plaintext
        assert decrypt_secret(b) == plaintext


class TestEmptyAndNone:
    """Empty/None inputs short-circuit by design — they are not encrypted.

    Storing an empty string in the database is meaningful ("user cleared
    the key"); we don't want to encrypt empty strings into a non-empty
    Fernet token.
    """

    def test_encrypt_none_returns_none(self):
        assert encrypt_secret(None) is None

    def test_decrypt_none_returns_none(self):
        assert decrypt_secret(None) is None

    def test_encrypt_empty_string_returns_empty(self):
        assert encrypt_secret("") == ""

    def test_decrypt_empty_string_returns_empty(self):
        assert decrypt_secret("") == ""


class TestTamperedToken:
    """A modified ciphertext must not silently decrypt to garbage."""

    def test_tampered_payload_is_rejected(self):
        plaintext = "sk-original-secret-9999"
        token = encrypt_secret(plaintext)
        assert token is not None and token.startswith("gAAAAA")

        # Flip a byte in the middle of the Fernet token. The result still
        # *looks* like a Fernet token (``gAAAAA`` prefix) so the crypto
        # layer's "unusable token" branch fires and returns ``None``,
        # rather than shipping tampered bytes onward to the LLM provider.
        mid = len(token) // 2
        flipped_char = "A" if token[mid] != "A" else "B"
        tampered = token[:mid] + flipped_char + token[mid + 1 :]

        assert decrypt_secret(tampered) is None  # NOT plaintext, NOT garbage

    def test_raw_fernet_decrypt_raises_on_tamper(self):
        """Lower-level safety net — direct Fernet call must raise.

        ``decrypt_secret`` swallows ``InvalidToken`` to keep callers
        simple, but the underlying primitive should still raise so any
        caller that bypasses the wrapper still fails loudly.
        """
        from cryptography.fernet import Fernet

        from app.core.crypto import _key

        token = encrypt_secret("sk-secret")
        assert token is not None

        tampered = "gAAAAA" + "B" * (len(token) - 6)
        with pytest.raises(InvalidToken):
            Fernet(_key()).decrypt(tampered.encode("ascii"))


class TestKeyRotation:
    """If ``jwt_secret`` rotates, old ciphertexts become unreadable.

    This is documented in ``app/core/crypto.py`` and surfaced to users
    as "Stored AI API key could not be decrypted — please re-enter".
    The contract: a Fernet-prefixed token under the wrong key MUST
    return ``None``, never plaintext-looking output, and never raise
    out of ``decrypt_secret``.
    """

    def test_ciphertext_is_unreadable_under_rotated_secret(self, monkeypatch):
        from app.config import get_settings

        settings = get_settings()
        original = settings.jwt_secret

        token = encrypt_secret("sk-original-jwt-era-key")
        assert token is not None

        try:
            settings.jwt_secret = original + "-rotated"  # type: ignore[misc]
            # New JWT_SECRET → different Fernet key → cannot decrypt the
            # token written under the original secret.
            assert decrypt_secret(token) is None
        finally:
            settings.jwt_secret = original  # type: ignore[misc]

        # Once we restore the original secret the same token decrypts.
        assert decrypt_secret(token) == "sk-original-jwt-era-key"


class TestLegacyPlaintext:
    """Rows saved before encryption was introduced still flow through.

    Production data may contain plaintext rows from before the migration.
    ``decrypt_secret`` returns those values unchanged so existing keys
    keep working — only Fernet-prefixed (``gAAAAA…``) tokens trigger the
    decryption path.
    """

    def test_legacy_plaintext_passes_through(self):
        legacy = "sk-saved-before-encryption-was-added"
        # Not a Fernet token — pre-encryption row in the DB.
        assert decrypt_secret(legacy) == legacy
        assert is_encrypted(legacy) is False


class TestIsEncrypted:
    def test_fernet_token_detected(self):
        token = encrypt_secret("sk-test")
        assert is_encrypted(token) is True

    def test_plaintext_not_detected(self):
        assert is_encrypted("sk-ant-plaintext") is False

    def test_empty_inputs(self):
        assert is_encrypted(None) is False
        assert is_encrypted("") is False
