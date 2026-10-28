# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for pre-construction scope-ambiguity scoring (#24).

The service reads a project's bill-of-quantities lines and grades each for the
signals that breed a downstream variation (a provisional sum, vague wording, a
missing quantity or unit, an under-specified description). These tests seed real
positions on PostgreSQL and assert the wiring: each line is graded with the
right reasons, a section heading is exempt from the measure signals, the report
is fenced to its project, and a ``boq_id`` filter scopes to one bill.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.change_intelligence.scope_service import assess_project_scope
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"scope-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="SCOPE",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"SCOPE {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


async def _boq(session: AsyncSession, project_id: uuid.UUID, *, name: str = "Tender BOQ") -> uuid.UUID:
    boq = BOQ(project_id=project_id, name=name)
    session.add(boq)
    await session.flush()
    return boq.id


async def _position(
    session: AsyncSession,
    boq_id: uuid.UUID,
    *,
    ordinal: str,
    description: str,
    unit: str = "",
    quantity: str = "0",
    unit_rate: str = "0",
    parent_id: uuid.UUID | None = None,
) -> uuid.UUID:
    pos = Position(
        boq_id=boq_id,
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=quantity,
        unit_rate=unit_rate,
        parent_id=parent_id,
    )
    session.add(pos)
    await session.flush()
    return pos.id


def _by_id(report: object) -> dict:
    """Index a report's graded lines by their line id."""
    return {line.line_id: line for line in report.lines}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_grades_lines_and_exempts_headings(session: AsyncSession) -> None:
    """Each line gets the right reasons; a parent (heading) skips measure signals."""
    pid = await _project(session)
    boq_id = await _boq(session, pid)

    # A section heading: parent of the line below, so it carries no measure and
    # must NOT trip the missing-quantity / missing-unit / under-specified signals.
    heading = await _position(session, boq_id, ordinal="1", description="Section 1 Substructure works")
    # A clean, fully specified child line under the heading.
    clean = await _position(
        session,
        boq_id,
        ordinal="1.1",
        description="Excavate to reduce levels in firm clay",
        unit="m3",
        quantity="85",
        unit_rate="12.50",
        parent_id=heading,
    )
    # A provisional sum / allowance line: provisional + vague wording.
    provisional = await _position(
        session,
        boq_id,
        ordinal="2",
        description="Provisional sum allowance for external landscaping",
        unit="item",
        quantity="1",
        unit_rate="0",
    )
    # A thin line with no quantity and no unit.
    sparse = await _position(session, boq_id, ordinal="3", description="Sundries")

    report = await assess_project_scope(session, project_id=pid)
    by = _by_id(report)

    assert len(report.lines) == 4

    # Heading and clean line are clean: no reasons, low band. The heading proves
    # the exemption (it has no unit and a zero quantity yet is not flagged).
    assert by[str(heading)].reasons == ()
    assert by[str(heading)].band == "low"
    assert by[str(clean)].reasons == ()
    assert by[str(clean)].band == "low"

    # Provisional line: provisional-sum + vague wording, high band.
    assert "provisional_sum" in by[str(provisional)].reasons
    assert "vague_language" in by[str(provisional)].reasons
    assert by[str(provisional)].band == "high"

    # Sparse line: vague + missing quantity + missing unit + under-specified.
    sparse_reasons = set(by[str(sparse)].reasons)
    assert {"vague_language", "missing_quantity", "missing_unit", "underspecified_description"} <= sparse_reasons

    # Roll-ups: two high (provisional, sparse), two low (heading, clean).
    assert report.counts_by_band == {"high": 2, "elevated": 0, "low": 2}
    # Mean of 0 + 0 + 85 + 100 over four lines.
    assert report.ambiguity_index == pytest.approx(46.25)
    # Vague wording fired on two lines, more than any other reason.
    assert report.top_reasons[0] == "vague_language"


@pytest.mark.asyncio
async def test_report_is_scoped_to_project(session: AsyncSession) -> None:
    """A project's report never includes another project's BOQ lines (IDOR)."""
    pid = await _project(session)
    other = await _project(session)
    boq_id = await _boq(session, pid)
    await _position(session, boq_id, ordinal="1", description="Provisional sum allowance")

    report = await assess_project_scope(session, project_id=other)
    assert report.lines == ()
    assert report.ambiguity_index == 0.0
    assert report.counts_by_band == {"high": 0, "elevated": 0, "low": 0}


@pytest.mark.asyncio
async def test_boq_id_filter_scopes_to_one_bill(session: AsyncSession) -> None:
    """When a boq_id is given only that bill's lines are graded."""
    pid = await _project(session)
    boq_a = await _boq(session, pid, name="Bill A")
    boq_b = await _boq(session, pid, name="Bill B")
    a_line = await _position(
        session, boq_a, ordinal="1", description="Excavate firm clay to levels", unit="m3", quantity="10"
    )
    await _position(session, boq_b, ordinal="1", description="Provisional sum allowance", unit="item", quantity="1")

    report = await assess_project_scope(session, project_id=pid, boq_id=boq_a)
    line_ids = {line.line_id for line in report.lines}
    assert line_ids == {str(a_line)}


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_foreign_boq_id_yields_empty_report(session: AsyncSession) -> None:
    """A boq_id belonging to another project resolves to no rows, not a leak."""
    pid = await _project(session)
    other = await _project(session)
    other_boq = await _boq(session, other)
    await _position(session, other_boq, ordinal="1", description="Provisional sum allowance")

    report = await assess_project_scope(session, project_id=pid, boq_id=other_boq)
    assert report.lines == ()
