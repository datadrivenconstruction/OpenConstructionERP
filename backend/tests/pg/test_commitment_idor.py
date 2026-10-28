# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Who may read, link, release and decide, over HTTP against PostgreSQL; plus the API contract.

Identity is the variable under test: a stranger from another tenant, a
project member reaching for another project's document, an editor touching
the matrix, and a holder of a lower tier trying to decide a higher one.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.commitment_release.permissions import register_commitment_permissions
from app.modules.commitment_release.router import router
from tests._pg import isolated_engine
from tests.pg.commitment_fixtures import World, add_contract, build_world, item, link, request, state

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/commitment-release"


async def state_of_release(w: World, release_id: uuid.UUID):
    from app.modules.commitment_release.models import ReleaseDecision

    async with w.factory() as s:
        return await s.get(ReleaseDecision, release_id)


@pytest_asyncio.fixture
async def world():
    register_commitment_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str):
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session

    app = FastAPI()
    app.include_router(router, prefix=BASE)

    async def _session():
        async with w.factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": str(user_id),
        "role": role,
        "permissions": [],
        "tenant_id": str(user_id),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://cmt-test") as c:
        yield c


async def test_a_stranger_from_another_tenant_cannot_read_link_or_release(world: World) -> None:
    iid = await item(world, amount="10000")
    cid = await add_contract(world, "10000")
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.outsider, "manager") as c:
        listed = await c.get(f"{p}/items")
        read = await c.get(f"{p}/items/{iid}")
        linked = await c.post(f"{p}/items/{iid}/links", json={"kind": "contract", "document_id": str(cid)})
        released = await c.post(f"{p}/items/{iid}/releases", json={"amount": "10000"})
    assert [r.status_code for r in (listed, read, linked, released)] == [404, 404, 404, 404]
    assert (await state(world, iid)).status == "planned"


async def test_another_projects_document_is_404_and_is_not_linked(world: World) -> None:
    other = await build_world(world.factory)
    foreign = await add_contract(other, "10000")
    iid = await item(world, amount="10000")
    async with client_as(world, world.requester, "editor") as c:
        r = await c.post(
            f"{BASE}/projects/{world.project_id}/items/{iid}/links",
            json={"kind": "contract", "document_id": str(foreign)},
        )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "document_not_found"


async def test_an_editor_cannot_pin_the_schedule(world: World) -> None:
    async with client_as(world, world.requester, "editor") as c:
        r = await c.put(f"{BASE}/projects/{world.project_id}/matrix", json={"enforcement": "off"})
    assert r.status_code == 403


async def test_a_lower_tier_holder_cannot_decide_a_higher_tier_release(world: World) -> None:
    from app.modules.approval_routes.schemas import DecisionSubmit
    from app.modules.approval_routes.service import ApprovalRouteService

    iid = await item(world, amount="400000")
    d = await request(world, iid, "400000")
    assert d.required_tier == "sponsor"
    async with world.factory() as s:
        svc = ApprovalRouteService(s)
        inst = await svc.get_instance(d.approval_instance_id)
        step = (await svc.repo.list_steps(inst.route_id))[0]
        with pytest.raises(HTTPException) as exc:
            await svc.submit_decision(
                inst.id,
                DecisionSubmit(step_id=step.id, decision="approved", comment=None),
                approver_id=world.pm,
                caller_role="manager",
            )
    assert exc.value.status_code == 403
    assert (await state(world, iid)).status == "release_requested"


async def test_list_envelope_and_coded_validation_errors(world: World) -> None:
    await item(world, code="CR-A", amount="10000")
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.requester, "editor") as c:
        listed = await c.get(f"{p}/items")
        bad = await c.post(
            f"{p}/items",
            json={"code": "CR-B", "title": "x", "commitment_type": "no_such_type", "planned_source": "manual"},
        )
        float_amount = await c.post(f"{p}/items/{uuid.uuid4()}/releases", json={"amount": 10000.5})
    body = listed.json()
    assert {"items", "total", "offset", "limit"} <= set(body)
    assert body["total"] == 1
    assert bad.status_code == 422
    assert float_amount.status_code == 422


