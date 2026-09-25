"""PG: the cost breakdown's Grand Total is the grid's Grand Total, to the cent.

The toolbar's Grand Total card reads ``get_cost_breakdown``. The grid, the
markup panel and the exports read ``get_boq_structured``. The breakdown used to
rebuild each position from its resource rows (``res.quantity x res.unit_rate``
times the position quantity) while everything else summed the position's own
``quantity x unit_rate``. The two agree only while the rows add up to the rate
to the cent, and lines taken from a cost database do not always: a catalogue
component carries a separately rounded cost. One bill then showed two Grand
Totals a few hundred apart.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from app.modules.users.models import User


async def _bill_with_a_drifting_line(session) -> BOQ:
    owner = User(email="card-grid@example.test", hashed_password="x", full_name="Card")
    session.add(owner)
    await session.flush()
    project = Project(name="Card and grid", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Drift")
    session.add(boq)
    await session.flush()

    session.add_all(
        [
            # Rate 100.07 was stored from the catalogue's rounded component
            # costs; its rows multiply out to 0.333 x 150.01 + 1 x 50.11 =
            # 100.06333, so 12 of them rebuilt from the rows is 1200.76 while
            # the line itself says 1200.84.
            Position(
                boq_id=boq.id,
                ordinal="01.001",
                description="Timber frame wall",
                unit="m2",
                quantity="12",
                unit_rate="100.07",
                total="1200.84",
                metadata_={
                    "resources": [
                        {"name": "Carpenter", "type": "labor", "unit": "h", "quantity": 0.333, "unit_rate": 150.01},
                        {"name": "Studs", "type": "material", "unit": "m2", "quantity": 1, "unit_rate": 50.11},
                    ]
                },
            ),
            Position(
                boq_id=boq.id,
                ordinal="01.002",
                description="Concrete slab",
                unit="m3",
                quantity="3",
                unit_rate="210.5",
                total="631.50",
            ),
        ]
    )
    session.add(
        BOQMarkup(
            boq_id=boq.id,
            name="Overhead",
            markup_type="percentage",
            category="overhead",
            percentage="10",
            apply_to="direct_cost",
            is_active=True,
        )
    )
    await session.flush()
    return boq


@pytest.mark.asyncio
async def test_the_card_and_the_grid_print_the_same_grand_total(pg_session) -> None:
    boq = await _bill_with_a_drifting_line(pg_session)
    service = BOQService(pg_session)

    card = await service.get_cost_breakdown(boq.id)
    grid = await service.get_boq_structured(boq.id)

    assert grid.direct_cost == Decimal("1832.34")
    assert card.direct_cost == grid.direct_cost
    assert card.grand_total == grid.grand_total


@pytest.mark.asyncio
async def test_the_categories_still_add_up_to_the_direct_cost(pg_session) -> None:
    """The split keeps its shape: labour and material from the rows, the rest by keyword."""
    boq = await _bill_with_a_drifting_line(pg_session)

    card = await BOQService(pg_session).get_cost_breakdown(boq.id)

    by_type = {c.type: c.amount for c in card.categories}
    assert "labor" in by_type
    assert "material" in by_type
    # Each category is rounded to the cent on its own, so the parts may sit a
    # cent per category away from the rounded whole, never more.
    assert abs(sum(by_type.values()) - card.direct_cost) <= Decimal("0.01") * len(by_type)
