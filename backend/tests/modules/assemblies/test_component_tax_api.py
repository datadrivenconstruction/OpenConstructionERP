# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Component input tax through the API on PostgreSQL (issue #559).

Rates are fixtures. The switch is per project and off by default: with it off an
assembly prices exactly as before, tax fields or not.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.assemblies.permissions import register_assemblies_permissions
from app.modules.assemblies.router import router as assemblies_router
from app.modules.assemblies.validators import register_assemblies_validation_rules
from app.modules.catalog.models import CatalogResource
from app.modules.i18n_foundation.models import TaxConfiguration
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

D = Decimal


@pytest_asyncio.fixture
async def env() -> AsyncIterator[tuple[AsyncClient, object, User]]:
    register_assemblies_permissions()
    register_assemblies_validation_rules()
    async with transactional_session() as session:
        user = User(email=f"tax-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
        session.add(user)
        await session.flush()
        await session.commit()
        app = FastAPI()
        app.include_router(assemblies_router, prefix="/v1/assemblies")

        async def _session():
            yield session

        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_current_user_id] = lambda: str(user.id)
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": str(user.id),
            "role": "admin",
            "permissions": [],
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, session, user


async def project(session, user: User, *, enabled: bool, treatment: str = "cost_incorporated", country: str = "ZZ"):
    row = Project(
        name=f"P-{uuid.uuid4().hex[:5]}",
        owner_id=user.id,
        country_code=country,
        component_tax_enabled=enabled,
        component_tax_treatment=treatment,
    )
    session.add(row)
    await session.flush()
    return row


