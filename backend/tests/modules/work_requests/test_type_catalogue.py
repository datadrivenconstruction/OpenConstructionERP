# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The department's own request-type catalogue.

The owner adds the next type without waiting on a release, orders them,
and RETIRES the ones that have had their day - a type anything was ever
raised against is never deleted, so no request loses its label.

Also the startup reconcile that tops a live install up with what a later
release seeded, additively and without touching a thing the owner edited.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.work_requests import service
from app.modules.work_requests.router import router as wr_router
from app.modules.work_requests.seeds import (
    DEFAULT_DEPARTMENTS,
    LEGACY_HAZARDOUS_AREA_COLOUR,
    reconcile_seeded_departments,
)
from tests._pg import isolated_engine, transactional_session
from tests.modules.work_requests._helpers import make_project, make_user, raise_request, seeded

USER_ID = "00000000-0000-0000-0000-0000000000c2"
BASE = "/api/v1/work-requests"
MANAGER = {
    "role": "manager",
    "permissions": [
        "work_requests.read",
        "work_requests.create",
        "work_requests.update",
        "work_requests.manage",
    ],
}
EDITOR = {"role": "editor", "permissions": MANAGER["permissions"][:3]}


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest_asyncio.fixture
async def ctx():
    """A live app, a non-admin manager, and a project they own."""
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            user = User(
                id=uuid.UUID(USER_ID),
                email=f"tc-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Alex Example",
                role="editor",
            )
            s.add(user)
            await s.flush()
            project = Project(
                name="Example Client Pty Ltd - MCC upgrade",
                owner_id=user.id,
                currency="AUD",
                project_code="25406",
                client_id="Acme Holdings",
            )
            s.add(project)
            await s.commit()
            project_id = str(project.id)

        state = {"payload": dict(MANAGER)}
        app = FastAPI()
        app.include_router(wr_router, prefix=BASE)
        app.dependency_overrides[get_current_user_id] = lambda: USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {"sub": USER_ID, **state["payload"]}

        async def _session_override():
            async with maker() as s:
                yield s

        app.dependency_overrides[get_session] = _session_override
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client, project_id, state


# ── The seeded catalogue and its colours ─────────────────────────────────


@pytest.mark.asyncio
async def test_the_seeded_colours_are_mutually_distinct(session: AsyncSession) -> None:
    depts = await seeded(session)
    colours = {k: d.colour for k, d in depts.items()}
    assert colours["hazardous_area"] == "red", "hazardous area reads as a hazard"
    assert len(set(colours.values())) == len(colours), f"two departments share a colour: {colours}"
    assert colours == {
        "engineering": "blue",
        "drafting": "violet",
        "workshop": "orange",
        "automation": "teal",
        "hazardous_area": "red",
    }


@pytest.mark.asyncio
async def test_the_catalogue_carries_every_seeded_type_in_order(session: AsyncSession) -> None:
    depts = await seeded(session)
    got = {k: [t["key"] for t in service.ordered_request_types(d)] for k, d in depts.items()}
    assert got["engineering"] == [
        "eng_only",
        "eng_and_drafting",
        "load_study",
        "cable_schedule",
        "arc_flash_study",
        "protection_settings",
        "site_survey",
        "design_review",
    ]
    assert got["drafting"] == [
        "drafting_only",
        "update_as_built",
        "ifc_issue",
        "schematics",
        "panel_layout",
        "redlines_to_as_built",
        "cable_schedule_drafting",
    ]
    assert got["workshop"] == [
        "switchboard",
        "control_panel",
        "fab_plinth_other",
        "modification_retrofit",
        "gear_tray",
        "terminal_box",
        "repair",
        "testing_only",
    ]
    assert got["automation"] == [
        "plc_programming",
        "scada",
        "fds",
        "commissioning",
        "hmi_screens",
        "network_config",
        "safety_plc",
        "software_fat",
        "other",
    ]
    assert got["hazardous_area"] == [
        "area_classification",
        "design_review",
        "inspection_dossier",
        "ex_inspection",
        "equipment_selection",
        "verification_dossier",
        "other",
    ]
    for key, dept in depts.items():
        types = service.ordered_request_types(dept)
        assert [t["position"] for t in types] == list(range(len(types))), f"{key} positions are 0..n"
        for t in types:
            assert t["active"] is True
            assert t["label"] and t["label"] != t["key"], f"{key}/{t['key']} needs a label"
            assert t["disciplines"], f"{key}/{t['key']} needs a discipline"
        # A new type reuses its department's field set rather than inventing one.
        assert len({tuple(f["key"] for f in t["fields"]) for t in types}) == 1


