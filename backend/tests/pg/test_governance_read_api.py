# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What the governance screens read: labels, catalogue phases, caller capabilities, the matrix.

The capability test is the important one. ``can.decide`` is only honest if it
is false exactly when the decide endpoint refuses the same caller, so every
actor is asked first and then made to try.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.project_governance.events as gov_events
from app.modules.project_governance.catalogue_store import CatalogueStore
from app.modules.project_governance.permissions import register_governance_permissions
from app.modules.project_governance.router import router
from app.modules.project_governance.service import GovernanceService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import World, add_container, areas, build_world, gate, prepare_gate

pytestmark = [pytest.mark.asyncio]

BASE = "/api/v1/project-governance"
G1 = "strategy_to_brief"
NS = "governance.catalogue.neutral"


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    register_governance_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(gov_events, "async_session_factory", factory)
        w = await build_world(factory)
        w.engine = engine  # type: ignore[attr-defined]
        yield w


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


def _p(w: World) -> str:
    return f"{BASE}/projects/{w.project_id}"


# ── 1 labels ──


async def test_areas_gates_and_documents_carry_catalogue_labels(world: World) -> None:
    g = await prepare_gate(world, G1)
    async with client_as(world, world.manager, "manager") as c:
        area_items = (await c.get(f"{_p(world)}/areas")).json()["items"]
        gate_items = (await c.get(f"{_p(world)}/gates")).json()["items"]
        doc_items = (await c.get(f"{_p(world)}/documents")).json()["items"]
        detail = (await c.get(f"{_p(world)}/gates/{g.id}")).json()
    assert {a["code"]: a["name"] for a in area_items}["cost_finance"] == {
        "key": f"{NS}.area.cost_finance",
        "text": None,
    }
    assert all(a["name"]["key"] == f"{NS}.area.{a['code']}" for a in area_items)
    assert all(x["name"]["key"] == f"{NS}.gate.{x['code']}" for x in gate_items)
    assert all(d["name"]["key"] == f"{NS}.doc.{d['doc_type']}" for d in doc_items)
    by_code = {a["code"]: a for a in detail["areas"]}
    assert by_code["cost_finance"]["name"]["key"] == f"{NS}.area.cost_finance"
    cost_docs = by_code["cost_finance"]["documents"]
    assert all(d["name"]["key"] == f"{NS}.doc.{d['doc_type']}" for d in cost_docs)
    assert f"{NS}.doc.business_case" in [d["name"]["key"] for d in cost_docs]
    assert detail["gate"]["name"]["key"] == f"{NS}.gate.{G1}"


async def test_an_area_the_catalogue_no_longer_has_answers_an_empty_label(world: World) -> None:
    async with world.factory() as s:
        area = (await GovernanceService(s).repo.list_areas(world.project_id))[0]
        area.code = "gone_area"
        await s.commit()
    async with client_as(world, world.manager, "manager") as c:
        items = (await c.get(f"{_p(world)}/areas")).json()["items"]
    assert {a["code"]: a["name"] for a in items}["gone_area"] == {"key": None, "text": None}


# ── 2 catalogue phases ──


async def test_catalogue_list_items_carry_their_phases(world: World) -> None:
    tenant = str(world.manager)
    async with world.factory() as s:
        store = CatalogueStore(s)
        row = await store.create(
            tenant,
            code="house",
            name="House model",
            based_on_source="shipped",
            based_on_id="neutral",
            based_on_version=None,
            actor_id=world.manager,
        )
        await store.publish(tenant, row.id, actor_id=world.manager)
        draft = await store.create(
            tenant,
            code="draft_only",
            name="Draft",
            based_on_source="shipped",
            based_on_id="hoai_lph",
            based_on_version=None,
            actor_id=world.manager,
        )
        await s.commit()
    async with client_as(world, world.manager, "manager") as c:
        items = (await c.get(f"{BASE}/catalogues")).json()["items"]
    by_id = {i["id"]: i for i in items}
    neutral = by_id["neutral"]["phases"]
    assert [p["code"] for p in neutral][:2] == ["strategy", "brief"]
    assert neutral[0] == {"code": "strategy", "order": 1, "name": {"key": f"{NS}.phase.strategy", "text": None}}
    assert [p["code"] for p in by_id[str(row.id)]["phases"]] == [p["code"] for p in neutral]
    assert [p["code"] for p in by_id[str(draft.id)]["phases"]] == [f"lph{i}" for i in range(1, 10)]


