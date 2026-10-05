# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a manager lists only themselves (gate E7).

``users.list`` and ``users.read`` are manager permissions and every learner on
an academy box is a manager, so the user directory handed one learner every
other learner's name and email. In academy mode a non-admin now sees their own
row only, and another user's record answers 404 as if it did not exist. Admins
keep the full directory, and with the flag off nothing changes.

The router functions are called directly with every query argument spelled out,
since outside a request FastAPI leaves the ``Query`` defaults unresolved.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.modules.users.router import get_user, get_user_module_access, list_users
from app.modules.users.service import UserService
from tests.pg.academy_isolation.rows import make_user, payload_of

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _list(session, caller, *, offset: int = 0, is_active: bool | None = None) -> list[str]:
    rows = await list_users(
        viewer_id=str(caller.id),
        current_user=payload_of(caller),
        service=UserService(session, get_settings()),
        offset=offset,
        limit=500,
        is_active=is_active,
    )
    return [r.email for r in rows]


async def _get(session, caller, target):
    return await get_user(
        user_id=target.id,
        viewer_id=str(caller.id),
        current_user=payload_of(caller),
        service=UserService(session, get_settings()),
    )


async def _module_access(session, caller, target):
    return await get_user_module_access(
        user_id=target.id,
        current_user=payload_of(caller),
        service=UserService(session, get_settings()),
    )


async def test_list_users_returns_self(pg_session, academy) -> None:
    academy(True)
    alice = await make_user(pg_session, name="Alice Learner")
    bob = await make_user(pg_session, name="Bob Learner")

    assert await _list(pg_session, bob) == [bob.email]
    assert alice.email not in await _list(pg_session, bob, is_active=True)
    # Paging past the one row returns nothing rather than other people.
    assert await _list(pg_session, bob, offset=1) == []


async def test_get_other_user_is_404(pg_session, academy) -> None:
    academy(True)
    alice = await make_user(pg_session)
    bob = await make_user(pg_session)

    with pytest.raises(HTTPException) as caught:
        await _get(pg_session, bob, alice)
    assert (caught.value.status_code, caught.value.detail) == (404, "User not found")
    with pytest.raises(HTTPException) as access:
        await _module_access(pg_session, bob, alice)
    assert access.value.status_code == 404
    # The allow side of the same gate: a learner still reads their own record.
    assert (await _get(pg_session, bob, bob)).email == bob.email
    await _module_access(pg_session, bob, bob)


async def test_admin_still_lists_all(pg_session, academy) -> None:
    academy(True)
    alice = await make_user(pg_session)
    bob = await make_user(pg_session)
    operator = await make_user(pg_session, role="admin")

    listed = await _list(pg_session, operator)
    assert {alice.email, bob.email, operator.email} <= set(listed)
    assert (await _get(pg_session, operator, alice)).email == alice.email


async def test_academy_off_unchanged(pg_session, academy) -> None:
    academy(False)
    alice = await make_user(pg_session)
    bob = await make_user(pg_session)

    listed = await _list(pg_session, bob)
    expected, _ = await UserService(pg_session, get_settings()).list_users(offset=0, limit=500)
    assert listed == [u.email for u in expected]
    assert alice.email in listed
    assert (await _get(pg_session, bob, alice)).email == alice.email
    await _module_access(pg_session, bob, alice)
