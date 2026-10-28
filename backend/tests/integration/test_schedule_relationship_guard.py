"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression: relationship create + predecessor completion guard.

Two behaviours, both introduced with the dependency-unification work and both
only reproducible against a real (async) database, so they run against an
isolated throwaway PostgreSQL (``tests._pg.transactional_session``) rather than
a fake/in-memory session:

1. ``create_relationship`` must not raise. The handler rebuilds the successor's
   derived ``dependencies`` JSON mirror after inserting the edge, and that
   rebuild calls ``session.expire_all()``. Serialising the freshly-inserted
   ``ScheduleRelationship`` *after* the expire triggered an implicit async
   refresh from Pydantic's synchronous attribute access, which raised
   ``MissingGreenlet`` and surfaced as a 500. The fix snapshots the response
   model before the mirror rebuild. A fake session cannot reproduce the
   greenlet error, so the guard exercises the real handler against the real
   engine.

2. An activity cannot be marked complete while a canonical predecessor is still
   open: ``update_progress`` raises 409 naming the blocking predecessor, and
   succeeds once the predecessor is completed.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.modules.schedule import router as schedule_router
from app.modules.schedule.schemas import ActivityCreate, RelationshipCreate, ScheduleCreate
from app.modules.schedule.service import ScheduleService
from tests._pg import transactional_session


@pytest.mark.asyncio
async def test_relationship_create_and_completion_guard() -> None:
    # ``disable_fks`` lets us build a real Schedule + two real Activities with a
    # synthetic project_id, without seeding a full Project row through every
    # dependent migration. The guard logic reads the activity/relationship rows
    # directly, so FK enforcement is irrelevant to what is under test.
    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)

        schedule = await service.create_schedule(ScheduleCreate(project_id=uuid.uuid4(), name="Rel Guard Schedule"))
        pred = await service.create_activity(
            ActivityCreate(
                schedule_id=schedule.id,
                name="QA Predecessor",
                start_date="2026-07-01",
                end_date="2026-07-05",
            )
        )
        succ = await service.create_activity(
            ActivityCreate(
                schedule_id=schedule.id,
                name="QA Successor",
                start_date="2026-07-06",
                end_date="2026-07-10",
            )
        )
        pred_id, succ_id = pred.id, succ.id

        # Patch the owner-check to a no-op so the test stays focused on the
        # handler's create + mirror-rebuild path, not the JWT/RBAC stack.
        async def _noop_verify(*args, **kwargs):
            return None

        original = schedule_router._verify_schedule_owner
        schedule_router._verify_schedule_owner = _noop_verify  # type: ignore[assignment]
        try:
            # (1) MissingGreenlet regression: serialising the edge after the
            #     mirror rebuild's expire_all() used to raise. Must return a
            #     populated response model.
            response = await schedule_router.create_relationship(
                schedule_id=schedule.id,
                data=RelationshipCreate(
                    predecessor_id=pred_id,
                    successor_id=succ_id,
                    relationship_type="FS",
                    lag_days=0,
                ),
                session=session,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                service=service,
            )
        finally:
            schedule_router._verify_schedule_owner = original  # type: ignore[assignment]

        assert response.predecessor_id == pred_id
        assert response.successor_id == succ_id

        # (2a) Completing the successor while the predecessor is open is rejected
        #      with a 409 that names the blocking predecessor.
        with pytest.raises(HTTPException) as exc:
            await service.update_progress(succ_id, 100.0)
        assert exc.value.status_code == 409
        assert "predecessor" in str(exc.value.detail).lower()
        assert "QA Predecessor" in str(exc.value.detail)

        # (2b) Once the predecessor is complete, the successor can complete.
        done_pred = await service.update_progress(pred_id, 100.0)
        assert done_pred.status == "completed"
        done_succ = await service.update_progress(succ_id, 100.0)
        assert done_succ.status == "completed"
