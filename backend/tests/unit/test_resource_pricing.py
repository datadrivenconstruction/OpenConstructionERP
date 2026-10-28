"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Resource price sheet: seed, edit and re-price coefficient bases.

CWICR coefficient bases (Vietnam Dinh Muc, Indonesia AHSP) import their work
items with the full labour / material / machine breakdown as norm quantities but
NO prices, so every work item lands with a zero rate. The resource price sheet
(:mod:`app.modules.costs.resource_pricing`) is what makes them estimable: it
holds one editable unit price per resource per region, seeds from whatever a base
already carries, and re-prices every work item as
``sum(component.quantity x sheet_price)``.

These tests pin:

* ``resource_key_for`` - coded vs codeless identity.
* ``seed_region`` - one row per distinct resource; coefficient rows land unpriced
  (0), priced rows keep the observed price; idempotent and user-edit preserving.
* ``set_price`` - marks the row user-edited.
* ``reprice_region`` - rate = sum(qty x price); components and the metadata
  breakdown are refreshed; ``dry_run`` writes nothing.

Isolation uses the shared PostgreSQL transactional session
(``tests._pg.transactional_session``): each test runs inside an outer
transaction rolled back on teardown.

Run:
    cd backend
    python -m pytest tests/unit/test_resource_pricing.py -v --tb=short
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import select

from app.modules.costs.models import CostItem, ResourcePrice
from app.modules.costs.resource_pricing import (
    ResourcePriceService,
    component_quantity,
    resource_key_for,
)
from app.modules.costs.schemas import CostItemCreate, CostItemUpdate
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


def _comp(name, code, qty, unit_rate, ctype, unit):
    return {
        "name": name,
        "code": code,
        "unit": unit,
        "quantity": qty,
        "unit_rate": unit_rate,
        "cost": round(qty * unit_rate, 2),
        "type": ctype,
    }


async def _add_item(session, *, region, code, rate, components, currency="VND"):
    item = CostItem(
        code=code,
        description=f"Work item {code}",
        unit="m3",
        rate=str(rate),
        currency=currency,
        source="cwicr",
        region=region,
        components=components,
        is_active=True,
    )
    session.add(item)
    await session.flush()
    return item


# ── pure key helper ──────────────────────────────────────────────────────────


def test_resource_key_coded_uses_code():
    assert resource_key_for("R-001", "Concrete") == "R-001"


def test_resource_key_codeless_normalizes_name():
    # Whitespace collapsed, lowercased, name: prefixed.
    assert resource_key_for("", "  Ready-Mix   Concrete C25/30 ") == "name:ready-mix concrete c25/30"
    assert resource_key_for(None, "Mason") == "name:mason"


def test_resource_key_codeless_same_name_same_key():
    assert resource_key_for("", "Mason") == resource_key_for(None, " mason ")


# ── seeding ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_coefficient_base_creates_unpriced_sheet(session):
    region = "VN_SEEDTEST"
    # Two work items sharing the same Cement material and Mason labour, all at
    # unit_rate 0 (a coefficient base carries quantities, not prices).
    await _add_item(
        session,
        region=region,
        code="VN-1",
        rate=0,
        components=[
            _comp("Mason", "", 2.5, 0.0, "labor", "hour"),
            _comp("Cement", "M1", 10.0, 0.0, "material", "kg"),
        ],
    )
    await _add_item(
        session,
        region=region,
        code="VN-2",
        rate=0,
        components=[
            _comp("Cement", "M1", 5.0, 0.0, "material", "kg"),
            _comp("Mason", "", 1.0, 0.0, "labor", "hour"),
        ],
    )

    result = await ResourcePriceService(session).seed_region(region)

    assert result.resources == 2  # deduped: one Cement, one Mason
    assert result.created == 2
    assert result.priced == 0
    assert result.unpriced == 2
    assert result.as_dict()["coverage"] == 0.0

    rows = (await session.execute(select(ResourcePrice).where(ResourcePrice.region == region))).scalars().all()
    by_key = {r.resource_key: r for r in rows}
    assert set(by_key) == {"M1", "name:mason"}
    assert by_key["M1"].resource_type == "material"
    assert by_key["M1"].unit == "kg"
    assert by_key["name:mason"].resource_type == "labor"
    assert all(r.unit_price in ("0", "0.00") for r in rows)
    assert all(r.source == "cwicr_import" for r in rows)


