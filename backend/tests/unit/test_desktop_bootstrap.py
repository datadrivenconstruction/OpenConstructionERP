"""Desktop first-run + bootstrap flow.

Covers the backend half of the desktop first-run contract:

    GET  /api/v1/auth/first-run        - public status, never errors
    POST /api/v1/auth/desktop-bootstrap - auto-provision / re-auth local owner

Cases:
    * first-run shape on an empty DB
    * bootstrap creates the local admin owner and returns a token pair
    * a second bootstrap reuses the same owner row (no duplicate)
    * bootstrap is 403 when desktop mode is off
    * bootstrap is 403 when a real registered user exists but no local owner
    * seeded demo accounts (``*@openconstructionerp.com``) do not flip
      ``fresh_install`` to False

These tests drive the service layer directly against a transaction-isolated
PostgreSQL session (``tests._pg.transactional_session``) so neither the
persistent dev DB nor the demo-seed lifespan taints the result. Desktop mode is
toggled via ``monkeypatch`` of the ``OE_DESKTOP`` environment variable.

NOTE: DB-backed pytest on Windows can be flaky under whole-suite parallelism
(asyncpg loop binding); each test here is self-contained and was verified
passing when this file is run in isolation.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session

OWNER_EMAIL = "owner@openestimate.local"


@pytest_asyncio.fixture
async def session():
    """Transaction-isolated PostgreSQL session - empty at t=0."""
    async with transactional_session() as s:
        yield s


def _service(session: AsyncSession):
    from app.config import get_settings
    from app.modules.users.service import UserService

    return UserService(session, get_settings())


def _register_payload(email: str):
    from app.modules.users.schemas import UserCreate

    return UserCreate(email=email, password="RealUser1234", full_name="Real User")


# ── desktop_mode helper ─────────────────────────────────────────────────────


def test_desktop_mode_env_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    """``desktop_mode()`` reads OE_DESKTOP each call (no settings cache)."""
    from app.config import desktop_mode

    monkeypatch.delenv("OE_DESKTOP", raising=False)
    assert desktop_mode() is False

    monkeypatch.setenv("OE_DESKTOP", "1")
    assert desktop_mode() is True

    monkeypatch.setenv("OE_DESKTOP", "true")
    assert desktop_mode() is True

    monkeypatch.setenv("OE_DESKTOP", "0")
    assert desktop_mode() is False


# ── first-run status (service layer) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_run_shape_on_empty_db(session: AsyncSession) -> None:
    """Empty DB: fresh install, no local account, onboarding flag is None."""
    status = await _service(session).first_run_status(is_desktop=True)

    assert status.desktop_mode is True
    assert status.fresh_install is True
    assert status.has_local_account is False
    assert status.onboarding_completed is None


@pytest.mark.asyncio
async def test_first_run_desktop_mode_reflects_arg(session: AsyncSession) -> None:
    """``is_desktop`` is passed straight through to the response."""
    status = await _service(session).first_run_status(is_desktop=False)
    assert status.desktop_mode is False


# ── bootstrap: create + reuse ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_creates_admin_owner_and_returns_tokens(session: AsyncSession) -> None:
    """First bootstrap creates the admin owner and mints a token pair."""
    from app.modules.users.repository import UserRepository

    svc = _service(session)
    tokens = await svc.desktop_bootstrap()
    await session.commit()

    assert tokens.access_token
    assert tokens.refresh_token
    assert tokens.token_type == "bearer"
    assert tokens.expires_in > 0

    owner = await UserRepository(session).get_by_email(OWNER_EMAIL)
    assert owner is not None
    assert owner.role == "admin"
    assert owner.is_active is True
    assert owner.full_name == "Workspace Owner"
    assert (owner.metadata_ or {}).get("local_desktop") is True

    # The minted access token carries the owner's identity.
    from jose import jwt

    from app.config import get_settings

    s = get_settings()
    claims = jwt.decode(tokens.access_token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    assert claims["sub"] == str(owner.id)
    assert claims["email"] == OWNER_EMAIL
    assert claims["role"] == "admin"


@pytest.mark.asyncio
async def test_second_bootstrap_reuses_owner(session: AsyncSession) -> None:
    """A second bootstrap finds the same owner - no duplicate row."""
    from app.modules.users.repository import UserRepository

    svc = _service(session)

    first = await svc.desktop_bootstrap()
    await session.commit()
    repo = UserRepository(session)
    owner1 = await repo.get_by_email(OWNER_EMAIL)
    assert owner1 is not None

    second = await svc.desktop_bootstrap()
    await session.commit()
    owner2 = await repo.get_by_email(OWNER_EMAIL)
    assert owner2 is not None

    assert owner1.id == owner2.id
    # Fresh tokens issued for the same user both times.
    assert first.access_token and second.access_token

    # Exactly one owner row.
    users, _ = await repo.list_all(limit=500)
    owner_rows = [u for u in users if u.email == OWNER_EMAIL]
    assert len(owner_rows) == 1


@pytest.mark.asyncio
async def test_first_run_after_bootstrap_reports_local_account(session: AsyncSession) -> None:
    """After bootstrap: has_local_account True, still fresh (owner excluded)."""
    svc = _service(session)
    await svc.desktop_bootstrap()
    await session.commit()

    status = await svc.first_run_status(is_desktop=True)
    assert status.has_local_account is True
    # The local owner is excluded from "real" users, so still fresh.
    assert status.fresh_install is True
    assert status.onboarding_completed is False


# ── router-level guards (403s) ──────────────────────────────────────────────


class _FakeClient:
    host = "127.0.0.1"


class _FakeRequest:
    """Minimal stand-in for fastapi.Request for the loopback guard test."""

    def __init__(self, host: str | None = "127.0.0.1") -> None:
        self.client = _FakeClient() if host is not None else None
        if host is not None:
            self.client.host = host


@pytest.mark.asyncio
async def test_bootstrap_403_when_desktop_mode_off(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The router endpoint refuses to run when desktop mode is off."""
    from app.modules.users import router as users_router

    monkeypatch.delenv("OE_DESKTOP", raising=False)

    with pytest.raises(HTTPException) as exc:
        await users_router.desktop_bootstrap(
            request=_FakeRequest("127.0.0.1"),
            service=_service(session),
        )
    assert exc.value.status_code == 403
    assert "desktop app" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_bootstrap_403_when_real_user_exists_and_no_owner(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A workspace with a real registered user but no owner is off-limits."""
    from app.modules.users import router as users_router

    monkeypatch.setenv("OE_DESKTOP", "1")

    # A real human registers (no local owner row yet).
    svc = _service(session)
    real = await svc.register(_register_payload(f"human-{uuid.uuid4().hex[:6]}@example.com"))
    await session.commit()
    assert real.role == "admin"  # first registrant bootstraps to admin

    with pytest.raises(HTTPException) as exc:
        await users_router.desktop_bootstrap(
            request=_FakeRequest("127.0.0.1"),
            service=_service(session),
        )
    assert exc.value.status_code == 403
    assert "registered users" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_bootstrap_403_when_not_loopback(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-loopback client host is rejected even in desktop mode."""
    from app.modules.users import router as users_router

    monkeypatch.setenv("OE_DESKTOP", "1")

    with pytest.raises(HTTPException) as exc:
        await users_router.desktop_bootstrap(
            request=_FakeRequest("203.0.113.7"),
            service=_service(session),
        )
    assert exc.value.status_code == 403
    assert "local machine" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_bootstrap_allowed_after_owner_even_with_real_user(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the local owner exists, bootstrap re-auth is allowed.

    Even when a real registered user is also present, has_local_account is
    True so the owner can keep logging in through the desktop path.
    """
    from app.modules.users import router as users_router

    monkeypatch.setenv("OE_DESKTOP", "1")

    svc = _service(session)
    await svc.desktop_bootstrap()  # creates owner
    await session.commit()
    await svc.register(_register_payload(f"human-{uuid.uuid4().hex[:6]}@example.com"))
    await session.commit()

    tokens = await users_router.desktop_bootstrap(
        request=_FakeRequest("127.0.0.1"),
        service=_service(session),
    )
    assert tokens.access_token


# ── demo seed must not break fresh_install ──────────────────────────────────


# ── HTTP route mount (/api/v1/auth/...) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_routes_mounted_under_api_v1_auth(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two routes resolve at /api/v1/auth/* and round-trip over HTTP.

    Mounts only the dedicated ``desktop_auth_router`` at the contract prefix
    and overrides the DB session with our transaction-isolated one, so this
    verifies the path AND the full request -> service -> response wiring
    (including the loopback relaxation when ``request.client`` is None under
    the ASGI transport) without standing up the whole app lifespan.
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.dependencies import get_session
    from app.modules.users.router import desktop_auth_router

    monkeypatch.setenv("OE_DESKTOP", "1")

    app = FastAPI()
    app.include_router(desktop_auth_router, prefix="/api/v1/auth")

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # first-run on an empty DB
        r1 = await ac.get("/api/v1/auth/first-run")
        assert r1.status_code == 200, r1.text
        body = r1.json()
        assert body["desktop_mode"] is True
        assert body["fresh_install"] is True
        assert body["has_local_account"] is False
        assert body["onboarding_completed"] is None

        # bootstrap mints tokens
        r2 = await ac.post("/api/v1/auth/desktop-bootstrap")
        assert r2.status_code == 200, r2.text
        tok = r2.json()
        assert tok["access_token"] and tok["refresh_token"]
        assert tok["token_type"] == "bearer"

        # first-run now reports the local account
        r3 = await ac.get("/api/v1/auth/first-run")
        assert r3.json()["has_local_account"] is True


@pytest.mark.asyncio
async def test_demo_seed_emails_do_not_break_fresh_install(session: AsyncSession) -> None:
    """Seeded demo accounts (*@openconstructionerp.com) keep the DB fresh."""
    from app.modules.users.models import User
    from app.modules.users.service import hash_password

    demo = User(
        id=uuid.uuid4(),
        email="demo@openconstructionerp.com",
        hashed_password=hash_password("DemoPass1234!"),
        full_name="Demo User",
        role="admin",
        locale="en",
        is_active=True,
        metadata_={},
    )
    session.add(demo)
    await session.commit()

    status = await _service(session).first_run_status(is_desktop=True)
    assert status.fresh_install is True, "Demo seed must not flip fresh_install to False"
    assert status.has_local_account is False
