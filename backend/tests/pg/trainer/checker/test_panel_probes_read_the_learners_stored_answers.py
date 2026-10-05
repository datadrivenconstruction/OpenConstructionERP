# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: ``panel.answer`` and ``panel.option`` read real ``oe_trainer_answer`` rows.

The course, enrolment and answers are written through the ORM: the answer
service is Wave 2, and these rows are the shape it will write (``value_text``
as typed, ``option_index`` for a trace or explain choice, one row per
enrolment, task and answer name). A row of another enrolment or another task
is never read.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest_asyncio

from app.modules.trainer.checker.matching import Expectation
from app.modules.trainer.checker.registry import run_probe
from app.modules.trainer.models import TrainerAnswer, TrainerCourse, TrainerEnrolment
from app.modules.users.models import User

TASK = "t1-direct-cost"
QUESTIONS = {"trace": "t1-trace", "explain": "t1-explain"}


@pytest_asyncio.fixture
async def enrolments(world) -> tuple[uuid.UUID, uuid.UUID]:
    session = world.session
    course = TrainerCourse(
        course_key=f"fx-{uuid.uuid4().hex[:8]}",
        version="1.0.0",
        country="GB",
        language="en",
        currency="GBP",
        title="Fixture course",
        source_file="course_fixture_v1.json",
        sha256="0" * 64,
        loaded_at=dt.datetime.now(dt.UTC),
    )
    session.add(course)
    await session.flush()
    # One enrolment per learner and course: the second learner is a stranger.
    stranger = User(
        email=f"stranger-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="Other", role="manager"
    )
    session.add(stranger)
    await session.flush()
    ids = []
    for user_id in (world.user_id, stranger.id):
        enrolment = TrainerEnrolment(
            user_id=user_id,
            course_id=course.id,
            course_sha256=course.sha256,
            project_id=world.project_id,
            status="active",
            source="admin",
        )
        session.add(enrolment)
        await session.flush()
        ids.append(enrolment.id)
    mine, other = ids
    session.add_all(
        [
            TrainerAnswer(
                enrolment_id=mine, task_id=TASK, answer_name="direct_cost", kind="number", value_text="30414.00"
            ),
            TrainerAnswer(enrolment_id=mine, task_id=TASK, answer_name="t1-trace", kind="option", option_index=2),
            TrainerAnswer(enrolment_id=mine, task_id=TASK, answer_name="t1-explain", kind="option", option_index=None),
            TrainerAnswer(
                enrolment_id=other, task_id=TASK, answer_name="direct_cost", kind="number", value_text="1.00"
            ),
            TrainerAnswer(enrolment_id=other, task_id=TASK, answer_name="t1-explain", kind="option", option_index=1),
            TrainerAnswer(
                enrolment_id=mine, task_id="t2-markups", answer_name="t1-explain", kind="option", option_index=1
            ),
        ]
    )
    await session.flush()
    return mine, other


async def _probe(world, enrolment_id: uuid.UUID, probe: dict, expectation: Expectation):
    ctx = world.ctx({}, enrolment_id=enrolment_id, task_id=TASK, question_answer_names=QUESTIONS)
    return await run_probe(world.session, probe, ctx, expectation)


async def test_the_typed_answer_is_read_as_typed(world, enrolments) -> None:
    mine, other = enrolments
    probe = {"type": "panel.answer", "args": {"answer_name": "direct_cost"}}
    expectation = Expectation(value=Decimal("30414.00"), kind="number", tolerance=Decimal("0.01"))
    read = await _probe(world, mine, probe, expectation)
    assert (read.value, read.status) == ("30414.00", "match")
    theirs = await _probe(world, other, probe, expectation)
    assert (theirs.value, theirs.status) == ("1.00", "mismatch")


async def test_the_chosen_option_is_read_by_its_question(world, enrolments) -> None:
    mine, _other = enrolments
    trace = await _probe(
        world, mine, {"type": "panel.option", "args": {"question": "trace"}}, Expectation(value=2, kind="number")
    )
    assert (trace.value, trace.status) == (Decimal(2), "match")


async def test_an_unanswered_question_is_missing_not_option_zero(world, enrolments) -> None:
    mine, _other = enrolments
    explain = await _probe(
        world, mine, {"type": "panel.option", "args": {"question": "explain"}}, Expectation(value=0, kind="number")
    )
    assert (explain.value, explain.status, explain.is_missing) == (None, "unknown", True)
    absent = await _probe(
        world,
        mine,
        {"type": "panel.answer", "args": {"answer_name": "blockwork_rate"}},
        Expectation(value=Decimal("46.20"), kind="number", tolerance=Decimal("0.005")),
    )
    assert absent.is_missing
