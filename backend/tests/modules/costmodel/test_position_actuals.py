# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The bill position read back with everything recorded against it.

Two kinds of assertion here and they check different things. The pure ones
drive ``assemble_rows`` with dictionaries and prove the join and the arithmetic
without a database. The rest go through ``build_position_actuals`` against real
rows, because the join is only correct if each aggregate is keyed the way its
own module keys it, and a dictionary the test built itself cannot show that.

The zero cases matter as much as the filled ones. A position with no cost line
and a position with a cost line nothing has been spent against both report zero
money, and the two mean opposite things to the reader, so the report has to
tell them apart rather than leaving a page of zeros to be interpreted.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.costmodel.models import CostLine
from app.modules.costmodel.position_actuals import assemble_rows, build_position_actuals
from app.modules.procurement.schemas import POCreate, POItemCreate
from app.modules.procurement.service import ProcurementService
from app.modules.progress.models import ProgressEntry
from app.modules.site_inventory.ledger import MovementType
from app.modules.site_inventory.models import StockItem, StockMovement
from tests._pg import transactional_session

# ``asyncio_mode = "auto"`` in pyproject collects the async tests below without
# a marker, and marking the synchronous ones would only produce a warning.


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
def project_id() -> uuid.UUID:
    return uuid.uuid4()


# ── The join and the arithmetic, without a database ──────────────────────────


def fake_position(**overrides: object) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "ordinal": "1.1",
        "description": "Reinforced concrete, C30/37",
        "unit": "m3",
        "quantity": "120",
        "unit_rate": "180.00",
        "total": "21600.00",
        "cost_line_id": uuid.uuid4(),
        "sort_order": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_money_is_looked_up_by_cost_line_and_progress_by_position() -> None:
    """The one row where the two spines meet.

    Money is keyed by cost line, physical facts by position. Getting this
    backwards would leave every column zero on a project that is fully wired,
    which reads as an idle site rather than as a broken join.
    """
    pos = fake_position()
    key = str(pos.cost_line_id)

    rows = assemble_rows(
        [pos],
        budget={key: {"planned": Decimal("20000"), "actual": Decimal("500"), "committed": Decimal("0")}},
        committed={key: Decimal("1800.00")},
        contracted={key: Decimal("21000.00")},
        claimed={key: Decimal("3000.00")},
        cost_line_codes={key: "CL-1.1"},
        installed_pct={pos.id: 40.0},
        consumed={pos.id: (Decimal("55"), Decimal("9900.00"))},
    )

    (row,) = rows
    assert row.cost_line_code == "CL-1.1"
    assert row.estimate_amount == Decimal("21600.00")
    assert row.committed_amount == Decimal("1800.00")
    assert row.contracted_amount == Decimal("21000.00")
    assert row.claimed_amount == Decimal("3000.00")
    assert row.budget_planned == Decimal("20000.00")
    assert row.budget_actual == Decimal("500.00")
    assert row.installed_percent == Decimal("40.00")
    assert row.consumed_quantity == Decimal("55.0000")
    assert row.consumed_amount == Decimal("9900.00")
    assert row.on_cost_spine is True


def test_uncommitted_is_the_estimate_less_what_has_been_ordered() -> None:
    """Committed against remaining, the number the founder asked for by name."""
    pos = fake_position()
    key = str(pos.cost_line_id)
    (row,) = assemble_rows(
        [pos],
        budget={},
        committed={key: Decimal("1800.00")},
        contracted={},
        claimed={},
        cost_line_codes={},
        installed_pct={},
        consumed={},
    )
    assert row.uncommitted_amount == Decimal("19800.00")


def test_ordering_more_than_was_estimated_is_reported_signed() -> None:
    """An overspend is a finding, so it must not be floored at zero.

    Clamping would turn the one row a cost manager needs to see into a row that
    looks exactly like a fully committed item.
    """
    pos = fake_position()
    key = str(pos.cost_line_id)
    (row,) = assemble_rows(
        [pos],
        budget={},
        committed={key: Decimal("25000.00")},
        contracted={},
        claimed={},
        cost_line_codes={},
        installed_pct={},
        consumed={},
    )
    assert row.uncommitted_amount == Decimal("-3400.00")


def test_a_position_never_reported_on_is_not_reported_as_zero_percent() -> None:
    """No observation and an observation of zero are different facts.

    A bar drawn at zero says the crew looked and found nothing done. None says
    nobody has looked, and the drawer has to be able to draw that differently.
    """
    (row,) = assemble_rows(
        [fake_position()],
        budget={},
        committed={},
        contracted={},
        claimed={},
        cost_line_codes={},
        installed_pct={},
        consumed={},
    )
    assert row.installed_percent is None
    assert row.installed_amount == Decimal("0")


def test_a_position_off_the_spine_still_reports_its_work() -> None:
    """The crew's work is real whether or not the cost spine exists.

    A row that vanished for want of a cost line would read as no work done,
    which is the opposite of the truth on a project that has simply never
    generated the spine.
    """
    pos = fake_position(cost_line_id=None)
    (row,) = assemble_rows(
        [pos],
        budget={},
        committed={},
        contracted={},
        claimed={},
        cost_line_codes={},
        installed_pct={pos.id: 60.0},
        consumed={pos.id: (Decimal("70"), Decimal("12600.00"))},
    )
    assert row.on_cost_spine is False
    assert row.committed_amount == Decimal("0")
    assert row.installed_percent == Decimal("60.00")
    assert row.consumed_amount == Decimal("12600.00")


def test_an_empty_estimate_does_not_break_the_row() -> None:
    """A position whose money was never filled in holds "" and not "0"."""
    pos = fake_position(quantity="", unit_rate="", total="")
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
    assert row.estimate_amount == Decimal("0")
    assert row.estimate_quantity == Decimal("0")


