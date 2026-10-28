# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Repricing a region has to reach the assemblies built on it.

Three code paths write ``CostItem.rate``. Two of them announced the change and
the assemblies subscriber pulled the new price through. The third,
``reprice_region`` - the one that rewrites a whole region from the resource
price sheet, and the one a user reaches for when prices move - announced
nothing. So the rates moved, every assembly quoting them kept its own copy of
``unit_cost``, and a budget built from assemblies never saw the reprice. It was
reported from a live self-hosted install, not found by reading.

Two things are asserted here and they fail for different reasons.

The first is the fix: a component priced from a region follows that region's
new rate, and its parent's ``total_rate`` follows the component. Both are stored
snapshots, so both have to be checked - re-reading the component and leaving the
parent stale would still leave the budget wrong.

The second is the guard around it. The refresh reads the rate out of the table,
and a rate that cannot be parsed as a number must leave the row alone. The
obvious way to write this loop uses the module's ``_safe_decimal``, which
answers 0 for anything it cannot read; that is right for a missing factor and
catastrophic for a price, because one unreadable rate would zero every component
built on it and collapse the parent to nothing. A test that only checks the
happy path passes just as well with that bug in place.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.modules.assemblies.events import refresh_region
from app.modules.assemblies.models import Assembly, Component
from app.modules.costs.models import CostItem

_REGION = "CL-test"


async def _make_item(session, *, code: str, rate: str) -> CostItem:
    item = CostItem(
        id=uuid.uuid4(),
        code=code,
        description="Hormigón H-25 elaborado, colocado",
        unit="m3",
        rate=rate,
        currency="CLP",
        region=_REGION,
        is_active=True,
    )
    session.add(item)
    await session.flush()
    return item


async def _make_assembly(session, *, item: CostItem, unit_cost: str, factor: str, quantity: str) -> Assembly:
    assembly = Assembly(
        id=uuid.uuid4(),
        code=f"APU.{item.code}",
        name="Muro de hormigón armado, análisis de precio unitario",
        unit="m2",
        bid_factor="1.0",
        total_rate=str(Decimal(factor) * Decimal(quantity) * Decimal(unit_cost)),
    )
    session.add(assembly)
    await session.flush()
    session.add(
        Component(
            id=uuid.uuid4(),
            assembly_id=assembly.id,
            cost_item_id=item.id,
            description=item.description,
            unit=item.unit,
            factor=factor,
            quantity=quantity,
            unit_cost=unit_cost,
            total=str(Decimal(factor) * Decimal(quantity) * Decimal(unit_cost)),
        )
    )
    await session.flush()
    return assembly


async def test_a_repriced_region_reaches_the_assembly_and_its_total(pg_session) -> None:
    item = await _make_item(pg_session, code="CL.HORM.H25", rate="82000")
    assembly = await _make_assembly(pg_session, item=item, unit_cost="82000", factor="1.0", quantity="0.25")

    # What reprice_region does: rewrite the rate and leave every copy of it alone.
    item.rate = "94500"
    await pg_session.flush()

    refreshed, assemblies, unreadable = await refresh_region(pg_session, _REGION)
    assert (refreshed, assemblies, unreadable) == (1, 1, 0)

    comp = (await pg_session.execute(select(Component).where(Component.assembly_id == assembly.id))).scalar_one()
    assert Decimal(comp.unit_cost) == Decimal("94500"), "the component kept the old rate"
    assert Decimal(comp.total) == Decimal("23625"), "1.0 x 0.25 x 94500"

    refreshed_assembly = (await pg_session.execute(select(Assembly).where(Assembly.id == assembly.id))).scalar_one()
    assert Decimal(refreshed_assembly.total_rate) == Decimal("23625"), (
        "the component moved but the assembly total did not, so a budget built "
        "from this assembly still carries the old price"
    )


async def test_an_unreadable_rate_leaves_the_component_alone_instead_of_zeroing_it(pg_session) -> None:
    good = await _make_item(pg_session, code="CL.ACERO.A630", rate="1150000")
    bad = await _make_item(pg_session, code="CL.MOLDAJE.M1", rate="")

    priced = await _make_assembly(pg_session, item=good, unit_cost="1150000", factor="1.0", quantity="0.08")
    unpriceable = await _make_assembly(pg_session, item=bad, unit_cost="17500", factor="1.0", quantity="2.0")

    refreshed, assemblies, unreadable = await refresh_region(pg_session, _REGION)
    assert unreadable == 1, "an empty rate has to be counted, not parsed as zero"
    assert (refreshed, assemblies) == (1, 1), "only the readable one may be touched"

    kept = (await pg_session.execute(select(Component).where(Component.assembly_id == unpriceable.id))).scalar_one()
    assert Decimal(kept.unit_cost) == Decimal("17500"), "an unreadable rate zeroed a real price"
    assert Decimal(kept.total) == Decimal("35000")

    moved = (await pg_session.execute(select(Component).where(Component.assembly_id == priced.id))).scalar_one()
    assert Decimal(moved.unit_cost) == Decimal("1150000")


async def test_running_it_twice_changes_nothing_the_second_time(pg_session) -> None:
    item = await _make_item(pg_session, code="CL.EXCAV.E1", rate="4300")
    assembly = await _make_assembly(pg_session, item=item, unit_cost="1", factor="1.0", quantity="3.0")

    await refresh_region(pg_session, _REGION)
    first = (await pg_session.execute(select(Assembly).where(Assembly.id == assembly.id))).scalar_one().total_rate

    await refresh_region(pg_session, _REGION)
    second = (await pg_session.execute(select(Assembly).where(Assembly.id == assembly.id))).scalar_one().total_rate

    assert Decimal(first) == Decimal("12900")
    assert Decimal(second) == Decimal(first), "a replayed event must land on the same numbers"
