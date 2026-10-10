"""JWT signing key ring with ``kid`` headers.

Every token the platform mints is signed with the current ``JWT_SECRET`` and
carries a ``kid`` header derived from that secret (a short one-way hash, never
the secret itself). Verification accepts the current secret plus any previous
secrets listed in ``JWT_PREVIOUS_SECRETS`` (comma-separated), so an operator
can rotate the signing secret without logging every user out:

* a token with a ``kid`` is verified only against the key with that ``kid``;
  an unknown ``kid`` is rejected outright;
* a legacy token without a ``kid`` (minted before key ids existed) is tried
  against the current key first and then each previous key.

See ``docs/jwt-key-rotation.md`` for the rotation procedure.
"""

from __future__ import annotations

import hashlib
from typing import Any

from jose import ExpiredSignatureError, JWTError, jwt
from jose.exceptions import JWTClaimsError

from app.config import Settings

_KID_DOMAIN = b"oe-jwt-kid:v1:"
_KID_HEX_LENGTH = 16


def key_id_for_secret(secret: str) -> str:
    """Return the public key id for ``secret``.

    The id is a truncated SHA-256 over a domain-separated copy of the secret.
    It identifies the key without revealing it.
    """
    return hashlib.sha256(_KID_DOMAIN + secret.encode("utf-8")).hexdigest()[:_KID_HEX_LENGTH]


def _previous_secrets(settings: Settings) -> list[str]:
    raw = getattr(settings, "jwt_previous_secrets", "") or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def verification_keys(settings: Settings) -> list[tuple[str, str]]:
    """Return ``(kid, secret)`` pairs, current key first, duplicates dropped."""
    keys: list[tuple[str, str]] = []
    seen: set[str] = set()
    for secret in [settings.jwt_secret, *_previous_secrets(settings)]:
        if not secret or secret in seen:
            continue
        seen.add(secret)
        keys.append((key_id_for_secret(secret), secret))
    return keys


def ring_secrets(settings: Settings) -> list[str]:
    """Return every secret in the ring, current first.

    For HMAC signatures that carry no ``kid`` (share links, upload URLs,
    review tokens): sign with the first entry, accept a match on any entry,
    so rotating ``JWT_SECRET`` keeps already issued links working for as
    long as the old secret stays in ``JWT_PREVIOUS_SECRETS``.
    """
    return [secret for _kid, secret in verification_keys(settings)]


def encode_jwt(payload: dict[str, Any], settings: Settings) -> str:
    """Sign ``payload`` with the current secret and stamp its ``kid``."""
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        headers={"kid": key_id_for_secret(settings.jwt_secret)},
    )


def decode_jwt(token: str, settings: Settings) -> dict[str, Any]:
    """Verify ``token`` against the key ring and return its claims.

    Raises:
        JWTError: the token is malformed, expired, carries an unknown ``kid``
            or verifies against none of the configured keys.
    """
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    algorithms = [settings.jwt_algorithm]
    keys = verification_keys(settings)

    if kid is not None:
        for key_id, secret in keys:
            if key_id == kid:
                return jwt.decode(token, secret, algorithms=algorithms)
        raise JWTError("Unknown signing key id")

    last_error: JWTError | None = None
    for _key_id, secret in keys:
        try:
            return jwt.decode(token, secret, algorithms=algorithms)
        except (ExpiredSignatureError, JWTClaimsError):
            # The signature matched this key, so the claims are the problem
            # and no other key can fix them.
            raise
        except JWTError as exc:
            last_error = exc
    raise last_error or JWTError("No signing key configured")
