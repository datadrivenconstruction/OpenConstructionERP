# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Who may read and decide a gate, over HTTP against PostgreSQL; plus the API contract.

Identity is the variable under test: a stranger to the project (another
tenant), an editor, a manager who is a project member but not named by the
gate's approval route, and an area owner under four-eyes. The contract part
pins the list envelope, 404 versus 403 and coded validation errors.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.project_governance.events as gov_events
from app.modules.project_governance.permissions import register_governance_permissions
from app.modules.project_governance.router import router
from app.modules.project_governance.service import GovernanceService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import World, build_world, gate, prepare_gate

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/project-governance"
G1 = "strategy_to_brief"


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    register_governance_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(gov_events, "async_session_factory", factory)
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
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(user_id), "role": role, "permissions": []}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gov-test") as c:
        yield c


def _decide_body(outcome: str = "go") -> dict:
    return {"outcome": outcome, "rationale": "" if outcome == "go" else "because"}


async def test_a_stranger_from_another_tenant_cannot_read_or_decide(world: World) -> None:
    g = await prepare_gate(world, G1)
    async with client_as(world, world.outsider, "manager") as c:
        read = await c.get(f"{BASE}/projects/{world.project_id}/gates/{g.id}")
        listed = await c.get(f"{BASE}/projects/{world.project_id}/gates")
        decided = await c.post(f"{BASE}/projects/{world.project_id}/gates/{g.id}/decide", json=_decide_body())
    assert read.status_code == 404
    assert listed.status_code == 404
    assert decided.status_code == 404
    assert (await gate(world, G1)).status == "in_review"


async def test_a_gate_id_from_another_project_is_404_even_for_its_owner(world: World) -> None:
    other = await build_world(world.factory)
    g_other = await gate(other, G1)
    async with client_as(world, world.manager, "manager") as c:
        r = await c.get(f"{BASE}/projects/{world.project_id}/gates/{g_other.id}")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "gate_not_found"


async def test_an_editor_cannot_decide(world: World) -> None:
    g = await prepare_gate(world, G1)
    async with client_as(world, world.editor, "editor") as c:
        r = await c.post(f"{BASE}/projects/{world.project_id}/gates/{g.id}/decide", json=_decide_body())
    assert r.status_code == 403
    assert (await gate(world, G1)).status == "in_review"


async def test_a_manager_not_named_by_the_route_cannot_decide(world: World) -> None:
    g = await prepare_gate(world, G1)
    async with client_as(world, world.manager, "manager") as c:  # project owner, not the route approver
        r = await c.post(f"{BASE}/projects/{world.project_id}/gates/{g.id}/decide", json=_decide_body())
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "decider_not_entitled"


async def test_an_area_owner_cannot_decide_under_four_eyes_and_can_without(world: World) -> None:
    g = await prepare_gate(world, G1)
    async with world.factory() as s:
        svc = GovernanceService(s)
        area = (await svc.repo.list_areas(world.project_id))[0]
        await svc.update_area(
            world.project_id, area.id, changes={"deputy_user_id": world.decider}, actor_id=world.manager
        )
        await s.commit()
    async with client_as(world, world.decider, "manager") as c:
        blocked = await c.post(f"{BASE}/projects/{world.project_id}/gates/{g.id}/decide", json=_decide_body())
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "decider_is_area_owner"
        # The rule cannot be switched off for the gate it is protecting.
        off = await c.patch(f"{BASE}/projects/{world.project_id}/model", json={"four_eyes": False})
        assert (off.status_code, off.json()["detail"]["code"]) == (409, "settings_frozen_in_review")
        still = await c.post(f"{BASE}/projects/{world.project_id}/gates/{g.id}/decide", json=_decide_body())
        assert still.status_code == 403
        # Sending the value it already has is not a change, and pinning a route is not frozen.
        same = await c.patch(f"{BASE}/projects/{world.project_id}/model", json={"four_eyes": True})
        assert same.status_code == 200, same.text
    async with world.factory() as s:
        assert (await GovernanceService(s).require_model(world.project_id)).four_eyes is True


async def test_without_four_eyes_an_area_owner_decides(world: World) -> None:
    """Switched off before the gate goes to review, the rule does not apply, and the decision says so."""
    async with client_as(world, world.manager, "manager") as c:
        off = await c.patch(f"{BASE}/projects/{world.project_id}/model", json={"four_eyes": False})
        assert off.status_code == 200, off.text
    g = await prepare_gate(world, G1)
    async with world.factory() as s:
        svc = GovernanceService(s)
        area = (await svc.repo.list_areas(world.project_id))[0]
        await svc.update_area(
            world.project_id, area.id, changes={"deputy_user_id": world.decider}, actor_id=world.manager
        )
        await s.commit()
    async with client_as(world, world.decider, "manager") as c:
        ok = await c.post(f"{BASE}/projects/{world.project_id}/gates/{g.id}/decide", json=_decide_body())
    assert ok.status_code == 201, ok.text
    assert ok.json()["snapshot"]["four_eyes"] is False


async def test_an_area_is_not_taken_out_of_a_gate_that_is_being_decided(world: World) -> None:
    g = await prepare_gate(world, G1)
    async with world.factory() as s:
        area = (await GovernanceService(s).repo.list_areas(world.project_id))[0]
    url = f"{BASE}/projects/{world.project_id}/areas/{area.id}"
    async with client_as(world, world.manager, "manager") as c:
        out = await c.patch(url, json={"applicable": False, "na_rationale": "Not part of this project"})
        assert (out.status_code, out.json()["detail"]["code"]) == (409, "settings_frozen_in_review")
        # The owner may still change: that resets the area's readiness, which is visible.
        owner = await c.patch(url, json={"owner_user_id": str(world.decider)})
        assert owner.status_code == 200, owner.text
    async with world.factory() as s:
        assert (await GovernanceService(s).repo.get_area(world.project_id, area.id)).applicable is True
    assert (await gate(world, G1)).id == g.id


