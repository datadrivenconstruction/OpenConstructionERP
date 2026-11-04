"""Resource quantities entered per unit of the position or for the whole position.

Stored resource rows are per-unit norms: ``sum(quantity * unit_rate)`` is the
position's unit rate, and the total is ``quantity * unit_rate``. Catalogue
build-ups are written that way, but an estimator pricing an item by hand often
enters what the whole item consumes. Read as norms, those totals multiplied the
position by its own quantity a second time (resources worth 10,000 on a
position of 50 gave a unit rate of 10,000 and a total of 500,000, issue #555).

A position can now declare ``metadata.resource_quantity_basis = "per_position"``.
Its rows keep the entered ``quantity_for_position``, the stored norm is derived
from it, the unit rate is the resources total divided by the quantity, and a
quantity edit keeps the entered totals. The default stays per-unit, so every
catalogue build-up prices exactly as before; the control tests pin that.

Isolation mirrors ``test_boq_resourceless_unit_rate``: each service test runs
inside a rolled-back outer transaction via ``tests._pg``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.boq.resource_basis import (
    BASIS_KEY,
    PER_POSITION,
    PER_UNIT,
    ROW_POSITION_QUANTITY_KEY,
    apply_resource_basis,
    resource_basis,
    rows_at_position_quantities,
)
from app.modules.boq.schemas import PositionUpdate
from app.modules.boq.service import BOQService, _derived_unit_rate_str
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


def _row(name: str, *, rate: str, quantity: object = None, for_position: object = None) -> dict:
    row: dict = {"name": name, "type": "material", "unit": "pcs", "unit_rate": rate}
    if quantity is not None:
        row["quantity"] = quantity
    if for_position is not None:
        row[ROW_POSITION_QUANTITY_KEY] = for_position
    return row


# ── Pure helpers ─────────────────────────────────────────────────────────


def test_basis_defaults_to_per_unit() -> None:
    assert resource_basis(None) == PER_UNIT
    assert resource_basis({}) == PER_UNIT
    assert resource_basis({BASIS_KEY: "anything"}) == PER_UNIT
    assert resource_basis({BASIS_KEY: PER_POSITION}) == PER_POSITION


def test_per_position_rows_store_the_norm_derived_from_the_entered_total() -> None:
    meta = {BASIS_KEY: PER_POSITION, "resources": [_row("pole", rate="400", for_position=25)]}

    assert apply_resource_basis(meta, "50") is True

    row = meta["resources"][0]
    assert row[ROW_POSITION_QUANTITY_KEY] == 25
    assert Decimal(str(row["quantity"])) == Decimal("0.5")
    assert Decimal(str(row["total"])) == Decimal("200")


def test_rows_without_an_entered_total_take_it_from_their_norm() -> None:
    # A row added from the catalogue carries a norm only.
    meta = {BASIS_KEY: PER_POSITION, "resources": [_row("rebar", rate="900", quantity="0.12")]}

    apply_resource_basis(meta, "40")

    assert Decimal(str(meta["resources"][0][ROW_POSITION_QUANTITY_KEY])) == Decimal("4.8")
    assert Decimal(str(meta["resources"][0]["quantity"])) == Decimal("0.12")


def test_per_unit_basis_drops_the_entered_totals_and_keeps_the_norms() -> None:
    meta = {"resources": [_row("pole", rate="400", quantity=0.5, for_position=25)]}

    assert apply_resource_basis(meta, "50") is True
    assert ROW_POSITION_QUANTITY_KEY not in meta["resources"][0]
    assert meta["resources"][0]["quantity"] == 0.5


def test_a_zero_position_quantity_leaves_the_rows_alone() -> None:
    meta = {BASIS_KEY: PER_POSITION, "resources": [_row("pole", rate="400", quantity=1, for_position=25)]}

    assert apply_resource_basis(meta, "0") is False
    assert meta["resources"][0]["quantity"] == 1


def test_rows_at_position_quantities_reads_the_entered_totals() -> None:
    rows = rows_at_position_quantities([_row("pole", rate="400", quantity=0.5, for_position=25)])
    assert rows[0]["quantity"] == "25"


def test_reporter_example_gives_a_unit_rate_of_200() -> None:
    # Resources worth 10,000 for a position of 50: unit rate 200, not 10,000.
    meta = {BASIS_KEY: PER_POSITION, "resources": [_row("pole", rate="400", for_position=25)]}
    apply_resource_basis(meta, "50")

    assert Decimal(_derived_unit_rate_str(meta["resources"], meta, "50", {}, "")) == Decimal("200")


def test_per_unit_norms_still_sum_without_division() -> None:
    # The catalogue convention: 0.5 per unit at 400 is a unit rate of 200.
    meta = {"resources": [_row("pole", rate="400", quantity="0.5")]}

    assert Decimal(_derived_unit_rate_str(meta["resources"], meta, "50", {}, "")) == Decimal("200")


def test_a_total_that_does_not_divide_evenly_rounds_only_the_rate() -> None:
    meta = {BASIS_KEY: PER_POSITION, "resources": [_row("crane day", rate="1000", for_position=10)]}
    apply_resource_basis(meta, "3")

    assert _derived_unit_rate_str(meta["resources"], meta, "3", {}, "") == "3333.3333"


# ── Through update_position ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(User(id=OWNER_ID, email=f"o-{uuid.uuid4().hex[:6]}@test.io", hashed_password="x", full_name="O"))
        await s.flush()
        await s.commit()
        yield s


async def _make_position(session, *, quantity: str, unit_rate: str = "0", metadata_: dict | None = None):
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    session.add(Project(id=project_id, name="P", owner_id=OWNER_ID, currency="KWD"))
    await session.flush()
    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="B")
    session.add(boq)
    await session.flush()
    pos = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="01.20.10",
        description="pole-11",
        unit="set",
        quantity=quantity,
        unit_rate=unit_rate,
        total=str(Decimal(quantity) * Decimal(unit_rate)),
        metadata_=metadata_,
        sort_order=10,
    )
    session.add(pos)
    await session.commit()
    return BOQService(session), pos


def _money(value: object) -> Decimal:
    return Decimal(str(value))


@pytest.mark.asyncio
async def test_per_unit_rows_still_multiply_by_the_position_quantity(session) -> None:
    """Control: the default basis is the norm convention, unchanged."""
    service, pos = await _make_position(session, quantity="50")

    updated = await service.update_position(
        pos.id,
        PositionUpdate(metadata={"resources": [_row("pole", rate="200", quantity=50)]}),
        actor_id=OWNER_ID,
    )

    assert _money(updated.unit_rate) == Decimal("10000")
    assert _money(updated.total) == Decimal("500000")


@pytest.mark.asyncio
async def test_rows_entered_for_the_whole_position_divide_by_its_quantity(session) -> None:
    service, pos = await _make_position(session, quantity="50")

    updated = await service.update_position(
        pos.id,
        PositionUpdate(
            metadata={BASIS_KEY: PER_POSITION, "resources": [_row("pole", rate="200", for_position=50)]},
        ),
        actor_id=OWNER_ID,
    )

    assert _money(updated.unit_rate) == Decimal("200")
    assert _money(updated.total) == Decimal("10000")
    row = updated.metadata_["resources"][0]
    assert _money(row["quantity"]) == Decimal("1")
    assert row[ROW_POSITION_QUANTITY_KEY] == 50


@pytest.mark.asyncio
async def test_a_quantity_edit_keeps_whole_position_resources_and_rederives_the_rate(session) -> None:
    """The screenshot's flow: resources 26,250 entered on a quantity of 1, then 50."""
    service, pos = await _make_position(session, quantity="1")
    await service.update_position(
        pos.id,
        PositionUpdate(
            metadata={
                BASIS_KEY: PER_POSITION,
                "resources": [
                    _row("11 meter pole", rate="500", for_position=50),
                    _row("earth", rate="50", for_position=25),
                ],
            },
        ),
        actor_id=OWNER_ID,
    )

    updated = await service.update_position(pos.id, PositionUpdate(quantity=50), actor_id=OWNER_ID)

    assert _money(updated.unit_rate) == Decimal("525")
    assert _money(updated.total) == Decimal("26250")
    rows = updated.metadata_["resources"]
    assert [r[ROW_POSITION_QUANTITY_KEY] for r in rows] == [50, 25]
    assert [_money(r["quantity"]) for r in rows] == [Decimal("1"), Decimal("0.5")]


