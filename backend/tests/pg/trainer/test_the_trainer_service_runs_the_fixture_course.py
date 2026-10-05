# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: the trainer service over the fixture course, on one real session.

The enrolment is started through :meth:`TrainerService.start_enrolment`, so
the learner's project is seeded through the real ERP services. The ERP is
changed through ``BOQService`` (never the ORM), and every verdict comes from
the real probes reading that project.

The entry points that open their own session (``seed_on_enrol``, the admin
reseed, the debounced recheck) are covered by the HTTP integration test; here
the service methods they wrap run on the test session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.config import get_settings
from app.modules.boq.models import Position
from app.modules.boq.schemas import PositionUpdate
from app.modules.boq.service import BOQService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.trainer import service as service_module
from app.modules.trainer.events import resolve_project_id
from app.modules.trainer.loader import parse_course_bytes
from app.modules.trainer.models import TrainerAttempt, TrainerCourse, TrainerEnrolment
from app.modules.trainer.provisioning import provision_learner, suspend_order
from app.modules.trainer.repository import TrainerRepository
from app.modules.trainer.schemas import AnswerIn, AnswersPut, CheckRequest
from app.modules.trainer.seeder import SeedError, seeding
from app.modules.trainer.service import TrainerService
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

COURSE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "trainer" / "course_fixture_v1.json"


def _stored_spec() -> tuple[dict[str, Any], str]:
    parsed = parse_course_bytes(COURSE_PATH.read_bytes(), COURSE_PATH.name)
    assert parsed.errors == [], parsed.errors
    assert parsed.spec is not None
    return parsed.spec, parsed.sha256


