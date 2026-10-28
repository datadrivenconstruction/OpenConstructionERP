# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Who may read and change a logistics plan, over HTTP against PostgreSQL.

A stranger to the project is 404 on every plan route; an id of another
project's row is 404 inside an accessible project; an editor cannot move a
transport (approve) and does not see customs values.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.site_logistics.permissions import register_site_logistics_permissions
from app.modules.site_logistics.plan_service import LogisticsPlanService
from tests._pg import isolated_engine
from tests.pg.site_logistics_fixtures import BASE, World, build_world, client_as, square, window

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


@pytest_asyncio.fixture
async def world():
    register_site_logistics_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


async def _seed_rows(w: World) -> dict:
    start, end = window(5, 8, 2)
    async with w.factory() as s:
        svc = LogisticsPlanService(s)
        stage = (await svc.stages(w.project_id))[0]
        area = await svc.create_area(
            w.project_id, {"code": "Y1", "name": "Yard", "area_kind": "storage", "geometry": square(10)}, w.manager
        )
        transport = await svc.create_transport(
            w.project_id,
            {
                "direction": "inbound",
                "transport_kind": "inbound_delivery",
                "title": "Rebar",
                "planned_window_start": start,
                "planned_window_end": end,
            },
            w.manager,
        )
        case = await svc.create_customs(
            w.project_id,
            {
                "direction": "import",
                "title": "Switchgear",
                "incoterm": "FCA",
                "transport_mode": "road",
                "customs_value": Decimal("1000.00"),
                "currency": "EUR",
            },
            w.manager,
            can_see_values=True,
        )
        await s.commit()
        return {"stage": stage.id, "area": area.id, "transport": transport.id, "case": case.id}


@pytest.mark.parametrize(
    "path",
    [
        "stages",
        "areas",
        "balance",
        "media",
        "concept",
        "transports",
        "permits",
        "customs",
        "neighbourhood",
        "neighbour-issues",
        "coordination",
        "readiness",
        "catalogue",
        "frame-summary",
    ],
)
async def test_a_stranger_gets_404_on_every_plan_list(world: World, path: str) -> None:
    async with client_as(world, world.outsider, "manager") as c:
        r = await c.get(f"{BASE}/projects/{world.project_id}/{path}")
    assert r.status_code == 404, r.text


async def test_a_stranger_cannot_write(world: World) -> None:
    async with client_as(world, world.outsider, "manager") as c:
        r = await c.post(f"{BASE}/projects/{world.project_id}/stages", json={"code": "x", "title": "X"})
    assert r.status_code == 404


async def test_ids_of_another_project_are_404(world: World) -> None:
    other = await build_world(world.factory)
    rows = await _seed_rows(other)
    pid = world.project_id
    async with client_as(world, world.manager, "manager") as c:
        responses = [
            await c.patch(f"{BASE}/projects/{pid}/stages/{rows['stage']}", json={"title": "Taken"}),
            await c.patch(f"{BASE}/projects/{pid}/areas/{rows['area']}", json={"name": "Taken"}),
            await c.get(f"{BASE}/projects/{pid}/transports/{rows['transport']}"),
            await c.post(
                f"{BASE}/projects/{pid}/transports/{rows['transport']}/transition", json={"target": "cancelled"}
            ),
            await c.get(f"{BASE}/projects/{pid}/customs/{rows['case']}"),
            await c.delete(f"{BASE}/projects/{pid}/customs/{rows['case']}"),
            await c.post(
                f"{BASE}/projects/{pid}/permits",
                json={"permit_kind": "oversize_permit", "transport_id": str(rows["transport"])},
            ),
            await c.put(
                f"{BASE}/projects/{pid}/areas/{rows['area']}/allocations",
                json={"items": [{"stage_id": str(rows["stage"]), "allocated_m2": "1"}]},
            ),
        ]
    assert [r.status_code for r in responses] == [404] * len(responses), [r.text for r in responses]
    for r in responses:
        assert r.json()["detail"]["code"].endswith("not_found")


async def test_a_stage_of_another_project_cannot_be_allocated(world: World) -> None:
    other = await build_world(world.factory)
    foreign = await _seed_rows(other)
    own = await _seed_rows(world)
    async with client_as(world, world.manager, "manager") as c:
        r = await c.put(
            f"{BASE}/projects/{world.project_id}/areas/{own['area']}/allocations",
            json={"items": [{"stage_id": str(foreign["stage"]), "allocated_m2": "1"}]},
        )
    assert r.status_code == 404


