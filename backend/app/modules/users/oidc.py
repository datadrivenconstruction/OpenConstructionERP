"""OpenID Connect helpers: discovery, JWKS, ID token verification, role mapping.

Provider neutral: endpoints come from ``<issuer>/.well-known/openid-configuration``,
so Keycloak, Microsoft Entra ID and any other compliant provider work alike.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from fastapi import HTTPException, status
from jose import jwt
from jose.exceptions import JOSEError

VALID_ROLES = ("admin", "manager", "editor", "viewer")
_CACHE_TTL_S = 3600.0
_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def oidc_error(status_code: int, code: str, message: str) -> HTTPException:
    """Build an HTTPException carrying a frontend i18n key."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message_key": f"auth.oidc_errors.{code}", "message": message},
    )


def clear_caches() -> None:
    """Drop cached discovery documents and key sets (tests, key rotation)."""
    _discovery_cache.clear()
    _jwks_cache.clear()


async def _get_json(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise oidc_error(status.HTTP_502_BAD_GATEWAY, "provider_unreachable", "Could not reach OIDC provider.")
    return resp.json()


async def get_discovery(issuer_url: str) -> dict[str, Any]:
    """Return the provider's discovery document, cached for an hour."""
    issuer = issuer_url.rstrip("/")
    cached = _discovery_cache.get(issuer)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL_S:
        return cached[1]
    try:
        doc = await _get_json(f"{issuer}/.well-known/openid-configuration")
    except httpx.HTTPError as exc:
        raise oidc_error(status.HTTP_502_BAD_GATEWAY, "provider_unreachable", "Could not reach OIDC provider.") from exc
    for key in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not doc.get(key):
            raise oidc_error(status.HTTP_502_BAD_GATEWAY, "provider_invalid", f"Discovery document lacks {key}.")
    if doc["issuer"].rstrip("/") != issuer:
        raise oidc_error(status.HTTP_502_BAD_GATEWAY, "provider_invalid", "Discovery issuer does not match.")
    _discovery_cache[issuer] = (time.monotonic(), doc)
    return doc


async def get_jwks(jwks_uri: str, *, refresh: bool = False) -> dict[str, Any]:
    """Return the provider's JSON Web Key Set, cached unless *refresh*."""
    cached = _jwks_cache.get(jwks_uri)
    if not refresh and cached and time.monotonic() - cached[0] < _CACHE_TTL_S:
        return cached[1]
    try:
        jwks = await _get_json(jwks_uri)
    except httpx.HTTPError as exc:
        raise oidc_error(status.HTTP_502_BAD_GATEWAY, "provider_unreachable", "Could not fetch provider keys.") from exc
    _jwks_cache[jwks_uri] = (time.monotonic(), jwks)
    return jwks


async def verify_id_token(
    id_token: str,
    *,
    discovery: dict[str, Any],
    client_id: str,
    nonce: str,
) -> dict[str, Any]:
    """Verify signature (JWKS), iss, aud, exp and nonce; return the claims."""
    invalid = oidc_error(status.HTTP_401_UNAUTHORIZED, "invalid_id_token", "ID token verification failed.")
    try:
        header = jwt.get_unverified_header(id_token)
    except JOSEError as exc:
        raise invalid from exc
    alg = header.get("alg", "")
    if not alg or alg == "none" or alg.startswith("HS"):
        raise invalid
    jwks = await get_jwks(discovery["jwks_uri"])
    kid = header.get("kid")
    if kid and not any(k.get("kid") == kid for k in jwks.get("keys", [])):
        jwks = await get_jwks(discovery["jwks_uri"], refresh=True)  # provider rotated keys
    keys = [k for k in jwks.get("keys", []) if not kid or k.get("kid") == kid]
    if not keys:
        raise invalid
    try:
        claims = jwt.decode(
            id_token,
            {"keys": keys},
            algorithms=[alg],
            audience=client_id,
            issuer=discovery["issuer"],
            options={"verify_at_hash": False},
        )
    except JOSEError as exc:
        raise invalid from exc
    if not nonce or claims.get("nonce") != nonce:
        raise invalid
    return claims


def _claim(source: dict[str, Any], path: str) -> Any:
    value: Any = source
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def extract_groups(claim_names: str, id_claims: dict[str, Any], userinfo: dict[str, Any]) -> list[str]:
    """Collect group / role values from the configured claims.

    *claim_names* is comma separated; dotted paths reach nested claims
    (Keycloak ``realm_access.roles``). The ID token is read first, userinfo
    only for claims the ID token does not carry.
    """
    found: list[str] = []
    for name in (n.strip() for n in claim_names.split(",")):
        if not name:
            continue
        value = _claim(id_claims, name)
        if value is None:
            value = _claim(userinfo, name)
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            found.extend(str(v) for v in value)
    return found


def resolve_role(groups: list[str], group_role_map: str) -> str | None:
    """Map groups to a local role; the most privileged match wins."""
    if not group_role_map:
        return None
    try:
        mapping = json.loads(group_role_map)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(mapping, dict):
        return None
    matched = {mapping[g] for g in groups if mapping.get(g) in VALID_ROLES}
    for role in VALID_ROLES:
        if role in matched:
            return role
    return None