async def test_a_fixed_decision_date_travels_over_http_and_is_stored_as_text(world: World) -> None:
    """A ``date`` in the body must reach the VARCHAR column as ISO text: asyncpg refuses a date object there."""
    p = f"{BASE}/projects/{world.project_id}"
    body = {
        "code": "CR-D",
        "title": "Dated",
        "commitment_type": "design",
        "planned_source": "manual",
        "planned_manual_amount": "1000",
        "currency": "EUR",
        "latest_decision_date_fixed": "2026-12-01",
    }
    async with client_as(world, world.requester, "editor") as c:
        created = await c.post(f"{p}/items", json=body)
        assert created.status_code == 201, created.text
        iid = created.json()["id"]
        assert created.json()["latest_decision_date_fixed"] == "2026-12-01"
        patched = await c.patch(f"{p}/items/{iid}", json={"latest_decision_date_fixed": "2027-01-15"})
        assert patched.status_code == 200, patched.text
        cleared = await c.patch(f"{p}/items/{iid}", json={"latest_decision_date_fixed": None})
    assert patched.json()["latest_decision_date_fixed"] == "2027-01-15"
    assert patched.json()["latest_decision_date"] == "2027-01-15"
    assert cleared.status_code == 200, cleared.text
    assert (await state(world, uuid.UUID(iid))).latest_decision_date_fixed is None


async def test_a_release_request_ignores_a_date_in_the_query(world: World) -> None:
    """``?today=`` on a write is not a parameter: the decision freezes the server day, not the caller's."""
    from datetime import UTC, datetime

    iid = await item(world, code="CR-T", amount="10000", currency="GBP")
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.requester, "editor") as c:
        r = await c.post(f"{p}/items/{iid}/releases?today=2020-01-01", json={"amount": "1000", "currency": "GBP"})
    assert r.status_code == 201, r.text
    assert r.json()["fx_rate_date"] != "2020-01-01"
    # The rate is the stored one in force on the server day. It is dated after the day in the
    # query, so it could not have been chosen for that day.
    assert r.json()["fx_rate_date"] is None or r.json()["fx_rate_date"] > "2020-01-01"
    # The day the request was frozen is the server's, whatever the rate's own date says.
    stored = (await state_of_release(world, uuid.UUID(r.json()["id"]))).snapshot
    assert stored["requested_at"][:10] == datetime.now(UTC).date().isoformat()


async def test_the_item_says_what_the_caller_may_do_and_why_not(world: World) -> None:
    iid = await item(world, amount="10000")
    url = f"{BASE}/projects/{world.project_id}/items/{iid}"
    async with client_as(world, world.requester, "editor") as c:
        can = (await c.get(url)).json()["can"]
    assert can["request_release"] == {"allowed": True, "reason": None}
    assert can["decide"] == {"allowed": False, "reason": "no_pending_release"}
    assert can["transfer"] == {"allowed": False, "reason": "manage_required"}
    await request(world, iid, "10000")
    async with client_as(world, world.requester, "editor") as c:
        can = (await c.get(url)).json()["can"]
    assert can["decide"] == {"allowed": False, "reason": "four_eyes_violation"}
    assert can["withdraw"]["allowed"] is True
    async with client_as(world, world.pm, "manager") as c:
        can = (await c.get(url)).json()["can"]
    assert can["decide"] == {"allowed": True, "reason": None}
    async with client_as(world, world.sponsor, "manager") as c:
        can = (await c.get(url)).json()["can"]
    assert can["decide"] == {"allowed": False, "reason": "not_entitled_decider"}


