"""Data-integrity: deleting / restoring a BOQ must scrub orphaned position refs.

Schedule activities can reference BOQ positions through the
``Activity.boq_position_ids`` JSON array.  ``delete_position`` already
removes the soon-to-be-deleted ids from those arrays via
``BOQService._scrub_activity_position_refs`` so an activity never holds a
dangling reference to a position that no longer exists.

Two sibling paths wipe positions WITHOUT going through ``delete_position``
and so previously left those JSON references dangling:

* ``delete_boq`` - the DB CASCADE removes every position row, but the
  Activity JSON arrays keep the (now-orphaned) ids.
* ``restore_snapshot`` - every position is deleted and recreated with a
  FRESH UUID, so any pre-existing reference can never resolve again.

These tests pin the fix: both paths now capture the position ids up front
and forward them to ``_scrub_activity_position_refs``.  The scrub helper
itself is mocked (it touches the Schedule module + DB); we only assert it
is invoked with the captured ids - the per-row JSON cleanup is already
covered by the schedule integration tests.

The session is a pure mock, so no PostgreSQL is required to run these.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.boq.service import BOQService


def _scalars_result(values: list) -> MagicMock:
    """Build a mock SQLAlchemy ``Result`` whose ``.scalars().all()`` is ``values``."""
    scalars = MagicMock()
    scalars.all.return_value = values
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


@pytest.mark.asyncio
async def test_delete_boq_scrubs_orphaned_position_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete_boq must forward its position ids (and project id) to the scrub."""
    boq_id = uuid.uuid4()
    project_id = uuid.uuid4()
    pos_a = uuid.uuid4()
    pos_b = uuid.uuid4()

    session = MagicMock()
    # The position-id SELECT is the only ``execute`` the method issues
    # before the scrub; return both ids via the .scalars().all() chain.
    session.execute = AsyncMock(return_value=_scalars_result([pos_a, pos_b]))

    service = BOQService(session)
    # get_boq -> boq_repo.get_by_id (session.get). Hand back a lightweight
    # stand-in carrying just project_id (all delete_boq reads off it).
    service.boq_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(project_id=project_id))
    service.boq_repo.delete = AsyncMock()
    # The lock guard is one more read on the session; stub it so the
    # ``execute`` above stays the delete's own position-id SELECT. The locked
    # case has its own test on a real database
    # (tests/modules/boq/test_a_locked_bill_cannot_be_deleted.py).
    writable = AsyncMock()
    service._ensure_boq_writable = writable  # type: ignore[method-assign]
    scrub = AsyncMock()
    service._scrub_activity_position_refs = scrub  # type: ignore[method-assign]
    # The generated budgets are released on a real database
    # (tests/modules/boq/test_deleting_a_bill_takes_its_budgets_with_it.py).
    release = AsyncMock()
    service._release_generated_budgets = release  # type: ignore[method-assign]
    monkeypatch.setattr("app.modules.boq.service._safe_publish", AsyncMock())

    await service.delete_boq(boq_id)

    writable.assert_awaited_once_with(boq_id)
    release.assert_awaited_once_with(boq_id, project_id, [str(pos_a), str(pos_b)])
    scrub.assert_awaited_once()
    args, kwargs = scrub.call_args
    # boq_id positional, the captured ids as strings, project id forwarded
    # explicitly (the BOQ row is gone after delete, so the helper cannot
    # re-resolve it).
    assert args[0] == boq_id
    assert args[1] == [str(pos_a), str(pos_b)]
    assert kwargs.get("project_id") == project_id
    service.boq_repo.delete.assert_awaited_once_with(boq_id)


@pytest.mark.asyncio
async def test_delete_boq_skips_scrub_when_no_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty BOQ has nothing to scrub - the helper must not be called."""
    boq_id = uuid.uuid4()
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalars_result([]))

    service = BOQService(session)
    service.boq_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(project_id=uuid.uuid4()))
    service.boq_repo.delete = AsyncMock()
    writable = AsyncMock()
    service._ensure_boq_writable = writable  # type: ignore[method-assign]
    scrub = AsyncMock()
    service._scrub_activity_position_refs = scrub  # type: ignore[method-assign]
    service._release_generated_budgets = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr("app.modules.boq.service._safe_publish", AsyncMock())

    await service.delete_boq(boq_id)

    scrub.assert_not_awaited()
    service.boq_repo.delete.assert_awaited_once_with(boq_id)


@pytest.mark.asyncio
async def test_restore_snapshot_scrubs_old_position_refs() -> None:
    """restore_snapshot must scrub the OLD position ids before recreating.

    Restore deletes every position and recreates with fresh UUIDs, so the
    old ids must be scrubbed out of the Activity JSON arrays or they dangle
    forever.
    """
    boq_id = uuid.uuid4()
    old_a = uuid.uuid4()
    old_b = uuid.uuid4()

    # A snapshot whose payload has no positions/markups: restore wipes the
    # current rows then rebuilds nothing, which keeps the mock simple while
    # still exercising the capture + scrub of the existing rows.
    snap = SimpleNamespace(snapshot_data={"positions": [], "markups": []})

    session = MagicMock()

    # ``execute`` is called several times. The FIRST call loads the snapshot
    # (scalar_one_or_none), the SECOND is the old-position-id SELECT
    # (.scalars().all()); the remaining calls are the two DELETEs. Drive them
    # in order via side_effect.
    snap_result = MagicMock()
    snap_result.scalar_one_or_none.return_value = snap
    session.execute = AsyncMock(
        side_effect=[
            snap_result,  # load snapshot
            _scalars_result([old_a, old_b]),  # capture old position ids
            MagicMock(),  # delete Position
            MagicMock(),  # delete BOQMarkup
        ]
    )
    session.flush = AsyncMock()

    service = BOQService(session)
    # The lock guard is one more read on the session; stub it so the
    # ``execute`` sequence above stays the restore's own. The locked case has
    # its own test on a real database
    # (tests/modules/boq/test_a_locked_bill_refuses_restore_and_duplicate.py).
    writable = AsyncMock()
    service._ensure_boq_writable = writable  # type: ignore[method-assign]
    scrub = AsyncMock()
    service._scrub_activity_position_refs = scrub  # type: ignore[method-assign]
    # restore_snapshot ends by reloading the BOQ for serialization - stub it.
    service.get_boq_with_positions = AsyncMock(return_value=SimpleNamespace(id=boq_id))

    await service.restore_snapshot(boq_id, uuid.uuid4())

    writable.assert_awaited_once_with(boq_id)
    scrub.assert_awaited_once()
    args, _kwargs = scrub.call_args
    # The BOQ survives a restore, so the helper resolves project scope from
    # boq_id itself - only (boq_id, old_ids) are passed positionally.
    assert args[0] == boq_id
    assert args[1] == [str(old_a), str(old_b)]