# ── Against real rows ────────────────────────────────────────────────────────


async def seed_position(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    ordinal: str = "1.1",
    with_cost_line: bool = True,
) -> tuple[Position, CostLine | None]:
    boq = BOQ(project_id=project_id, name="Bill of quantities", description="")
    session.add(boq)
    await session.flush()
    position = Position(
        boq_id=boq.id,
        ordinal=ordinal,
        description="Reinforced concrete, C30/37",
        unit="m3",
        quantity="120",
        unit_rate="180.00",
        total="21600.00",
    )
    session.add(position)
    await session.flush()
    if not with_cost_line:
        return position, None
    cost_line = CostLine(
        project_id=project_id,
        code=f"CL-{ordinal}",
        description=position.description,
        unit="m3",
        source="boq",
        boq_position_id=position.id,
        boq_id=boq.id,
        estimate_quantity="120",
        estimate_unit_rate="180.00",
        estimate_amount="21600.00",
        currency="",
        status="active",
    )
    session.add(cost_line)
    await session.flush()
    position.cost_line_id = cost_line.id
    await session.flush()
    return position, cost_line


async def test_an_issued_order_shows_up_against_the_position_that_raised_it(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """End to end, and the reason this endpoint is worth having.

    The order is raised the way a buyer raises one, against a bill position and
    never naming a cost line, and it comes back on the position's own row. This
    is the same path the committed report reads, seen from the estimator's side
    of the bill.
    """
    position, cost_line = await seed_position(session, project_id)
    assert cost_line is not None

    po = await ProcurementService(session).create_po(
        POCreate(
            project_id=project_id,
            po_number="PO-0001",
            items=[
                POItemCreate(
                    description="Reinforced concrete, C30/37",
                    quantity="10",
                    unit="m3",
                    unit_rate="180.00",
                    boq_position_id=str(position.id),
                )
            ],
        )
    )
    po.status = "issued"
    await session.flush()

    report = await build_position_actuals(session, project_id)
    (row,) = report.rows
    assert row.boq_position_id == position.id
    assert row.cost_line_code == "CL-1.1"
    assert row.committed_amount == Decimal("1800.00")
    assert row.uncommitted_amount == Decimal("19800.00")
    assert report.totals["committed_amount"] == Decimal("1800.00")
    assert report.positions_off_spine == 0


async def test_consumption_counts_and_waste_does_not(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Waste left the store without becoming part of the works.

    Counting it here would report the item as further advanced than it is. The
    site inventory module reports waste on its own, which is where it belongs.
    """
    position, _ = await seed_position(session, project_id)
    item = StockItem(project_id=project_id, name="C30/37", unit="m3", boq_position_id=position.id)
    session.add(item)
    await session.flush()

    occurred = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    for movement_type, quantity in (
        (MovementType.INBOUND, "80"),
        (MovementType.CONSUMPTION, "55"),
        (MovementType.WASTE, "5"),
    ):
        session.add(
            StockMovement(
                project_id=project_id,
                item_id=item.id,
                movement_type=movement_type.value,
                quantity=Decimal(quantity),
                unit_cost=Decimal("180.00"),
                boq_position_id=position.id,
                occurred_at=occurred,
            )
        )
    await session.flush()

    report = await build_position_actuals(session, project_id)
    (row,) = report.rows
    assert row.consumed_quantity == Decimal("55.0000"), (
        "the consumed quantity counts something other than CONSUMPTION; inbound stock or waste is "
        "being read as work done"
    )
    assert row.consumed_amount == Decimal("9900.00")


async def test_the_latest_progress_observation_is_the_one_reported(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """Progress is append only, so the row has to take the newest entry."""
    position, _ = await seed_position(session, project_id)
    for pct, period in ((25.0, "2026-06"), (40.0, "2026-07")):
        session.add(
            ProgressEntry(
                project_id=project_id,
                boq_position_id=position.id,
                percent_complete=pct,
                period_label=period,
            )
        )
        await session.flush()

    report = await build_position_actuals(session, project_id)
    (row,) = report.rows
    assert row.installed_percent == Decimal("40.00")
    assert row.installed_amount == Decimal("8640.00")


async def test_a_position_with_no_cost_line_is_counted_and_not_hidden(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """Zero money for want of a link is a different report from zero spend."""
    await seed_position(session, project_id, ordinal="1.1", with_cost_line=False)
    await seed_position(session, project_id, ordinal="2.1", with_cost_line=True)

    report = await build_position_actuals(session, project_id)
    assert len(report.rows) == 2
    assert report.positions_off_spine == 1
    off = [r for r in report.rows if not r.on_cost_spine]
    assert len(off) == 1
    assert off[0].estimate_amount == Decimal("21600.00"), (
        "a position off the spine lost its estimate as well as its money; only the money columns "
        "depend on the cost line"
    )


@pytest.mark.tenant_isolation
async def test_another_projects_position_cannot_be_asked_about(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The narrow-by-id path fetches by id alone, so it has to check ownership.

    Without the check a caller reads a neighbouring project's estimate through
    an endpoint scoped to theirs.
    """
    foreign_position, _ = await seed_position(session, uuid.uuid4(), ordinal="9.9")
    mine, _ = await seed_position(session, project_id)

    report = await build_position_actuals(session, project_id, position_ids=[mine.id, foreign_position.id])
    assert [r.boq_position_id for r in report.rows] == [mine.id]


async def test_an_empty_project_reports_nothing_rather_than_failing(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    report = await build_position_actuals(session, project_id)
    assert report.rows == []
    assert report.positions_off_spine == 0
