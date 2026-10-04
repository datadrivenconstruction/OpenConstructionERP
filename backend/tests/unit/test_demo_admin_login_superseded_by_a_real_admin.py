# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The password-free Admin tile works until a real administrator exists.

``UserService.demo_login`` is the one sink both password-free paths reach: the
``/auth/demo-login`` endpoint behind the login page tiles, and the shortcut in
``UserService.login`` that lets a demo email through the normal form with any
password. Next to a real administrator a password-free admin session would be
handed to anyone who can reach the port, so it is refused there
(``app.core.demo_admin``).

This pins both halves on state the test owns rather than on whatever the
suite's shared database holds by the time it runs: ``transactional_session``
starts every test on an empty database and rolls it back afterwards, so "no
real administrator" is a fact of the fixture, not of test order. The predicate
the rule reads, ``UserRepository.has_admin``, is the real one throughout; only
the inputs it reads are arranged.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from tests._pg import transactional_session

DEMO_ADMIN = "demo@openconstructionerp.com"
DEMO_MANAGER = "manager@openconstructionerp.com"


@pytest_asyncio.fixture
async def session(monkeypatch):
    """An empty database holding the two seeded demo rows the tests sign in to."""
    import app.core.demo_login
    from app.modules.users.models import User
    from app.modules.users.service import hash_password

    # The two switches in front of the shortcut, set the way a self-installed
    # platform with the demo seed on has them. The developer's own data dir
    # must not decide whether the demo login is switched on.
    monkeypatch.setenv("SEED_DEMO", "true")
    monkeypatch.setattr(app.core.demo_login, "demo_login_enabled", lambda *_a, **_k: True)

    async with transactional_session() as s:
        for email, role in ((DEMO_ADMIN, "admin"), (DEMO_MANAGER, "manager")):
            s.add(
                User(
                    id=uuid.uuid4(),
                    email=email,
                    hashed_password=hash_password(uuid.uuid4().hex),
                    full_name=email.split("@")[0],
                    role=role,
                    locale="en",
                    is_active=True,
                    metadata_={},
                )
            )
        await s.commit()
        yield s


def _service(session):
    from app.config import get_settings
    from app.modules.users.service import UserService

    return UserService(session, get_settings())


async def _add_real_admin(session) -> None:
    from app.modules.users.models import User
    from app.modules.users.service import hash_password

    session.add(
        User(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("RealAdmin1234!"),
            full_name="Real Admin",
            role="admin",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.commit()


def _form(email: str):
    from app.modules.users.schemas import LoginRequest

    return LoginRequest(email=email, password="not-the-stored-password")


def _assert_superseded(exc: HTTPException) -> None:
    from app.core.demo_admin import DEMO_ADMIN_SUPERSEDED

    assert exc.status_code == 403, exc.detail
    assert isinstance(exc.detail, dict) and exc.detail.get("error") == DEMO_ADMIN_SUPERSEDED, exc.detail


@pytest.mark.asyncio
async def test_the_admin_tile_signs_in_while_nobody_has_taken_the_install_over(session) -> None:
    from app.modules.users.repository import UserRepository

    assert await UserRepository(session).has_admin() is False, "the fixture must start with no real administrator"

    tokens = await _service(session).demo_login(DEMO_ADMIN)
    assert tokens.access_token

    # The form shortcut reaches the same sink and gets the same answer.
    tokens = await _service(session).login(_form(DEMO_ADMIN))
    assert tokens.access_token


@pytest.mark.asyncio
async def test_a_real_administrator_ends_the_password_free_admin_session_on_both_paths(session) -> None:
    from app.modules.users.repository import UserRepository

    await _add_real_admin(session)
    assert await UserRepository(session).has_admin() is True

    with pytest.raises(HTTPException) as tile:
        await _service(session).demo_login(DEMO_ADMIN)
    _assert_superseded(tile.value)

    # Without this the rule could be stepped around by typing the demo email
    # into the normal login form with any password.
    with pytest.raises(HTTPException) as form:
        await _service(session).login(_form(DEMO_ADMIN))
    _assert_superseded(form.value)


@pytest.mark.asyncio
async def test_the_tiles_below_admin_keep_working_next_to_a_real_administrator(session) -> None:
    """The control: without it a refusal above could mean every demo login is refused."""
    await _add_real_admin(session)

    assert (await _service(session).demo_login(DEMO_MANAGER)).access_token
    assert (await _service(session).login(_form(DEMO_MANAGER))).access_token