async def test_an_editor_cannot_move_a_transport_but_a_manager_can(world: World) -> None:
    rows = await _seed_rows(world)
    url = f"{BASE}/projects/{world.project_id}/transports/{rows['transport']}/transition"
    async with client_as(world, world.editor, "editor") as c:
        denied = await c.post(url, json={"target": "scheduled"})
    async with client_as(world, world.manager, "manager") as c:
        allowed = await c.post(url, json={"target": "scheduled"})
    assert denied.status_code == 403
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["state"] == "scheduled"


async def test_customs_values_are_hidden_from_an_editor(world: World) -> None:
    rows = await _seed_rows(world)
    url = f"{BASE}/projects/{world.project_id}/customs/{rows['case']}"
    async with client_as(world, world.editor, "editor") as c:
        editor_view = (await c.get(url)).json()
    async with client_as(world, world.manager, "manager") as c:
        manager_view = (await c.get(url)).json()
    assert editor_view["values_hidden"] is True and editor_view["customs_value"] is None
    assert manager_view["values_hidden"] is False and manager_view["customs_value"] == "1000.00"


async def test_list_envelope_and_coded_errors(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        listed = await c.get(f"{BASE}/projects/{world.project_id}/stages")
        bad = await c.post(f"{BASE}/projects/{world.project_id}/areas", json={"code": "Z", "area_kind": "moon_base"})
    # The envelope, and whether this caller may add a record to the list.
    assert set(listed.json()) == {"items", "total", "offset", "limit", "can"}
    assert set(listed.json()["can"]) == {"create"}
    assert bad.status_code == 422
    detail = bad.json()["detail"]
    assert detail["code"] == "unknown_area_kind"
    assert detail["message_key"] == "site_logistics.errors.unknown_area_kind"
    assert detail["message"] and "site_logistics." not in detail["message"]


async def test_links_to_rows_of_another_project_and_wrong_values_are_refused(world: World) -> None:
    """Soft links are checked like ids in the path; wrong values answer with a code, never a 500."""
    import uuid

    from app.modules.site_logistics.models import Gate

    other = await build_world(world.factory)
    foreign = await _seed_rows(other)
    own = await _seed_rows(world)
    async with other.factory() as s:
        foreign_gate = Gate(project_id=other.project_id, name="Theirs")
        s.add(foreign_gate)
        await s.commit()
    async with world.factory() as s:
        own_gate = Gate(project_id=world.project_id, name="Ours")
        s.add(own_gate)
        await s.commit()
    pid = world.project_id
    base = f"{BASE}/projects/{pid}"
    start, end = window(6, 9, 1)
    booking = {
        "project_id": str(pid),
        "gate_id": str(own_gate.id),
        "supplier_name": "Supplier",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
    }
    async with client_as(world, world.manager, "manager") as c:
        not_found = {
            "transport gate": await c.post(
                f"{base}/transports", json={"transport_kind": "inbound_delivery", "gate_id": str(foreign_gate.id)}
            ),
            "transport customs case": await c.patch(
                f"{base}/transports/{own['transport']}", json={"customs_case_id": str(foreign["case"])}
            ),
            "permit covers": await c.post(
                f"{base}/permits",
                json={"permit_kind": "oversize_permit", "covers_transport_ids": [str(foreign["transport"])]},
            ),
            "permit covers an unknown transport": await c.post(
                f"{base}/permits",
                json={"permit_kind": "oversize_permit", "covers_transport_ids": [str(uuid.uuid4())]},
            ),
            "complaint transport": await c.post(
                f"{base}/neighbour-issues", json={"kind": "noise", "transport_id": str(foreign["transport"])}
            ),
            "delivery transport": await c.post(
                f"{BASE}/deliveries/", json={**booking, "transport_id": str(foreign["transport"])}
            ),
            "delivery takt area": await c.post(
                f"{BASE}/deliveries/", json={**booking, "takt_location_id": str(uuid.uuid4())}
            ),
        }
        assert {k: r.status_code for k, r in not_found.items()} == dict.fromkeys(not_found, 404), {
            k: r.text for k, r in not_found.items()
        }

        # A link into a module that is not installed cannot be checked, so it is not stored.
        unchecked = await c.post(
            f"{base}/transports", json={"transport_kind": "inbound_delivery", "plant_item_id": str(uuid.uuid4())}
        )
        assert unchecked.status_code == 422, unchecked.text
        assert unchecked.json()["detail"]["code"] == "link_target_unavailable"
        unchecked = await c.post(f"{BASE}/deliveries/", json={**booking, "plant_item_id": str(uuid.uuid4())})
        assert unchecked.status_code == 400, unchecked.text
        assert unchecked.json()["detail"].startswith("link_target_unavailable")
        unknown_flow = await c.post(f"{BASE}/deliveries/", json={**booking, "flow_code": "no_such_flow"})
        assert unknown_flow.status_code == 400 and unknown_flow.json()["detail"].startswith("flow_code_unknown")

        # Null on a column that cannot be null, a value finer than the column, a same-state move.
        null = await c.patch(f"{base}/transports/{own['transport']}", json={"title": None})
        assert (null.status_code, null.json()["detail"]["code"]) == (422, "field_required")
        too_fine = await c.patch(f"{base}/transports/{own['transport']}", json={"gross_weight_t": "24.123"})
        assert too_fine.status_code == 422, too_fine.text
        too_large = await c.patch(f"{base}/transports/{own['transport']}", json={"gross_weight_t": "123456789.00"})
        assert too_large.status_code == 422, too_large.text
        moved = await c.post(f"{base}/transports/{own['transport']}/transition", json={"target": "scheduled"})
        assert moved.status_code == 200, moved.text
        again = await c.post(f"{base}/transports/{own['transport']}/transition", json={"target": "scheduled"})
        assert (again.status_code, again.json()["detail"]["code"]) == (409, "invalid_transition")

        # The sweep runs on the server's date: a date in the body is not accepted.
        assert (await c.post(f"{base}/sweep", json={"today": "2020-01-01"})).status_code == 422
        swept = await c.post(f"{base}/sweep", json={})
        assert swept.status_code == 200, swept.text
        assert set(swept.json()) == {"permits", "complaints_overdue", "transports_arrived"}

        # The site clock is part of the concept and comes back on a read.
        bad_zone = await c.put(f"{base}/concept", json={"site_timezone": "Mars/Olympus"})
        assert (bad_zone.status_code, bad_zone.json()["detail"]["code"]) == (422, "timezone_invalid")
        zone = await c.put(f"{base}/concept", json={"site_timezone": "Europe/Berlin"})
        assert zone.status_code == 200, zone.text
        assert (await c.get(f"{base}/concept")).json()["site_timezone"] == "Europe/Berlin"

        # An amount needs its currency, on the case and on a line.
        no_currency = await c.post(
            f"{base}/customs", json={"direction": "import", "title": "X", "incoterm": "FCA", "customs_value": "10.00"}
        )
        assert (no_currency.status_code, no_currency.json()["detail"]["code"]) == (422, "currency_required")
    async with client_as(world, world.editor, "editor") as c:
        # Reading the rule results is a read; it needs no more than the plan does.
        assert (await c.post(f"{base}/validate")).status_code == 200


async def test_a_catalogue_of_another_tenant_is_not_pinned_and_a_stored_pin_keeps_resolving(world: World) -> None:
    from app.modules.project_governance.catalogue_store import CatalogueStore
    from app.modules.site_logistics.catalogue import SITE_LOGISTICS_KIND
    from app.modules.site_logistics.errors import LogisticsError

    owner, stranger = str(world.manager), str(world.outsider)
    pid = world.project_id
    async with world.factory() as s:
        store = CatalogueStore(s)
        row = await store.create(
            owner,
            code="house",
            name="House rules",
            based_on_source="shipped",
            based_on_id="neutral",
            based_on_version=None,
            actor_id=world.manager,
            kind=SITE_LOGISTICS_KIND,
        )
        await store.publish(owner, row.id, actor_id=world.manager)
        await s.commit()
        cid = str(row.id)

    # An id from a request resolves only for the tenant that owns it, and for nobody without a tenant.
    for tenant in (stranger, None):
        async with world.factory() as s:
            with pytest.raises(LogisticsError) as exc:
                await LogisticsPlanService(s).pin_catalogue(
                    pid, tenant_id=tenant, source="tenant", catalogue_id=cid, version=1, actor_id=world.outsider
                )
            assert (exc.value.code, exc.value.status_code) == ("unknown_catalogue", 404), tenant
            await s.rollback()
    async with world.factory() as s:
        before = await LogisticsPlanService(s).concept_view(pid)
        assert (before["catalogue_source"], before["catalogue_id"]) != ("tenant", cid)
        await LogisticsPlanService(s).pin_catalogue(
            pid, tenant_id=owner, source="tenant", catalogue_id=cid, version=1, actor_id=world.manager
        )
        await s.commit()

    # The stored pin was checked when it was written: every member of the project reads the plan
    # through it, and no tenant is asked again.
    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        pinned = await svc.concept_view(pid)
        assert (pinned["catalogue_source"], pinned["catalogue_id"], pinned["catalogue_version"]) == ("tenant", cid, 1)
        assert "power" in (await svc.catalogue(pid)).codes("media_kinds")
    async with client_as(world, world.editor, "editor") as c:
        assert (await c.get(f"{BASE}/projects/{pid}/catalogue")).status_code == 200
