# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cost Explorer service against a real PostgreSQL database.

Exercises the reverse-index reindex and the four read paths end to end on a
throwaway PostgreSQL database, so the SQL the pure unit tests cannot reach (the
synonym-expanded search, the is_active joins, the staleness scan, the
cross-currency substitute guard) is validated against the real dialect rather
than only compiled.

Covered:

* reindex builds edges and a deactivated work drops out of by-resources.
* find_work matches a construction synonym ("rebar" finds "reinforcement").
* compare lists one rate code across regions and flags mixed currencies.
* substitute re-prices a line by an explicit rate, and refuses a substitute
  priced only in a foreign currency instead of silently blending it.
* substitute flags a swap to a resource priced per a different unit, and stays
  silent when the units match.
* index_status reports a component-bearing region that was never indexed as
  stale, and reports nothing stale once every region is indexed.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests._pg import isolated_engine

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def factory() -> AsyncGenerator[async_sessionmaker, None]:
    """Per-test throwaway PostgreSQL, cloned from the schema-loaded template."""
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _svc(session: AsyncSession):
    from app.modules.cost_explorer.repository import CostExplorerRepository
    from app.modules.cost_explorer.service import CostExplorerService

    return CostExplorerService(CostExplorerRepository(session))


async def _add_work(
    factory: async_sessionmaker,
    *,
    code: str,
    description: str,
    region: str,
    currency: str,
    components: list[dict],
    rate: str = "100.00",
    unit: str = "m3",
    source: str = "cwicr",
    is_active: bool = True,
) -> str:
    """Seed one priced work and return its id as a string."""
    from app.modules.costs.models import CostItem

    async with factory() as s:
        work = CostItem(
            code=code,
            description=description,
            unit=unit,
            rate=rate,
            currency=currency,
            source=source,
            region=region,
            is_active=is_active,
            components=components,
            classification={},
        )
        s.add(work)
        await s.commit()
        return str(work.id)


async def _deactivate(factory: async_sessionmaker, work_id: str) -> None:
    """Soft-delete a work, leaving any index edge behind it stale."""
    import uuid

    from app.modules.costs.models import CostItem

    async with factory() as s:
        work = await s.get(CostItem, uuid.UUID(work_id))
        work.is_active = False
        await s.commit()


async def _add_catalog(
    factory: async_sessionmaker,
    *,
    resource_code: str,
    name: str,
    region: str,
    currency: str,
    base_price: str,
    resource_type: str = "material",
    unit: str = "kg",
) -> None:
    """Seed one catalog price-book row."""
    from app.modules.catalog.models import CatalogResource

    async with factory() as s:
        s.add(
            CatalogResource(
                resource_code=resource_code,
                name=name,
                resource_type=resource_type,
                category="Test",
                unit=unit,
                base_price=base_price,
                currency=currency,
                region=region,
                is_active=True,
            )
        )
        await s.commit()


def _line(
    code: str,
    *,
    name: str = "",
    qty: str = "1",
    unit_rate: str = "10",
    rtype: str = "material",
    unit: str = "",
) -> dict:
    """A components entry (the reindex source for one resource line)."""
    comp = {"code": code, "name": name or code, "type": rtype, "quantity": qty, "unit_rate": unit_rate}
    if unit:
        comp["unit"] = unit
    return comp


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reindex_and_by_resources_excludes_deactivated_work(factory) -> None:
    """A work consuming the resource shows up; once deactivated it does not."""
    from app.modules.cost_explorer.schemas import ByResourcesRequest, ResourceQuery

    keep = await _add_work(
        factory,
        code="W-KEEP",
        description="Reinforced concrete wall",
        region="TR_ANKARA",
        currency="TRY",
        components=[_line("CEM-A", name="Cement", qty="0.3", unit_rate="120")],
    )
    drop = await _add_work(
        factory,
        code="W-DROP",
        description="Reinforced concrete slab",
        region="TR_ANKARA",
        currency="TRY",
        components=[_line("CEM-A", name="Cement", qty="0.25", unit_rate="120")],
    )

    async with factory() as s:
        svc = _svc(s)
        report = await svc.reindex()
        assert report.edges_written >= 2

        req = ByResourcesRequest(resources=[ResourceQuery(code="CEM-A")], limit=50)
        before = await svc.find_by_resources(req)
        codes_before = {r.code for r in before.results}
        assert {"W-KEEP", "W-DROP"} <= codes_before
        # Persist the edges so the later sessions read them: the plain session
        # context does not auto-commit, and the deactivation + final read happen
        # on their own connections that must see this build's edges.
        await s.commit()

    await _deactivate(factory, drop)

    async with factory() as s:
        svc = _svc(s)
        req = ByResourcesRequest(resources=[ResourceQuery(code="CEM-A")], limit=50)
        after = await svc.find_by_resources(req)
        codes_after = {r.code for r in after.results}
        assert "W-KEEP" in codes_after
        assert "W-DROP" not in codes_after
        assert keep  # id captured, kept for symmetry


