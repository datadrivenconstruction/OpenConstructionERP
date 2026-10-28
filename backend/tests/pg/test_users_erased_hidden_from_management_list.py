"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: an erased account leaves the user management list (issue #418).

Deleting a user anonymises the row in place rather than removing it. Projects
point at the user through ``owner_id`` and activity / audit rows through
``actor_id``, and the projects foreign key cascades, so a hard delete would take
the user's projects, BOQs and documents down with the account. The row survives,
stripped of every personal field and unable to authenticate.

What it must not do is stay on the management page. An administrator who deleted
a colleague kept seeing the account: no name, and an email reading
``deleted+<hash>@deleted.invalid``. It looks like a deletion that failed, and
deleting it again answers 404, because the erasure path refuses a row that is
already erased. So the list is what changes here, not the row.

The discriminating case is the suspended account. Erasure also flips
``is_active`` to False, so a filter written on ``is_active`` would satisfy the
two absence tests below and still be wrong: an account an administrator merely
suspended has to keep appearing under the inactive filter, which is the screen
they go to in order to reactivate it. That test passes both before and after the
fix on purpose - it is what pins the filter to ``deleted_at``.

Real PostgreSQL because the predicate has to reach the count subquery as well as
the page. Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest

from app.config import get_settings
from app.modules.users.models import User
from app.modules.users.service import UserService

PLACEHOLDER_DOMAIN = "@deleted.invalid"


def _user(*, email: str, role: str = "editor", is_active: bool = True) -> User:
    """One account row. The password hash is a placeholder - nothing logs in."""
    return User(
        email=email,
        hashed_password="x",
        full_name="Directory Person",
        role=role,
        is_active=is_active,
    )


async def _seed_workspace(session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """An admin, a member about to be deleted, a live member and a suspended one.

    Returns their ids in that order, all four still live.
    """
    suffix = uuid.uuid4().hex[:8]
    admin = _user(email=f"admin-{suffix}@example.com", role="admin")
    doomed = _user(email=f"doomed-{suffix}@example.com")
    live = _user(email=f"live-{suffix}@example.com")
    suspended = _user(email=f"suspended-{suffix}@example.com", is_active=False)
    session.add_all([admin, doomed, live, suspended])
    await session.flush()
    return admin.id, doomed.id, live.id, suspended.id


async def _erase(session, actor_id: uuid.UUID, target_id: uuid.UUID) -> None:
    """Delete an account through the real administrator path.

    Not a hand-written anonymised row: if the erasure model itself changes, these
    tests have to see it.
    """
    await UserService(session, get_settings()).admin_erase_account(actor_id, target_id)
    await session.flush()


async def _seed_and_erase(session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """The workspace above with the doomed member already deleted."""
    admin_id, doomed_id, live_id, suspended_id = await _seed_workspace(session)
    await _erase(session, admin_id, doomed_id)
    return admin_id, doomed_id, live_id, suspended_id


@pytest.mark.asyncio
async def test_erased_account_is_absent_from_the_management_list(pg_session) -> None:
    """The deleted colleague is gone from the page the administrator is looking at."""
    admin_id, erased_id, live_id, suspended_id = await _seed_and_erase(pg_session)

    rows, _total = await UserService(pg_session, get_settings()).list_users(limit=500)

    ids = {u.id for u in rows}
    assert erased_id not in ids, "the erased account must not be listed"
    assert {admin_id, live_id, suspended_id} <= ids, "the accounts that were not deleted must stay"
    assert [u.email for u in rows if u.email.endswith(PLACEHOLDER_DOMAIN)] == [], (
        "no anonymised placeholder address may reach the management list"
    )


@pytest.mark.asyncio
async def test_erased_account_is_absent_from_the_inactive_filter(pg_session) -> None:
    """Erasure deactivates the row, so the inactive view is where it would surface."""
    _admin_id, erased_id, _live_id, _suspended_id = await _seed_and_erase(pg_session)

    rows, _total = await UserService(pg_session, get_settings()).list_users(limit=500, is_active=False)

    assert erased_id not in {u.id for u in rows}, "the inactive filter must not resurrect it"
    assert [u.email for u in rows if u.email.endswith(PLACEHOLDER_DOMAIN)] == []


@pytest.mark.asyncio
async def test_suspended_account_is_still_listed_under_the_inactive_filter(pg_session) -> None:
    """A suspended account is not a deleted one and must stay reachable.

    This is the test that distinguishes a filter on ``deleted_at`` from a filter
    on ``is_active``: it holds before and after the fix, and the second of those
    two implementations would break it.
    """
    _admin_id, _erased_id, _live_id, suspended_id = await _seed_and_erase(pg_session)

    rows, _total = await UserService(pg_session, get_settings()).list_users(limit=500, is_active=False)

    assert suspended_id in {u.id for u in rows}, "an administrator must still be able to reactivate it"


@pytest.mark.asyncio
async def test_reported_total_drops_when_an_account_is_deleted(pg_session) -> None:
    """The count and the page apply the same predicate.

    ``list_users`` returns ``(rows, total)`` and the total feeds the pager. A
    filter applied to the fetch alone would leave a total that counts a row
    nobody can reach, so the last page of the directory comes back short.

    Measured as the difference across the deletion rather than against an
    absolute number: this lane shares one cluster with every other file in it,
    and an account another test committed is none of this test's business.
    """
    svc = UserService(pg_session, get_settings())
    admin_id, doomed_id, live_id, suspended_id = await _seed_workspace(pg_session)
    rows_before, total_before = await svc.list_users(limit=500)
    assert doomed_id in {u.id for u in rows_before}, "the account is listed while it is live"
    assert total_before == len(rows_before), "guard: the page has to hold every counted row"

    await _erase(pg_session, admin_id, doomed_id)

    rows_after, total_after = await svc.list_users(limit=500)
    assert total_after == total_before - 1, "deleting one account must lower the total by one"
    assert total_after == len(rows_after), "the count query counted a row the page does not return"
    assert doomed_id not in {u.id for u in rows_after}
    assert {admin_id, live_id, suspended_id} <= {u.id for u in rows_after}
