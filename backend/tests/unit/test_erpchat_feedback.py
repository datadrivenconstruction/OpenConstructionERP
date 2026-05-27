"""T8 — ERP-Chat per-turn feedback + admin observability tests.

Coverage:

* ``submit_feedback`` writes a row with the requested rating.
* Re-submitting on the same ``(message_id, user_id)`` flips the rating
  in place — exactly one row exists, not two.
* ``get_admin_stats`` correctly counts thumbs up / down and computes the
  feedback-rate percentage off the *assistant-message* denominator.
* Token + cache-hit aggregation reflects the new
  ``tokens_input`` / ``tokens_output`` / ``cache_hit`` columns.

The fixtures spin up an in-memory SQLite engine and create only the
tables this suite needs — no FastAPI app, no migrations — so the test
runs in well under a second and isn't sensitive to the multi-head
state of the live alembic graph.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.modules.erp_chat.models import ChatMessage, ChatSession, ChatTurnFeedback
from app.modules.erp_chat.service import ERPChatService


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                ChatSession.__table__,
                ChatMessage.__table__,
                ChatTurnFeedback.__table__,
            ],
        )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _seed_session_and_assistant(
    session,
    user_id: uuid.UUID,
    *,
    content: str = "Sample reply.",
    tokens_in: int | None = 100,
    tokens_out: int | None = 50,
    cache_hit: bool | None = False,
    created_at: datetime | None = None,
) -> tuple[ChatSession, ChatMessage]:
    chat = ChatSession(user_id=user_id, title="Test")
    session.add(chat)
    await session.flush()

    msg = ChatMessage(
        session_id=chat.id,
        role="assistant",
        content=content,
        tokens_used=(tokens_in or 0) + (tokens_out or 0),
        tokens_input=tokens_in,
        tokens_output=tokens_out,
        cache_hit=cache_hit,
        latency_ms=250,
    )
    if created_at is not None:
        msg.created_at = created_at
        chat.created_at = created_at
    session.add(msg)
    await session.flush()
    return chat, msg


# ── submit_feedback ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_feedback_creates_row_with_thumbs_up(session_factory) -> None:
    user_id = uuid.uuid4()
    async with session_factory() as session:
        _chat, msg = await _seed_session_and_assistant(session, user_id)
        await session.commit()

    async with session_factory() as session:
        service = ERPChatService(session)
        row = await service.submit_feedback(
            message_id=msg.id,
            user_id=str(user_id),
            rating=1,
        )
        await session.commit()
        assert row.rating == 1
        assert row.message_id == msg.id
        assert row.user_id == user_id

    async with session_factory() as session:
        rows = (await session.execute(select(ChatTurnFeedback))).scalars().all()
        assert len(rows) == 1
        assert rows[0].rating == 1


@pytest.mark.asyncio
async def test_submit_feedback_flip_updates_in_place(session_factory) -> None:
    """Same (message, user) re-submit must flip the rating, not duplicate."""
    user_id = uuid.uuid4()
    async with session_factory() as session:
        _chat, msg = await _seed_session_and_assistant(session, user_id)
        await session.commit()

    async with session_factory() as session:
        service = ERPChatService(session)
        first = await service.submit_feedback(
            message_id=msg.id,
            user_id=str(user_id),
            rating=1,
        )
        await session.commit()
        first_id = first.id

    async with session_factory() as session:
        service = ERPChatService(session)
        second = await service.submit_feedback(
            message_id=msg.id,
            user_id=str(user_id),
            rating=-1,
            comment="Hallucinated cost code",
        )
        await session.commit()
        assert second.rating == -1
        assert second.comment == "Hallucinated cost code"
        assert second.id == first_id  # same row, not a new one

    async with session_factory() as session:
        rows = (await session.execute(select(ChatTurnFeedback))).scalars().all()
        assert len(rows) == 1
        assert rows[0].rating == -1


@pytest.mark.asyncio
async def test_submit_feedback_rejects_invalid_rating(session_factory) -> None:
    user_id = uuid.uuid4()
    async with session_factory() as session:
        _chat, msg = await _seed_session_and_assistant(session, user_id)
        await session.commit()

    async with session_factory() as session:
        service = ERPChatService(session)
        with pytest.raises(ValueError):
            await service.submit_feedback(
                message_id=msg.id,
                user_id=str(user_id),
                rating=0,
            )
        with pytest.raises(ValueError):
            await service.submit_feedback(
                message_id=msg.id,
                user_id=str(user_id),
                rating=99,
            )


@pytest.mark.asyncio
async def test_submit_feedback_idor_guard(session_factory) -> None:
    """Submitting on a message owned by another user must surface as 404."""
    owner = uuid.uuid4()
    attacker = uuid.uuid4()
    async with session_factory() as session:
        _chat, msg = await _seed_session_and_assistant(session, owner)
        await session.commit()

    async with session_factory() as session:
        service = ERPChatService(session)
        with pytest.raises(LookupError):
            await service.submit_feedback(
                message_id=msg.id,
                user_id=str(attacker),
                rating=1,
            )


@pytest.mark.asyncio
async def test_submit_feedback_unknown_message_id(session_factory) -> None:
    user_id = uuid.uuid4()
    async with session_factory() as session:
        service = ERPChatService(session)
        with pytest.raises(LookupError):
            await service.submit_feedback(
                message_id=uuid.uuid4(),  # never persisted
                user_id=str(user_id),
                rating=1,
            )


# ── get_admin_stats ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_stats_counts_thumbs_and_feedback_rate(session_factory) -> None:
    """4 assistant messages · 2 thumbs up · 1 thumbs down → 75% feedback rate.

    3 distinct rated messages / 4 total = 75%. The user gives both a thumbs-up
    *and later changes their mind to thumbs-down* on one message; that should
    only count as one distinct rated message.
    """
    user_id = uuid.uuid4()
    async with session_factory() as session:
        chat, m1 = await _seed_session_and_assistant(
            session,
            user_id,
            content="Reply 1",
            tokens_in=100,
            tokens_out=50,
        )
        m2 = ChatMessage(
            session_id=chat.id,
            role="assistant",
            content="Reply 2",
            tokens_used=120,
            tokens_input=80,
            tokens_output=40,
            cache_hit=True,
        )
        m3 = ChatMessage(
            session_id=chat.id,
            role="assistant",
            content="Reply 3",
            tokens_used=200,
            tokens_input=120,
            tokens_output=80,
            cache_hit=False,
        )
        m4 = ChatMessage(
            session_id=chat.id,
            role="assistant",
            content="Reply 4",
            tokens_used=0,
            tokens_input=None,
            tokens_output=None,
            cache_hit=None,
        )
        session.add_all([m2, m3, m4])
        await session.flush()

        # Also seed a couple of user-prompt messages — these should NOT be
        # counted in total_messages.
        u1 = ChatMessage(
            session_id=chat.id,
            role="user",
            content="how much is rebar?",
        )
        u2 = ChatMessage(
            session_id=chat.id,
            role="user",
            content="what about steel?",
        )
        session.add_all([u1, u2])
        await session.flush()

        # 2 thumbs up
        session.add_all(
            [
                ChatTurnFeedback(message_id=m1.id, user_id=user_id, rating=1),
                ChatTurnFeedback(message_id=m2.id, user_id=user_id, rating=1),
            ]
        )
        # 1 thumbs down
        session.add(
            ChatTurnFeedback(
                message_id=m3.id,
                user_id=user_id,
                rating=-1,
                comment="wrong unit",
            )
        )
        await session.commit()

    async with session_factory() as session:
        service = ERPChatService(session)
        stats = await service.get_admin_stats(window_days=30)

    assert stats["total_messages"] == 4
    assert stats["total_thumbs_up"] == 2
    assert stats["total_thumbs_down"] == 1
    # 3 of 4 assistant messages have a rating → 75%
    assert stats["feedback_rate_pct"] == 75.0
    # tokens: 100+80+120 input; 50+40+80 output
    assert stats["total_tokens_input"] == 300
    assert stats["total_tokens_output"] == 170
    # cache_hit denominator counts only non-NULL rows (3) — 1 hit → 33.33%
    assert stats["cache_hit_rate_pct"] == pytest.approx(33.33, rel=1e-2)
    # top_negative_prompts surfaces the message-3 downvote
    assert len(stats["top_negative_prompts"]) == 1
    assert stats["top_negative_prompts"][0]["thumbs_down"] == 1
    # daily_breakdown seeds every day of the window
    assert len(stats["daily_breakdown"]) == 30


@pytest.mark.asyncio
async def test_admin_stats_empty_window_returns_zeroes(session_factory) -> None:
    """No data → all zeroes, no division-by-zero blowups."""
    async with session_factory() as session:
        service = ERPChatService(session)
        stats = await service.get_admin_stats(window_days=7)

    assert stats["total_messages"] == 0
    assert stats["total_thumbs_up"] == 0
    assert stats["total_thumbs_down"] == 0
    assert stats["feedback_rate_pct"] == 0.0
    assert stats["cache_hit_rate_pct"] == 0.0
    assert stats["top_negative_prompts"] == []
    assert len(stats["daily_breakdown"]) == 7


@pytest.mark.asyncio
async def test_admin_stats_top_negative_prompts_uses_preceding_user_message(
    session_factory,
) -> None:
    """Downvoted assistant turn surfaces the immediately-preceding user prompt."""
    user_id = uuid.uuid4()
    base = datetime.now(UTC) - timedelta(hours=2)
    async with session_factory() as session:
        chat = ChatSession(user_id=user_id, title="x")
        session.add(chat)
        await session.flush()
        u1 = ChatMessage(
            session_id=chat.id,
            role="user",
            content="please compute the BOQ total for project alpha quickly",
        )
        u1.created_at = base
        session.add(u1)
        await session.flush()
        a1 = ChatMessage(
            session_id=chat.id,
            role="assistant",
            content="42 EUR",
        )
        a1.created_at = base + timedelta(minutes=1)
        session.add(a1)
        await session.flush()

        session.add(ChatTurnFeedback(message_id=a1.id, user_id=user_id, rating=-1))
        await session.commit()

    async with session_factory() as session:
        service = ERPChatService(session)
        stats = await service.get_admin_stats(window_days=30)
    snippets = stats["top_negative_prompts"]
    assert len(snippets) == 1
    assert snippets[0]["snippet"].startswith("please compute the BOQ total")
    assert snippets[0]["thumbs_down"] == 1
