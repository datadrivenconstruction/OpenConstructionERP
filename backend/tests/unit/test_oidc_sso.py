"""OIDC single sign-on: discovery, ID token verification, role mapping, login rules.

Discovery and JWKS are served from memory with a locally generated RSA key, so
the tests exercise real signature checks without a network or an identity provider.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jose import jwk, jwt

from app.modules.users import oidc

ISSUER = "https://login.microsoftonline.com/tenant-id/v2.0"
CLIENT_ID = "client-123"
DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize",
    "token_endpoint": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token",
    "jwks_uri": "https://login.microsoftonline.com/tenant-id/discovery/v2.0/keys",
}


def _key_pair(kid: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    public_jwk = jwk.construct(pub, "RS256").to_dict()
    public_jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return pem, public_jwk


PEM, PUBLIC_JWK = _key_pair("k1")


def _token(pem: bytes = PEM, kid: str = "k1", **overrides) -> str:
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "entra-sub-1",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "nonce": "n-1",
        "email": "anna@example.com",
        "groups": ["11111111-2222-3333-4444-555555555555"],
        "roles": ["Estimator"],
    }
    claims.update(overrides)
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def provider(monkeypatch):
    """Serve discovery and JWKS from memory; return the mutable key list."""
    oidc.clear_caches()
    keys = [PUBLIC_JWK]

    async def fake_get_json(url: str):
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return DISCOVERY
        if url == DISCOVERY["jwks_uri"]:
            return {"keys": list(keys)}
        raise AssertionError(url)

    monkeypatch.setattr(oidc, "_get_json", fake_get_json)
    yield keys
    oidc.clear_caches()


async def _verify(token: str, nonce: str = "n-1"):
    disc = await oidc.get_discovery(ISSUER)
    return await oidc.verify_id_token(token, discovery=disc, client_id=CLIENT_ID, nonce=nonce)


@pytest.mark.asyncio
async def test_discovery_supplies_provider_endpoints(provider):
    disc = await oidc.get_discovery(ISSUER + "/")
    assert disc["authorization_endpoint"].endswith("/oauth2/v2.0/authorize")


@pytest.mark.asyncio
async def test_valid_id_token_is_accepted(provider):
    claims = await _verify(_token())
    assert claims["sub"] == "entra-sub-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://evil.example.com"},
        {"aud": "another-client"},
        {"exp": int(time.time()) - 600},
        {"nonce": "replayed"},
    ],
)
async def test_bad_claims_are_rejected(provider, overrides):
    with pytest.raises(HTTPException) as exc:
        await _verify(_token(**overrides))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_foreign_signature_is_rejected(provider):
    foreign_pem, _ = _key_pair("k1")
    with pytest.raises(HTTPException):
        await _verify(_token(pem=foreign_pem))


@pytest.mark.asyncio
async def test_rotated_key_is_fetched_once(provider):
    await _verify(_token())  # warms the JWKS cache with k1 only
    pem2, jwk2 = _key_pair("k2")
    provider.append(jwk2)
    claims = await _verify(_token(pem=pem2, kid="k2"))
    assert claims["sub"] == "entra-sub-1"


def test_groups_read_from_id_token_with_userinfo_fallback():
    claims = {"groups": ["g-id"], "roles": ["Estimator"]}
    assert oidc.extract_groups("groups,roles", claims, {"groups": ["ignored"]}) == ["g-id", "Estimator"]
    assert oidc.extract_groups("groups", {}, {"groups": ["kc-group"]}) == ["kc-group"]
    assert oidc.extract_groups("realm_access.roles", {"realm_access": {"roles": ["r"]}}, {}) == ["r"]


def test_role_map_accepts_group_ids_and_app_roles_highest_wins():
    mapping = json.dumps({"11111111-2222-3333-4444-555555555555": "editor", "Admins": "admin", "x": "god"})
    assert oidc.resolve_role(["11111111-2222-3333-4444-555555555555"], mapping) == "editor"
    assert oidc.resolve_role(["11111111-2222-3333-4444-555555555555", "Admins"], mapping) == "admin"
    assert oidc.resolve_role(["x"], mapping) is None
    assert oidc.resolve_role(["a"], "") is None


def test_default_role_setting_is_least_privileged():
    from app.config import Settings

    assert Settings.model_fields["oidc_default_role"].default == "viewer"


# ── service rules (PostgreSQL) ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def session():
    from tests._pg import transactional_session

    async with transactional_session() as s:
        yield s


def _service(session):
    from app.config import get_settings
    from app.modules.users.service import UserService

    return UserService(session, get_settings())


def _login_kwargs(**kw):
    base = {
        "oidc_sub": f"sub-{uuid.uuid4().hex[:8]}",
        "oidc_issuer": ISSUER,
        "email": f"sso-{uuid.uuid4().hex[:8]}@example.com",
        "full_name": "Anna Site",
    }
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_linked_user_with_unchanged_role_signs_in_again(session):
    svc = _service(session)
    kw = _login_kwargs(role_from_groups="editor")
    await svc.oidc_login(**kw)
    tokens = await svc.oidc_login(**kw)
    assert tokens.access_token


@pytest.mark.asyncio
async def test_linked_user_without_mapping_signs_in_again(session):
    svc = _service(session)
    kw = _login_kwargs()
    await svc.oidc_login(**kw)
    assert (await svc.oidc_login(**kw)).access_token


@pytest.mark.asyncio
async def test_unknown_user_without_auto_create_gets_403_with_key(session):
    with pytest.raises(HTTPException) as exc:
        await _service(session).oidc_login(**_login_kwargs(auto_create=False))
    assert exc.value.status_code == 403
    assert exc.value.detail["message_key"] == "auth.oidc_errors.account_not_found"


@pytest.mark.asyncio
async def test_new_user_without_mapping_gets_default_role(session):
    from sqlalchemy import select

    from app.modules.users.models import User

    kw = _login_kwargs()
    await _service(session).oidc_login(**kw)
    user = (await session.execute(select(User).where(User.oidc_sub == kw["oidc_sub"]))).scalar_one()
    assert user.role == "viewer"