@pytest.mark.asyncio
async def test_switching_a_catalogue_buildup_to_whole_position_keeps_its_price(session) -> None:
    norms = {"resources": [_row("concrete", rate="120", quantity="1.02"), _row("labour", rate="45", quantity="0.8")]}
    service, pos = await _make_position(session, quantity="40", unit_rate="158.4000", metadata_=norms)

    switched = await service.update_position(
        pos.id,
        PositionUpdate(metadata={**norms, BASIS_KEY: PER_POSITION}),
        actor_id=OWNER_ID,
    )

    assert _money(switched.unit_rate) == Decimal("158.4")
    assert _money(switched.total) == Decimal("6336")
    assert [_money(r[ROW_POSITION_QUANTITY_KEY]) for r in switched.metadata_["resources"]] == [
        Decimal("40.8"),
        Decimal("32"),
    ]

    # Now the resources are fixed totals: doubling the quantity halves the rate.
    doubled = await service.update_position(pos.id, PositionUpdate(quantity=80), actor_id=OWNER_ID)
    assert _money(doubled.unit_rate) == Decimal("79.2")
    assert _money(doubled.total) == Decimal("6336")


@pytest.mark.asyncio
async def test_a_quantity_edit_on_a_catalogue_buildup_still_scales_the_total(session) -> None:
    """Control: per-unit norms keep the rate and scale the total."""
    norms = {"resources": [_row("concrete", rate="120", quantity="1.02")]}
    service, pos = await _make_position(session, quantity="40", unit_rate="122.4000", metadata_=norms)

    updated = await service.update_position(pos.id, PositionUpdate(quantity=80), actor_id=OWNER_ID)

    assert _money(updated.unit_rate) == Decimal("122.4")
    assert _money(updated.total) == Decimal("9792")
    assert updated.metadata_["resources"][0]["quantity"] == "1.02"
