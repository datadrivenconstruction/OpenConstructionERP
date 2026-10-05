"""A schedule milestone announces itself when reached, once, and when reopened.

Payment plans fall due on programme milestones, so ``schedule.milestone.reached``
has to fire when one is actually completed on site and at no other time: not
twice for the same completion, not for ordinary work, and not for a schedule
imported with milestones already finished. The tests drive the real completion
paths (activity editor, progress endpoint, field progress entry, typed
progress, guarded real-time edit, CSV import) against PostgreSQL and record
what each one publishes.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, event_bus
from app.modules.schedule import events as schedule_events
from app.modules.schedule import milestone_events
from app.modules.schedule.milestone_events import REACHED_AT_KEY
from app.modules.schedule.models import Activity, Schedule
from app.modules.schedule.progress_schemas import TypedProgressRequest
from app.modules.schedule.progress_service import ScheduleProgressService as TypedProgressService
from app.modules.schedule.realtime_service import ScheduleRealtimeService
from app.modules.schedule.schemas import ActivityUpdate
from app.modules.schedule.service import ScheduleService
from app.modules.schedule.service_4d import ScheduleProgressService, import_schedule_csv
from tests._pg import transactional_session

REACHED = "schedule.milestone.reached"
REOPENED = "schedule.milestone.reopened"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Every milestone event deferred to the commit, in order."""
    seen: list[tuple[str, dict[str, Any]]] = []

    def _record(_session: Any, name: str, data: dict[str, Any] | None = None, **_kw: Any) -> None:
        seen.append((name, dict(data or {})))

    monkeypatch.setattr(milestone_events, "publish_after_commit", _record)
    return seen


async def _schedule(session: AsyncSession) -> Schedule:
    schedule = Schedule(project_id=uuid.uuid4(), name="Milestone events")
    session.add(schedule)
    await session.flush()
    return schedule


async def _activity(
    session: AsyncSession,
    schedule: Schedule,
    *,
    activity_type: str = "milestone",
    progress: str = "0",
    status: str = "not_started",
    metadata: dict[str, Any] | None = None,
) -> Activity:
    activity = Activity(
        schedule_id=schedule.id,
        name=f"Foundation complete {uuid.uuid4().hex[:6]}",
        start_date="2026-07-01",
        end_date="2026-07-01",
        duration_days=0,
        progress_pct=progress,
        status=status,
        activity_type=activity_type,
        metadata_=dict(metadata or {}),
    )
    session.add(activity)
    await session.flush()
    return activity


@pytest.mark.asyncio
async def test_completing_a_milestone_announces_it_once(
    session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
) -> None:
    schedule = await _schedule(session)
    contract_id = str(uuid.uuid4())
    actor = uuid.uuid4()
    ms = await _activity(
        session, schedule, metadata={"milestone_event": "foundation_complete", "sales_contract_id": contract_id}
    )
    svc = ScheduleProgressService(session)

    await svc.record(task_id=ms.id, progress_percent=100.0, recorded_by_user_id=actor, actual_finish_date="2026-07-03")

    assert [name for name, _ in published] == [REACHED]
    payload = published[0][1]
    assert payload == {
        "project_id": str(schedule.project_id),
        "schedule_id": str(schedule.id),
        "activity_id": str(ms.id),
        "activity_name": ms.name,
        "reached_at": "2026-07-03",
        "actor_id": str(actor),
        "milestone_event": "foundation_complete",
        "sales_contract_id": contract_id,
    }
    await session.refresh(ms)
    assert ms.metadata_[REACHED_AT_KEY] == "2026-07-03"
    # The marker joins the metadata; it does not replace what was there.
    assert ms.metadata_["sales_contract_id"] == contract_id

    # done -> done: a second full reading is not a second milestone.
    await svc.record(task_id=ms.id, progress_percent=100.0, recorded_by_user_id=actor)
    assert [name for name, _ in published] == [REACHED]


@pytest.mark.asyncio
async def test_reopening_announces_it_and_a_later_completion_announces_again(
    session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
) -> None:
    schedule = await _schedule(session)
    ms = await _activity(session, schedule)
    svc = ScheduleProgressService(session)

    await svc.record(task_id=ms.id, progress_percent=100.0, actual_finish_date="2026-07-03")
    await svc.record(task_id=ms.id, progress_percent=60.0)

    assert [name for name, _ in published] == [REACHED, REOPENED]
    reopened = published[1][1]
    assert reopened["activity_id"] == str(ms.id)
    assert reopened["reached_at"] == "2026-07-03", "the reopen names the completion it withdraws"
    assert reopened["actor_id"] is None
    await session.refresh(ms)
    assert REACHED_AT_KEY not in ms.metadata_

    # No actual finish recorded this time, so the date defaults to today.
    await svc.record(task_id=ms.id, progress_percent=100.0)
    assert [name for name, _ in published] == [REACHED, REOPENED, REACHED]
    assert published[2][1]["reached_at"] == datetime.now(UTC).date().isoformat()