async def assembly(c: AsyncClient, project_id: object | None, **kw: object) -> str:
    r = await c.post(
        "/v1/assemblies/",
        json={
            "code": f"A-{uuid.uuid4().hex[:6]}",
            "name": "Wall",
            "unit": "m2",
            "currency": "EUR",
            "project_id": str(project_id) if project_id else None,
            "is_template": False,
            **kw,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def add(c: AsyncClient, aid: str, unit_cost: str, **kw: object) -> dict:
    r = await c.post(
        f"/v1/assemblies/{aid}/components/",
        json={"description": kw.pop("description", "Line"), "unit": "pcs", "quantity": 1, "unit_cost": unit_cost, **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def full(c: AsyncClient, aid: str) -> dict:
    r = await c.get(f"/v1/assemblies/{aid}")
    assert r.status_code == 200, r.text
    return r.json()


def money(value: object) -> Decimal:
    return D(str(value))


@pytest.mark.asyncio
async def test_switch_off_ignores_tax_fields_and_matches_plain_pricing(env) -> None:
    c, session, user = env
    off = await project(session, user, enabled=False)
    plain, tagged = await assembly(c, off.id), await assembly(c, off.id)
    await add(c, plain, "1000")
    comp = await add(c, tagged, "1000", tax_status="taxable", tax_rate="18", input_tax_treatment="cost_incorporated")
    assert money(comp["total"]) == D("1000")
    assert "tax" not in comp["metadata"]
    a, b = await full(c, plain), await full(c, tagged)
    assert a["total_rate"] == b["total_rate"] == 1000
    assert "tax_totals" not in b["metadata"]
    # an assembly outside any project is never taxed either
    free = await assembly(c, None)
    await add(c, free, "1000", tax_status="taxable", tax_rate="18")
    assert (await full(c, free))["total_rate"] == 1000


@pytest.mark.asyncio
async def test_issue_example_totals_with_switch_on(env) -> None:
    c, session, user = env
    proj = await project(session, user, enabled=True)
    aid = await assembly(c, proj.id)
    mat = await add(c, aid, "1000", description="Material A", tax_status="taxable", tax_rate="18")
    lab = await add(c, aid, "500", description="Labor B", tax_status="exempt")
    free = await add(c, aid, "100", description="Unclassified")
    assert money(mat["total"]) == D("1180.00")  # project default: cost-incorporated
    assert money(lab["total"]) == D("500.00")
    assert money(free["total"]) == D("100")
    assert "tax" not in free["metadata"]
    body = await full(c, aid)
    assert body["total_rate"] == 1780
    totals = body["metadata"]["tax_totals"]
    assert (money(totals["net"]), money(totals["tax_in_cost"]), money(totals["tax_recoverable"])) == (
        D("1600"),
        D("180"),
        D("0"),
    )
    assert (money(totals["cost"]), money(totals["gross_outlay"])) == (D("1780"), D("1780"))


@pytest.mark.asyncio
async def test_recoverable_and_inclusive_and_component_override(env) -> None:
    c, session, user = env
    proj = await project(session, user, enabled=True, treatment="recoverable")
    aid = await assembly(c, proj.id)
    inc = await add(c, aid, "1180", tax_status="taxable", tax_rate="18", price_includes_tax=True)
    own = await add(c, aid, "1000", tax_status="taxable", tax_rate="18", input_tax_treatment="cost_incorporated")
    assert money(inc["total"]) == D("1000.00")  # inclusive, recoverable: cost is the net
    assert money(own["total"]) == D("1180.00")  # component overrides the project default
    totals = (await full(c, aid))["metadata"]["tax_totals"]
    assert (money(totals["tax_recoverable"]), money(totals["tax_in_cost"])) == (D("180"), D("180"))
    assert money(totals["gross_outlay"]) == D("2360")  # 1180 + 1180 paid out


@pytest.mark.asyncio
async def test_registry_code_resolves_for_project_country_and_date(env) -> None:
    c, session, user = env
    country = "ZY"
    for code, rate, to in (("STD", "18", None), ("RED", "8", None), ("OLD", "10", "2019-12-31")):
        session.add(
            TaxConfiguration(
                country_code=country,
                tax_name=code,
                tax_code=code,
                rate_pct=rate,
                tax_type="vat",
                combination="national",
                effective_from="2015-01-01",
                effective_to=to,
                is_default=code == "STD",
                metadata_={},
            )
        )
    await session.flush()
    proj = await project(session, user, enabled=True, country=country)
    aid = await assembly(c, proj.id)
    std = await add(c, aid, "1000", tax_code="STD", tax_status="taxable")
    red = await add(c, aid, "1000", tax_code="RED", tax_status="taxable")
    old = await add(c, aid, "1000", description="Expired", tax_code="OLD", tax_status="taxable")
    assert money(std["total"]) == D("1180.00")
    assert money(std["metadata"]["tax"]["rate_pct"]) == D("18")
    assert money(red["total"]) == D("1080.00")
    assert money(red["metadata"]["tax"]["rate_pct"]) == D("8")
    assert "tax" not in old["metadata"]  # no rate in force: left untaxed, reported by the rules
    findings = (await c.get(f"/v1/assemblies/{aid}/tax-findings/")).json()
    assert {f["rule_id"] for f in findings} >= {"assemblies.tax_006_rate_in_force"}


@pytest.mark.asyncio
async def test_resource_defaults_feed_the_component_and_component_overrides(env) -> None:
    c, session, user = env
    res = CatalogResource(
        resource_code=f"R-{uuid.uuid4().hex[:6]}",
        name="Cement",
        resource_type="material",
        category="Cement",
        unit="t",
        base_price="1000",
        currency="EUR",
        tax_status="taxable",
        tax_rate="18",
        input_tax_treatment="cost_incorporated",
    )
    session.add(res)
    await session.flush()
    proj = await project(session, user, enabled=True)
    aid = await assembly(c, proj.id)
    inherits = await add(c, aid, "1000", catalog_resource_id=str(res.id))
    overrides = await add(c, aid, "1000", catalog_resource_id=str(res.id), tax_status="exempt")
    assert money(inherits["total"]) == D("1180.00")
    assert money(overrides["total"]) == D("1000.00")


@pytest.mark.asyncio
async def test_update_component_retaxes_and_clearing_status_removes_the_split(env) -> None:
    c, session, user = env
    proj = await project(session, user, enabled=True)
    aid = await assembly(c, proj.id)
    comp = await add(c, aid, "1000", tax_status="taxable", tax_rate="18")
    r = await c.patch(f"/v1/assemblies/{aid}/components/{comp['id']}", json={"quantity": 2})
    assert r.status_code == 200, r.text
    assert money(r.json()["total"]) == D("2360.00")
    r = await c.patch(f"/v1/assemblies/{aid}/components/{comp['id']}", json={"tax_rate": "8"})
    assert money(r.json()["total"]) == D("2160.00")
    assert (await full(c, aid))["total_rate"] == 2160


@pytest.mark.asyncio
async def test_recalculation_takes_master_price_for_unapproved_and_never_touches_approved(env) -> None:
    c, session, user = env
    res = CatalogResource(
        resource_code=f"R-{uuid.uuid4().hex[:6]}",
        name="Rebar",
        resource_type="material",
        category="Steel",
        unit="t",
        base_price="100",
        currency="EUR",
    )
    session.add(res)
    await session.flush()
    proj = await project(session, user, enabled=True)
    draft, approved = await assembly(c, proj.id), await assembly(c, proj.id)
    for aid in (draft, approved):
        await add(c, aid, "100", catalog_resource_id=str(res.id), tax_status="taxable", tax_rate="10")
    assert (await c.patch(f"/v1/assemblies/{approved}", json={"metadata": {"status": "approved"}})).status_code == 200

    res.base_price = "200"  # the master price moves
    await session.flush()
    before = await full(c, draft)
    assert before["total_rate"] == 110  # no silent re-pricing

    drift = (await c.get(f"/v1/assemblies/{draft}/tax-findings/")).json()
    assert "assemblies.tax_005_master_price_drift" in {f["rule_id"] for f in drift}

    refused = await c.post(f"/v1/assemblies/{approved}/recalculate-tax/")
    assert refused.status_code == 409

    done = await c.post(f"/v1/assemblies/{draft}/recalculate-tax/")
    assert done.status_code == 200, done.text
    assert done.json()["updated"] is True
    assert done.json()["total_rate"] == 220
    assert "assemblies.tax_005_master_price_drift" not in {f["rule_id"] for f in done.json()["findings"]}

    bulk = await c.post(f"/v1/assemblies/recalculate-tax/?project_id={proj.id}")
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["updated"] == [draft]
    assert bulk.json()["skipped_approved"] == [approved]
    assert (await full(c, approved))["total_rate"] == 110


@pytest.mark.asyncio
async def test_master_price_events_leave_a_tax_managed_assembly_alone(env) -> None:
    from app.modules.assemblies.events import _without_tax_managed
    from app.modules.assemblies.models import Component

    c, session, user = env
    on, off = await project(session, user, enabled=True), await project(session, user, enabled=False)
    a_on, a_off = await assembly(c, on.id), await assembly(c, off.id)
    await add(c, a_on, "10")
    await add(c, a_off, "10")
    from sqlalchemy import select

    comps = list(
        (
            await session.execute(
                select(Component).where(Component.assembly_id.in_([uuid.UUID(a_on), uuid.UUID(a_off)]))
            )
        ).scalars()
    )
    kept = await _without_tax_managed(session, comps)
    assert {str(k.assembly_id) for k in kept} == {a_off}


@pytest.mark.asyncio
async def test_recalculate_without_the_switch_does_nothing(env) -> None:
    c, session, user = env
    off = await project(session, user, enabled=False)
    aid = await assembly(c, off.id)
    await add(c, aid, "10")
    r = await c.post(f"/v1/assemblies/{aid}/recalculate-tax/")
    assert r.status_code == 200
    assert (r.json()["updated"], r.json()["skipped_reason"]) == (False, "component_tax_disabled")
    assert (await c.get(f"/v1/assemblies/{aid}/tax-findings/")).json() == []


@pytest.mark.asyncio
async def test_schema_rejects_bad_profiles(env) -> None:
    c, session, user = env
    aid = await assembly(c, (await project(session, user, enabled=True)).id)
    for bad in ({"tax_rate": "180"}, {"tax_rate": "abc"}, {"tax_status": "maybe"}, {"input_tax_treatment": "x"}):
        r = await c.post(f"/v1/assemblies/{aid}/components/", json={"description": "x", "unit": "pcs", **bad})
        assert r.status_code == 422, bad


@pytest.mark.asyncio
async def test_export_import_round_trip_keeps_tax_profile_and_plain_export_is_unchanged(env) -> None:
    c, session, user = env
    proj = await project(session, user, enabled=True)
    aid = await assembly(c, proj.id)
    await add(c, aid, "1000", tax_status="taxable", tax_rate="18", price_includes_tax=False)
    plain_id = await assembly(c, proj.id)
    await add(c, plain_id, "5")
    exported = (await c.get(f"/v1/assemblies/{aid}/export/")).json()
    assert exported["components"][0]["tax_rate"] == "18"
    plain = (await c.get(f"/v1/assemblies/{plain_id}/export/")).json()
    assert not any(k.startswith("tax_") for k in plain["components"][0])
    exported["code"] = f"IMP-{uuid.uuid4().hex[:6]}"
    r = await c.post("/v1/assemblies/import/", json={"assembly": {**exported, "project_id": None}})
    assert r.status_code in (200, 201), r.text
    bad = {**exported, "code": f"IMP-{uuid.uuid4().hex[:6]}"}
    bad["components"] = [{**exported["components"][0], "tax_rate": "400"}]
    assert (await c.post("/v1/assemblies/import/", json={"assembly": bad})).status_code == 422
