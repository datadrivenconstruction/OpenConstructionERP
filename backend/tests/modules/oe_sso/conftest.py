"""Fixtures: an app with the SSO and users routers over a throwaway PostgreSQL, plus a test IdP key pair."""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests._pg import isolated_engine

import app.config as app_config
import app.core.data_repairs  # noqa: F401  (registers the delivery ledger table)
import app.dependencies as deps
from app.modules.sso.router import router as sso_router
from app.modules.users.models import User
from app.modules.users.router import router as users_router
from app.modules.users.service import create_access_token, hash_password

ORIGINAL_GET_SETTINGS = app_config.get_settings
BASE = "https://test"  # https: the SAML request cookie is Secure
IDP = "https://idp.corp.example/saml"
SAML_NS = 'xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"'


def make_keypair(days: int = 365) -> tuple[Any, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-idp")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=2))
        .not_valid_after(now + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


KEY, CERT = make_keypair()
OTHER_KEY, OTHER_CERT = make_keypair()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_response(
    *,
    in_response_to: str,
    acs_url: str,
    audience: str,
    name_id: str = "u-1001",
    email: str = "ann@corp.example",
    groups: tuple[str, ...] = ("estimators",),
    issuer: str = IDP,
    not_after: datetime | None = None,
    sign: str = "assertion",
    key: Any = None,
    cert: str | None = None,
    assertion_id: str | None = None,
) -> str:
    """Return a base64 SAMLResponse. *sign*: "assertion", "response" or "none"."""
    from lxml import etree
    from signxml import XMLSigner

    now = datetime.now(UTC)
    not_after = not_after or now + timedelta(minutes=5)
    aid = assertion_id or "_a" + uuid.uuid4().hex
    attrs = "".join(
        f'<saml:Attribute Name="{n}">'
        + "".join(f"<saml:AttributeValue>{v}</saml:AttributeValue>" for v in vals)
        + "</saml:Attribute>"
        for n, vals in (("email", [email]), ("displayName", ["Ann Example"]), ("groups", list(groups)))
    )
    assertion = (
        f'<saml:Assertion {SAML_NS} ID="{aid}" Version="2.0" IssueInstant="{_iso(now)}">'
        f"<saml:Issuer>{issuer}</saml:Issuer>"
        f"<saml:Subject><saml:NameID>{name_id}</saml:NameID>"
        '<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData InResponseTo="{in_response_to}" Recipient="{acs_url}" '
        f'NotOnOrAfter="{_iso(not_after)}"/></saml:SubjectConfirmation></saml:Subject>'
        f'<saml:Conditions NotBefore="{_iso(now - timedelta(minutes=1))}" NotOnOrAfter="{_iso(not_after)}">'
        f"<saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction>"
        "</saml:Conditions>"
        f'<saml:AuthnStatement AuthnInstant="{_iso(now)}" SessionIndex="s1"/>'
        f"<saml:AttributeStatement>{attrs}</saml:AttributeStatement></saml:Assertion>"
    )
    key = key or KEY
    cert = cert or CERT
    signer = XMLSigner(signature_algorithm="rsa-sha256", digest_algorithm="sha256")
    a_el = etree.fromstring(assertion.encode())
    if sign == "assertion":
        a_el = signer.sign(a_el, key=key, cert=cert, reference_uri=aid)
    rid = "_r" + uuid.uuid4().hex
    resp = etree.fromstring(
        (
            f'<samlp:Response {SAML_NS} ID="{rid}" Version="2.0" IssueInstant="{_iso(now)}" '
            f'InResponseTo="{in_response_to}"><saml:Issuer>{issuer}</saml:Issuer>'
            '<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>'
            "</samlp:Response>"
        ).encode()
    )
    resp.append(a_el)
    if sign == "response":
        resp = signer.sign(resp, key=key, cert=cert, reference_uri=rid)
    return base64.b64encode(etree.tostring(resp)).decode("ascii")


@dataclass
class Env:
    client: AsyncClient
    factory: async_sessionmaker
    settings: Any
    admin_id: uuid.UUID
    headers: dict[str, str]

    async def add_user(self, email: str, role: str = "viewer", **kw: Any) -> uuid.UUID:
        async with self.factory() as s:
            u = User(email=email, hashed_password=hash_password("Passw0rd!x1"), full_name="P", role=role, **kw)
            s.add(u)
            await s.commit()
            return u.id

    async def get(self, model: type, row_id: uuid.UUID) -> Any:
        async with self.factory() as s:
            row = await s.get(model, row_id)
            if row is not None:
                s.expunge(row)
            return row


@pytest.fixture
def saml_required() -> None:
    pytest.importorskip("signxml")


@pytest_asyncio.fixture
async def env(monkeypatch: pytest.MonkeyPatch):
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(deps, "async_session_factory", factory)
        settings = ORIGINAL_GET_SETTINGS().model_copy(update={"frontend_url": BASE, "cors_origins": [BASE]})
        monkeypatch.setattr(app_config, "get_settings", lambda: settings)

        app = FastAPI()
        app.include_router(sso_router, prefix="/api/v1/sso")
        app.include_router(users_router, prefix="/api/v1/users")
        app.dependency_overrides[ORIGINAL_GET_SETTINGS] = lambda: settings

        async with factory() as s:
            admin = User(email="owner@corp.example", hashed_password=hash_password("x"), full_name="A", role="admin")
            s.add(admin)
            await s.commit()
            token = create_access_token(admin, settings)
            admin_id = admin.id
        e = Env(
            client=AsyncClient(transport=ASGITransport(app=app), base_url=BASE),
            factory=factory,
            settings=settings,
            admin_id=admin_id,
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            yield e
        finally:
            await e.client.aclose()
