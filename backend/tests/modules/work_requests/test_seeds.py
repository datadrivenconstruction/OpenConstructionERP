# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The five departments a fresh install starts with, and that a
configured install is never re-seeded over."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_requests import service
from app.modules.work_requests.seeds import seed_departments_if_empty
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import make_user, seeded


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_seed_plants_five_departments_once(session: AsyncSession) -> None:
    assert await seed_departments_if_empty(session) == 5
    assert await seed_departments_if_empty(session) == 0, "a second run must not duplicate"
    depts = await seeded(session)
    assert list(depts) == ["engineering", "drafting", "workshop", "automation", "hazardous_area"]
    assert {d.prefix for d in depts.values()} == {"ENG", "DRF", "WKS", "AUT", "HAZ"}
    for d in depts.values():
        assert d.active
        assert d.stages, f"{d.key} needs a stage run"
        assert d.stages[-1]["closes"], f"{d.key}'s run must end in a closing stage"
        assert d.request_types, f"{d.key} needs request types"


@pytest.mark.asyncio
async def test_seed_carries_the_spreadsheet_columns(session: AsyncSession) -> None:
    depts = await seeded(session)
    workshop = depts["workshop"]
    assert [s["key"] for s in workshop.stages] == [
        "requested",
        "drawings_received",
        "materials_ordered",
        "build",
        "wiring",
        "testing",
        "ready_for_fat",
        "delivered",
    ]
    board = service.request_type_spec(workshop, "switchboard")
    keys = {f["key"]: f for f in board["fields"]}
    assert keys["custom_plinth"]["options"] == ["No", "Yes", "Yes - stand"]
    assert keys["drawings_to_factory_by"]["type"] == "date"
    assert keys["tested_by"]["type"] == "date"

    drafting = depts["drafting"]
    assert [s["key"] for s in drafting.stages][0] == "ready_to_draft"
    scope = service.request_type_spec(drafting, "drafting_only")
    assert {f["key"] for f in scope["fields"]} == {"drawing_link", "scope"}

    auto = service.request_type_spec(depts["automation"], "plc_programming")
    assert {f["key"] for f in auto["fields"]} == {"planner_uploaded", "info_link"}

    haz = service.request_type_spec(depts["hazardous_area"], "area_classification")
    assert {f["key"] for f in haz["fields"]} == {"zone", "standard"}

    eng = service.request_type_spec(depts["engineering"], "eng_and_drafting")
    assert eng["disciplines"] == ["engineering", "drafting"]


@pytest.mark.asyncio
async def test_an_edited_department_is_not_reseeded(session: AsyncSession) -> None:
    depts = await seeded(session)
    lead = await make_user(session, name="Sam Example")
    await service.update_department(
        session,
        depts["workshop"],
        {
            "name": "Factory",
            "hourly_rate": "185",
            "lead_user_id": str(lead.id),
            "stages": [{"key": "in", "name": "In", "colour": "slate"}, {"key": "out", "name": "Out", "closes": True}],
        },
    )
    await service.ensure_seeded(session)
    again = await service.department_or_error(session, "workshop")
    assert again.name == "Factory"
    assert again.hourly_rate == "185.00", "money is normalised text"
    assert again.lead_user_id == str(lead.id)
    assert [s["key"] for s in again.stages] == ["in", "out"]
    assert again.prefix == "WKS", "the prefix is fixed for life - references carry it"


@pytest.mark.asyncio
async def test_custom_department_mints_from_its_key_and_refuses_a_shared_prefix(session: AsyncSession) -> None:
    await seeded(session)
    site = await service.create_department(session, {"key": "site_services", "name": "Site Services"})
    assert site.prefix == "SIT"
    with pytest.raises(service.ConflictError):
        await service.create_department(session, {"key": "engineering_support", "name": "Eng Support"})
    chosen = await service.create_department(
        session, {"key": "engineering_support", "name": "Eng Support", "prefix": "ESP"}
    )
    assert chosen.prefix == "ESP"
    with pytest.raises(service.WorkRequestError):
        await service.create_department(session, {"key": "Bad Key!", "name": "x"})
    with pytest.raises(service.WorkRequestError):
        await service.update_department(
            session, site, {"stages": [{"key": "a", "name": "A"}, {"key": "a", "name": "A again"}]}
        )
    with pytest.raises(service.WorkRequestError):
        await service.update_department(
            session,
            site,
            {"request_types": [{"key": "t", "label": "T", "fields": [{"key": "pick", "type": "select"}]}]},
        )