@pytest.mark.asyncio
async def test_seed_priced_base_keeps_observed_price(session):
    region = "ES_SEEDTEST"
    await _add_item(
        session,
        region=region,
        code="ES-1",
        rate=100,
        currency="EUR",
        components=[_comp("Concrete C30/37", "C1", 1.0, 100.0, "material", "m3")],
    )
    result = await ResourcePriceService(session).seed_region(region)
    assert result.resources == 1
    assert result.priced == 1
    assert result.unpriced == 0

    row = (await session.execute(select(ResourcePrice).where(ResourcePrice.region == region))).scalar_one()
    assert Decimal(row.unit_price) == Decimal("100.00")
    assert row.currency == "EUR"


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_preserves_user_edits(session):
    region = "VN_IDEMPOTENT"
    await _add_item(
        session,
        region=region,
        code="VN-1",
        rate=0,
        components=[_comp("Cement", "M1", 10.0, 0.0, "material", "kg")],
    )
    svc = ResourcePriceService(session)
    await svc.seed_region(region)

    # User prices the Cement.
    await svc.set_price(region, "M1", "3.50")

    # Re-seed (as a re-import would): the user price must survive.
    result = await svc.seed_region(region)
    assert result.preserved_user_edits == 1

    row = (await session.execute(select(ResourcePrice).where(ResourcePrice.region == region))).scalar_one()
    assert Decimal(row.unit_price) == Decimal("3.50")
    assert row.source == "user"


# ── editing ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_price_marks_user_and_rounds(session):
    region = "VN_SET"
    await _add_item(
        session,
        region=region,
        code="VN-1",
        rate=0,
        components=[_comp("Cement", "M1", 10.0, 0.0, "material", "kg")],
    )
    svc = ResourcePriceService(session)
    await svc.seed_region(region)
    row = await svc.set_price(region, "M1", "3.456", currency="VND")
    assert row.source == "user"
    assert Decimal(row.unit_price) == Decimal("3.46")  # rounded to 2dp
    assert row.currency == "VND"


@pytest.mark.asyncio
async def test_set_price_rejects_negative(session):
    region = "VN_NEG"
    await _add_item(
        session,
        region=region,
        code="VN-1",
        rate=0,
        components=[_comp("Cement", "M1", 10.0, 0.0, "material", "kg")],
    )
    svc = ResourcePriceService(session)
    await svc.seed_region(region)
    with pytest.raises(ValueError):
        await svc.set_price(region, "M1", "-5")


# ── re-pricing ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reprice_computes_rate_from_sheet(session):
    region = "VN_REPRICE"
    await _add_item(
        session,
        region=region,
        code="VN-1",
        rate=0,
        components=[
            _comp("Mason", "", 2.5, 0.0, "labor", "hour"),
            _comp("Cement", "M1", 10.0, 0.0, "material", "kg"),
        ],
    )
    await _add_item(
        session,
        region=region,
        code="VN-2",
        rate=0,
        components=[
            _comp("Cement", "M1", 5.0, 0.0, "material", "kg"),
            _comp("Mason", "", 1.0, 0.0, "labor", "hour"),
        ],
    )
    svc = ResourcePriceService(session)
    await svc.seed_region(region)
    await svc.set_price(region, "M1", "3.00")
    await svc.set_price(region, "name:mason", "20.00")

    result = await svc.reprice_region(region)
    assert result.items_total == 2
    assert result.items_repriced == 2
    assert result.items_changed == 2
    assert result.items_fully_priced == 2
    assert result.as_dict()["coverage"] == 1.0

    items = {
        i.code: i for i in ((await session.execute(select(CostItem).where(CostItem.region == region))).scalars().all())
    }
    # VN-1 = 2.5*20 + 10*3 = 80.00 ; VN-2 = 5*3 + 1*20 = 35.00
    assert Decimal(items["VN-1"].rate) == Decimal("80.00")
    assert Decimal(items["VN-2"].rate) == Decimal("35.00")

    # Component unit_rate/cost rewritten from the sheet.
    vn1_comps = {c["name"]: c for c in items["VN-1"].components}
    assert vn1_comps["Mason"]["unit_rate"] == 20.0
    assert vn1_comps["Mason"]["cost"] == 50.0
    assert vn1_comps["Cement"]["cost"] == 30.0
    # Metadata breakdown refreshed.
    assert items["VN-1"].metadata_["labor_cost"] == 50.0
    assert items["VN-1"].metadata_["material_cost"] == 30.0