# ── Adding, editing, retiring, ordering ──────────────────────────────────


@pytest.mark.asyncio
async def test_a_type_is_added_with_its_key_slugged_from_the_label(ctx) -> None:
    client, _pid, _state = ctx
    await client.get(f"{BASE}/departments")  # first read seeds
    r = await client.post(
        f"{BASE}/departments/automation/request-types",
        json={
            "label": "Safety instrumented function",
            "disciplines": ["automation"],
            "fields": [{"key": "sil_rating", "label": "SIL rating", "type": "select", "options": ["1", "2", "3"]}],
        },
    )
    assert r.status_code == 201, r.text
    spec = r.json()["request_type"]
    assert spec["key"] == "safety_instrumented_function"
    assert spec["active"] is True
    assert spec["position"] == 9, "appended after the nine seeded ones"
    assert [t["key"] for t in r.json()["department"]["request_types"]][-1] == "safety_instrumented_function"

    clash = await client.post(
        f"{BASE}/departments/automation/request-types", json={"label": "Safety Instrumented Function!"}
    )
    assert clash.status_code == 409 and "safety_instrumented_function" in clash.json()["detail"]["error"]

    explicit = await client.post(
        f"{BASE}/departments/automation/request-types", json={"key": "sif_v2", "label": "Safety instrumented (v2)"}
    )
    assert explicit.status_code == 201 and explicit.json()["request_type"]["key"] == "sif_v2"

    assert (await client.post(f"{BASE}/departments/nowhere/request-types", json={"label": "x"})).status_code == 404


@pytest.mark.asyncio
async def test_a_field_spec_is_validated_before_it_lands(ctx) -> None:
    client, _pid, _state = ctx
    await client.get(f"{BASE}/departments")
    bad_type = await client.post(
        f"{BASE}/departments/workshop/request-types",
        json={"label": "Busbar run", "fields": [{"key": "length", "type": "furlong"}]},
    )
    assert bad_type.status_code == 422, "an unknown field type never reaches the service"
    no_options = await client.post(
        f"{BASE}/departments/workshop/request-types",
        json={"label": "Busbar run", "fields": [{"key": "finish", "type": "select"}]},
    )
    assert no_options.status_code == 400 and "needs options" in no_options.json()["detail"]
    bad_key = await client.post(
        f"{BASE}/departments/workshop/request-types",
        json={"label": "Busbar run", "fields": [{"key": "Length!", "type": "text"}]},
    )
    assert bad_key.status_code == 400 and "Length!".lower() in bad_key.json()["detail"].lower()
    dupe = await client.post(
        f"{BASE}/departments/workshop/request-types",
        json={
            "label": "Busbar run",
            "fields": [{"key": "length", "type": "text"}, {"key": "length", "type": "number"}],
        },
    )
    assert dupe.status_code == 400 and "duplicate field key" in dupe.json()["detail"]
    unlabelled = await client.post(f"{BASE}/departments/workshop/request-types", json={"label": "   "})
    assert unlabelled.status_code == 400


@pytest.mark.asyncio
async def test_a_type_in_use_is_retired_not_deleted(ctx) -> None:
    client, pid, _state = ctx
    await client.get(f"{BASE}/departments")
    made = await client.post(
        f"{BASE}/requests",
        json={
            "project_id": pid,
            "department": "automation",
            "request_types": ["scada", "fds"],
            "title": "MCC-02 automation package",
        },
    )
    assert made.status_code == 201, made.text

    refused = await client.delete(f"{BASE}/departments/automation/request-types/fds")
    assert refused.status_code == 409
    assert "1 request already use" in refused.json()["detail"]["error"]
    assert "set it inactive" in refused.json()["detail"]["error"]

    # Not the first of the list either - membership is what counts.
    assert (await client.delete(f"{BASE}/departments/automation/request-types/scada")).status_code == 409
    # One nothing has been raised against goes.
    gone = await client.delete(f"{BASE}/departments/automation/request-types/software_fat")
    assert gone.status_code == 200
    assert "software_fat" not in [t["key"] for t in gone.json()["department"]["request_types"]]
    assert (await client.delete(f"{BASE}/departments/automation/request-types/software_fat")).status_code == 404

    # Retiring hides it from the raise form but never from its requests.
    retired = await client.patch(f"{BASE}/departments/automation/request-types/fds", json={"active": False})
    assert retired.status_code == 200 and retired.json()["request_type"]["active"] is False
    live = (await client.get(f"{BASE}/departments")).json()["items"]
    assert "fds" not in [t["key"] for t in live[3]["request_types"]]
    every = (await client.get(f"{BASE}/departments", params={"include_inactive": "true"})).json()["items"]
    assert "fds" in [t["key"] for t in every[3]["request_types"]]

    still = (await client.get(f"{BASE}/requests/{made.json()['id']}")).json()
    assert still["request_types"] == ["scada", "fds"]
    assert still["request_type_labels"] == ["SCADA", "FDS creation"], "a retired type keeps its label where it was used"
    assert [f["key"] for f in still["field_specs"]] == ["planner_uploaded", "info_link"]

    blocked = await client.post(
        f"{BASE}/requests",
        json={"project_id": pid, "department": "automation", "request_types": ["fds"], "title": "New one"},
    )
    assert blocked.status_code == 400 and "retired" in blocked.json()["detail"]