@pytest.mark.asyncio
async def test_find_work_matches_construction_synonym(factory) -> None:
    """A search for 'rebar' finds a work described with 'reinforcement'."""
    from app.modules.cost_explorer.schemas import FindWorkRequest

    await _add_work(
        factory,
        code="W-REBAR",
        description="Reinforcement steel B500B for slabs",
        region="TR_ANKARA",
        currency="TRY",
        components=[_line("STL-1", name="Steel", rtype="material")],
    )
    await _add_work(
        factory,
        code="W-PAINT",
        description="Emulsion paint two coats",
        region="TR_ANKARA",
        currency="TRY",
        components=[_line("PNT-1", name="Paint")],
    )

    async with factory() as s:
        resp = await _svc(s).find_work(FindWorkRequest(q="rebar", limit=20))
        codes = {r.code for r in resp.results}
        assert "W-REBAR" in codes


@pytest.mark.asyncio
async def test_find_work_matches_across_languages_and_accents(factory) -> None:
    """An English query finds a German-described work, and an accent-free query a
    French one; a foreign short synonym does not poison an unrelated row."""
    from app.modules.cost_explorer.schemas import FindWorkRequest

    await _add_work(
        factory,
        code="W-DE",
        description="Beton C30/37 fuer Wand",  # German for concrete, as a standalone word
        region="DE_BERLIN",
        currency="EUR",
        components=[_line("CEM-A", name="Zement")],
    )
    await _add_work(
        factory,
        code="W-FR",
        description="Béton armé pour dalle",  # accented French
        region="FR_PARIS",
        currency="EUR",
        components=[_line("CEM-B", name="Ciment")],
    )
    await _add_work(
        factory,
        code="W-SUPPORT",
        description="Supported precast beam",  # contains "porte" as a substring
        region="DE_BERLIN",
        currency="EUR",
        components=[_line("STL-1", name="Steel")],
    )

    async with factory() as s:
        svc = _svc(s)
        # English "concrete" reaches the German "Beton" and French "Béton".
        resp = await svc.find_work(FindWorkRequest(q="concrete", limit=20))
        codes = {r.code for r in resp.results}
        assert "W-DE" in codes
        assert "W-FR" in codes

        # An accent-free query still lands on the accented French row.
        resp2 = await svc.find_work(FindWorkRequest(q="beton", limit=20))
        assert "W-FR" in {r.code for r in resp2.results}

        # "door" expands to French "porte", but the word-boundary rule keeps it
        # from matching inside "Supported".
        resp3 = await svc.find_work(FindWorkRequest(q="door", limit=20))
        assert "W-SUPPORT" not in {r.code for r in resp3.results}


