# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the AI accuracy scoreboard service (PostgreSQL, py3.12).

Seeds AgentRun rows with trust confidences, records outcomes, and checks the
calibration roll-up plus the owner-scoping of outcome recording.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_agents.accuracy_service import build_scoreboard, record_run_outcome
from app.modules.ai_agents.models import AgentRun
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"acc-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Acc",
        role="admin",
    )
    session.add(user)
    await session.flush()
    return user.id


@pytest.mark.asyncio
async def test_record_outcome_then_scoreboard(session: AsyncSession) -> None:
    uid = await _user(session)
    run_hit = AgentRun(agent_name="project_analyst", user_id=uid, status="completed", trust={"confidence": 0.9})
    run_miss = AgentRun(agent_name="project_analyst", user_id=uid, status="completed", trust={"confidence": 0.2})
    session.add_all([run_hit, run_miss])
    await session.flush()

    assert await record_run_outcome(session, run_hit.id, correct=True, recorded_by=uid) is not None
    assert await record_run_outcome(session, run_miss.id, correct=False, recorded_by=uid) is not None

    scores = await build_scoreboard(session, user_id=uid)
    assert len(scores) == 1
    score = scores[0]
    assert score.agent_name == "project_analyst"
    assert score.count == 2
    # Confident-correct (0.9) and confident-not-wrong (0.2 -> outcome False) are
    # both well calibrated, so the Brier score is low.
    assert score.brier_score < 0.1
    assert score.observed_rate == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_outcome_recording_is_scoped_to_owner(session: AsyncSession) -> None:
    owner = await _user(session)
    other = await _user(session)
    run = AgentRun(agent_name="schedule_analyst", user_id=owner, status="completed", trust={"confidence": 0.5})
    session.add(run)
    await session.flush()

    # A different user cannot record an outcome on someone else's run.
    assert await record_run_outcome(session, run.id, correct=True, recorded_by=other) is None
    # The owner can.
    assert await record_run_outcome(session, run.id, correct=True, recorded_by=owner) is not None


@pytest.mark.asyncio
async def test_scoreboard_skips_runs_without_outcome(session: AsyncSession) -> None:
    uid = await _user(session)
    # Confidence present but no recorded outcome -> not a scored prediction.
    session.add(
        AgentRun(agent_name="risk_register_builder", user_id=uid, status="completed", trust={"confidence": 0.7})
    )
    await session.flush()

    scores = await build_scoreboard(session, user_id=uid)
    assert scores == []
