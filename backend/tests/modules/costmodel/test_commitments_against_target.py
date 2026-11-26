# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Commitments and forecasts read against the target cost, and the drill-down behind a grid row.

Worked example used throughout: 120 m3 of concrete, sold at 180.00 (21,600.00),
target cost 150.00 (18,000.00). An order for 120 m3 at 160.00 (19,200.00) is
within the price and 1,200.00 above the target.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.commitment_grid import build_commitment_grid, position_sources
from app.modules.costmodel.cost_control import (
    FINDING_OVER_PLAN,
    FINDING_OVER_TARGET,
    LineFigures,
    LineInput,
    line_findings,
)
from app.modules.costmodel.cost_control_data import target_by_cost_line
from app.modules.costmodel.position_actuals import assemble_rows
from app.modules.procurement.schemas import POCreate, POItemCreate
from app.modules.procurement.service import ProcurementService
from tests._pg import transactional_session
from tests.modules.costmodel.test_position_actuals import seed_position


def _pos(**overrides: object) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "ordinal": "1.1",
        "description": "Reinforced concrete, C30/37",
        "unit": "m3",
        "quantity": "120",
        "unit_rate": "180.00",
        "target_rate": "150.00",
        "total": "21600.00",
        "cost_line_id": uuid.uuid4(),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_target_per_cost_line_counts_only_positions_with_a_target() -> None:
    line = uuid.uuid4()
    other = uuid.uuid4()
    out = target_by_cost_line(
        [
            _pos(cost_line_id=line),
            _pos(cost_line_id=line, quantity="10", target_rate="100"),
            _pos(cost_line_id=other, target_rate=None),
        ]
    )
    assert out == {str(line): Decimal("19000.00")}


def test_forecast_within_plan_but_above_target_is_flagged() -> None:
    figures = LineFigures(budget=Decimal("21600"), awarded=Decimal("19200"), target=Decimal("18000"))
    found = line_findings([LineInput(key="L1", code="CL-1.1", figures=figures)])
    ids = [f.rule_id for f in found]
    assert FINDING_OVER_PLAN not in ids
    (over,) = [f for f in found if f.rule_id == FINDING_OVER_TARGET]
    assert over.amount == Decimal("1200")
    assert over.details["target"] == "18000"


def test_no_target_finding_when_the_plan_is_the_target() -> None:
    figures = LineFigures(budget=Decimal("18000"), awarded=Decimal("19200"), target=Decimal("18000"))
    ids = [f.rule_id for f in line_findings([LineInput(key="L1", code="CL-1.1", figures=figures)])]
    assert FINDING_OVER_PLAN in ids
    assert FINDING_OVER_TARGET not in ids


def test_no_target_finding_without_a_target() -> None:
    figures = LineFigures(budget=Decimal("21600"), awarded=Decimal("25000"))
    ids = [f.rule_id for f in line_findings([LineInput(key="L1", code="CL-1.1", figures=figures)])]
    assert FINDING_OVER_TARGET not in ids


def test_position_uncommitted_is_read_against_the_target() -> None:
    pos = _pos()
    key = str(pos.cost_line_id)
    (row,) = assemble_rows(
        [pos],
        budget={},
        committed={key: Decimal("19200.00")},
        contracted={},
        claimed={},
        cost_line_codes={},
        installed_pct={},
        consumed={},
    )
    assert row.budget_basis == "target"
    assert row.estimate_amount == Decimal("21600.00")
    assert row.cost_budget_amount == Decimal("18000.00")
    assert row.uncommitted_amount == Decimal("-1200.00")


def test_position_without_target_keeps_the_estimate() -> None:
    pos = _pos(target_rate=None)
    (row,) = assemble_rows(
        [pos],
        budget={},
        committed={},
        contracted={},
        claimed={},
        cost_line_codes={},
        installed_pct={},
        consumed={},
    )
    assert row.budget_basis == "unit_rate"
    assert row.uncommitted_amount == Decimal("21600.00")


# ── Against real rows ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _order(session: AsyncSession, project_id: uuid.UUID, position_id: uuid.UUID, number: str, status: str):
    po = await ProcurementService(session).create_po(
        POCreate(
            project_id=project_id,
            po_number=number,
            items=[
                POItemCreate(
                    description="Ready-mix concrete C30/37",
                    quantity="120",
                    unit="m3",
                    unit_rate="160.00",
                    boq_position_id=str(position_id),
                )
            ],
        )
    )
    po.status = status
    await session.flush()
    return po


async def test_grid_row_sources_sum_to_its_committed_figure(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    position, _ = await seed_position(session, project_id)
    position.target_rate = "150.00"
    await session.flush()
    issued = await _order(session, project_id, position.id, "PO-0001", "issued")
    await _order(session, project_id, position.id, "PO-0002", "draft")

    grid = await build_commitment_grid(session, project_id)
    (row,) = grid.rows
    assert row.budget_basis == "target"
    assert row.budget_value == Decimal("18000.00")
    assert row.committed_value == Decimal("19200.00")
    assert row.remaining_value == Decimal("-1200.00")

    pos, sources = await position_sources(session, project_id, position.id)
    assert pos is not None
    (src,) = sources
    assert src.kind == "purchase_order"
    assert src.document_id == issued.id
    assert src.document_number == "PO-0001"
    assert src.committed_value == row.committed_value
    assert src.committed_qty == row.committed_qty


async def test_sources_of_a_position_on_another_project_are_not_found(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    position, _ = await seed_position(session, project_id)
    pos, sources = await position_sources(session, uuid.uuid4(), position.id)
    assert pos is None
    assert sources == []


async def test_position_without_cost_line_has_no_sources(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    position, _ = await seed_position(session, project_id, with_cost_line=False)
    pos, sources = await position_sources(session, project_id, position.id)
    assert pos is not None
    assert sources == []