@pytest.mark.asyncio
async def test_reprice_dry_run_writes_nothing(session):
    region = "VN_DRY"
    await _add_item(
        session,
        region=region,
        code="VN-1",
        rate=0,
        components=[_comp("Cement", "M1", 10.0, 0.0, "material", "kg")],
    )
    svc = ResourcePriceService(session)
    await svc.seed_region(region)
    await svc.set_price(region, "M1", "3.00")

    result = await svc.reprice_region(region, dry_run=True)
    assert result.dry_run is True
    assert result.items_repriced == 1
    assert result.items_changed == 1

    item = (await session.execute(select(CostItem).where(CostItem.region == region))).scalar_one()
    assert Decimal(item.rate) == Decimal("0")  # unchanged - dry run


@pytest.mark.asyncio
async def test_reprice_partial_coverage(session):
    region = "VN_PARTIAL"
    await _add_item(
        session,
        region=region,
        code="VN-1",
        rate=0,
        components=[
            _comp("Cement", "M1", 10.0, 0.0, "material", "kg"),
            _comp("Sand", "M2", 3.0, 0.0, "material", "kg"),  # left unpriced
        ],
    )
    svc = ResourcePriceService(session)
    await svc.seed_region(region)
    await svc.set_price(region, "M1", "3.00")  # only cement priced

    result = await svc.reprice_region(region)
    assert result.items_partially_priced == 1
    assert result.items_fully_priced == 0
    assert "M2" in result.missing_resources
    # Rate reflects only the priced line: 10 * 3 = 30.00
    item = (await session.execute(select(CostItem).where(CostItem.region == region))).scalar_one()
    assert Decimal(item.rate) == Decimal("30.00")


@pytest.mark.asyncio
async def test_region_stats(session):
    region = "VN_STATS"
    await _add_item(
        session,
        region=region,
        code="VN-1",
        rate=0,
        components=[
            _comp("Cement", "M1", 10.0, 0.0, "material", "kg"),
            _comp("Mason", "", 2.0, 0.0, "labor", "hour"),
        ],
    )
    svc = ResourcePriceService(session)
    await svc.seed_region(region)
    await svc.set_price(region, "M1", "3.00")

    stats = await svc.region_stats(region)
    assert stats["resources"] == 2
    assert stats["priced"] == 1
    assert stats["unpriced"] == 1
    assert stats["coverage"] == 0.5


# ── shipped recipe template ──────────────────────────────────────────────────
#
# The defect these pin: the template shipped its component quantities under
# ``factor``, nothing read that key, and the reader turned the absence into a
# quantity of zero. Every line then priced at nothing while still counting as
# priced, so the base repriced to 0.00 and reported itself fully priced with no
# missing resources. Three artefacts had to agree on the wrong shape for that to
# ship - the template, the reader, and a smoke test that only checked the blob
# survived storage - so these pin the mechanism, not just the template.

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE_JSON = _REPO_ROOT / "data" / "templates" / "cost_database_with_assemblies.json"
_TEMPLATE_CSV = _REPO_ROOT / "data" / "templates" / "example_us_construction.csv"


def _shipped_recipes() -> list[dict]:
    return json.loads(_TEMPLATE_JSON.read_text(encoding="utf-8"))


def _shipped_leaf_prices() -> dict[str, str]:
    """Resource code -> unit price, from the flat CSV the recipes reference."""
    with _TEMPLATE_CSV.open(encoding="utf-8") as fh:
        return {row["code"]: row["rate"] for row in csv.DictReader(fh)}


def _breakdown_total(metadata: dict) -> Decimal:
    """Sum of the published breakdown buckets, which must equal the rate."""
    keys = ("labor_cost", "material_cost", "equipment_cost", "other_cost")
    return sum((Decimal(str(metadata.get(key, 0))) for key in keys), Decimal("0"))


