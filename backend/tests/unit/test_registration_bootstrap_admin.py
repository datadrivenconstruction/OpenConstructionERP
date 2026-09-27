"""Public registration hands out admin only on a genuinely fresh install.

The bootstrap used to ask a single question, "is there an active real admin?".
On a public server in ``open`` mode whose operator never registered, that
answer stayed "no" for as long as nobody claimed it, so strangers who reached
the form first became admins. The same happened on any install whose last
admin was deactivated: the next registrant, whoever it was, got admin.

The rule now is: admin only while no real user row exists at all (active or
inactive) and no real active admin exists. Seeded demo accounts
(``*@openconstructionerp.com``) and the desktop owner are not real users. Once
anybody real is on record a registrant never becomes admin, and the service
logs a warning naming the recovery command, ``promote-admin``, which is
covered here too.

The service layer runs against a transaction-isolated PostgreSQL session, so
the database is empty at t=0 and rolled back afterwards.
"""

from __future__ import annotations

import inspect
import logging
import re
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session

SERVICE_LOGGER = "app.modules.users.service"
DEMO_EMAILS = (
    "demo@openconstructionerp.com",
    "estimator@openconstructionerp.com",
    "manager@openconstructionerp.com",
)


@pytest_asyncio.fixture
async def session():
    """Transaction-isolated PostgreSQL session, empty at t=0."""
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _restore_registration_mode():
    """The settings object is a shared singleton; put the mode back after each test."""
    from app.config import get_settings

    settings = get_settings()
    saved = getattr(settings, "registration_mode", "open")
    yield
    settings.registration_mode = saved  # type: ignore[attr-defined]


@pytest.fixture
def service_warnings(caplog: pytest.LogCaptureFixture):
    """Capture WARNING records from the users service logger directly.

    The handler is attached to the service logger itself so the capture does
    not depend on whether app logging propagates to the root logger.
    """
    target = logging.getLogger(SERVICE_LOGGER)
    target.addHandler(caplog.handler)
    caplog.handler.setLevel(logging.WARNING)
    try:
        yield caplog
    finally:
        target.removeHandler(caplog.handler)


def _service(session: AsyncSession, *, mode: str = "open"):
    from app.config import get_settings
    from app.modules.users.service import UserService

    settings = get_settings()
    settings.registration_mode = mode  # type: ignore[attr-defined]
    return UserService(session, settings)


def _payload(email: str | None = None):
    from app.modules.users.schemas import UserCreate

    return UserCreate(
        email=email or f"reg-{uuid.uuid4().hex[:8]}@example.com",
        password="BootstrapAdmin99!",
        full_name="Registrant",
    )


async def _add_user(session: AsyncSession, email: str, *, role: str = "viewer", is_active: bool = True, **kw):
    from app.modules.users.models import User
    from app.modules.users.service import hash_password

    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("Existing1234!"),
        full_name="Existing",
        role=role,
        locale="en",
        is_active=is_active,
        metadata_=kw.pop("metadata_", {}),
        **kw,
    )
    session.add(user)
    await session.commit()
    return user


def _no_admin_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if "no active administrator" in r.getMessage()]


# ── fresh installs still bootstrap ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_fresh_install_first_registrant_is_admin(session, service_warnings):
    user = await _service(session).register(_payload())
    await session.commit()

    assert user.role == "admin"
    assert user.is_active is True
    assert _no_admin_warnings(service_warnings) == []


@pytest.mark.asyncio
async def test_demo_only_database_first_registrant_is_admin(session, service_warnings):
    """The three seeded demo accounts (one of them an admin) do not make an install non-fresh."""
    for email, role in zip(DEMO_EMAILS, ("admin", "estimator", "manager"), strict=True):
        await _add_user(session, email, role=role)

    user = await _service(session, mode="admin-approve").register(_payload())
    await session.commit()

    assert user.role == "admin"
    assert user.is_active is True
    assert _no_admin_warnings(service_warnings) == []


