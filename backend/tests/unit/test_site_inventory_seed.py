# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free unit tests for the site-inventory demo seed.

The module with the strongest estimate integration in the platform shipped
without a seeder, so every demo project opened it empty and post-calculation had
no material actuals to read. These tests cover the parts of that seeder that can
be checked without a database, and the two failure modes this project has been
bitten by before.

The first is a seeder written and never wired: the daily diary shipped complete
and unregistered, and the register stayed empty on every install. So the wiring
is asserted here rather than trusted.

The second is a vocabulary the database will accept and the module will not.
``movement_type`` is a ``Literal`` on the create schema rather than a
``Field(pattern=...)``, so the seed-vocabulary gate cannot see it, and the
column behind it is a plain ``String`` that would store "consumption" happily
while the ledger's sign table has never heard of it. Every token this seeder
writes is therefore pushed through the same schema the API uses.
"""

from __future__ import annotations

import random
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.site_inventory.ledger import _ONHAND_SIGN, MovementType
from app.modules.site_inventory.schemas import MovementCreate, StockItemCreate
from app.modules.site_inventory.seed import (
    _ASSUMED_INSTALLED_MAX,
    _ASSUMED_INSTALLED_MIN,
    _DRAW_FACTOR_MAX,
    _DRAW_FACTOR_MIN,
    _LOCATION_COUNTS,
    _LOCATIONS,
    _METERED_POSITIONS,
    _METERED_SPAN,
    _PURCHASE_FACTOR_MAX,
    _PURCHASE_FACTOR_MIN,
    _between,
    _material_lines,
    _per_unit_cost,
    _rng_for,
    seed_site_inventory_demo,
)

_PROJECT = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")


# ── What gets metered ───────────────────────────────────────────────────────


def test_only_material_resources_are_metered() -> None:
    """A store meters material. Labour hours and plant time are not stock."""
    resources = [
        {"name": "Concrete C30/37", "type": "material", "quantity": 1.0, "unit_rate": 110.0},
        {"name": "Concreter", "type": "labor", "quantity": 2.0, "unit_rate": 45.0},
        {"name": "Pump", "type": "equipment", "quantity": 0.2, "unit_rate": 90.0},
        {"name": "Rebar", "type": "materials", "quantity": 1.0, "unit_rate": 60.0},
    ]
    names = [line["name"] for line in _material_lines(resources)]
    assert names == ["Concrete C30/37", "Rebar"]


def test_a_missing_or_broken_split_meters_nothing() -> None:
    """A position with no readable split is skipped, never invented."""
    assert _material_lines(None) == []
    assert _material_lines("resources") == []
    assert _material_lines([None, 7, "material"]) == []


def test_the_unit_cost_survives_a_stale_total() -> None:
    """Prefer quantity * rate, the same self-healing rule the BoQ breakdown uses."""
    resource = {"type": "material", "quantity": "2", "unit_rate": "55", "total": "1"}
    assert _per_unit_cost(resource) == Decimal("110")


def test_the_unit_cost_falls_back_to_the_stored_total() -> None:
    """Without a factor pair the stored money is all there is."""
    assert _per_unit_cost({"type": "material", "total": "88.5"}) == Decimal("88.5")


def test_a_material_line_priced_at_nothing_yields_no_unit_cost() -> None:
    """A zero unit cost is what makes an actual cost unknowable rather than free."""
    assert _per_unit_cost({"type": "material"}) == Decimal("0")


# ── The drawn factors ───────────────────────────────────────────────────────


def test_drawn_factors_stay_inside_their_bounds() -> None:
    rng = random.Random(1)
    for _ in range(200):
        purchase = _between(rng, _PURCHASE_FACTOR_MIN, _PURCHASE_FACTOR_MAX)
        draw = _between(rng, _DRAW_FACTOR_MIN, _DRAW_FACTOR_MAX)
        installed = _between(rng, _ASSUMED_INSTALLED_MIN, _ASSUMED_INSTALLED_MAX)
        assert _PURCHASE_FACTOR_MIN <= purchase <= _PURCHASE_FACTOR_MAX
        assert _DRAW_FACTOR_MIN <= draw <= _DRAW_FACTOR_MAX
        assert _ASSUMED_INSTALLED_MIN <= installed <= _ASSUMED_INSTALLED_MAX


def test_a_drawn_factor_is_an_exact_decimal() -> None:
    """Money and quantities are built from these; a binary float would leak in."""
    value = _between(random.Random(3), Decimal("0.9"), Decimal("1.1"))
    assert isinstance(value, Decimal)
    assert value == value.quantize(Decimal("0.001"))


def test_the_factors_land_on_both_sides_of_the_estimate() -> None:
    """A pool that only ever overspends teaches half the report.

    The product of the two factors is what post-calculation reports as the
    material variance, so it has to be able to come out under 1 as well as over.
    """
    rng = random.Random(11)
    products = [
        _between(rng, _PURCHASE_FACTOR_MIN, _PURCHASE_FACTOR_MAX) * _between(rng, _DRAW_FACTOR_MIN, _DRAW_FACTOR_MAX)
        for _ in range(300)
    ]
    assert any(value < Decimal("1") for value in products)
    assert any(value > Decimal("1") for value in products)


def test_a_project_reproduces_its_own_ledger() -> None:
    """Deterministic per project, so a re-seed writes the same yard."""
    first = [_rng_for(_PROJECT).random() for _ in range(5)]
    second = [_rng_for(_PROJECT).random() for _ in range(5)]
    assert first == second
    assert first != [_rng_for(uuid.uuid4()).random() for _ in range(5)]


# ── Variety across projects ─────────────────────────────────────────────────


def test_two_neighbouring_projects_do_not_meter_the_same_amount() -> None:
    """A rotation over a pool hands out no more pictures than the pool is long.

    Past the end of the tuple a whole span is added rather than one, so every
    block of four occupies a range of counts disjoint from every other block and
    project 5 does not repeat project 1.
    """
    counts = [
        _METERED_POSITIONS[i % len(_METERED_POSITIONS)] + (i // len(_METERED_POSITIONS)) * _METERED_SPAN
        for i in range(16)
    ]
    assert len(set(counts)) == len(counts)


def test_the_yard_is_sampled_rather_than_rotated() -> None:
    """Four locations drawn from six give fifteen sets, not four."""
    assert max(_LOCATION_COUNTS) < len(_LOCATIONS)
    seen = {
        tuple(sorted(name for name, _code, _address in _rng_for(uuid.uuid4()).sample(_LOCATIONS, k=4)))
        for _ in range(40)
    }
    assert len(seen) > len(_LOCATION_COUNTS)


def test_every_location_states_a_code_and_a_place() -> None:
    """A location without a code is a row a storeman cannot refer to."""
    for name, code, address in _LOCATIONS:
        assert name and code and address
        assert len(code) <= 64


# ── The vocabulary the module actually enforces ─────────────────────────────


@pytest.mark.parametrize("movement_type", [m.value for m in MovementType])
def test_every_movement_type_the_seed_writes_is_one_the_module_accepts(movement_type: str) -> None:
    """The create schema is the gate here; the column would store anything."""
    extra = (
        {"location_id": uuid.uuid4(), "to_location_id": uuid.uuid4()}
        if movement_type == MovementType.TRANSFER.value
        else {}
    )
    payload = MovementCreate(item_id=uuid.uuid4(), movement_type=movement_type, quantity="1", **extra)
    assert payload.movement_type == movement_type
    assert movement_type in _ONHAND_SIGN


def test_a_lower_cased_movement_type_is_refused() -> None:
    """Proof the check above checks something: the database would accept this."""
    with pytest.raises(ValueError, match="movement_type"):
        MovementCreate(item_id=uuid.uuid4(), movement_type="consumption", quantity="1")


def test_a_seeded_item_passes_the_same_schema_the_api_uses() -> None:
    """Every stock item is written through the service, so it validates first."""
    payload = StockItemCreate(
        name="Concrete C30/37",
        sku="CW-101-M1",
        unit="m3",
        boq_position_id=uuid.uuid4(),
        standard_unit_cost="110.00",
        currency="EUR",
        reorder_point="5.0000",
    )
    assert payload.standard_unit_cost == "110.00"


# ── Wiring ──────────────────────────────────────────────────────────────────


async def test_no_projects_writes_nothing() -> None:
    """Called with an empty estate it returns before it ever needs a session."""
    assert await seed_site_inventory_demo(None, []) == {
        "projects": 0,
        "locations": 0,
        "items": 0,
        "movements": 0,
    }


def test_the_seeder_is_wired_into_the_demo_enrichment() -> None:
    """A seeder written and never registered leaves the module empty forever.

    The daily diary shipped exactly that way. Read from the source rather than
    by running the enrichment, which needs a database and every other module.
    """
    source = (Path(__file__).resolve().parents[2] / "app" / "core" / "demo_enrichment.py").read_text(encoding="utf-8")
    assert "from app.modules.site_inventory.seed import seed_site_inventory_demo" in source
    assert '("site_inventory", None, lambda s: seed_site_inventory_demo(s, _demo_pids))' in source


def test_the_seed_runs_on_the_demo_estate_only() -> None:
    """A consumption booked against a bill states what a job really used.

    Writing that into a customer's live project is a data-integrity problem, so
    the seeder is handed the demo projects rather than every project.
    """
    source = (Path(__file__).resolve().parents[2] / "app" / "core" / "demo_enrichment.py").read_text(encoding="utf-8")
    assert "seed_site_inventory_demo(s, _all_pids)" not in source
