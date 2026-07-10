"""Resource price sheet: seed, edit and re-price coefficient bases.

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

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.costs.models import CostItem, ResourcePrice
from app.modules.costs.resource_pricing import ResourcePriceService, resource_key_for
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