@pytest.mark.asyncio
async def test_editing_a_type_keeps_its_key_and_reaches_the_raise_form(ctx) -> None:
    client, pid, _state = ctx
    await client.get(f"{BASE}/departments")
    r = await client.patch(
        f"{BASE}/departments/hazardous_area/request-types/ex_inspection",
        json={
            "label": "Ex inspection (detailed)",
            "disciplines": ["hazardous_area", "engineering"],
            "fields": [{"key": "grade", "label": "Inspection grade", "type": "select", "options": ["Visual", "Close"]}],
        },
    )
    assert r.status_code == 200
    spec = r.json()["request_type"]
    assert spec["key"] == "ex_inspection", "the key is fixed for life"
    assert spec["label"] == "Ex inspection (detailed)"

    made = await client.post(
        f"{BASE}/requests",
        json={
            "project_id": pid,
            "department": "hazardous_area",
            "request_types": ["ex_inspection", "area_classification"],
            "title": "Zone 2 dossier",
            "fields": {"grade": "Close", "zone": "2"},
            "cost_centres": {"engineering": "CC-300"},
        },
    )
    assert made.status_code == 201, made.text
    assert [f["key"] for f in made.json()["field_specs"]] == ["grade", "zone", "standard"]
    assert made.json()["fields"]["grade"] == "Close"
    bad = await client.post(
        f"{BASE}/requests",
        json={
            "project_id": pid,
            "department": "hazardous_area",
            "request_types": ["ex_inspection"],
            "title": "x",
            "fields": {"grade": "Sideways"},
        },
    )
    assert bad.status_code == 400 and "Inspection grade" in bad.json()["detail"]
    assert (
        await client.patch(f"{BASE}/departments/hazardous_area/request-types/nope", json={"label": "x"})
    ).status_code == 404


@pytest.mark.asyncio
async def test_the_order_endpoint_sets_the_order_and_never_drops_a_type(ctx) -> None:
    client, _pid, state = ctx
    await client.get(f"{BASE}/departments")
    r = await client.put(
        f"{BASE}/departments/workshop/request-types/order",
        json={"keys": ["repair", "switchboard", "gear_tray"]},
    )
    assert r.status_code == 200
    keys = [t["key"] for t in r.json()["request_types"]]
    assert keys[:3] == ["repair", "switchboard", "gear_tray"]
    assert set(keys) == {
        "switchboard",
        "control_panel",
        "fab_plinth_other",
        "modification_retrofit",
        "gear_tray",
        "terminal_box",
        "repair",
        "testing_only",
    }, "a stale list must never drop the types it left out"
    assert [t["position"] for t in r.json()["request_types"]] == list(range(8))
    listed = (await client.get(f"{BASE}/departments")).json()["items"][2]["request_types"]
    assert [t["key"] for t in listed][:3] == ["repair", "switchboard", "gear_tray"]

    unknown = await client.put(
        f"{BASE}/departments/workshop/request-types/order", json={"keys": ["repair", "painting"]}
    )
    assert unknown.status_code == 400 and "painting" in unknown.json()["detail"]


@pytest.mark.asyncio
async def test_the_catalogue_is_manager_only(ctx) -> None:
    client, _pid, state = ctx
    await client.get(f"{BASE}/departments")
    state["payload"] = dict(EDITOR)
    assert (await client.post(f"{BASE}/departments/workshop/request-types", json={"label": "X"})).status_code == 403
    assert (
        await client.patch(f"{BASE}/departments/workshop/request-types/repair", json={"label": "X"})
    ).status_code == 403
    assert (await client.delete(f"{BASE}/departments/workshop/request-types/repair")).status_code == 403
    assert (await client.put(f"{BASE}/departments/workshop/request-types/order", json={"keys": []})).status_code == 403
    assert (await client.get(f"{BASE}/departments")).status_code == 200, "reading is not managing"


