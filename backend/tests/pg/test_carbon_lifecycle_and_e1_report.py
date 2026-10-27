# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Life-cycle​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ carbon and the company E1 report against real PostgreSQL.

The demo seed must leave one project over its carbon budget, an alternative
that saves CO2 for a small cost delta, two EPDs and one company E1 report whose
every figure traces back to a source row.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.carbon.lifecycle_service import CarbonLifecycleService
from app.modules.carbon.models import CarbonCompanyReport, EmbodiedCarbonEntry, EPDRecord
from app.modules.carbon.schemas import CarbonInventoryCreate
from app.modules.carbon.seed import DEMO_COMPANY, DEMO_EPD_IDS, seed_carbon_demo
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

ILCD = b"""<processDataSet xmlns="http://lca.jrc.it/ILCD/Process" xmlns:common="http://lca.jrc.it/ILCD/Common"
 xmlns:epd="http://www.iai.kit.edu/EPD/2013"><processInformation><dataSetInformation>
<common:UUID>pg-ilcd-0001</common:UUID><name><baseName>Timber CLT</baseName></name></dataSetInformation>
</processInformation><LCIAResults><LCIAResult><referenceToLCIAMethodDataSet>
<common:shortDescription>Climate change (GWP total)</common:shortDescription></referenceToLCIAMethodDataSet>
<common:other><epd:amount epd:module="A1-A3">95</epd:amount></common:other></LCIAResult></LCIAResults>
</processDataSet>"""


async def _projects(session, n: int = 2) -> list[uuid.UUID]:
    owner = User(email=f"lc-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Owner")
    session.add(owner)
    await session.flush()
    out = []
    for i in range(n):
        p = Project(name=f"LC {i}", owner_id=owner.id, currency="EUR", country_code="DE")
        session.add(p)
        await session.flush()
        out.append(p.id)
    return out


async def test_demo_seed_gives_overrun_alternative_and_traceable_e1(pg_session) -> None:
    pids = await _projects(pg_session)
    await seed_carbon_demo(pg_session, pids)
    svc = CarbonLifecycleService(pg_session)

    epds = (await pg_session.execute(select(EPDRecord).where(EPDRecord.epd_id.in_(DEMO_EPD_IDS)))).scalars().all()
    assert len(epds) == 2

    budget = await svc.budget(pids[0])
    assert budget["over_budget"] is True

    entry = (
        await pg_session.execute(
            select(EmbodiedCarbonEntry).where(EmbodiedCarbonEntry.description.like("Foundation slab%"))
        )
    ).scalar_one()
    alt = entry.metadata_["demo_alternative"]
    swap = await svc.swap(
        entry.id,
        alternative_factor_id=uuid.UUID(alt["factor_id"]),
        current_unit_rate=Decimal(alt["current_unit_rate"]),
        alternative_unit_rate=Decimal(alt["alternative_unit_rate"]),
    )
    assert Decimal(swap["co2_delta_kg"]) < 0 < Decimal(swap["cost_delta"])
    assert Decimal(swap["cost_delta"]) < Decimal(swap["cost_current"]) * Decimal("0.1")

    report = (
        await pg_session.execute(select(CarbonCompanyReport).where(CarbonCompanyReport.company_name == DEMO_COMPANY))
    ).scalar_one()
    assert Decimal(report.datapoints["E1-6_scope1"]["value"]) > 0
    assert report.audit["E1-6_scope2_location"], "scope 2 has no source rows"
    for item in report.audit["E1-6_scope1"]:
        assert item["source_id"] and item["data_quality"] in {"measured", "calculated", "estimated"}

    widget = await svc.dashboard_widget(pids[0])
    assert widget["budget"]["over_budget"] is True and widget["system"] == "din276"

    # A second run is a no-op for the life-cycle demo.
    again = await seed_carbon_demo(pg_session, pids)
    assert again["lifecycle_epds"] == 0


async def test_ilcd_import_stage_lines_and_checks(pg_session) -> None:
    pids = await _projects(pg_session, 1)
    svc = CarbonLifecycleService(pg_session)
    inv = await svc.base.create_inventory(CarbonInventoryCreate(project_id=pids[0], name="LC"))
    result = await svc.import_epd_file(ILCD, "clt.xml", material_class="timber")
    assert result["format"] == "ilcd_xml" and len(result["imported"]) == 1
    again = await svc.import_epd_file(ILCD, "clt.xml")
    assert again["imported"] == result["imported"], "re-import must upsert, not duplicate"

    a4 = await svc.add_transport_a4(inv.id, mass_kg=Decimal("24000"), distance_km=Decimal("100"), mode="road_truck")
    assert a4.stage == "a4" and Decimal(str(a4.carbon_kg)) == Decimal("256.8")
    a5 = await svc.add_site_energy_a5(inv.id, fuel_litres={"diesel": Decimal("100")}, electricity_kwh=Decimal("0"))
    assert a5.stage == "a5" and a5.data_quality == "measured"

    pg_session.add(EmbodiedCarbonEntry(inventory_id=inv.id, description="no factor", quantity=1, unit="m3"))
    await pg_session.flush()
    pos = uuid.uuid4()
    pg_session.add(
        EmbodiedCarbonEntry(
            inventory_id=inv.id, element_ref=f"boq:{pos}", quantity=10, unit="m3", factor_value_used=100, carbon_kg=1000
        )
    )
    await pg_session.flush()
    bid = await svc.bid_carbon([{"ref": "1", "position_id": pos, "quantity": Decimal("4"), "unit": "m3"}])
    assert bid["lines"][0]["status"] == "ok" and Decimal(bid["total_kg"]) == Decimal("400")

    checks = await svc.checks(pids[0])
    assert len(checks["no_factor"]) == 1
