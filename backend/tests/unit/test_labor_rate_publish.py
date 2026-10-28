# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for publishing a labour-rate template as a reusable labor cost item.

A pure check locks the published rate to :func:`rate_math.all_in_rate` for a
known template (no database). DB-backed checks drive
:meth:`LaborRateService.publish_template_as_cost_item` against the
transaction-isolated embedded PostgreSQL - the same fixture style the
norm-expansion build tests use - and prove a publish creates exactly one labour
cost item with the right unit / kind / rate, and that a re-publish of the same
template, region and catalog updates that row rather than duplicating it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.costs.models import CostItem
from app.modules.labor_rates import rate_math
from app.modules.labor_rates.models import LaborRateTemplate, OnCostComponent
from app.modules.labor_rates.service import (
    LaborRateService,
    LaborRateTemplateNotFoundError,
    _template_all_in_rate,
)
from tests._pg import transactional_session

D = Decimal


# ── Pure: published rate == all_in_rate(...) ─────────────────────────────────


def test_published_rate_equals_all_in_rate_for_a_known_template() -> None:
    """The rate a publish would carry equals the pure all-in build-up."""
    # 30/h base + 20% statutory + 1.50/h small tools -> 30 + 6 + 1.50 = 37.50.
    template = LaborRateTemplate(name="Plasterer", base_wage=D("30"), currency="EUR")
    template.components.append(
        OnCostComponent(label="Statutory charges", kind="percentage", value=D("20"), sort_order=0)
    )
    template.components.append(OnCostComponent(label="Small tools", kind="fixed", value=D("1.5"), sort_order=1))

    expected = rate_math.all_in_rate(
        D("30"),
        [
            rate_math.OnCost("Statutory charges", "percentage", D("20")),
            rate_math.OnCost("Small tools", "fixed", D("1.5")),
        ],
    )
    published = _template_all_in_rate(template)
    assert published == expected == D("37.50")


# ── DB-backed publish ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _seed_template(s, *, base_wage: str = "30", pct: str = "20", currency: str = "EUR") -> LaborRateTemplate:
    """A template that builds up to (base_wage + pct%) per hour."""
    template = LaborRateTemplate(name="Plasterer", base_wage=D(base_wage), currency=currency)
    template.components.append(
        OnCostComponent(label="Statutory charges", kind="percentage", value=D(pct), sort_order=0)
    )
    s.add(template)
    await s.flush()
    return template


async def _count_published(s, template_id: uuid.UUID) -> int:
    """Count published cost items derived from one template (any region/catalog)."""
    result = await s.execute(
        select(func.count(CostItem.id)).where(CostItem.code.like(f"LABOR-RATE-{template_id.hex}-%"))
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_publish_creates_one_labor_cost_item(session) -> None:
    template = await _seed_template(session)  # 30 + 20% = 36.00/h
    service = LaborRateService(session)

    item = await service.publish_template_as_cost_item(template.id, region="DE_BERLIN")

    # The exact CostItem shape a labour rate must carry.
    assert item.unit == "h"
    assert D(str(item.rate)) == D("36.00")
    assert item.currency == "EUR"
    assert item.region == "DE_BERLIN"
    assert item.source == "labor_rate"
    assert item.is_active is True
    assert item.tags == ["labor"]
    assert item.classification["collection"] == "Labour"
    assert item.classification["resource_kind"] == "labor"
    assert item.metadata_["resource_kind"] == "labor"
    assert item.metadata_["labor_rate_template_id"] == str(template.id)
    assert item.description == "Plasterer (DE_BERLIN)"

    # Exactly one published cost item exists for this template.
    assert await _count_published(session, template.id) == 1


@pytest.mark.asyncio
async def test_publish_rate_matches_the_norm_build_rate(session) -> None:
    """The published rate equals what a priced assembly build resolves to."""
    template = await _seed_template(session, base_wage="30", pct="20")
    service = LaborRateService(session)

    item = await service.publish_template_as_cost_item(template.id)

    expected = rate_math.all_in_rate(D("30"), [rate_math.OnCost("Statutory charges", "percentage", D("20"))])
    assert D(str(item.rate)) == expected == D("36.00")
    # No region -> a global (region-less) cost item.
    assert item.region is None


@pytest.mark.asyncio
async def test_republish_updates_rather_than_duplicates(session) -> None:
    template = await _seed_template(session)
    # Capture the id as a plain UUID: the costs update path calls expire_all(),
    # which expires the ORM template, so a later template.id access would trigger
    # a sync lazy-load outside the async greenlet.
    template_id = template.id
    service = LaborRateService(session)

    first = await service.publish_template_as_cost_item(template_id, region="DE_BERLIN")
    first_id = first.id  # capture before the update-path expire_all below

    # Change the build-up, then re-publish the same template + region + catalog.
    template.base_wage = D("40")  # 40 + 20% = 48.00/h
    await session.flush()
    second = await service.publish_template_as_cost_item(template_id, region="DE_BERLIN")

    assert second.id == first_id  # same row, updated in place
    assert D(str(second.rate)) == D("48.00")
    # Still exactly one published item for this template.
    assert await _count_published(session, template_id) == 1


@pytest.mark.asyncio
async def test_publish_into_two_catalogs_are_distinct_items(session) -> None:
    """Same template + region but different catalogs are separate cost lines."""
    from app.modules.costs.models import CostCatalog

    template = await _seed_template(session)
    cat_a = CostCatalog(name=f"Cat A {uuid.uuid4().hex[:6]}", currency="EUR", source="manual")
    cat_b = CostCatalog(name=f"Cat B {uuid.uuid4().hex[:6]}", currency="EUR", source="manual")
    session.add_all([cat_a, cat_b])
    await session.flush()

    service = LaborRateService(session)
    a = await service.publish_template_as_cost_item(template.id, region="DE_BERLIN", catalog=cat_a.id)
    b = await service.publish_template_as_cost_item(template.id, region="DE_BERLIN", catalog=cat_b.id)

    assert a.id != b.id
    assert a.catalog_id == cat_a.id
    assert b.catalog_id == cat_b.id
    # Two catalog-scoped items for the same template + region.
    assert await _count_published(session, template.id) == 2


@pytest.mark.asyncio
async def test_publish_missing_template_raises(session) -> None:
    service = LaborRateService(session)
    with pytest.raises(LaborRateTemplateNotFoundError):
        await service.publish_template_as_cost_item(uuid.uuid4())


# ── Endpoint wiring ──────────────────────────────────────────────────────────


def test_publish_route_is_registered_and_gated() -> None:
    """POST .../templates/{template_id}/publish returns a cost item, gated by two perms."""
    from app.modules.costs.schemas import CostItemResponse
    from app.modules.labor_rates.router import router

    routes = [r for r in router.routes if getattr(r, "path", "").endswith("/templates/{template_id}/publish")]
    assert len(routes) == 1
    route = routes[0]
    assert route.methods == {"POST"}
    assert route.response_model is CostItemResponse
    # Gated by the module write permission plus the costs create permission.
    assert len(route.dependencies) == 2
