"""SSO identities are scoped to their issuer; SAML answers only our own request, once."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import ModuleType, SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.modules.users import router as users_router
from app.modules.users import saml

OIDC_ISS = "https://login.example/tenant/v2.0"
SAML_ISS = "https://idp.example/"

# ── service: issuer-scoped lookup and email linking (PostgreSQL) ───────────


@pytest_asyncio.fixture
async def session():
    from tests._pg import transactional_session

    async with transactional_session() as s:
        yield s


def _service(session):
    from app.config import get_settings
    from app.modules.users.service import UserService

    return UserService(session, get_settings())


def _uid() -> str:
    return uuid.uuid4().hex[:8]


async def _user_by(session, **where):
    from sqlalchemy import select

    from app.modules.users.models import User

    q = select(User)
    for k, v in where.items():
        col = getattr(User, k)
        q = q.where(col.is_(None) if v is None else col == v)
    return (await session.execute(q)).scalar_one_or_none()


async def _local_user(session, email: str, **kw):
    from app.modules.users.models import User

    user = User(email=email, hashed_password="x", full_name="Local", role="editor", is_active=True, **kw)
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_same_subject_from_another_issuer_is_a_different_person(session):
    sub = f"shared-{_uid()}"
    svc = _service(session)
    await svc.oidc_login(oidc_sub=sub, oidc_issuer=OIDC_ISS, email=f"o-{_uid()}@example.com", full_name="O")
    owner = await _user_by(session, oidc_sub=sub, oidc_issuer=OIDC_ISS)
    await svc.oidc_login(oidc_sub=sub, oidc_issuer=SAML_ISS, email=f"s-{_uid()}@example.com", full_name="S")
    other = await _user_by(session, oidc_sub=sub, oidc_issuer=SAML_ISS)
    assert other is not None
    assert other.id != owner.id


@pytest.mark.asyncio
async def test_untrusted_email_does_not_link_an_existing_account(session):
    email = f"local-{_uid()}@example.com"
    await _local_user(session, email)
    with pytest.raises(HTTPException) as exc:
        await _service(session).oidc_login(oidc_sub=_uid(), oidc_issuer=SAML_ISS, email=email, full_name="X")
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "account_link_refused"
    assert (await _user_by(session, email=email)).oidc_sub is None


@pytest.mark.asyncio
async def test_trusted_email_never_relinks_an_account_bound_elsewhere(session):
    email = f"bound-{_uid()}@example.com"
    await _local_user(session, email, oidc_sub="orig", oidc_issuer=OIDC_ISS)
    with pytest.raises(HTTPException) as exc:
        await _service(session).oidc_login(
            oidc_sub=_uid(), oidc_issuer=SAML_ISS, email=email, full_name="X", email_trusted=True
        )
    assert exc.value.detail["code"] == "account_link_refused"
    user = await _user_by(session, email=email)
    assert (user.oidc_sub, user.oidc_issuer) == ("orig", OIDC_ISS)


@pytest.mark.asyncio
async def test_trusted_email_links_an_unbound_account(session):
    email = f"free-{_uid()}@example.com"
    await _local_user(session, email)
    sub = _uid()
    await _service(session).oidc_login(
        oidc_sub=sub, oidc_issuer=OIDC_ISS, email=email, full_name="X", email_trusted=True
    )
    user = await _user_by(session, email=email)
    assert (user.oidc_sub, user.oidc_issuer) == (sub, OIDC_ISS)


@pytest.mark.asyncio
async def test_legacy_null_issuer_row_matches_only_with_fallback_and_is_backfilled(session):
    email = f"legacy-{_uid()}@example.com"
    sub = f"legacy-{_uid()}"
    await _local_user(session, email, oidc_sub=sub)
    svc = _service(session)
    with pytest.raises(HTTPException):
        await svc.oidc_login(oidc_sub=sub, oidc_issuer=SAML_ISS, email=email, full_name="X")
    await svc.oidc_login(oidc_sub=sub, oidc_issuer=OIDC_ISS, email=email, full_name="X", legacy_issuer_fallback=True)
    assert (await _user_by(session, email=email)).oidc_issuer == OIDC_ISS


@pytest.mark.asyncio
async def test_replayed_assertion_is_refused(session):
    svc = _service(session)
    aid = f"_a{_uid()}"
    until = datetime.now(UTC) + timedelta(minutes=5)
    assert await svc.consume_saml_assertion(aid, until)
    assert not await svc.consume_saml_assertion(aid, until)


# ── saml.read_response with python3-saml mocked ────────────────────────────


def _settings(**kw) -> Settings:
    base = {
        "saml_enabled": True,
        "saml_sp_entity_id": "https://erp.example/sp",
        "saml_acs_url": "https://erp.example:8443/api/v1/users/auth/saml/acs/",
        "saml_idp_entity_id": SAML_ISS,
        "saml_idp_sso_url": "https://idp.example/sso",
        "saml_idp_x509_cert": "MIIC",
    }
    return Settings(**{**base, **kw})


class _FakeAuth:
    last: _FakeAuth | None = None
    in_response_to: str | None = "req-1"

    def __init__(self, request_data, _settings) -> None:
        self.request_data = request_data
        self.processed_with = "unset"
        _FakeAuth.last = self

    def login(self, return_to=None) -> str:
        return "https://idp.example/sso?SAMLRequest=x"

    def get_last_request_id(self) -> str:
        return "req-1"

    def process_response(self, request_id=None) -> None:
        self.processed_with = request_id

    def get_errors(self) -> list:
        return []

    def is_authenticated(self) -> bool:
        return True

    def get_last_assertion_id(self) -> str:
        return "_assert1"

    def get_last_assertion_not_on_or_after(self) -> int:
        return 2_000_000_000

    def get_attributes(self) -> dict:
        return {"email": ["a@b.test"]}

    def get_nameid(self) -> str:
        return "nid-1"


@pytest.fixture
def fake_saml(monkeypatch):
    mod = ModuleType("onelogin.saml2.auth")
    mod.OneLogin_Saml2_Auth = _FakeAuth
    monkeypatch.setattr(saml, "require_saml_library", lambda: mod)
    monkeypatch.setattr(saml, "_in_response_to", lambda _h: _FakeAuth.in_response_to)
    _FakeAuth.in_response_to = "req-1"
    return _FakeAuth


def test_response_without_our_request_is_refused_by_default(fake_saml) -> None:
    with pytest.raises(HTTPException) as exc:
        saml.read_response(_settings(), {"SAMLResponse": "x"}, None)
    assert exc.value.detail["code"] == "invalid_saml_response"


def test_idp_initiated_only_when_enabled(fake_saml) -> None:
    fake_saml.in_response_to = None
    info = saml.read_response(_settings(saml_allow_idp_initiated=True), {"SAMLResponse": "x"}, None)
    assert info["sub"] == "nid-1"
    assert fake_saml.last.processed_with is None


def test_request_id_is_passed_and_must_match(fake_saml) -> None:
    info = saml.read_response(_settings(), {"SAMLResponse": "x"}, "req-1")
    assert fake_saml.last.processed_with == "req-1"
    assert info["assertion_id"] == "_assert1"
    assert info["expires_at"] == datetime.fromtimestamp(2_000_000_000, tz=UTC)
    for answered in ("req-other", None):
        fake_saml.in_response_to = answered
        with pytest.raises(HTTPException):
            saml.read_response(_settings(), {"SAMLResponse": "x"}, "req-1")


def test_request_data_host_comes_from_settings(fake_saml) -> None:
    saml.read_response(_settings(), {"SAMLResponse": "x"}, "req-1")
    data = fake_saml.last.request_data
    assert data["http_host"] == "erp.example"
    assert data["server_port"] == "8443"
    assert data["script_name"] == "/api/v1/users/auth/saml/acs/"
    assert data["https"] == "on"


def test_request_cookie_round_trip_and_forgery() -> None:
    s = _settings()
    assert saml.verify_request_id(s, saml.sign_request_id(s, "req-9")) == "req-9"
    assert saml.verify_request_id(s, "forged.token.value") is None
    assert saml.verify_request_id(s, None) is None


# ── router: cookie set on login, read on ACS, replay refused ───────────────


class _Service:
    def __init__(self, fresh: bool = True) -> None:
        self.fresh = fresh
        self.kwargs: dict = {}

    async def consume_saml_assertion(self, *_a) -> bool:
        return self.fresh

    async def oidc_login(self, **kw):
        self.kwargs = kw
        return SimpleNamespace(access_token="AT", refresh_token="RT", token_type="bearer")


def _client(monkeypatch, service: _Service) -> TestClient:
    cfg = _settings()
    monkeypatch.setattr("app.config.get_settings", lambda: cfg)
    app = FastAPI()
    app.include_router(users_router.router, prefix="/api/v1/users")
    app.dependency_overrides[users_router._get_service] = lambda: service
    return TestClient(app, base_url="https://erp.example", follow_redirects=False)


def test_login_sets_signed_request_cookie_and_acs_uses_it(monkeypatch, fake_saml) -> None:
    service = _Service()
    client = _client(monkeypatch, service)
    r = client.get("/api/v1/users/auth/saml/login/")
    assert r.status_code == 302
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "samesite=none" in cookie.lower()
    token = r.cookies[saml.REQUEST_COOKIE]
    r = client.post(
        "/api/v1/users/auth/saml/acs/",
        data={"SAMLResponse": "x"},
        cookies={saml.REQUEST_COOKIE: token},
        headers={"accept": "application/json"},
    )
    assert r.status_code == 200
    assert fake_saml.last.processed_with == "req-1"
    assert service.kwargs["oidc_issuer"] == SAML_ISS
    assert service.kwargs["email_trusted"] is False


def test_acs_without_request_cookie_is_refused(monkeypatch, fake_saml) -> None:
    r = _client(monkeypatch, _Service()).post(
        "/api/v1/users/auth/saml/acs/", data={"SAMLResponse": "x"}, headers={"accept": "application/json"}
    )
    assert r.status_code == 401


def test_acs_refuses_a_replayed_assertion(monkeypatch, fake_saml) -> None:
    s = _settings()
    r = _client(monkeypatch, _Service(fresh=False)).post(
        "/api/v1/users/auth/saml/acs/",
        data={"SAMLResponse": "x"},
        cookies={saml.REQUEST_COOKIE: saml.sign_request_id(s, "req-1")},
        headers={"accept": "text/html"},
    )
    assert r.headers["location"] == "/auth/saml/callback#error=invalid_saml_response"