@pytest.mark.asyncio
async def test_a_milestone_already_announced_is_not_announced_again(
    session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
) -> None:
    """The marker wins over the transition, whatever path left the status behind."""
    schedule = await _schedule(session)
    ms = await _activity(session, schedule, metadata={REACHED_AT_KEY: "2026-06-30"})

    await ScheduleProgressService(session).record(task_id=ms.id, progress_percent=100.0)

    assert published == []


@pytest.mark.asyncio
async def test_reopening_a_milestone_never_announced_withdraws_nothing(
    session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
) -> None:
    """A milestone imported finished was never announced, so there is nothing to reopen.

    Completing it again afterwards is a real completion on site and is announced.
    """
    schedule = await _schedule(session)
    ms = await _activity(session, schedule, progress="100", status="completed")
    svc = ScheduleProgressService(session)

    await svc.record(task_id=ms.id, progress_percent=40.0)
    assert published == []

    await svc.record(task_id=ms.id, progress_percent=100.0)
    assert [name for name, _ in published] == [REACHED]


@pytest.mark.asyncio
async def test_completing_ordinary_work_announces_nothing(
    session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
) -> None:
    schedule = await _schedule(session)
    task = await _activity(session, schedule, activity_type="task")
    svc = ScheduleProgressService(session)

    await svc.record(task_id=task.id, progress_percent=100.0)
    await svc.record(task_id=task.id, progress_percent=0.0)

    assert published == []
    await session.refresh(task)
    assert REACHED_AT_KEY not in task.metadata_


@pytest.mark.asyncio
async def test_importing_finished_activities_announces_nothing(
    session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
) -> None:
    schedule = await _schedule(session)
    csv_text = "wbs_code,name,start,end,progress\n1,Foundation complete,2026-07-01,2026-07-01,100\n"

    result = await import_schedule_csv(session, schedule_id=schedule.id, csv_text=csv_text)

    assert result.activities_created == 1
    assert published == []


@pytest.mark.asyncio
async def test_typed_progress_announces_with_the_actor(
    session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
) -> None:
    schedule = await _schedule(session)
    ms = await _activity(session, schedule)
    actor = uuid.uuid4()

    await TypedProgressService(session).set_typed_progress(
        ms.id, TypedProgressRequest(percent_complete_type="physical", percent=100.0), actor_id=actor
    )

    assert [name for name, _ in published] == [REACHED]
    assert published[0][1]["actor_id"] == str(actor)


@pytest.mark.asyncio
async def test_a_guarded_realtime_edit_announces_and_reopens(
    session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
) -> None:
    schedule = await _schedule(session)
    ms = await _activity(session, schedule)
    svc = ScheduleRealtimeService(session)
    user = str(uuid.uuid4())

    done, _ = await svc.guarded_update(
        ms.id, client_base_revision=0, fields={"status": "completed", "progress_pct": 100}, user_id=user
    )
    await svc.guarded_update(
        ms.id,
        client_base_revision=done.revision,
        fields={"status": "in_progress", "progress_pct": 50},
        user_id=user,
    )

    assert [name for name, _ in published] == [REACHED, REOPENED]
    assert published[0][1]["actor_id"] == user