@pytest.mark.parametrize("field", ["applicable", "na_rationale", "name_override"])
async def test_an_explicit_null_on_an_area_field_is_refused(world: World, field: str) -> None:
    async with world.factory() as s:
        area = (await GovernanceService(s).repo.list_areas(world.project_id))[0]
    async with client_as(world, world.manager, "manager") as c:
        r = await c.patch(f"{BASE}/projects/{world.project_id}/areas/{area.id}", json={field: None})
        assert (r.status_code, r.json()["detail"]["code"]) == (422, "null_not_allowed")
        # An override is cleared with an empty string, not with null.
        cleared = await c.patch(f"{BASE}/projects/{world.project_id}/areas/{area.id}", json={"name_override": ""})
        assert cleared.status_code == 200, cleared.text


async def test_an_explicit_null_for_four_eyes_is_refused(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        r = await c.patch(f"{BASE}/projects/{world.project_id}/model", json={"four_eyes": None})
    assert (r.status_code, r.json()["detail"]["code"]) == (422, "null_not_allowed")


async def test_the_route_approver_decides_and_the_trail_exports(world: World) -> None:
    g = await prepare_gate(world, G1)
    async with client_as(world, world.decider, "manager") as c:
        r = await c.post(f"{BASE}/projects/{world.project_id}/gates/{g.id}/decide", json=_decide_body())
        assert r.status_code == 201, r.text
        again = await c.post(f"{BASE}/projects/{world.project_id}/gates/{g.id}/decide", json=_decide_body())
        assert again.status_code == 409
        pdf = await c.get(f"{BASE}/projects/{world.project_id}/export", params={"format": "pdf"})
        xlsx = await c.get(f"{BASE}/projects/{world.project_id}/export", params={"format": "xlsx"})
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


async def test_list_endpoints_answer_with_the_envelope(world: World) -> None:
    async with client_as(world, world.editor, "editor") as c:
        for path in ("areas", "gates", "documents", "conditions", "change-requests", "validation"):
            r = await c.get(f"{BASE}/projects/{world.project_id}/{path}")
            assert r.status_code == 200, (path, r.text)
            body = r.json()
            assert set(body) == {"items", "total", "offset", "limit"}, path
        cats = await c.get(f"{BASE}/catalogues")
    assert cats.status_code == 200 and cats.json()["total"] >= 1


async def test_validation_errors_carry_codes(world: World) -> None:
    g = await prepare_gate(world, G1)
    async with client_as(world, world.decider, "manager") as c:
        unknown = await c.post(f"{BASE}/projects/{world.project_id}/gates/{g.id}/decide", json={"outcome": "maybe"})
        no_reason = await c.post(
            f"{BASE}/projects/{world.project_id}/gates/{g.id}/decide", json={"outcome": "stop", "rationale": ""}
        )
    assert unknown.status_code == 422  # schema
    assert no_reason.status_code == 422
    detail = no_reason.json()["detail"]
    assert detail["code"] == "rationale_required"
    assert detail["message_key"] == "governance.errors.rationale_required"
    assert any(v["code"] == "rationale_required" for v in detail["violations"])


async def test_an_editor_who_does_not_own_the_area_cannot_attest_it(world: World) -> None:
    g = await prepare_gate(world, G1, submit=False)
    async with world.factory() as s:
        area = (await GovernanceService(s).repo.list_areas(world.project_id))[0]
    async with client_as(world, world.editor, "editor") as c:
        r = await c.put(f"{BASE}/projects/{world.project_id}/gates/{g.id}/checks/{area.id}", json={"status": "ready"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "not_area_owner"
    async with world.factory() as s:
        checks = await GovernanceService(s).repo.list_checks(g.id, g.attempt_no)
    # The refused request left the attestation of the real owner as it was.
    assert [(c.status, c.confirmed_by) for c in checks if c.area_id == area.id] == [("ready", world.owner)]


async def test_a_gate_is_not_linked_to_a_schedule_activity_of_another_project(world: World) -> None:
    """The link is a soft id, so the service has to prove the activity is this project's."""
    from tests.pg.governance_fixtures import add_activity

    other = await build_world(world.factory)
    async with world.factory() as s:
        foreign = await add_activity(s, other.project_id, "Their milestone", "2027-05-15")
        await s.commit()
    mine = await gate(world, G1)
    theirs = await gate(other, G1)
    async with client_as(world, world.manager, "manager") as c:
        linked = await c.patch(
            f"{BASE}/projects/{world.project_id}/gates/{mine.id}", json={"schedule_activity_id": str(foreign)}
        )
        unknown = await c.patch(
            f"{BASE}/projects/{world.project_id}/gates/{mine.id}", json={"schedule_activity_id": str(uuid.uuid4())}
        )
        foreign_gate = await c.patch(
            f"{BASE}/projects/{world.project_id}/gates/{theirs.id}", json={"target_date": "2027-01-01"}
        )
    assert linked.status_code == 422 and linked.json()["detail"]["code"] == "activity_not_in_project"
    assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "activity_not_in_project"
    assert foreign_gate.status_code == 404
    after = await gate(world, G1)
    assert after.schedule_activity_id is None and after.target_date == ""
    assert (await gate(other, G1)).target_date == ""
