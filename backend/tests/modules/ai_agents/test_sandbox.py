# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the seeded AI sandbox (PostgreSQL, py3.12).

Seeds the sample agent runs and checks that they are scored (so the accuracy
scoreboard renders populated), idempotent, per-user scoped, and clearly marked
so they can be identified and removed.

The scoring tests run as the hosted demo, because that is the only deployment
where seeding happens at all and the only one where sample runs count toward
accuracy. The opposite case has its own test at the bottom of the file.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_agents.accuracy_service import OUTCOME_KEY, build_scoreboard
from app.modules.ai_agents.models import AgentRun
from app.modules.ai_agents.sandbox import (
    SAMPLE_FLAG_KEY,
    SAMPLE_RUNS,
    SAMPLE_TRIGGER_SOURCE,
    seed_sandbox_runs,
)
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest.fixture(autouse=True)
def demo_box(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put these tests on a demo box, the only deployment that seeds samples.

    The seeding endpoint is gated on ``OE_DEMO_MODE`` and the scoreboard leaves
    sample runs out of the aggregate unless the same flag is set, so "seeded
    samples on a box that is not the demo" is a state the product cannot reach.
    Asserting the scoreboard against it pins behaviour no user can observe, and
    it also empties the scoreboard for every user at once, which is enough to
    make a scoping assertion pass without scoping working.

    The exclusion itself is not left unguarded:
    :func:`test_samples_stay_out_of_the_scoreboard_off_the_demo_box` drops the
    flag and asserts the opposite outcome over the same rows.
    """
    monkeypatch.setenv("OE_DEMO_MODE", "1")


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"sbx-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Sandbox",
        role="admin",
    )
    session.add(user)
    await session.flush()
    return user.id


async def _runs_for(session: AsyncSession, uid: uuid.UUID) -> list[AgentRun]:
    return list((await session.execute(select(AgentRun).where(AgentRun.user_id == uid))).scalars().all())


@pytest.mark.asyncio
async def test_seed_creates_scored_runs(session: AsyncSession) -> None:
    uid = await _user(session)

    result = await seed_sandbox_runs(session, user_id=uid)
    assert result["created"] == len(SAMPLE_RUNS)
    assert result["total"] == len(SAMPLE_RUNS)
    # Three distinct analytical agents, alphabetically ordered.
    assert result["agents"] == ["estimate_reviewer", "project_analyst", "schedule_analyst"]

    runs = await _runs_for(session, uid)
    assert len(runs) == len(SAMPLE_RUNS)
    for run in runs:
        assert run.status == "completed"
        assert run.trigger_source == SAMPLE_TRIGGER_SOURCE
        assert isinstance(run.trust, dict)
        # Every seeded run is a scored prediction: a stated confidence AND a
        # recorded outcome, which is exactly what the scoreboard needs.
        assert isinstance(run.trust.get("confidence"), float)
        assert isinstance(run.trust.get(OUTCOME_KEY), bool)
        assert run.trust.get("sources")  # real-looking citations present

    # The scoreboard now renders populated - one score per agent.
    scores = await build_scoreboard(session, user_id=uid)
    assert {s.agent_name for s in scores} == {"estimate_reviewer", "project_analyst", "schedule_analyst"}
    for score in scores:
        assert score.count == 3  # three sample runs per agent
        assert 0.0 <= score.observed_rate <= 1.0
        assert 0.0 <= score.brier_score <= 1.0


@pytest.mark.asyncio
async def test_seed_is_idempotent(session: AsyncSession) -> None:
    uid = await _user(session)

    first = await seed_sandbox_runs(session, user_id=uid)
    assert first["created"] == len(SAMPLE_RUNS)

    # A second call creates nothing and does not duplicate any row.
    second = await seed_sandbox_runs(session, user_id=uid)
    assert second["created"] == 0

    total = (
        await session.execute(select(func.count()).select_from(AgentRun).where(AgentRun.user_id == uid))
    ).scalar_one()
    assert total == len(SAMPLE_RUNS)

    # The scoreboard is stable across the repeat seed.
    scores = await build_scoreboard(session, user_id=uid)
    assert len(scores) == 3


@pytest.mark.asyncio
async def test_seed_is_user_scoped(session: AsyncSession) -> None:
    owner = await _user(session)
    other = await _user(session)

    await seed_sandbox_runs(session, user_id=owner)

    # Seeding the owner never creates rows for, or scores, another user.
    assert await _runs_for(session, other) == []
    assert await build_scoreboard(session, user_id=other) == []

    # The other user can seed their own independent set (distinct ids).
    other_result = await seed_sandbox_runs(session, user_id=other)
    assert other_result["created"] == len(SAMPLE_RUNS)
    assert len(await _runs_for(session, other)) == len(SAMPLE_RUNS)
    # The owner's set is untouched.
    assert len(await _runs_for(session, owner)) == len(SAMPLE_RUNS)


@pytest.mark.asyncio
async def test_sample_runs_are_marked_for_cleanup(session: AsyncSession) -> None:
    uid = await _user(session)
    await seed_sandbox_runs(session, user_id=uid)

    for run in await _runs_for(session, uid):
        # Two independent markers so the rows are unambiguously sample data.
        assert run.trigger_source == SAMPLE_TRIGGER_SOURCE
        assert run.trust.get(SAMPLE_FLAG_KEY) is True


@pytest.mark.asyncio
async def test_samples_stay_out_of_the_scoreboard_off_the_demo_box(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Illustrative sample runs never count toward accuracy off the demo box.

    This is the other direction of :func:`demo_box`, and the pair is the point.
    The same nine rows score three agents with the flag set and score nothing
    without it, so a scoreboard that counted every row would fail here and one
    that counted none would fail in the seeding tests. Neither test can pass by
    agreeing with a predicate that is simply always true.
    """
    uid = await _user(session)
    await seed_sandbox_runs(session, user_id=uid)

    # The rows exist either way. Only the aggregate is gated.
    assert len(await _runs_for(session, uid)) == len(SAMPLE_RUNS)
    assert len(await build_scoreboard(session, user_id=uid)) == 3

    monkeypatch.delenv("OE_DEMO_MODE", raising=False)
    assert await build_scoreboard(session, user_id=uid) == []