# ── The startup reconcile ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_adds_only_what_is_missing_and_repaints_the_old_colour(session: AsyncSession) -> None:
    depts = await seeded(session)
    # An install from before this release: the old colour, none of the new
    # types, one the owner added, and one seeded type they retired.
    haz = depts["hazardous_area"]
    haz.colour = LEGACY_HAZARDOUS_AREA_COLOUR
    haz.request_types = [
        {
            "key": "area_classification",
            "label": "Area classification (our wording)",
            "disciplines": ["hazardous_area"],
            "fields": [{"key": "zone", "label": "Zone", "type": "text", "required": True}],
            "active": True,
            "position": 0,
        },
        {
            "key": "design_review",
            "label": "Design review",
            "disciplines": ["hazardous_area"],
            "fields": [],
            "active": False,
            "position": 1,
        },
        {
            "key": "dust_atmospheres",
            "label": "Dust atmospheres",
            "disciplines": ["hazardous_area"],
            "fields": [],
            "active": True,
            "position": 2,
        },
    ]
    custom = await service.create_department(session, {"key": "site_services", "name": "Site Services"})
    await service.create_request_type(session, custom, {"label": "Site attendance"})
    await session.flush()

    result = await reconcile_seeded_departments(session)

    haz = await service.department_or_error(session, "hazardous_area")
    assert haz.colour == "red", "an install still on the old seeded colour is repainted"
    assert result["recoloured"] == ["hazardous_area"]

    types = {t["key"]: t for t in service.ordered_request_types(haz, include_inactive=True)}
    assert types["area_classification"]["label"] == "Area classification (our wording)", "their wording is untouched"
    assert types["area_classification"]["fields"][0]["required"] is True
    assert types["design_review"]["active"] is False, "a retired type is never reactivated"
    assert types["dust_atmospheres"]["position"] == 2, "their own type is never moved"
    assert result["added"]["hazardous_area"] == [
        "inspection_dossier",
        "ex_inspection",
        "equipment_selection",
        "verification_dossier",
        "other",
    ]
    assert [t["key"] for t in service.ordered_request_types(haz, include_inactive=True)][:3] == [
        "area_classification",
        "design_review",
        "dust_atmospheres",
    ], "the new ones land at the END"

    after = await service.department_or_error(session, "site_services")
    assert [t["key"] for t in after.request_types] == ["site_attendance"]
    assert "site_services" not in result["added"], "a custom department is never seeded into"

    # And it is idempotent: a second run finds nothing left to do.
    again = await reconcile_seeded_departments(session)
    assert again == {"added": {}, "recoloured": []}


@pytest.mark.asyncio
async def test_reconcile_leaves_a_chosen_colour_alone(session: AsyncSession) -> None:
    depts = await seeded(session)
    depts["hazardous_area"].colour = "amber"
    await session.flush()
    result = await reconcile_seeded_departments(session)
    assert result["recoloured"] == []
    assert (await service.department_or_error(session, "hazardous_area")).colour == "amber"


@pytest.mark.asyncio
async def test_reconcile_on_an_empty_database_does_nothing(session: AsyncSession) -> None:
    assert await reconcile_seeded_departments(session) == {"added": {}, "recoloured": []}
    assert await service.list_departments(session) == []


@pytest.mark.asyncio
async def test_a_retired_type_still_reads_on_the_requests_that_use_it(session: AsyncSession) -> None:
    depts = await seeded(session)
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    req = await raise_request(
        session, project=proj, user=pm, department="workshop", request_type="gear_tray", title="Gear tray for MSB-01"
    )
    await service.update_request_type(session, depts["workshop"], "gear_tray", {"active": False})

    out = await service.payload(session, req)
    assert out["request_types"] == ["gear_tray"]
    assert out["request_type_labels"] == ["Gear tray"]
    assert [f["key"] for f in out["field_specs"]][0] == "factory_cost_centre"
    # And it is still editable - a retirement must not freeze live work.
    await service.update_request(session, req, {"title": "Gear tray, revised"}, user_id=str(pm.id), can_manage=True)
    assert req.title == "Gear tray, revised"


@pytest.mark.asyncio
async def test_the_seed_catalogue_keys_are_unique_per_department() -> None:
    for spec in DEFAULT_DEPARTMENTS:
        keys = [t["key"] for t in spec["request_types"]]
        assert len(keys) == len(set(keys)), f"{spec['key']} seeds a duplicate request type key"
        assert all(service.slugify_key(k) == k for k in keys), f"{spec['key']} seeds an unslugged key"