async def _course_row(session, key: str = "fx-quillmere", version: str = "1") -> TrainerCourse:
    spec, sha = _stored_spec()
    row = TrainerCourse(
        course_key=f"{key}-{uuid.uuid4().hex[:6]}",
        version=version,
        country="GB",
        language="en",
        currency="GBP",
        title=spec["title"],
        source_file=COURSE_PATH.name,
        sha256=sha,
        spec=spec,
        validation_report={},
        status="active",
        loaded_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


async def _enrol(session, user: User, course: TrainerCourse, status: str = "provisioning") -> TrainerEnrolment:
    enrolment = TrainerEnrolment(
        user_id=user.id,
        course_id=course.id,
        course_sha256=course.sha256,
        status=status,
        source="admin",
        seeded_refs={},
        current_task_n=1,
        metadata_={},
    )
    session.add(enrolment)
    await session.flush()
    return enrolment


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        yield s


@pytest_asyncio.fixture
async def learner(session) -> User:
    user = User(id=uuid.uuid4(), email=f"learner-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", role="manager")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def started(session, learner) -> TrainerEnrolment:
    course = await _course_row(session)
    enrolment = await _enrol(session, learner, course)
    with seeding(enrolment.id):
        await TrainerService(session).start_enrolment(enrolment.id)
        await session.commit()
    return enrolment


def _svc(session) -> TrainerService:
    return TrainerService(session, get_settings())


async def _answer_t1(svc: TrainerService, user_id: uuid.UUID, revision: int, *, right: bool = True) -> int:
    saved = await svc.put_answers(
        user_id,
        "t1-direct-cost",
        AnswersPut(
            revision=revision,
            answers=[
                AnswerIn(name="direct_cost", value_text="30414.00"),
                AnswerIn(name="t1-trace", option_index=0 if right else 1),
                AnswerIn(name="t1-explain", option_index=0),
            ],
        ),
    )
    return saved.revision


async def _price_blockwork(session, enrolment: TrainerEnrolment) -> None:
    boq_id = uuid.UUID(enrolment.seeded_refs["boq.main"])
    position = (
        await session.execute(select(Position).where(Position.boq_id == boq_id, Position.ordinal == "01.002"))
    ).scalar_one()
    await BOQService(session).update_position(position.id, PositionUpdate(unit_rate=Decimal("46.20")))
    await session.flush()


# ── Enrolment start ──────────────────────────────────────────────────────────


async def test_start_creates_every_task_state_with_task_one_open(session, started) -> None:
    states = sorted(started.task_states, key=lambda s: s.task_n)
    assert [(s.task_n, s.state) for s in states] == [
        (1, "unlocked"),
        (2, "locked"),
        (3, "locked"),
        (4, "locked"),
        (5, "locked"),
    ]
    assert states[0].seed_status == "done"
    assert started.status == "active"
    assert started.project_id is not None
    assert {"project", "boq.main"} <= set(started.seeded_refs)

    svc = _svc(session)
    course = await svc.course_of(started)
    svc._ensure_task_states(started, course)
    assert len(started.task_states) == 5, "a second start adds no task state"


# ── /me and the task view ────────────────────────────────────────────────────


async def test_me_shows_the_course_map_and_the_task_view_hides_every_secret(session, started, learner) -> None:
    svc = _svc(session)
    me = await svc.get_me(learner.id)
    assert [t.status for t in me.tasks] == ["not_started", "locked", "locked", "locked", "locked"]
    assert me.tasks[0].target is not None
    assert me.tasks[0].target.route == f"/boq/{started.seeded_refs['boq.main']}"
    assert all(u.state == "locked" for u in me.unlocks)
    assert me.progress.done == 0 and me.progress.total == 5
    assert me.week is not None and len(me.week.days) == 7
    assert me.course.locale == "en-GB"

    view = await svc.get_task_view(learner.id, "t1-direct-cost")
    assert view.hints == [] and view.hints_total == 2
    dumped = view.model_dump_json()
    assert '"correct"' not in dumped
    assert "30414" not in dumped, "the expected direct cost leaks into the task view"

    with pytest.raises(HTTPException) as locked:
        await svc.get_task_view(learner.id, "t2-markups")
    assert locked.value.status_code == 409
    with pytest.raises(HTTPException) as unknown:
        await svc.get_task_view(learner.id, "t9-none")
    assert unknown.value.status_code == 404


async def test_a_learner_without_an_enrolment_gets_404(session) -> None:
    with pytest.raises(HTTPException) as caught:
        await _svc(session).get_me(uuid.uuid4())
    assert caught.value.status_code == 404


# ── Answers ──────────────────────────────────────────────────────────────────


async def test_answers_replace_the_whole_set_and_refuse_a_stale_revision(session, started, learner) -> None:
    svc = _svc(session)
    revision = await _answer_t1(svc, learner.id, 0)
    assert revision == 1

    replaced = await svc.put_answers(
        learner.id, "t1-direct-cost", AnswersPut(revision=1, answers=[AnswerIn(name="direct_cost", value_text="1")])
    )
    assert [a.name for a in replaced.answers] == ["direct_cost"]
    view = await svc.get_task_view(learner.id, "t1-direct-cost")
    assert [a.name for a in view.answers] == ["direct_cost"], "the options of the first PUT were not replaced"
    assert view.answers_revision == 2

    with pytest.raises(HTTPException) as stale:
        await svc.put_answers(
            learner.id, "t1-direct-cost", AnswersPut(revision=1, answers=[AnswerIn(name="direct_cost", value_text="2")])
        )
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as unknown:
        await svc.put_answers(
            learner.id, "t1-direct-cost", AnswersPut(revision=2, answers=[AnswerIn(name="nope", value_text="2")])
        )
    assert unknown.value.status_code == 422
    with pytest.raises(HTTPException) as bad_option:
        await svc.put_answers(
            learner.id, "t1-direct-cost", AnswersPut(revision=2, answers=[AnswerIn(name="t1-trace", option_index=9)])
        )
    assert bad_option.value.status_code == 422


# ── Check ────────────────────────────────────────────────────────────────────


async def test_check_fails_on_the_untouched_erp_then_passes_and_unlocks_task_two(session, started, learner) -> None:
    svc = _svc(session)
    revision = await _answer_t1(svc, learner.id, 0)

    first_id = uuid.uuid4()
    failed = await svc.check(learner.id, "t1-direct-cost", CheckRequest(client_attempt_id=first_id, revision=revision))
    assert failed.verdict == "fail"
    assert failed.unlocked == []
    assert failed.revealed_hint is not None, "a failed check reveals the next hint"
    assert {f.key for f in failed.fields if f.verdict != "ok"} == {"blockwork_rate", "direct_cost"}

    replay = await svc.check(learner.id, "t1-direct-cost", CheckRequest(client_attempt_id=first_id, revision=revision))
    assert replay.attempt_id == failed.attempt_id
    assert replay.revealed_hint is None
    count = await session.scalar(
        select(func.count()).select_from(TrainerAttempt).where(TrainerAttempt.enrolment_id == started.id)
    )
    assert count == 1, "a retried check records nothing new"

    with pytest.raises(HTTPException) as stale:
        await svc.check(learner.id, "t1-direct-cost", CheckRequest(client_attempt_id=uuid.uuid4(), revision=0))
    assert stale.value.status_code == 409

    readback = await svc.readback(learner.id, "t1-direct-cost")
    assert {i.id: i.state for i in readback.items} == {"rb0": "mismatch", "rb1": "mismatch"}

    await _price_blockwork(session, started)
    passed = await svc.check(learner.id, "t1-direct-cost", CheckRequest(client_attempt_id=uuid.uuid4()))
    assert passed.verdict == "pass"
    assert passed.unlocked == ["boq.markups_panel"]
    assert passed.task_status == "passed"
    assert passed.progress.done == 1

    me = await svc.get_me(learner.id)
    assert [t.status for t in me.tasks][:2] == ["passed", "not_started"]
    assert me.tasks[1].target is not None and me.tasks[1].target.anchor == "boq-markups-panel"
    markups = next(u for u in me.unlocks if u.lock_id == "boq.markups_panel")
    assert (markups.state, markups.seen) == ("open", False)

    await svc.mark_unlock_seen(learner.id, "boq.markups_panel")
    await svc.mark_unlock_seen(learner.id, "boq.markups_panel")  # idempotent
    me = await svc.get_me(learner.id)
    assert next(u for u in me.unlocks if u.lock_id == "boq.markups_panel").seen is True
    with pytest.raises(HTTPException) as not_open:
        await svc.mark_unlock_seen(learner.id, "bid_management")
    assert not_open.value.status_code == 409

    # A later failing check keeps the pass and says so.
    await _answer_t1(
        svc, learner.id, (await svc.get_task_view(learner.id, "t1-direct-cost")).answers_revision, right=False
    )
    regressed = await svc.check(learner.id, "t1-direct-cost", CheckRequest(client_attempt_id=uuid.uuid4()))
    assert (regressed.verdict, regressed.regressed, regressed.task_status) == ("fail", True, "passed")


async def test_hint_reveal_is_idempotent_at_the_last_hint(session, started, learner) -> None:
    svc = _svc(session)
    one = await svc.reveal_hint(learner.id, "t1-direct-cost")
    two = await svc.reveal_hint(learner.id, "t1-direct-cost")
    again = await svc.reveal_hint(learner.id, "t1-direct-cost")
    assert (one.hints_revealed, two.hints_revealed, again.hints_revealed) == (1, 2, 2)
    assert again.hint == two.hint
    view = await svc.get_task_view(learner.id, "t1-direct-cost")
    assert len(view.hints) == 2


async def test_a_failed_unlock_seed_leaves_the_next_task_locked(session, started, learner, monkeypatch) -> None:
    async def broken(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise SeedError("t2 bill", "on_unlock(2)", "seed step failed on purpose")

    svc = _svc(session)
    revision = await _answer_t1(svc, learner.id, 0)
    await _price_blockwork(session, started)
    monkeypatch.setattr(service_module, "execute_stage", broken)
    passed = await svc.check(
        learner.id, "t1-direct-cost", CheckRequest(client_attempt_id=uuid.uuid4(), revision=revision)
    )
    assert passed.verdict == "pass"
    t2 = next(s for s in started.task_states if s.task_id == "t2-markups")
    assert (t2.state, t2.seed_status) == ("locked", "failed")
    assert "on purpose" in (t2.seed_error or "")

    monkeypatch.undo()
    reopened = await svc.retry_failed_unlocks(started)
    assert reopened == 1
    assert (t2.state, t2.seed_status) == ("unlocked", "done")


# ── Course completion and the queue (decision 43) ────────────────────────────


@pytest.mark.parametrize("seed_fails", [False, True])
async def test_completing_the_course_starts_the_queued_one(session, started, learner, monkeypatch, seed_fails) -> None:
    queued_course = await _course_row(session, key="fx-queued")
    queued = await _enrol(session, learner, queued_course, status="queued")
    if seed_fails:

        async def broken(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise SeedError("project", "on_enrol", "queued seed failed on purpose")

        monkeypatch.setattr(service_module, "execute_enrolment", broken)

    svc = _svc(session)
    course = await svc.course_of(started)
    last = course.task_by_n(5)
    assert last is not None
    await svc._after_pass(started, course, last)
    await session.flush()

    assert started.status == "completed"
    await session.refresh(queued)
    if seed_fails:
        assert queued.status == "failed"
        assert queued.metadata_.get("seed_error") == "SeedError"
    else:
        assert queued.status == "active"
        assert queued.project_id is not None
        assert len(queued.task_states) == 5
    me = await svc.get_me(learner.id)
    assert me.course.id == ("fx-quillmere-1")


# ── Refund (decision 42) ─────────────────────────────────────────────────────


async def test_a_refund_suspends_and_a_new_payment_reactivates(session, started, learner) -> None:
    settings = get_settings().model_copy(update={"academy_mode": True})
    result = await suspend_order(
        session, settings, provider="generic", email=learner.email, offer_code=None, order_ref=None
    )
    assert result.status == "processed"
    await session.flush()
    assert started.status == "suspended"
    with pytest.raises(HTTPException) as closed:
        await _svc(session).get_me(learner.id)
    assert closed.value.status_code == 404

    course = await session.get(TrainerCourse, started.course_id)
    assert course is not None
    again = await provision_learner(
        session,
        settings,
        email=learner.email,
        name="Learner",
        locale="en",
        course_keys=[course.course_key],
        source="webhook",
    )
    assert again.status == "processed"
    assert started.status == "active", "the project survived, so the course resumes in it"
    assert again.to_seed == ()
    me = await _svc(session).get_me(learner.id)
    assert me.tasks[0].status == "not_started"


# ── Events (design §6) ───────────────────────────────────────────────────────


async def test_events_resolve_to_the_learner_project(session, started) -> None:
    project_id = started.project_id
    boq_id = started.seeded_refs["boq.main"]
    position_id = await session.scalar(select(Position.id).where(Position.boq_id == uuid.UUID(boq_id)).limit(1))
    assert await resolve_project_id(session, {"boq_id": boq_id}) == project_id
    assert await resolve_project_id(session, {"position_id": str(position_id)}) == project_id
    assert await resolve_project_id(session, {"project_id": str(project_id)}) == project_id
    assert await resolve_project_id(session, {"boq_id": str(uuid.uuid4())}) is None
    assert await resolve_project_id(session, {"name": "nothing"}) is None
    ids = await TrainerRepository(session).running_enrolment_ids_for_project(project_id)
    assert ids == [started.id]


async def test_an_event_recheck_records_a_note_and_moves_nothing(session, started, learner) -> None:
    svc = _svc(session)
    repo = TrainerRepository(session)
    await repo.mark_stale([started.id], datetime.now(UTC))
    assert await svc.recheck_open_task(started.id) is None, "a task never checked is not rechecked"
    await session.refresh(started)
    assert started.stale_since is None

    revision = await _answer_t1(svc, learner.id, 0)
    await svc.check(learner.id, "t1-direct-cost", CheckRequest(client_attempt_id=uuid.uuid4(), revision=revision))
    await _price_blockwork(session, started)
    await repo.mark_stale([started.id], datetime.now(UTC))
    note = await svc.recheck_open_task(started.id)
    assert note is not None
    assert (note.trigger, note.passed) == ("event", True)
    await session.refresh(started)
    t1 = next(s for s in started.task_states if s.task_id == "t1-direct-cost")
    assert t1.state == "unlocked", "an event recheck never passes a task"
    assert started.stale_since is None
    me = await svc.get_me(learner.id)
    assert me.tasks[0].status == "needs_revision", "status reads the learner's own checks only"


async def test_only_the_learners_own_check_runs_the_probes_in_check_mode(
    session, started, learner, monkeypatch
) -> None:
    modes: list[str] = []
    real = service_module.run_task_probes

    async def recording(*args: Any, **kwargs: Any) -> Any:
        modes.append(kwargs["mode"])
        return await real(*args, **kwargs)

    monkeypatch.setattr(service_module, "run_task_probes", recording)
    svc = _svc(session)
    revision = await _answer_t1(svc, learner.id, 0)
    await svc.check(learner.id, "t1-direct-cost", CheckRequest(client_attempt_id=uuid.uuid4(), revision=revision))
    await TrainerRepository(session).mark_stale([started.id], datetime.now(UTC))
    await svc.recheck_open_task(started.id)
    await svc.readback(learner.id, "t1-direct-cost")
    assert modes == ["check", "read", "read"], "a recheck or a readback must never compute (decision 36)"