@pytest.mark.asyncio
async def test_find_work_no_results_returns_guidance_hint(factory) -> None:
    """A search that finds nothing carries a plain-language, filter-aware hint."""
    from app.modules.cost_explorer.schemas import FindWorkRequest

    await _add_work(
        factory,
        code="W-ONLY",
        description="Emulsion paint two coats",
        region="TR_ANKARA",
        currency="TRY",
        components=[_line("PNT-1", name="Paint")],
    )

    async with factory() as s:
        svc = _svc(s)
        resp = await svc.find_work(FindWorkRequest(q="zzzzznotathing", region="TR_ANKARA", limit=20))
        assert resp.result_count == 0
        assert resp.hint_code == "cost_explorer.hint.no_results"
        assert resp.hint and "region" in resp.hint.lower()


@pytest.mark.asyncio
async def test_find_work_whitespace_query_returns_empty_query_hint(factory) -> None:
    """A whitespace-only query is guarded and guides the user, without a DB scan."""
    from app.modules.cost_explorer.schemas import FindWorkRequest

    async with factory() as s:
        resp = await _svc(s).find_work(FindWorkRequest(q="   ", limit=20))
        assert resp.result_count == 0
        assert resp.hint_code == "cost_explorer.hint.empty_query"


@pytest.mark.asyncio
async def test_by_resources_no_match_returns_hint(factory) -> None:
    """A by-resources search for an unknown code returns a guidance hint."""
    from app.modules.cost_explorer.schemas import ByResourcesRequest, ResourceQuery

    async with factory() as s:
        svc = _svc(s)
        await svc.reindex()
        resp = await svc.find_by_resources(ByResourcesRequest(resources=[ResourceQuery(code="NOPE-404")], limit=20))
        assert resp.result_count == 0
        assert resp.hint_code == "cost_explorer.hint.no_results"


@pytest.mark.asyncio
async def test_compare_lists_code_across_regions_and_flags_mixed_currency(factory) -> None:
    """The same rate code priced in two currencies is reported as mixed."""
    from app.modules.cost_explorer.schemas import CompareRequest

    for region, currency in [("TR_ANKARA", "TRY"), ("DE_BERLIN", "EUR")]:
        await _add_work(
            factory,
            code="SH-1",
            description="Shared scope",
            region=region,
            currency=currency,
            components=[_line("CEM-A")],
        )

    async with factory() as s:
        resp = await _svc(s).compare(CompareRequest(code="SH-1"))
        assert resp.region_count == 2
        assert set(resp.currencies) == {"EUR", "TRY"}


@pytest.mark.asyncio
async def test_substitute_explicit_rate_moves_total_by_quantity_times_delta(factory) -> None:
    """Re-pricing a line by an explicit unit rate moves the total by qty*delta."""
    from app.modules.cost_explorer.schemas import SubstituteRequest

    work_id = await _add_work(
        factory,
        code="W-SUB",
        description="Concrete works",
        region="TR_ANKARA",
        currency="TRY",
        rate="100.00",
        components=[_line("CEM-A", name="Cement", qty="2", unit_rate="10")],
    )

    async with factory() as s:
        resp = await _svc(s).substitute(
            SubstituteRequest(cost_item_id=work_id, resource_code="CEM-A", new_unit_rate="15")
        )
        # qty 2 * (15 - 10) = 10 added to the 100 rate.
        assert Decimal(resp.old_rate) == Decimal("100")
        assert Decimal(resp.new_rate) == Decimal("110")
        assert Decimal(resp.delta) == Decimal("10")


@pytest.mark.asyncio
async def test_substitute_refuses_foreign_currency_price(factory) -> None:
    """A substitute priced only in another currency is refused, not blended."""
    from app.modules.cost_explorer.schemas import SubstituteRequest
    from app.modules.cost_explorer.service import CostExplorerNotFound

    work_id = await _add_work(
        factory,
        code="W-XCUR",
        description="Concrete works",
        region="TR_ANKARA",
        currency="TRY",
        components=[_line("CEM-A", name="Cement", qty="1", unit_rate="10")],
    )
    # The replacement resource is priced only in a EUR base, not in TRY.
    await _add_catalog(
        factory,
        resource_code="CEM-B",
        name="Premium cement",
        region="DE_BERLIN",
        currency="EUR",
        base_price="90",
    )

    async with factory() as s:
        with pytest.raises(CostExplorerNotFound):
            await _svc(s).substitute(
                SubstituteRequest(
                    cost_item_id=work_id,
                    resource_code="CEM-A",
                    substitute_resource_code="CEM-B",
                )
            )


