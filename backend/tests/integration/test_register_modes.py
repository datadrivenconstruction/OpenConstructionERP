"""Self-registration modes (BUG-RBAC03 / BUG-RBAC04 fix).

The platform exposes ``POST /auth/register`` so a fresh install can be
bootstrapped. For internet-exposed deployments that endpoint becomes a
privacy leak — anyone with network reach lands a ``viewer`` token and can
list every project on the instance. The fix introduces the
``OE_REGISTRATION_MODE`` setting:

* ``open`` (default, backwards-compat) — anyone can register; new users are
  ``is_active=True`` and can log in immediately.
* ``email-verify`` — reserved for a future verify-by-email flow; today the
  account is created ``is_active=False`` (same as admin-approve).
* ``admin-approve`` — account created ``is_active=False``; an admin must
  flip it active via ``PATCH /users/{id}`` before login works.
* ``closed`` — registration is rejected with 403. Bootstrap path is still
  honoured: if no admin exists yet, the very first registrant is allowed
  and promoted to admin (otherwise nobody could log in to a fresh install).

Login already returns the same generic 401 for inactive accounts as for
bad credentials, so no enumeration leak is introduced — see
``UserService.login`` lines around the ``if not user.is_active`` guard.

These tests drive the service layer directly against per-test fresh
SQLite files. No demo seed runs, so the bootstrap admin path is exercised
deterministically.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest_asyncio.fixture
async def session():
    """Per-test fresh SQLite DB — guarantees no admin exists at t=0."""
    tmp_db = Path(tempfile.mkdtemp()) / "regmodes.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    import app.modules.users.models  # noqa: F401  — register the user table
    from app.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


@pytest.fixture(autouse=True)
def _restore_registration_mode():
    """Restore ``settings.registration_mode`` after every test in this module.

    The cached settings singleton is shared across the whole test session,
    so a test that mutates ``registration_mode`` to "closed" would leak
    that state into the next test file (e.g. test_register_bootstrap)
    and break unrelated assertions. This fixture snapshots the value
    before each test runs and rolls it back afterwards.
    """
    from app.config import get_settings

    settings = get_settings()
    saved = getattr(settings, "registration_mode", "open")
    yield
    settings.registration_mode = saved  # type: ignore[attr-defined]


def _payload(email: str):
    from app.modules.users.schemas import UserCreate

    return UserCreate(email=email, password="ModesTest99!", full_name="Mode Tester")


def _service(session: AsyncSession, *, mode: str = "open"):
    """Build a UserService whose settings reflect the requested mode.

    The autouse ``_restore_registration_mode`` fixture rolls the field
    back to its prior value after each test, so the cached singleton is
    safe to mutate here.
    """
    from app.config import get_settings
    from app.modules.users.service import UserService

    settings = get_settings()
    settings.registration_mode = mode  # type: ignore[attr-defined]
    return UserService(session, settings)


# ─────────────────────────────────────────────────────────────────────────
# open mode — backwards-compat, every registrant immediately active
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_mode_first_registrant_is_admin_and_active(session):
    """open + no admin → first user is admin and active (bootstrap)."""
    svc = _service(session, mode="open")
    email = f"first-{uuid.uuid4().hex[:6]}@modes.io"

    user = await svc.register(_payload(email))
    await session.commit()

    assert user.role == "admin"
    assert user.is_active is True


@pytest.mark.asyncio
async def test_open_mode_subsequent_registrant_is_viewer_and_active(session):
    """open + admin exists → next user is viewer but immediately active."""
    svc = _service(session, mode="open")
    await svc.register(_payload(f"first-{uuid.uuid4().hex[:6]}@modes.io"))
    await session.commit()

    second = await svc.register(_payload(f"second-{uuid.uuid4().hex[:6]}@modes.io"))
    await session.commit()

    assert second.role == "viewer"
    assert second.is_active is True


# ─────────────────────────────────────────────────────────────────────────
# admin-approve mode — gated, registrant lands inactive
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_approve_bootstrap_admin_still_active(session):
    """admin-approve + no admin → first registrant is active (bootstrap escape).

    Without this, a fresh install configured with admin-approve has nobody
    who can ever approve anyone — chicken and egg.
    """
    svc = _service(session, mode="admin-approve")
    user = await svc.register(_payload(f"boot-{uuid.uuid4().hex[:6]}@modes.io"))
    await session.commit()

    assert user.role == "admin"
    assert user.is_active is True


@pytest.mark.asyncio
async def test_admin_approve_subsequent_registrant_is_inactive(session):
    """admin-approve + admin exists → new viewer arrives ``is_active=False``."""
    svc = _service(session, mode="admin-approve")
    await svc.register(_payload(f"first-{uuid.uuid4().hex[:6]}@modes.io"))
    await session.commit()

    second = await svc.register(_payload(f"second-{uuid.uuid4().hex[:6]}@modes.io"))
    await session.commit()

    assert second.role == "viewer"
    assert second.is_active is False


@pytest.mark.asyncio
async def test_admin_approve_inactive_user_cannot_login(session):
    """admin-approve registrant cannot log in until activated.

    ``login`` returns the generic 401 for inactive accounts (same as bad
    creds) so there is no enumeration leak.
    """
    from app.modules.users.schemas import LoginRequest

    svc = _service(session, mode="admin-approve")
    # Bootstrap admin (active)
    await svc.register(_payload(f"boot-{uuid.uuid4().hex[:6]}@modes.io"))
    await session.commit()

    # Self-registered viewer (inactive)
    email = f"second-{uuid.uuid4().hex[:6]}@modes.io"
    inactive = await svc.register(_payload(email))
    await session.commit()
    assert inactive.is_active is False

    with pytest.raises(HTTPException) as exc:
        await svc.login(LoginRequest(email=email, password="ModesTest99!"))
    assert exc.value.status_code == 401


# ─────────────────────────────────────────────────────────────────────────
# email-verify mode — currently behaves like admin-approve
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_email_verify_mode_creates_inactive_user(session):
    """email-verify mirrors admin-approve until the verify-email flow lands."""
    svc = _service(session, mode="email-verify")
    await svc.register(_payload(f"first-{uuid.uuid4().hex[:6]}@modes.io"))
    await session.commit()

    second = await svc.register(_payload(f"second-{uuid.uuid4().hex[:6]}@modes.io"))
    await session.commit()

    assert second.is_active is False


# ─────────────────────────────────────────────────────────────────────────
# closed mode — refuses every self-registration after bootstrap
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_closed_mode_allows_bootstrap_admin(session):
    """closed + no admin → first registrant still goes through (bootstrap)."""
    svc = _service(session, mode="closed")
    user = await svc.register(_payload(f"boot-{uuid.uuid4().hex[:6]}@modes.io"))
    await session.commit()

    assert user.role == "admin"
    assert user.is_active is True


@pytest.mark.asyncio
async def test_closed_mode_rejects_after_bootstrap(session):
    """closed + admin exists → 403 forbidden, account NOT created."""
    svc = _service(session, mode="closed")
    await svc.register(_payload(f"boot-{uuid.uuid4().hex[:6]}@modes.io"))
    await session.commit()

    target_email = f"second-{uuid.uuid4().hex[:6]}@modes.io"
    with pytest.raises(HTTPException) as exc:
        await svc.register(_payload(target_email))
    assert exc.value.status_code == 403

    # Confirm the row was not silently inserted
    from app.modules.users.repository import UserRepository

    repo = UserRepository(session)
    assert (await repo.get_by_email(target_email)) is None


@pytest.mark.asyncio
async def test_closed_mode_does_not_leak_existing_emails(session):
    """closed mode returns 403 BEFORE the email-exists check.

    A registered email being rejected with 409 ("Email already registered")
    while an unregistered one is rejected with 403 would let an attacker
    enumerate accounts. The fix order — gate first, exists check second —
    means both responses are identical 403s.
    """
    svc = _service(session, mode="closed")

    # Bootstrap admin so we are past the bootstrap escape
    boot_email = f"boot-{uuid.uuid4().hex[:6]}@modes.io"
    await svc.register(_payload(boot_email))
    await session.commit()

    # Re-registering the same email and a new email should both 403
    with pytest.raises(HTTPException) as exc_existing:
        await svc.register(_payload(boot_email))
    with pytest.raises(HTTPException) as exc_new:
        await svc.register(_payload(f"other-{uuid.uuid4().hex[:6]}@modes.io"))

    assert exc_existing.value.status_code == 403
    assert exc_new.value.status_code == 403