def test_component_quantity_tells_absent_from_zero():
    # A real zero is a quantity. An absent, blank or unusable one is not, and
    # must not be reported as zero - that is the whole defect in one function.
    assert component_quantity({"quantity": 2.5}) == Decimal("2.5")
    assert component_quantity({"quantity": 0}) == Decimal("0")
    assert component_quantity({"quantity": "0.00"}) == Decimal("0.00")
    assert component_quantity({}) is None
    assert component_quantity({"quantity": None}) is None
    assert component_quantity({"quantity": ""}) is None
    assert component_quantity({"quantity": "not a number"}) is None
    assert component_quantity({"quantity": float("nan")}) is None
    assert component_quantity({"quantity": -1}) is None
    # Legacy alias, and only when the canonical key carries nothing.
    assert component_quantity({"factor": 0.18}) == Decimal("0.18")
    assert component_quantity({"quantity": 3, "factor": 9}) == Decimal("3")


@pytest.mark.asyncio
async def test_shipped_recipe_template_prices_to_real_rates(session):
    """The shipped template, priced from its own companion CSV, is not zero."""
    region = "US_TEMPLATE"
    recipes = _shipped_recipes()
    for rec in recipes:
        await _add_item(
            session,
            region=region,
            code=rec["code"],
            rate=rec["rate"],
            components=rec["components"],
            currency="USD",
        )

    svc = ResourcePriceService(session)
    # Price the sheet directly. Seeding from the base cannot arm this test: the
    # recipes carry no unit_rate, so seed_region produces a sheet of zeros, every
    # resource reads as unpriced and the reprice leaves every item alone. That is
    # the run that hides the defect rather than the one that shows it.
    await svc.set_prices_bulk(
        region,
        [{"resource_key": code, "unit_price": price} for code, price in _shipped_leaf_prices().items()],
    )

    result = await svc.reprice_region(region)
    assert result.items_total == len(recipes)
    assert result.items_fully_priced == len(recipes)
    assert result.items_unreadable == 0
    assert result.items_zero_total == 0
    assert result.missing_resources == set()

    items = {
        i.code: i for i in ((await session.execute(select(CostItem).where(CostItem.region == region))).scalars().all())
    }
    for code, item in items.items():
        assert Decimal(item.rate) > 0, f"{code} repriced to {item.rate}"
        assert _breakdown_total(item.metadata_) == Decimal(item.rate), (
            f"{code}: breakdown {item.metadata_} does not add up to rate {item.rate}"
        )

    # The roofing recipe carries the subcontractor line, so it is where a
    # breakdown that only knows labour / material / equipment goes short.
    # 1.00 sq x 425.00 subcontractor + 0.18 hr x 95.00 foreman = 442.10.
    roof = items["WI-ROOF-ASPH-PITCH"]
    assert Decimal(roof.rate) == Decimal("442.10")
    assert roof.metadata_["labor_cost"] == 17.10
    assert roof.metadata_["other_cost"] == 425.00
    assert roof.metadata_["cost_by_type"]["subcontractor"] == 425.00


@pytest.mark.asyncio
async def test_reprice_reads_the_legacy_factor_alias(session):
    """A recipe written against the old documentation still prices."""
    region = "US_ALIAS"
    await _add_item(
        session,
        region=region,
        code="OLD-1",
        rate=0,
        components=[
            {"code": "M1", "factor": 4.0, "unit": "kg", "type": "material"},
            {"code": "L1", "factor": 0.5, "unit": "hr", "type": "labor"},
        ],
        currency="USD",
    )
    svc = ResourcePriceService(session)
    await svc.set_prices_bulk(
        region,
        [
            {"resource_key": "M1", "unit_price": "3.00"},
            {"resource_key": "L1", "unit_price": "40.00"},
        ],
    )

    result = await svc.reprice_region(region)
    assert result.items_fully_priced == 1
    assert result.items_unreadable == 0

    item = (await session.execute(select(CostItem).where(CostItem.region == region))).scalar_one()
    # 4 * 3.00 + 0.5 * 40.00 = 32.00
    assert Decimal(item.rate) == Decimal("32.00")
    assert _breakdown_total(item.metadata_) == Decimal("32.00")