@pytest.mark.asyncio
async def test_a_field_report_keeps_the_marker_its_progress_wrote(
    session: AsyncSession, published: list[tuple[str, dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The report handler stamps its id over the metadata as ``record()`` left it.

    It used to merge over a copy read before ``record()``, which erased the
    announcement marker ``record()`` had just written.
    """
    schedule = await _schedule(session)
    ms = await _activity(session, schedule, metadata={"milestone_event": "topping_out"})
    report_id = str(uuid.uuid4())

    @contextlib.asynccontextmanager
    async def _same_session() -> AsyncIterator[AsyncSession]:
        yield session

    monkeypatch.setattr(schedule_events, "async_session_factory", _same_session)
    event = Event(
        name="fieldreports.report.submitted",
        data={
            "report_id": report_id,
            "schedule_progress": [
                {"task_id": str(ms.id), "progress_percent": 100, "actual_finish_date": "2026-07-04"},
            ],
        },
    )

    await schedule_events._record_schedule_progress(event)

    assert [name for name, _ in published] == [REACHED]
    await session.refresh(ms)
    assert ms.metadata_[REACHED_AT_KEY] == "2026-07-04"
    assert ms.metadata_["field_report_progress"] == [report_id]
    assert ms.metadata_["milestone_event"] == "topping_out"


@pytest.mark.asyncio
async def test_the_event_waits_for_the_commit(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Subscribers read from their own sessions, so nothing goes out before the commit."""
    seen: list[str] = []
    monkeypatch.setattr(event_bus, "publish_detached", lambda name, *_a, **_kw: seen.append(name))
    schedule = await _schedule(session)
    ms = await _activity(session, schedule)

    await ScheduleProgressService(session).record(task_id=ms.id, progress_percent=100.0)
    assert REACHED not in seen

    await session.commit()
    assert seen.count(REACHED) == 1


# ── ScheduleService: the activity editor and the progress endpoint ──────────


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Every event that actually left for the bus, in order.

    Recorded at ``publish_detached``, below ``publish_after_commit``, so an
    event deferred to the commit shows up here only once the commit ran.
    """
    seen: list[tuple[str, dict[str, Any]]] = []

    def _record(name: str, data: dict[str, Any] | None = None, **_kw: Any) -> None:
        seen.append((name, dict(data or {})))

    monkeypatch.setattr(event_bus, "publish_detached", _record)
    return seen


def _names(events: list[tuple[str, dict[str, Any]]], name: str) -> list[dict[str, Any]]:
    return [data for event_name, data in events if event_name == name]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"status": "completed"}, id="status"),
        pytest.param({"progress_pct": 100.0}, id="progress"),
    ],
)
async def test_the_activity_editor_announces_a_milestone_once_after_the_commit(
    session: AsyncSession, dispatched: list[tuple[str, dict[str, Any]]], change: dict[str, Any]
) -> None:
    schedule = await _schedule(session)
    ms = await _activity(session, schedule)
    actor = str(uuid.uuid4())
    svc = ScheduleService(session)

    await svc.update_activity(ms.id, ActivityUpdate(**change), actor_id=actor)
    assert _names(dispatched, REACHED) == [], "announced before the commit"

    await session.commit()
    reached = _names(dispatched, REACHED)
    assert len(reached) == 1
    assert reached[0]["activity_id"] == str(ms.id)
    assert reached[0]["actor_id"] == actor

    # Saving the finished milestone again is an edit, not a second completion.
    await svc.update_activity(ms.id, ActivityUpdate(**change, description="signed off"), actor_id=actor)
    await session.commit()
    assert len(_names(dispatched, REACHED)) == 1


@pytest.mark.asyncio
async def test_the_progress_endpoint_announces_a_milestone_once_after_the_commit(
    session: AsyncSession, dispatched: list[tuple[str, dict[str, Any]]]
) -> None:
    schedule = await _schedule(session)
    ms = await _activity(session, schedule)
    actor = str(uuid.uuid4())
    svc = ScheduleService(session)

    done = await svc.update_progress(ms.id, 100.0, actor_id=actor)
    assert done.status == "completed"
    assert _names(dispatched, REACHED) == [], "announced before the commit"

    await session.commit()
    reached = _names(dispatched, REACHED)
    assert len(reached) == 1
    assert reached[0]["actor_id"] == actor
    assert reached[0]["project_id"] == str(schedule.project_id)

    await svc.update_progress(ms.id, 100.0, actor_id=actor)
    await session.commit()
    assert len(_names(dispatched, REACHED)) == 1

    await svc.update_progress(ms.id, 40.0, actor_id=actor)
    await session.commit()
    assert len(_names(dispatched, REOPENED)) == 1


@pytest.mark.asyncio
async def test_a_date_edit_is_dispatched_only_after_the_commit(
    session: AsyncSession, dispatched: list[tuple[str, dict[str, Any]]]
) -> None:
    """Subscribers recompute forecasts from the new dates in their own sessions."""
    schedule = await _schedule(session)
    task = await _activity(session, schedule, activity_type="task")

    await ScheduleService(session).update_activity(task.id, ActivityUpdate(end_date="2026-07-20"))
    assert _names(dispatched, "schedule.activity.updated") == []

    await session.commit()
    updated = _names(dispatched, "schedule.activity.updated")
    assert len(updated) == 1
    assert updated[0]["activity_id"] == str(task.id)
    assert "end_date" in updated[0]["fields"]


@pytest.mark.asyncio
async def test_the_activity_editor_does_not_reopen_a_milestone_never_announced(
    session: AsyncSession, dispatched: list[tuple[str, dict[str, Any]]]
) -> None:
    schedule = await _schedule(session)
    ms = await _activity(session, schedule, progress="100", status="completed")

    await ScheduleService(session).update_activity(ms.id, ActivityUpdate(status="in_progress", progress_pct=50.0))
    await session.commit()

    assert _names(dispatched, REOPENED) == []
    assert _names(dispatched, REACHED) == []