@pytest.mark.asyncio
async def test_substitute_flags_unit_mismatch_only_when_units_differ(factory) -> None:
    """A swap to a resource priced per a different unit is flagged; same unit is not."""
    from app.modules.cost_explorer.schemas import SubstituteRequest

    work_id = await _add_work(
        factory,
        code="W-UNIT",
        description="Rebar in slab",
        region="TR_ANKARA",
        currency="TRY",
        components=[_line("STL-KG", name="Rebar", qty="80", unit_rate="12", unit="kg")],
    )
    # Same currency (TRY) but priced per tonne, not per kg: the kept quantity no
    # longer lines up with the price basis, so the swap must warn.
    await _add_catalog(
        factory,
        resource_code="STL-T",
        name="Rebar bundle",
        region="TR_ANKARA",
        currency="TRY",
        base_price="12000",
        unit="t",
    )
    # A same-unit (kg) replacement in the same currency must NOT warn.
    await _add_catalog(
        factory,
        resource_code="STL-KG2",
        name="Alt rebar",
        region="TR_ANKARA",
        currency="TRY",
        base_price="13",
        unit="kg",
    )

    async with factory() as s:
        svc = _svc(s)
        mismatch = await svc.substitute(
            SubstituteRequest(
                cost_item_id=work_id,
                resource_code="STL-KG",
                substitute_resource_code="STL-T",
            )
        )
        assert mismatch.unit_mismatch is True
        assert mismatch.original_unit == "kg"
        assert mismatch.substitute_unit == "t"

        same = await svc.substitute(
            SubstituteRequest(
                cost_item_id=work_id,
                resource_code="STL-KG",
                substitute_resource_code="STL-KG2",
            )
        )
        assert same.unit_mismatch is False


@pytest.mark.asyncio
async def test_substitute_unit_compare_is_case_insensitive(factory) -> None:
    """A line measured in 'kg' and a substitute priced in 'KG' are the same unit."""
    from app.modules.cost_explorer.schemas import SubstituteRequest

    work_id = await _add_work(
        factory,
        code="W-CASE",
        description="Rebar in slab",
        region="TR_ANKARA",
        currency="TRY",
        components=[_line("STL-KG", name="Rebar", qty="80", unit_rate="12", unit="kg")],
    )
    # Same unit as the line but written in a different case; must not warn.
    await _add_catalog(
        factory,
        resource_code="STL-UP",
        name="Alt rebar",
        region="TR_ANKARA",
        currency="TRY",
        base_price="13",
        unit="KG",
    )

    async with factory() as s:
        resp = await _svc(s).substitute(
            SubstituteRequest(
                cost_item_id=work_id,
                resource_code="STL-KG",
                substitute_resource_code="STL-UP",
            )
        )
        assert resp.unit_mismatch is False


@pytest.mark.asyncio
async def test_index_status_reports_unindexed_region_then_clears(factory) -> None:
    """A component-bearing region that was skipped reads as stale until indexed."""
    for region in ("TR_ANKARA", "DE_BERLIN"):
        await _add_work(
            factory,
            code=f"W-{region}",
            description="Reinforced concrete",
            region=region,
            currency="EUR" if region.startswith("DE") else "TRY",
            components=[_line("CEM-A", qty="0.3", unit_rate="100")],
        )

    # Index only one region, so the other carries works but no edges.
    async with factory() as s:
        svc = _svc(s)
        await svc.reindex(region="TR_ANKARA")
        status = await svc.index_status()
        assert status["indexed_edges"] > 0
        assert status["unindexed_regions"] == ["DE_BERLIN"]

    # Index the rest; nothing should read as stale afterwards.
    async with factory() as s:
        svc = _svc(s)
        await svc.reindex()
        status = await svc.index_status()
        assert status["unindexed_regions"] == []
