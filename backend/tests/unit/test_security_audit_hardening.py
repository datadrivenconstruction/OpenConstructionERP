"""Regression tests for the application-level findings of the production security audit.

Each block pins one finding: demo-mode identity redaction on user-returning
endpoints, field magic-link secrets independent of APP_DEBUG, the hourly
registration cap and the out-of-band reset email, and X-Forwarded-For trusted
only from a configured proxy. No database: handlers are called directly with
small fakes so the file runs in seconds.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import BackgroundTasks
from starlette.requests import Request

import app.config as app_config
from app.core import rate_limiter
from app.core.demo_privacy import anonymize_email, redact_identity


def _request(peer: str | None, headers: dict[str, str] | None = None) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (peer, 5000) if peer else None,
    }
    return Request(scope)


def _user_row(email: str, full_name: str, uid: uuid.UUID | None = None) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uid or uuid.uuid4(),
        email=email,
        full_name=full_name,
        role="editor",
        locale="en",
        is_active=True,
        last_login_at=None,
        timezone="UTC",
        measurement_system="metric",
        paper_size="A4",
        number_format="1,234.56",
        date_format="YYYY-MM-DD",
        currency_code="EUR",
        created_at=now,
        updated_at=now,
    )


# ── 1. Demo-mode redaction ──────────────────────────────────────────────────


class _FakeUserService:
    def __init__(self, user: SimpleNamespace) -> None:
        self.user = user

    async def get_user(self, user_id: uuid.UUID) -> SimpleNamespace:
        return self.user

    async def update_profile(self, user_id: uuid.UUID, **fields: Any) -> SimpleNamespace:
        return self.user

    async def list_users(self, **_: Any) -> tuple[list[SimpleNamespace], int]:
        return [self.user], 1


@pytest.mark.asyncio
async def test_get_user_by_id_is_redacted_in_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.users.router import get_user

    monkeypatch.setenv("OE_DEMO_MODE", "true")
    other = _user_row("alice.real@acme.com", "Alice Real")
    resp = await get_user(other.id, viewer_id=str(uuid.uuid4()), service=_FakeUserService(other))
    assert resp.email != "alice.real@acme.com"
    assert resp.email.endswith("@acme.com")
    assert resp.email == anonymize_email("alice.real@acme.com")
    assert resp.full_name == ""


@pytest.mark.asyncio
async def test_get_user_by_id_keeps_the_callers_own_record(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.users.router import get_user

    monkeypatch.setenv("OE_DEMO_MODE", "true")
    me = _user_row("me@acme.com", "Me Myself")
    resp = await get_user(me.id, viewer_id=str(me.id), service=_FakeUserService(me))
    assert resp.email == "me@acme.com"
    assert resp.full_name == "Me Myself"


@pytest.mark.asyncio
async def test_get_user_is_untouched_outside_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.users.router import get_user

    monkeypatch.delenv("OE_DEMO_MODE", raising=False)
    other = _user_row("alice.real@acme.com", "Alice Real")
    resp = await get_user(other.id, viewer_id=str(uuid.uuid4()), service=_FakeUserService(other))
    assert resp.email == "alice.real@acme.com"
    assert resp.full_name == "Alice Real"


@pytest.mark.asyncio
async def test_update_and_list_echo_are_redacted_in_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.users.router import list_users, update_user
    from app.modules.users.schemas import UserAdminUpdate

    monkeypatch.setenv("OE_DEMO_MODE", "1")
    other = _user_row("bob@corp.io", "Bob Private")
    svc = _FakeUserService(other)
    viewer = str(uuid.uuid4())
    patched = await update_user(other.id, UserAdminUpdate(), viewer_id=viewer, service=svc)
    listed = await list_users(viewer_id=viewer, service=svc, offset=0, limit=50, is_active=None)
    for resp in (patched, listed[0]):
        assert resp.email == anonymize_email("bob@corp.io")
        assert resp.full_name == ""


def test_redact_identity_is_a_noop_for_the_viewer_and_outside_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    uid = uuid.uuid4()
    monkeypatch.setenv("OE_DEMO_MODE", "true")
    assert redact_identity({"email": "a@b.c", "full_name": "A"}, subject_id=uid, viewer_id=str(uid)) == {
        "email": "a@b.c",
        "full_name": "A",
    }
    monkeypatch.delenv("OE_DEMO_MODE")
    assert redact_identity({"email": "a@b.c", "full_name": "A"}, subject_id=uid, viewer_id=None)["full_name"] == "A"


def test_roster_user_search_is_narrowed_to_the_project_in_demo_mode() -> None:
    from app.modules.teams.roster_service import RosterService

    svc = RosterService.__new__(RosterService)
    everyone = str(svc._users_stmt("alice").compile(compile_kwargs={"literal_binds": True}))
    nobody = str(svc._users_stmt("alice", set()).compile(compile_kwargs={"literal_binds": True}))
    some = str(svc._users_stmt("alice", {uuid.uuid4()}).compile())
    assert " IN " not in everyone.upper()
    assert "false" in nobody.lower() or "0 = 1" in nobody or "1 != 1" in nobody
    assert " IN " in some.upper()


# ── 2. Field magic-link secrets ─────────────────────────────────────────────


def test_dev_auth_secrets_need_the_explicit_flag_not_debug() -> None:
    from app.modules.field_diary.service import dev_auth_secrets_exposed

    debug_only = SimpleNamespace(app_debug=True, app_env="development", expose_dev_auth_secrets=False)
    flagged = SimpleNamespace(app_debug=False, app_env="development", expose_dev_auth_secrets=True)
    flagged_prod = SimpleNamespace(app_debug=True, app_env="production", expose_dev_auth_secrets=True)
    assert dev_auth_secrets_exposed(debug_only) is False
    assert dev_auth_secrets_exposed(flagged) is True
    assert dev_auth_secrets_exposed(flagged_prod) is False


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        obj.id = uuid.uuid4()


class _FakeFieldService:
    async def request_magic_link(self, **_: Any) -> tuple[Any, str, str]:
        return SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(minutes=15)), "plain-token-xyz", "123456"


@pytest.mark.asyncio
async def test_magic_link_hides_secrets_with_debug_on_and_provisions_a_viewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.field_diary.router import request_magic_link
    from app.modules.field_diary.schemas import FieldMagicLinkRequest

    fake_settings = SimpleNamespace(app_debug=True, app_env="development", expose_dev_auth_secrets=False)
    monkeypatch.setattr(app_config, "get_settings", lambda: fake_settings)
    session = _FakeSession()
    resp = await request_magic_link(
        FieldMagicLinkRequest(phone="+491701234567", project_id=uuid.uuid4()),
        request=_request("203.0.113.9"),
        session=session,
        service=_FakeFieldService(),
    )
    assert resp.accepted is True
    assert resp.dev_token is None
    assert resp.dev_pin is None
    assert session.added and session.added[0].role == "viewer"


def test_mock_sms_does_not_log_or_keep_the_secret_by_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.modules.field_diary import service as fd

    fake_settings = SimpleNamespace(app_debug=True, app_env="development", expose_dev_auth_secrets=False)
    monkeypatch.setattr(app_config, "get_settings", lambda: fake_settings)
    fd.clear_sms_log()
    with caplog.at_level("INFO"):
        fd._send_sms("+491701234567", "link https://x/f/SECRET-TOKEN\nPIN: 654321")
    assert fd.get_sms_log() == []
    assert "SECRET-TOKEN" not in caplog.text
    assert "654321" not in caplog.text


def test_app_debug_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_DEBUG", "OE_APP_DEBUG"):
        monkeypatch.delenv(name, raising=False)
    s = app_config.Settings(_env_file=None, database_url="postgresql+asyncpg://x:y@localhost/z")
    assert s.app_debug is False


# ── 3. Registration cap and forgot-password timing ──────────────────────────


@pytest.mark.asyncio
async def test_register_hits_the_hourly_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    from app.modules.users import router as users_router
    from app.modules.users.schemas import UserCreate

    monkeypatch.setattr(users_router, "registration_limiter", rate_limiter.RateLimiter(2, 3600))
    monkeypatch.setattr(users_router, "login_limiter", rate_limiter.RateLimiter(1000, 60))

    class _Svc:
        async def register(self, data: Any, **_: Any) -> SimpleNamespace:
            return _user_row(data.email, "x")

    data = UserCreate(email="new@example.com", password="Str0ng-Passw0rd!", full_name="N")
    req = _request("198.51.100.7")
    await users_router.register(data, req, service=_Svc())
    await users_router.register(data, req, service=_Svc())
    with pytest.raises(HTTPException) as exc:
        await users_router.register(data, req, service=_Svc())
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_forgot_password_sends_the_email_after_the_response(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.users import service as users_service
    from app.modules.users.schemas import ForgotPasswordRequest

    sent: list[str] = []

    class _Email:
        async def send_password_reset(self, **kwargs: Any) -> SimpleNamespace:
            sent.append(kwargs["to"])
            return SimpleNamespace(ok=True)

    monkeypatch.setattr(users_service, "get_email_service", lambda: _Email())
    user = _user_row("known@example.com", "Known")

    class _Repo:
        async def get_by_email(self, email: str) -> SimpleNamespace | None:
            return user if email == "known@example.com" else None

    settings = SimpleNamespace(
        jwt_secret="x" * 40,
        jwt_algorithm="HS256",
        resolved_frontend_url="http://localhost:5173",
        app_debug=False,
    )
    svc = users_service.UserService.__new__(users_service.UserService)
    svc.settings = settings
    svc.user_repo = _Repo()

    bg = BackgroundTasks()
    known = await svc.forgot_password(ForgotPasswordRequest(email="known@example.com"), bg)
    unknown = await svc.forgot_password(ForgotPasswordRequest(email="nobody@example.com"), BackgroundTasks())
    assert known.message == unknown.message
    assert sent == []  # nothing on the request path
    await bg()
    assert sent == ["known@example.com"]


# ── 4. Trusted proxies ──────────────────────────────────────────────────────


@pytest.fixture
def _default_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        app_config,
        "get_settings",
        lambda: SimpleNamespace(trusted_proxies=rate_limiter._DEFAULT_TRUSTED_PROXIES),
    )


@pytest.mark.usefixtures("_default_proxies")
def test_xff_from_an_untrusted_peer_is_ignored() -> None:
    req = _request("203.0.113.50", {"X-Forwarded-For": "1.2.3.4", "X-Real-IP": "5.6.7.8"})
    assert rate_limiter.client_identifier(req) == "203.0.113.50"


@pytest.mark.usefixtures("_default_proxies")
def test_xff_from_a_trusted_proxy_takes_the_rightmost_untrusted_hop() -> None:
    # The client prepended a fake hop; nginx appended the real address.
    req = _request("172.18.0.2", {"X-Forwarded-For": "6.6.6.6, 198.51.100.23"})
    assert rate_limiter.client_identifier(req) == "198.51.100.23"
    chained = _request("127.0.0.1", {"X-Forwarded-For": "198.51.100.23, 10.0.0.5"})
    assert rate_limiter.client_identifier(chained) == "198.51.100.23"


@pytest.mark.usefixtures("_default_proxies")
def test_unparseable_peer_is_untrusted_and_missing_peer_is_unknown() -> None:
    assert rate_limiter.client_identifier(_request("testclient", {"X-Forwarded-For": "1.2.3.4"})) == "testclient"
    assert rate_limiter.client_identifier(_request(None, {"X-Forwarded-For": "1.2.3.4"})) == "unknown"


def test_trusted_proxies_setting_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_config, "get_settings", lambda: SimpleNamespace(trusted_proxies="203.0.113.0/24"))
    assert rate_limiter.client_identifier(_request("203.0.113.1", {"X-Forwarded-For": "8.8.8.8"})) == "8.8.8.8"
    # Loopback is not implied once the operator narrows the list.
    assert rate_limiter.client_identifier(_request("127.0.0.1", {"X-Forwarded-For": "8.8.8.8"})) == "127.0.0.1"
