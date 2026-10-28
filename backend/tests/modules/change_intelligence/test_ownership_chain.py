# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the ownership hand-off chain (PostgreSQL, py3.12).

Drives the wired write path - the change-order service's ``update_order`` - to
move ``ball_in_court`` between parties, which records ``ownership_handoff`` rows
in the activity log. Then reconstructs the chain through
``build_ownership_chain_for`` and checks the ordered segments, the current
holder, the per-party dwell, and the never-handed-off synthesis case.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import ActivityLog
from app.modules.change_intelligence.cycle_time import KIND_CHANGE_ORDER
from app.modules.change_intelligence.service import build_ownership_chain_for
from app.modules.changeorders.models import ChangeOrder
from app.modules.changeorders.schemas import ChangeOrderUpdate
from app.modules.changeorders.service import ChangeOrderService
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"own-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Own",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Own {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


async def _draft_order(session: AsyncSession, pid: uuid.UUID, ball: str | None) -> ChangeOrder:
    order = ChangeOrder(project_id=pid, code=f"CO-{uuid.uuid4().hex[:4]}", title="Owned", status="draft")
    order.ball_in_court = ball
    session.add(order)
    await session.flush()
    return order


@pytest.mark.asyncio
async def test_ball_in_court_changes_build_ownership_chain(session: AsyncSession) -> None:
    pid = await _project(session)
    order = await _draft_order(session, pid, "alice")
    svc = ChangeOrderService(session)

    # Two custody hand-offs through the wired update path: alice -> bob -> carol.
    await svc.update_order(order.id, ChangeOrderUpdate(ball_in_court="bob"), user_id=str(uuid.uuid4()))
    await svc.update_order(order.id, ChangeOrderUpdate(ball_in_court="carol"), user_id=str(uuid.uuid4()))
    await session.flush()

    # Each real custody change wrote exactly one ownership_handoff row.
    rows = (
        (
            await session.execute(
                select(ActivityLog)
                .where(ActivityLog.entity_type == KIND_CHANGE_ORDER)
                .where(ActivityLog.entity_id == str(order.id))
                .where(ActivityLog.action == "ownership_handoff")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {(r.from_status, r.to_status) for r in rows} == {("alice", "bob"), ("bob", "carol")}

    # Reconstruct as of a fixed instant well after the hand-offs so the open
    # segment accrues a clearly positive dwell.
    as_of = datetime.now(UTC) + timedelta(days=10)
    chain, project_id = await build_ownership_chain_for(session, KIND_CHANGE_ORDER, order.id, now=as_of)

    assert project_id == pid
    assert chain.current_holder == "carol"
    assert chain.has_current_holder is True
    # alice held the ball before the first recorded hand-off (no received-ts).
    assert chain.has_unrecorded_origin is True
    assert chain.chain_inconsistent is False
    assert chain.total_handoffs == 2

    # Ordered segments: bob then carol (alice's pre-history is not fabricated).
    assert [s.party for s in chain.segments] == ["bob", "carol"]
    assert chain.segments[0].is_open is False
    assert chain.segments[-1].is_open is True
    # The open segment dwells up to ``as_of`` -> close to ten days.
    assert chain.segments[-1].dwell_days >= 9.0

    dwell = {pd.party: pd for pd in chain.dwell_by_party}
    assert set(dwell) == {"bob", "carol"}
    assert dwell["carol"].segment_count == 1
    assert dwell["carol"].dwell_days >= 9.0


@pytest.mark.asyncio
async def test_never_handed_off_synthesizes_open_segment(session: AsyncSession) -> None:
    pid = await _project(session)
    # Assigned once at creation, never handed off: no ownership_handoff rows.
    order = await _draft_order(session, pid, "alice")

    chain, project_id = await build_ownership_chain_for(session, KIND_CHANGE_ORDER, order.id)

    assert project_id == pid
    assert chain.total_handoffs == 1  # one synthesized open segment
    assert chain.current_holder == "alice"
    assert chain.has_current_holder is True
    assert chain.ownership_ambiguous is False
    assert [s.party for s in chain.segments] == ["alice"]
    assert chain.segments[0].is_open is True


@pytest.mark.asyncio
async def test_unassigned_change_has_no_holder(session: AsyncSession) -> None:
    pid = await _project(session)
    order = await _draft_order(session, pid, None)

    chain, project_id = await build_ownership_chain_for(session, KIND_CHANGE_ORDER, order.id)

    assert project_id == pid
    assert chain.total_handoffs == 0
    assert chain.current_holder is None
    assert chain.has_current_holder is False
    # No current holder is the headline ambiguity case.
    assert chain.ownership_ambiguous is True
    assert chain.segments == []


@pytest.mark.asyncio
async def test_unknown_kind_raises_keyerror(session: AsyncSession) -> None:
    with pytest.raises(KeyError):
        await build_ownership_chain_for(session, "not_a_kind", uuid.uuid4())


@pytest.mark.asyncio
async def test_missing_record_raises_lookuperror(session: AsyncSession) -> None:
    with pytest.raises(LookupError):
        await build_ownership_chain_for(session, KIND_CHANGE_ORDER, uuid.uuid4())