# ── 3 capabilities ──


async def test_model_can_manage_follows_the_permission(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        mine = (await c.get(f"{_p(world)}/model")).json()["can"]
    async with client_as(world, world.editor, "editor") as c:
        theirs = (await c.get(f"{_p(world)}/model")).json()["can"]
    assert mine == {"manage": True}
    assert theirs == {"manage": False}


async def _can(w: World, gate_id: uuid.UUID, user: uuid.UUID, role: str) -> dict:
    async with client_as(w, user, role) as c:
        r = await c.get(f"{_p(w)}/gates/{gate_id}")
    assert r.status_code == 200, r.text
    return r.json()["can"]


async def _try_stop(w: World, gate_id: uuid.UUID, user: uuid.UUID, role: str) -> tuple[int, str | None]:
    async with client_as(w, user, role) as c:
        r = await c.post(f"{_p(w)}/gates/{gate_id}/decide", json={"outcome": "stop", "rationale": "probe"})
    detail = r.json().get("detail")
    code = detail.get("code") if isinstance(detail, dict) else ("missing_permission" if r.status_code == 403 else None)
    return r.status_code, code


async def test_can_decide_is_false_exactly_when_decide_is_refused(world: World) -> None:
    g = await prepare_gate(world, G1)
    # refused actors first: none of them changes state, so the gate stays in review for the next
    actors = [
        (world.editor, "editor"),  # lacks governance.decide
        (world.owner, "manager"),  # project member, not named by the route
        (world.manager, "manager"),  # project owner, not named by the route
        (world.decider, "manager"),  # entitled: the only one that succeeds
    ]
    seen: list[tuple[bool, int]] = []
    for user, role in actors:
        can = await _can(world, g.id, user, role)
        status, code = await _try_stop(world, g.id, user, role)
        assert can["decide"] is (status == 201), (role, can, status, code)
        if not can["decide"]:
            assert can["decide_reason"] == code, (can, code)
        seen.append((can["decide"], status))
    assert seen[-1] == (True, 201)
    # after the decision the gate is decided, and both sides say so the same way
    can = await _can(world, g.id, world.decider, "manager")
    status, code = await _try_stop(world, g.id, world.decider, "manager")
    assert can["decide"] is False and status == 409 and can["decide_reason"] == code


async def test_four_eyes_shows_up_in_can_decide(world: World) -> None:
    g = await prepare_gate(world, G1)
    async with world.factory() as s:
        area = (await areas(world))["risk"]
        await GovernanceService(s).update_area(
            world.project_id, area.id, changes={"owner_user_id": world.decider}, actor_id=world.manager
        )
        await s.commit()
    can = await _can(world, g.id, world.decider, "manager")
    status, code = await _try_stop(world, g.id, world.decider, "manager")
    # Named keys, not the whole dict: the gate answers more flags than the decision ones.
    assert {k: can[k] for k in ("edit", "decide", "decide_reason", "go", "go_reason")} == {
        "edit": True,
        "decide": False,
        "decide_reason": "decider_is_area_owner",
        "go": False,
        "go_reason": "decider_is_area_owner",
    }
    # Four eyes is about the person, so it closes every outcome, not only the go.
    assert can["outcomes"] and all(
        o == {"allowed": False, "reason": "decider_is_area_owner"} for o in can["outcomes"].values()
    )
    assert (status, code) == (403, "decider_is_area_owner")


async def test_can_go_reports_the_first_blocker_and_edit_follows_permission(world: World) -> None:
    g = await prepare_gate(world, G1)
    async with world.factory() as s:
        area = (await areas(world))["schedule"]
        await GovernanceService(s).update_area(
            world.project_id, area.id, changes={"owner_user_id": None}, actor_id=world.manager
        )
        await s.commit()
    can = await _can(world, g.id, world.decider, "manager")
    assert can["decide"] is True and can["go"] is False and can["go_reason"] == "area_without_owner"
    viewer = await _can(world, g.id, world.editor, "viewer")
    assert viewer["edit"] is False


# ── 4 matrix ──


async def test_matrix_shape(world: World) -> None:
    await prepare_gate(world, G1)
    async with client_as(world, world.manager, "manager") as c:
        m = (await c.get(f"{_p(world)}/matrix")).json()
    assert [x["code"] for x in m["gates"]][0] == G1
    assert m["gates"][0]["name"]["key"] == f"{NS}.gate.{G1}"
    assert m["next_gate"]["code"] == G1 and m["next_gate"]["blocker_count"] == 0
    rows = {r["code"]: r for r in m["areas"]}
    assert len(rows) == 10 and rows["cost_finance"]["owner_user_id"] == str(world.owner)
    cell = rows["cost_finance"]["cells"][G1]
    assert cell["check_status"] == "ready"
    assert cell["documents"] == [
        {
            "document_id": cell["documents"][0]["document_id"],
            "doc_type": "business_case",
            "status": "in_review",
            "required": True,
            "name": {"key": f"{NS}.doc.business_case", "text": None},
        }
    ]
    assert rows["integration"]["cells"][G1]["documents"] == []
    assert rows["integration"]["cells"]["brief_to_concept"]["check_status"] is None


async def test_matrix_counts_blockers_of_the_next_gate(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        m = (await c.get(f"{_p(world)}/matrix")).json()
    # fresh project: no owners anywhere, the business case not attached
    assert m["next_gate"]["code"] == G1 and m["next_gate"]["blocker_count"] >= 10


async def test_matrix_query_count_does_not_grow_with_documents(world: World) -> None:
    engine = world.engine  # type: ignore[attr-defined]
    counter = {"n": 0}

    def _count(*_a, **_k) -> None:
        counter["n"] += 1

    async def _measure() -> int:
        counter["n"] = 0
        event.listen(engine.sync_engine, "before_cursor_execute", _count)
        try:
            async with client_as(world, world.manager, "manager") as c:
                assert (await c.get(f"{_p(world)}/matrix")).status_code == 200
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _count)
        return counter["n"]

    await prepare_gate(world, G1)
    before = await _measure()
    async with world.factory() as s:
        # Every catalogue document type already has a row once the model is pinned, so the matrix
        # grows by linking more of them to CDE containers with revisions, not by new rows.
        svc = GovernanceService(s)
        docs = {d.doc_type: d for d in await svc.repo.list_documents(world.project_id)}
        for doc_type in ("risk_register", "quality_management_plan", "hse_plan"):
            container_id = await add_container(s, world.project_id, f"extra-{doc_type}")
            await svc.attach_container(
                world.project_id, docs[doc_type].id, container_id=container_id, actor_id=world.owner
            )
        await s.commit()
    assert await _measure() == before
    assert (await gate(world, G1)).status == "in_review"


async def test_unknown_evidence_leaves_the_go_open_and_has_to_be_named(world: World) -> None:
    from app.modules.project_governance import evidence as evd

    async def _down(session, project_id, attempt, area):
        raise RuntimeError("module is down")

    # Only this provider: on an integrated branch the modules have registered theirs.
    others = dict(evd._REGISTRY)
    evd._REGISTRY.clear()
    evd.register_evidence_provider("risk", _down, name="probe_down", blocking=True)
    try:
        g = await prepare_gate(world, G1)
        item = {"area_code": "risk", "code": "probe_down:error", "provider": "probe_down", "state": "unknown"}
        can = await _can(world, g.id, world.decider, "manager")
        assert can["go"] is True
        assert can["acknowledge"] == [item]
        async with client_as(world, world.decider, "manager") as c:
            url = f"{_p(world)}/gates/{g.id}"
            detail = (await c.get(url)).json()
            flagged = [
                (a["code"], e["code"]) for a in detail["areas"] for e in a["evidence"] if e["needs_acknowledgement"]
            ]
            assert flagged == [("risk", "probe_down:error")]
            assert detail["blockers"] == []
            silent = await c.post(f"{url}/decide", json={"outcome": "go"})
            assert silent.status_code == 422, silent.text
            assert silent.json()["detail"]["code"] == "unknown_evidence_not_acknowledged"
            assert (await gate(world, G1)).status == "in_review"
            named = await c.post(
                f"{url}/decide",
                json={"outcome": "go", "acknowledged_evidence": [{"area_code": "risk", "code": "probe_down:error"}]},
            )
            assert named.status_code == 201, named.text
            assert named.json()["snapshot"]["acknowledged_evidence"] == [item]
    finally:
        evd._REGISTRY.clear()
        evd._REGISTRY.update(others)
