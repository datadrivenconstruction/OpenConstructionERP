"""JWT key ring: ``kid`` headers and rotation without forced logout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from jose import JWTError, jwt

from app.config import Settings
from app.core import crypto
from app.core.jwt_keys import decode_jwt, encode_jwt, key_id_for_secret
from app.dependencies import decode_access_token

OLD = "old-secret-" + "a" * 40
NEW = "new-secret-" + "b" * 40


def _settings(secret: str, previous: str = "") -> Settings:
    return Settings(jwt_secret=secret, jwt_previous_secrets=previous)


def _claims(**extra: object) -> dict[str, object]:
    now = datetime.now(UTC)
    return {"sub": "user-1", "type": "access", "iat": now, "exp": now + timedelta(minutes=5), **extra}


def test_issued_token_carries_kid_that_is_not_the_secret() -> None:
    token = encode_jwt(_claims(), _settings(NEW))
    kid = jwt.get_unverified_header(token)["kid"]
    assert kid == key_id_for_secret(NEW)
    assert NEW not in kid and len(kid) == 16
    assert key_id_for_secret(OLD) != kid


def test_legacy_token_without_kid_still_valid() -> None:
    legacy = jwt.encode(_claims(), NEW, algorithm="HS256")
    assert "kid" not in jwt.get_unverified_header(legacy)
    assert decode_jwt(legacy, _settings(NEW))["sub"] == "user-1"
    assert decode_access_token(legacy, _settings(NEW))["sub"] == "user-1"


def test_legacy_token_signed_with_previous_key_valid_after_rotation() -> None:
    legacy = jwt.encode(_claims(), OLD, algorithm="HS256")
    assert decode_jwt(legacy, _settings(NEW, OLD))["sub"] == "user-1"


def test_token_signed_with_previous_key_valid_after_rotation() -> None:
    token = encode_jwt(_claims(), _settings(OLD))
    rotated = _settings(NEW, f"unrelated-{'c' * 40}, {OLD}")
    assert decode_jwt(token, rotated)["sub"] == "user-1"
    assert decode_access_token(token, rotated)["sub"] == "user-1"


def test_rotation_without_previous_key_rejects_old_tokens() -> None:
    token = encode_jwt(_claims(), _settings(OLD))
    with pytest.raises(JWTError):
        decode_jwt(token, _settings(NEW))
    with pytest.raises(HTTPException) as exc:
        decode_access_token(token, _settings(NEW))
    assert exc.value.status_code == 401


def test_unknown_kid_rejected_even_if_signature_matches_a_ring_key() -> None:
    forged = jwt.encode(_claims(), NEW, algorithm="HS256", headers={"kid": "deadbeefdeadbeef"})
    with pytest.raises(JWTError):
        decode_jwt(forged, _settings(NEW, OLD))
    with pytest.raises(HTTPException):
        decode_access_token(forged, _settings(NEW, OLD))


def test_kid_pins_the_key_no_fallback_to_others() -> None:
    # Signed with OLD but labelled with NEW's kid: must fail, not fall through.
    mislabelled = jwt.encode(_claims(), OLD, algorithm="HS256", headers={"kid": key_id_for_secret(NEW)})
    with pytest.raises(JWTError):
        decode_jwt(mislabelled, _settings(NEW, OLD))


def test_expired_token_is_not_retried_with_other_keys() -> None:
    now = datetime.now(UTC)
    expired = jwt.encode({"sub": "u", "exp": now - timedelta(minutes=1)}, NEW, algorithm="HS256")
    with pytest.raises(JWTError, match="(?i)expired"):
        decode_jwt(expired, _settings(NEW, OLD))


def test_fernet_secret_encrypted_with_previous_key_still_decrypts(monkeypatch: pytest.MonkeyPatch) -> None:
    ciphertext = Fernet(crypto._key_for(OLD)).encrypt(b"sk-test").decode("ascii")
    monkeypatch.setattr(crypto, "get_settings", lambda: _settings(NEW, OLD))
    assert crypto.decrypt_secret(ciphertext) == "sk-test"
    monkeypatch.setattr(crypto, "get_settings", lambda: _settings(NEW))
    assert crypto.decrypt_secret(ciphertext) is None