@pytest.mark.asyncio
async def test_reprice_refuses_a_component_with_no_quantity(session):
    """No quantity is not a quantity of nothing, and never a priced line."""
    region = "US_NOQTY"
    await _add_item(
        session,
        region=region,
        code="BROKEN-1",
        rate="38.50",
        components=[
            {"code": "M1", "unit": "kg", "type": "material"},  # neither key
            {"code": "L1", "quantity": 0.5, "unit": "hr", "type": "labor"},
        ],
        currency="USD",
    )
    svc = ResourcePriceService(session)
    await svc.set_prices_bulk(
        region,
        [
            {"resource_key": "M1", "unit_price": "3.00"},
            {"resource_key": "L1", "unit_price": "40.00"},
        ],
    )

    result = await svc.reprice_region(region)
    assert result.items_unreadable == 1
    assert result.items_fully_priced == 0
    assert result.items_partially_priced == 0
    assert result.items_repriced == 0
    assert result.as_dict()["coverage"] == 0.0
    assert "M1" in result.unreadable_resources
    assert result.as_dict()["unreadable_resources_sample"] == ["M1"]

    item = (await session.execute(select(CostItem).where(CostItem.region == region))).scalar_one()
    assert Decimal(item.rate) == Decimal("38.50"), "a rate we could not recompute must be left alone"


@pytest.mark.asyncio
async def test_reprice_refuses_to_zero_a_rate_that_computes_to_nothing(session):
    """A fully priced recipe worth 0.00 is reported, not published."""
    region = "US_ZERO"
    await _add_item(
        session,
        region=region,
        code="ZERO-1",
        rate="485.00",
        components=[{"code": "M1", "quantity": 0, "unit": "kg", "type": "material"}],
        currency="USD",
    )
    svc = ResourcePriceService(session)
    await svc.set_prices_bulk(region, [{"resource_key": "M1", "unit_price": "3.00"}])

    result = await svc.reprice_region(region)
    assert result.items_zero_total == 1
    assert result.items_fully_priced == 0
    assert result.items_repriced == 0

    item = (await session.execute(select(CostItem).where(CostItem.region == region))).scalar_one()
    assert Decimal(item.rate) == Decimal("485.00")


@pytest.mark.asyncio
async def test_reprice_breakdown_accounts_for_every_component_type(session):
    """Whatever a base calls a component type, its money is in the breakdown."""
    region = "US_TYPES"
    await _add_item(
        session,
        region=region,
        code="MIX-1",
        rate=0,
        components=[
            {"code": "L1", "quantity": 1, "unit": "hr", "type": "labor"},
            {"code": "M1", "quantity": 1, "unit": "kg", "type": "material"},
            {"code": "E1", "quantity": 1, "unit": "hr", "type": "equipment"},
            {"code": "S1", "quantity": 1, "unit": "sq", "type": "subcontractor"},
            {"code": "X1", "quantity": 1, "unit": "ea", "type": "transport"},
        ],
        currency="USD",
    )
    svc = ResourcePriceService(session)
    await svc.set_prices_bulk(
        region,
        [{"resource_key": code, "unit_price": "10.00"} for code in ("L1", "M1", "E1", "S1", "X1")],
    )

    await svc.reprice_region(region)
    item = (await session.execute(select(CostItem).where(CostItem.region == region))).scalar_one()
    assert Decimal(item.rate) == Decimal("50.00")
    meta = item.metadata_
    assert meta["labor_cost"] == 10.0
    assert meta["material_cost"] == 10.0
    assert meta["equipment_cost"] == 10.0
    assert meta["other_cost"] == 20.0, "subcontractor + transport are in the rate, so they are in the breakdown"
    assert _breakdown_total(meta) == Decimal("50.00")
    assert meta["cost_by_type"] == {
        "equipment": 10.0,
        "labor": 10.0,
        "material": 10.0,
        "subcontractor": 10.0,
        "transport": 10.0,
    }


# ── write-boundary canonicalisation ──────────────────────────────────────────


def test_cost_item_create_canonicalizes_factor_to_quantity():
    item = CostItemCreate(
        code="WI-1",
        unit="sf",
        rate=Decimal("10"),
        components=[{"code": "M1", "factor": 0.25, "type": "material"}],
    )
    assert item.components[0]["quantity"] == 0.25


def test_cost_item_create_refuses_conflicting_quantity_and_factor():
    with pytest.raises(ValidationError, match="legacy alias"):
        CostItemCreate(
            code="WI-1",
            unit="sf",
            rate=Decimal("10"),
            components=[{"code": "M1", "quantity": 0.25, "factor": 0.5, "type": "material"}],
        )


def test_cost_item_update_canonicalizes_factor_to_quantity():
    patch = CostItemUpdate(components=[{"code": "M1", "factor": "1.5", "type": "material"}])
    assert patch.components is not None
    assert patch.components[0]["quantity"] == "1.5"