async def test_a_tier_holder_decides_over_http_and_a_null_title_is_a_422(world: World) -> None:
    iid = await item(world, amount="10000")
    await request(world, iid, "10000")
    base = f"{BASE}/projects/{world.project_id}/items/{iid}"
    async with client_as(world, world.requester, "editor") as c:
        r = await c.patch(base, json={"title": None})
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "field_required"
        r = await c.post(f"{base}/releases/decide", json={"decision": "approved"})
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "four_eyes_violation"
    async with client_as(world, world.pm, "manager") as c:
        r = await c.post(f"{base}/releases/decide", json={"decision": "rejected"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "rationale_required"
        r = await c.post(f"{base}/releases/decide", json={"decision": "approved", "conditions": "Report first"})
        assert r.status_code == 200, r.text
        assert (r.json()["outcome"], r.json()["purpose"], r.json()["conditions"]) == (
            "released",
            "release",
            "Report first",
        )
    assert (await state(world, iid)).status == "released"


async def test_an_editor_cannot_transfer_and_an_abort_without_terms_says_why(world: World) -> None:
    iid = await item(world, amount="10000")
    other = await item(world, code="CR-9", amount="10000")
    # Money is bound, and nothing says what stopping it costs: the loss is unknown, not zero.
    await link(world, iid, "contract", await add_contract(world, "10000"))
    base = f"{BASE}/projects/{world.project_id}/items/{iid}"
    async with client_as(world, world.requester, "editor") as c:
        r = await c.post(f"{base}/transfer", json={"target_item_id": str(other), "reason": "merge"})
        assert r.status_code == 403
        r = await c.post(f"{base}/abort", json={"reason": "Scheme cancelled"})
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "abort_exposure_unknown"
        # Nothing is bound on the other item: stopping it loses nothing, and that is a request like any other.
        r = await c.post(f"{BASE}/projects/{world.project_id}/items/{other}/abort", json={"reason": "Not needed"})
        assert r.status_code == 201, r.text
        assert (r.json()["purpose"], r.json()["outcome"]) == ("abort", "pending")
        assert Decimal(r.json()["requested_amount"]) == Decimal("0")


async def test_another_tenants_schedule_does_not_resolve_from_a_request(world: World) -> None:
    """A tenant catalogue is private: its id sent by a member of another tenant answers 404, never its tiers."""
    body = {"schedule_source": "tenant", "commitment_type": "works", "amount": "250000.00"}
    async with client_as(world, world.manager, "admin") as c:
        made = await c.post(
            f"{BASE}/authority-schedules",
            json={"code": "own_rules", "name": "Own rules", "based_on_source": "shipped", "based_on_id": "neutral"},
        )
        assert made.status_code == 201, made.text
        schedule_id = made.json()["id"]
        published = await c.post(f"{BASE}/authority-schedules/{schedule_id}/publish")
        assert published.status_code == 200, published.text
        own = await c.post(f"{BASE}/authority-schedules/evaluate", json={**body, "schedule_id": schedule_id})
        assert own.status_code == 200, own.text
        assert own.json()["required_tier"] == "sponsor"
    async with client_as(world, world.outsider, "admin") as c:
        foreign = await c.post(f"{BASE}/authority-schedules/evaluate", json={**body, "schedule_id": schedule_id})
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "unknown_catalogue"


async def test_project_capabilities_and_route_states_come_from_the_server(world: World) -> None:
    from sqlalchemy import select

    from app.modules.approval_routes.models import Step

    url = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.requester, "editor") as c:
        caps = (await c.get(f"{url}/capabilities")).json()
    assert caps["matrix_exists"] is True
    assert caps["can"]["manage"] == {"allowed": False, "reason": "manage_required"}
    assert caps["can"]["add_item"] == {"allowed": True, "reason": None}
    async with client_as(world, world.requester, "viewer") as c:
        caps = (await c.get(f"{url}/capabilities")).json()
    assert caps["can"]["save_scenario"] == {"allowed": False, "reason": "edit_required"}

    iid = await item(world, amount="10000")
    async with client_as(world, world.requester, "editor") as c:
        can = (await c.get(f"{url}/items/{iid}")).json()["can"]
    assert can["defer"] == {"allowed": False, "reason": "manage_required"}
    assert can["edit_gate_fields"] == {"allowed": False, "reason": "manage_required"}
    async with client_as(world, world.requester, "editor") as c:
        refused = await c.patch(f"{url}/items/{iid}", json={"governance_area_code": "cost"})
    assert refused.status_code == 403, refused.text
    assert can["edit_gate_fields"]["reason"] in refused.text

    async with client_as(world, world.manager, "manager") as c:
        tiers = {t["code"]: t for t in (await c.get(f"{url}/matrix")).json()["tiers"]}
        assert {t["route_state"] for t in tiers.values()} == {"generated"}
        can = (await c.get(f"{url}/items/{iid}")).json()["can"]
        assert can["defer"] == {"allowed": True, "reason": None}
        assert can["edit_gate_fields"] == {"allowed": True, "reason": None}
        moved = await c.patch(f"{url}/items/{iid}", json={"governance_area_code": "cost"})
        assert moved.status_code == 200, moved.text
    async with world.factory() as s:
        step = (
            await s.execute(select(Step).where(Step.route_id == uuid.UUID(tiers["sponsor"]["route_id"])))
        ).scalar_one()
        step.sla_hours = 1
        await s.commit()
    async with client_as(world, world.manager, "manager") as c:
        tiers = {t["code"]: t["route_state"] for t in (await c.get(f"{url}/matrix")).json()["tiers"]}
    assert tiers == {"project_manager": "generated", "sponsor": "changed", "board": "generated"}


async def test_references_are_empty_lists_without_a_governance_model_and_targets_follow_access(
    world: World,
) -> None:
    from app.modules.commitment_release.service import CommitmentService
    from tests.pg.commitment_fixtures import add_project

    url = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.requester, "editor") as c:
        refs = await c.get(f"{url}/references")
    assert refs.status_code == 200, refs.text
    body = refs.json()
    # Whether the plant register is installed differs by install; a project without plant items lists none.
    assert body.pop("plant_items")["items"] == []
    assert body == {
        "has_model": False,
        "gates_in_use": False,
        "gates": [],
        "areas": [],
        "frame_documents": [],
        "funding_applications": [],
    }

    async with world.factory() as s:
        mine = await add_project(s, world.manager, [])
        theirs = await add_project(s, world.outsider, [])
        for pid, actor in ((mine, world.manager), (theirs, world.outsider)):
            await CommitmentService(s).set_matrix(pid, actor_id=actor, tenant_id=str(actor), schedule_id="neutral")
        await s.commit()
    iid = await item(world, amount="10000")
    other = await item(world, code="CR-8", amount="10000")
    async with client_as(world, world.manager, "manager") as c:
        targets = (await c.get(f"{url}/items/{iid}/transfer-targets")).json()["items"]
    assert [t["project_id"] for t in targets] == [str(world.project_id), str(mine)]
    assert targets[0]["same_project"] is True
    assert targets[0]["items"] == [{"id": str(other), "code": "CR-8", "title": "Item CR-8"}]
    assert all(t["can"] == {"allowed": True, "reason": None} for t in targets)

    cid = await add_contract(world, "10000")
    await link(world, iid, "contract", cid)
    async with client_as(world, world.manager, "manager") as c:
        targets = (await c.get(f"{url}/items/{iid}/transfer-targets")).json()["items"]
    assert [t["can"]["reason"] for t in targets] == [None, "transfer_links_stay_in_project"]


