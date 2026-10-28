# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the generic AI feedback sink (PostgreSQL, py3.12).

The accuracy scoreboard scores agent *runs*; this sink records verdicts on the
AI surfaces that have no run row (AI Estimator result, match suggestions, the
cost advisor). The tests check the row is attributed to the caller, that the
optional fields are normalised, and that long inputs are clamped.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_agents.accuracy_service import record_ai_feedback
from app.modules.ai_agents.models import AIFeedback
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"fb-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="FB",
        role="admin",
    )
    session.add(user)
    await session.flush()
    return user.id


@pytest.mark.asyncio
async def test_record_feedback_persists_for_caller(session: AsyncSession) -> None:
    uid = await _user(session)
    row = await record_ai_feedback(
        session,
        user_id=uid,
        surface="ai_estimator",
        correct=True,
        ref="run-123",
        note="Rates looked right.",
    )
    assert row.id is not None
    assert row.user_id == uid
    assert row.surface == "ai_estimator"
    assert row.correct is True
    assert row.ref == "run-123"
    assert row.note == "Rates looked right."

    stored = (await session.execute(select(AIFeedback).where(AIFeedback.id == row.id))).scalar_one()
    assert stored.surface == "ai_estimator"
    assert stored.correct is True


@pytest.mark.asyncio
async def test_record_feedback_normalises_blank_optionals(session: AsyncSession) -> None:
    uid = await _user(session)
    row = await record_ai_feedback(
        session,
        user_id=uid,
        surface="advisor",
        correct=False,
        ref="   ",
        note="   ",
    )
    # Blank ref / note collapse to NULL rather than being stored as whitespace.
    assert row.ref is None
    assert row.note is None
    assert row.correct is False


@pytest.mark.asyncio
async def test_record_feedback_clamps_oversize_fields(session: AsyncSession) -> None:
    uid = await _user(session)
    row = await record_ai_feedback(
        session,
        user_id=uid,
        surface="x" * 100,
        correct=True,
        ref="r" * 500,
        note="n" * 5000,
    )
    assert len(row.surface) == 40
    assert row.ref is not None and len(row.ref) == 200
    assert row.note is not None and len(row.note) == 2000