def test_demo_seeder_creates_only_demo_domain_accounts():
    """Every account the startup demo seeder creates must be exempt from the fresh check.

    A seeded account on any other domain would count as a real user, and every
    new install with demo data would then leave its first registrant without
    admin. The seeder is not run here (it opens its own sessions and installs
    projects), so its declared e-mails are read from source instead.
    """
    from app.main import _seed_demo_account

    emails = set(re.findall(r'"email":\s*"([^"]+)"', inspect.getsource(_seed_demo_account)))
    assert emails == set(DEMO_EMAILS), emails
    assert all(e.endswith("@openconstructionerp.com") for e in emails)


# ── any real user closes the bootstrap ──────────────────────────────────────


@pytest.mark.asyncio
async def test_inactive_real_user_means_registrant_is_not_admin(session, service_warnings):
    await _add_user(session, "former-admin@example.com", role="admin", is_active=False)

    user = await _service(session).register(_payload())
    await session.commit()

    assert user.role == "viewer"
    assert len(_no_admin_warnings(service_warnings)) == 1


@pytest.mark.asyncio
async def test_real_users_without_admin_give_no_admin_and_warn(session, service_warnings):
    await _add_user(session, "someone@example.com", role="editor")
    await _add_user(session, "another@example.com", role="viewer")

    user = await _service(session).register(_payload())
    await session.commit()

    assert user.role == "viewer"
    warnings = _no_admin_warnings(service_warnings)
    assert len(warnings) == 1
    assert "promote-admin" in warnings[0], "the warning must name the recovery step"


@pytest.mark.asyncio
async def test_second_registrant_after_bootstrap_is_not_admin(session, service_warnings):
    svc = _service(session)
    first = await svc.register(_payload())
    await session.commit()
    second = await svc.register(_payload())
    await session.commit()

    assert first.role == "admin"
    assert second.role == "viewer"
    assert _no_admin_warnings(service_warnings) == []


@pytest.mark.asyncio
async def test_desktop_owner_admin_keeps_registrant_from_admin(session, service_warnings):
    """The desktop owner is not a real user, but it is an admin, so nobody joins it as a second one."""
    from app.modules.users.repository import LOCAL_DESKTOP_OWNER_EMAIL

    await _add_user(session, LOCAL_DESKTOP_OWNER_EMAIL, role="admin", metadata_={"local_desktop": True})

    user = await _service(session).register(_payload())
    await session.commit()

    assert user.role == "viewer"
    assert _no_admin_warnings(service_warnings) == []


# ── closed mode ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_closed_mode_fresh_install_still_bootstraps(session):
    user = await _service(session, mode="closed").register(_payload())
    await session.commit()

    assert user.role == "admin"


@pytest.mark.asyncio
async def test_closed_mode_with_real_users_and_no_admin_is_403(session, service_warnings):
    from app.modules.users.repository import UserRepository

    await _add_user(session, "someone@example.com", role="viewer", is_active=False)
    target = f"late-{uuid.uuid4().hex[:6]}@example.com"

    with pytest.raises(HTTPException) as exc:
        await _service(session, mode="closed").register(_payload(target))

    assert exc.value.status_code == 403
    assert await UserRepository(session).get_by_email(target) is None
    assert len(_no_admin_warnings(service_warnings)) == 1


# ── recovery: promote-admin ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_promote_admin_makes_an_existing_user_an_active_admin(session):
    from app.cli import _promote_user_to_admin

    user = await _add_user(session, "Keeper@Example.com", role="viewer", is_active=False)

    message = await _promote_user_to_admin(session, "keeper@example.com")

    assert "now an active admin" in message
    assert user.role == "admin"
    assert user.is_active is True
    assert "already" in await _promote_user_to_admin(session, "keeper@example.com")


@pytest.mark.asyncio
async def test_promote_admin_refuses_missing_and_erased_accounts(session):
    from datetime import UTC, datetime

    from app.cli import _promote_user_to_admin

    await _add_user(session, "gone@example.com", deleted_at=datetime.now(UTC))

    with pytest.raises(LookupError):
        await _promote_user_to_admin(session, "nobody@example.com")
    with pytest.raises(LookupError):
        await _promote_user_to_admin(session, "gone@example.com")


def test_promote_admin_is_a_cli_command_with_a_data_dir():
    from app import cli

    args = cli._build_parser().parse_args(["promote-admin", "ops@example.com", "--data-dir", "/tmp/oe"])

    assert args.command == "promote-admin"
    assert args.email == "ops@example.com"
    assert args.data_dir is not None