async def test_a_precondition_is_removed_over_http_by_a_manager_with_a_reason(world: World) -> None:
    from app.modules.commitment_release.service import CommitmentService

    iid = await item(world, code="CR-RP", amount="10000")
    async with world.factory() as s:
        row = await CommitmentService(s).add_precondition(
            world.project_id, iid, kind="manual", ref_id=None, text="Brief signed", actor_id=world.requester
        )
        await s.commit()
        pre = row.id
    url = f"{BASE}/projects/{world.project_id}/items/{iid}/preconditions/{pre}"
    async with client_as(world, world.requester, "editor") as c:
        refused = await c.delete(url, params={"reason": "typo"})
    assert refused.status_code == 403, refused.text
    async with client_as(world, world.manager, "manager") as c:
        no_reason = await c.delete(url)
        assert (no_reason.status_code, no_reason.json()["detail"]["code"]) == (422, "rationale_required")
        done = await c.delete(url, params={"reason": "Added by mistake"})
        assert done.status_code == 204, done.text
        again = await c.delete(url, params={"reason": "Added by mistake"})
        assert (again.status_code, again.json()["detail"]["code"]) == (404, "precondition_not_found")
    async with client_as(world, world.outsider, "manager") as c:
        foreign = await c.delete(url, params={"reason": "x"})
    assert foreign.status_code in (403, 404), foreign.text
