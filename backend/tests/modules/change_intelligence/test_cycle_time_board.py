# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the change cycle-time board (PostgreSQL, py3.12).

Seeds change-family records directly and drives the service that feeds the pure
:mod:`cycle_time` engine, then checks the per-party rollup, that closed records
are excluded, and that the board is fenced to one project.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.change_intelligence.cycle_time import UNASSIGNED
from app.modules.change_intelligence.service import build_project_board
from app.modules.changeorders.models import ChangeOrder
from app.modules.moc.models import MoCEntry
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from app.modules.variations.models import Notice, VariationRequest
from tests._pg import transactional_session

PAST_DUE = "2020-01-01"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"cyc-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Cyc",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Cyc {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.mark.asyncio
async def test_board_groups_open_changes_by_party(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add_all(
        [
            # Two open change orders with Alice in court, one overdue.
            ChangeOrder(
                project_id=pid,
                code="CO-1",
                title="Alpha",
                status="submitted",
                ball_in_court="alice",
                response_due_date=PAST_DUE,
            ),
            ChangeOrder(
                project_id=pid,
                code="CO-2",
                title="Beta",
                status="draft",
                ball_in_court="alice",
            ),
            # One open notice with Bob in court.
            Notice(project_id=pid, code="NOT-1", title="Gamma", status="issued", ball_in_court="bob"),
            # One open variation request with nobody assigned.
            VariationRequest(project_id=pid, code="VR-1", title="Delta", status="submitted"),
            # A closed change order - must be excluded.
            ChangeOrder(project_id=pid, code="CO-3", title="Done", status="executed", ball_in_court="alice"),
            # A closed MoC entry - must be excluded.
            MoCEntry(project_id=pid, code="MOC-1", title="Impl", status="implemented", ball_in_court="bob"),
        ]
    )
    await session.flush()

    board = await build_project_board(session, pid)

    assert board.total_open == 4
    assert board.total_overdue == 1
    assert board.unassigned_open == 1

    loads = {p.party: p for p in board.parties}
    assert set(loads) == {"alice", "bob", UNASSIGNED}
    assert loads["alice"].open_count == 2
    assert loads["alice"].overdue_count == 1
    assert loads["bob"].open_count == 1
    assert loads[UNASSIGNED].open_count == 1

    # Most-loaded party ranks first; the overdue item sorts to the top.
    assert board.parties[0].party == "alice"
    assert board.items[0].overdue is True
    assert board.items[0].code == "CO-1"


@pytest.mark.asyncio
async def test_board_empty_when_all_closed(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add(ChangeOrder(project_id=pid, code="CO-X", title="Closed", status="executed"))
    await session.flush()

    board = await build_project_board(session, pid)
    assert board.total_open == 0
    assert board.parties == []
    assert board.items == []


@pytest.mark.asyncio
async def test_board_is_scoped_to_project(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    session.add_all(
        [
            ChangeOrder(project_id=pid, code="CO-A", title="Mine", status="submitted", ball_in_court="alice"),
            ChangeOrder(project_id=other, code="CO-B", title="Theirs", status="submitted", ball_in_court="bob"),
        ]
    )
    await session.flush()

    board = await build_project_board(session, pid)
    assert board.total_open == 1
    assert [r.code for r in board.items] == ["CO-A"]
    assert {p.party for p in board.parties} == {"alice"}
