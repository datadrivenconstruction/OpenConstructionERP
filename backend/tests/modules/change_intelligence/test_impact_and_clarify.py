# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for change impact projection and the clarifier service.

The impact test seeds approved change orders and an agreed variation order and
checks the materialized cost / schedule roll-up (and that non-approved changes
are excluded). The clarifier test exercises the thin service wrapper over the
pure engine.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.change_intelligence.service import (
    build_impact_projection,
    clarify_change_note,
)
from app.modules.changeorders.models import ChangeOrder
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from app.modules.variations.models import VariationOrder
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"imp-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Imp",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Imp {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.mark.asyncio
async def test_impact_projection_sums_committed_changes(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add_all(
        [
            ChangeOrder(
                project_id=pid,
                code="CO-1",
                title="Approved",
                status="executed",
                cost_impact=Decimal("1000.00"),
                schedule_impact_days=5,
                currency="EUR",
            ),
            # A draft change order is not committed and must be excluded.
            ChangeOrder(
                project_id=pid,
                code="CO-2",
                title="Draft",
                status="draft",
                cost_impact=Decimal("999.00"),
                schedule_impact_days=9,
                currency="EUR",
            ),
            VariationOrder(
                project_id=pid,
                code="VO-1",
                title="Agreed",
                status="completed",
                final_cost_impact=Decimal("500.00"),
                final_schedule_days=3,
                currency="EUR",
            ),
        ]
    )
    await session.flush()

    projection = await build_impact_projection(session, pid)

    assert projection.approved_count == 2
    assert projection.total_schedule_delta_days == 8
    assert projection.primary_currency == "EUR"
    assert projection.primary_currency_cost == Decimal("1500.00")
    kinds = {k.kind: k for k in projection.by_kind}
    assert kinds["change_order"].total_cost == Decimal("1000.00")
    assert kinds["variation_order"].total_cost == Decimal("500.00")


@pytest.mark.asyncio
async def test_impact_projection_empty_project(session: AsyncSession) -> None:
    pid = await _project(session)
    projection = await build_impact_projection(session, pid)
    assert projection.approved_count == 0
    assert projection.primary_currency == ""
    assert projection.primary_currency_cost == Decimal("0")


def test_clarify_change_note_flags_gaps() -> None:
    # A thin note with no cost, schedule, clause or party should flag them.
    clarified = clarify_change_note("Move the door")
    fields = {gap.field for gap in clarified.missing}
    assert "cost_impact" in fields
    assert "responsible_party" in fields
    assert clarified.completeness < 1.0


def test_clarify_change_note_fidic_clause() -> None:
    clarified = clarify_change_note(
        "Client wants extra works priced at 5000 EUR with a 10 day delay under clause 13.3, contractor to carry it.",
        contract_standard="FIDIC",
    )
    standards = {c.standard for c in clarified.clause_suggestions}
    assert "FIDIC" in standards
    assert clarified.completeness == 1.0
