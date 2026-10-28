# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Who may read and write a quality concept, over HTTP against PostgreSQL.

A stranger to the project answers 404 on every route, exactly like a missing
project. Inside a visible project a child id, an evidence row or a soft link
from elsewhere answers 404 and says nothing about the row. Reading never
writes: the concept exists only after an explicit create. Changing the plan
needs the manage permission, deciding a waiver the waive permission and a
second person. The gate evidence answers ``unknown`` rather than nothing when
the governance catalogue does not say where quality lives.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.quality_concept import evidence, hosting
from app.modules.quality_concept.models import QualityConcept
from app.modules.quality_concept.permissions import register_quality_concept_permissions
from app.modules.quality_concept.router import router
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import World, add_container, add_project, areas, build_world

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/quality-concept"
READS = ("concept", "proofs", "stages", "stage-progress", "acceptance-units", "preservation", "readiness")


@pytest_asyncio.fixture
async def world():
    register_quality_concept_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory, routes=False)


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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://qc-test") as c:
        yield c


def _p(w: World, tail: str) -> str:
    return f"{BASE}/projects/{w.project_id}/{tail}"


def _code(response) -> tuple[int, str | None]:
    detail = response.json().get("detail")
    return response.status_code, detail.get("code") if isinstance(detail, dict) else None


async def _concepts(w: World) -> int:
    async with w.factory() as s:
        stmt = select(func.count()).select_from(QualityConcept).where(QualityConcept.project_id == w.project_id)
        return (await s.execute(stmt)).scalar_one()


def _proof(evidence_type: str, **extra) -> dict:
    return {
        "package_ref": "P-01",
        "evidence_type": evidence_type,
        "required_by_kind": "date",
        "required_by_ref": "2026-12-01",
        "deliverer_role": "contractor",
        **extra,
    }


async def test_a_stranger_gets_404_on_reads_and_writes(world: World) -> None:
    async with client_as(world, world.outsider, "manager") as c:
        for path in (*READS, "validation"):
            assert (await c.get(_p(world, path))).status_code == 404, path
        assert (await c.post(_p(world, "concept"))).status_code == 404
        assert (await c.post(_p(world, "standards"), json={"code": "EN 206"})).status_code == 404
    assert await _concepts(world) == 0


async def test_reading_never_writes_and_the_plan_needs_the_manage_permission(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        # No read brings the concept into being.
        assert _code(await c.get(_p(world, "concept"))) == (404, "concept_missing")
        assert (await c.get(_p(world, "concept/catalogue"))).status_code == 200
        for path in READS[1:]:
            await c.get(_p(world, path))
        assert await _concepts(world) == 0

    async with client_as(world, world.editor, "editor") as c:
        assert _code(await c.post(_p(world, "concept"))) == (403, "manage_required")
    assert await _concepts(world) == 0

    async with client_as(world, world.manager, "manager") as c:
        made = await c.post(_p(world, "concept"))
        assert made.status_code == 201, made.text
        assert made.json()["can"] == {
            "manage": True,
            "edit_plan": True,
            "submit": False,
            "submit_reason": "concept_incomplete",
            # This project has gates: the gate approves and a change request reopens, so neither is offered here.
            "approve": False,
            "approve_reason": "approved_by_gate",
            "approve_applies": False,
            "reopen": False,
            "reopen_reason": "reopened_by_change_request",
            "reopen_applies": False,
        }
        assert _code(await c.post(_p(world, "concept"))) == (409, "concept_exists")
        patched = await c.patch(_p(world, "concept"), json={"packages": [{"ref": "P-01", "title": "Structure"}]})
        assert patched.status_code == 200, patched.text
        standard = await c.post(_p(world, "standards"), json={"code": "EN 206"})
        assert standard.status_code == 201, standard.text
        # Lists use the envelope; an explicit null on a field that cannot be null is a 422.
        listed = (await c.get(_p(world, "standards"))).json()
        assert set(listed) >= {"items", "total", "offset", "limit"}
        assert listed["total"] == 1
        nulled = await c.patch(_p(world, f"standards/{standard.json()['id']}"), json={"title": None})
        assert _code(nulled) == (422, "null_not_allowed")
        assert (await c.post(_p(world, "acceptance-units"), json={"kind": "no_such_kind"})).status_code == 422
        first = await c.post(_p(world, "proofs"), json=_proof("concrete_conformity_tests"))
        second = await c.post(_p(world, "proofs"), json=_proof("om_manual"))
        assert (first.status_code, second.status_code) == (201, 201), first.text + second.text
        first_id, second_id = first.json()["id"], second.json()["id"]

    async with client_as(world, world.editor, "editor") as c:
        # An editor reads the plan and records work, and is told why the plan is closed to them.
        seen = await c.get(_p(world, "concept"))
        assert seen.json()["can"] == {
            "manage": False,
            "edit_plan": False,
            "submit": False,
            "submit_reason": "manage_required",
            "approve": False,
            "approve_reason": "manage_required",
            "approve_applies": False,
            "reopen": False,
            "reopen_reason": "manage_required",
            "reopen_applies": False,
        }
        assert _code(await c.post(_p(world, "standards"), json={"code": "EN 1090-2"})) == (403, "manage_required")
        assert _code(await c.post(_p(world, "proofs"), json=_proof("warranty_certificate"))) == (
            403,
            "manage_required",
        )
        asked = await c.post(_p(world, f"proofs/{first_id}/waiver-request"), json={"rationale": "Supplier tested"})
        assert asked.status_code == 200, asked.text
        # Deciding a waiver is not an editor's permission, whoever asked for it.
        assert (
            await c.post(_p(world, f"proofs/{first_id}/waiver-decision"), json={"approve": True})
        ).status_code == 403
        assert (
            await c.post(_p(world, f"proofs/{second_id}/waiver-decision"), json={"approve": True})
        ).status_code == 403

    async with client_as(world, world.manager, "manager") as c:
        decided = await c.post(_p(world, f"proofs/{first_id}/waiver-decision"), json={"approve": True})
        assert decided.status_code == 200, decided.text
        assert decided.json()["decision"] == "waived"
        # Four eyes: the manager who asks cannot also decide.
        await c.post(_p(world, f"proofs/{second_id}/waiver-request"), json={"rationale": "Not issued"})
        same = await c.post(_p(world, f"proofs/{second_id}/waiver-decision"), json={"approve": True})
        assert _code(same) == (403, "approver_is_requester")


async def test_ids_from_elsewhere_are_refused_without_saying_what_they_are(world: World) -> None:
    async with world.factory() as s:
        other = await add_project(s, world.manager, [])
        foreign_document = await add_container(s, other, "foreign_manual")
        await s.commit()
    other_base = f"{BASE}/projects/{other}"
    async with client_as(world, world.manager, "manager") as c:
        for base in (other_base, f"{BASE}/projects/{world.project_id}"):
            assert (await c.post(f"{base}/concept")).status_code == 201
        await c.patch(_p(world, "concept"), json={"packages": [{"ref": "P-01", "title": "Structure"}]})

        # A child row of another project.
        made = await c.post(f"{other_base}/standards", json={"code": "EN 1090-2"})
        assert made.status_code == 201, made.text
        foreign = made.json()["id"]
        assert (await c.patch(_p(world, f"standards/{foreign}"), json={"title": "x"})).status_code == 404
        assert (await c.delete(_p(world, f"standards/{foreign}"))).status_code == 404
        assert (await c.get(f"{other_base}/standards")).json()["total"] == 1

        # Evidence from another project, and evidence of this one.
        proof = await c.post(_p(world, "proofs"), json=_proof("om_manual"))
        assert proof.status_code == 201, proof.text
        link = {"owner_kind": "proof", "owner_id": proof.json()["id"], "link_kind": "cde_document"}
        crossed = await c.post(_p(world, "evidence-links"), json={**link, "link_id": str(foreign_document)})
        assert _code(crossed) == (404, "linked_record_not_found")
        own = await c.post(
            _p(world, "evidence-links"), json={**link, "link_id": str(world.containers["business_case"])}
        )
        assert own.status_code == 201, own.text
        stray = {**link, "owner_id": str(uuid.uuid4()), "link_id": str(world.containers["business_case"])}
        assert _code(await c.post(_p(world, "evidence-links"), json=stray)) == (404, "owner_not_found")

        # Soft links are checked before they are stored.
        unknown = str(uuid.uuid4())
        refused = await c.post(_p(world, "proofs"), json=_proof("om_manual", package_ref="P-99"))
        assert _code(refused) == (422, "package_unknown")
        refused = await c.post(_p(world, "proofs"), json=_proof("om_manual", deliverer_contact_id=unknown))
        assert _code(refused) == (404, "contact_not_found")
        refused = await c.post(_p(world, "proofs"), json=_proof("om_manual", cx_system_id=unknown))
        assert _code(refused) == (404, "system_not_found")
        refused = await c.post(_p(world, "proofs"), json=_proof("om_manual", plant_item_id=unknown))
        assert _code(refused) == (422, "plant_register_unavailable")
        unit = {"kind": "total", "regime_code": "fidic_taking_over"}
        refused = await c.post(
            _p(world, "acceptance-units"), json={**unit, "preconditions": {"include_units": [unknown]}}
        )
        assert _code(refused) == (404, "included_unit_not_found")
        refused = await c.post(_p(world, "acceptance-units"), json={**unit, "schedule_activity_id": unknown})
        assert _code(refused) == (404, "schedule_activity_not_found")
        refused = await c.post(
            _p(world, "certifications"),
            json={"scheme_code": "other", "target_level": "x", "assessor_contact_id": unknown},
        )
        assert _code(refused) == (404, "contact_not_found")
        assert (await c.get(_p(world, "proofs"))).json()["total"] == 1


async def test_the_gate_evidence_never_fails_open(world: World) -> None:
    """Asked at the gate into construction, under the area that hosts quality, and nowhere else."""
    from app.modules.project_governance import public
    from app.modules.project_governance.evidence import GateAttempt

    by_code = await areas(world)
    async with world.factory() as s:
        host = await hosting.project_host(s, world.project_id)
        starts = await public.phases_enabling(s, world.project_id, hosting.CONSTRUCTION_START)
        gates = await public.project_gates(s, world.project_id)
    assert host is not None
    assert starts
    into = next(g for g in gates if g.to_phase in starts)
    elsewhere = next(g for g in gates if g.to_phase not in starts)
    other_area = next(code for code in sorted(by_code) if code != host.area_code)

    async def ask(session, gate, code: str):
        attempt = GateAttempt(gate.id, gate.code, 1)
        return await evidence.quality_readiness(session, world.project_id, attempt, by_code[code])

    async with world.factory() as s:
        # No concept yet: the hosting area answers not met with the reason; it never answers nothing.
        items = await ask(s, into, host.area_code)
        assert [(i.code, i.state, i.detail) for i in items] == [
            ("quality_concept.approved", "not_met", "quality_concept_missing")
        ]
        assert await ask(s, into, other_area) == []
        assert await ask(s, elsewhere, host.area_code) == []

    async with client_as(world, world.manager, "manager") as c:
        assert (await c.post(_p(world, "concept"))).status_code == 201

    async with world.factory() as s:
        # A draft concept is on the table: the items are answered, and none of them is met by default.
        items = {i.code: i.state for i in await ask(s, into, host.area_code)}
        assert items["quality_concept.approved"] == "not_met"
        assert items["quality_concept.complete"] == "not_met"
        assert set(items.values()) <= {"met", "not_met"}
        assert await ask(s, into, other_area) == []
        assert await ask(s, elsewhere, host.area_code) == []


async def test_a_catalogue_of_another_tenant_cannot_be_pinned_and_a_stored_pin_keeps_resolving(world: World) -> None:
    from app.modules.project_governance.catalogue_store import CatalogueStore
    from app.modules.quality_concept.catalogue import DEFAULT_CATALOGUE_ID, QUALITY_CONCEPT_KIND, register_kinds

    register_kinds()

    async def publish(tenant: uuid.UUID, code: str) -> str:
        async with world.factory() as s:
            store = CatalogueStore(s)
            row = await store.create(
                str(tenant),
                code=code,
                name=code,
                based_on_source="shipped",
                based_on_id=DEFAULT_CATALOGUE_ID,
                based_on_version=None,
                actor_id=tenant,
                kind=QUALITY_CONCEPT_KIND,
            )
            await store.publish(str(tenant), row.id, actor_id=tenant)
            await s.commit()
            return str(row.id)

    foreign = await publish(world.outsider, "foreign_quality")
    own = await publish(world.manager, "own_quality")
    async with client_as(world, world.manager, "manager") as c:
        assert (await c.post(_p(world, "concept"))).status_code == 201
        pin = {"catalogue_source": "tenant", "catalogue_version": 1}
        refused = await c.put(_p(world, "concept/catalogue"), json={**pin, "catalogue_id": foreign})
        assert _code(refused) == (404, "unknown_catalogue")
        pinned = await c.put(_p(world, "concept/catalogue"), json={**pin, "catalogue_id": own})
        assert pinned.status_code == 200, pinned.text
        assert pinned.json()["catalogue_id"] == own
    # The pin was checked when it was written: a member of the project reads the concept through it.
    async with client_as(world, world.editor, "editor") as c:
        seen = await c.get(_p(world, "concept"))
        assert seen.status_code == 200, seen.text
        assert (await c.get(_p(world, "concept/catalogue"))).status_code == 200


async def _contact(w: World, owner: uuid.UUID, company: str) -> str:
    from app.modules.contacts.models import Contact

    async with w.factory() as s:
        row = Contact(contact_type="company", company_name=company, tenant_id=str(owner), created_by=str(owner))
        s.add(row)
        await s.commit()
        return str(row.id)


async def test_the_flags_of_a_record_are_the_answers_of_its_routes(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        assert (await c.post(_p(world, "concept"))).status_code == 201
        await c.patch(_p(world, "concept"), json={"packages": [{"ref": "P-01", "title": "Structure"}]})
        standard = (await c.post(_p(world, "standards"), json={"code": "EN 206"})).json()
        assert standard["can"] == {"edit": True, "delete": True}
        asked_by_editor = (await c.post(_p(world, "proofs"), json=_proof("concrete_conformity_tests"))).json()["id"]
        asked_by_manager = (await c.post(_p(world, "proofs"), json=_proof("om_manual"))).json()["id"]
        await c.post(_p(world, f"proofs/{asked_by_manager}/waiver-request"), json={"rationale": "Not issued"})

    async with client_as(world, world.editor, "editor") as c:
        await c.post(_p(world, f"proofs/{asked_by_editor}/waiver-request"), json={"rationale": "Supplier tested"})
        rows = {r["id"]: r for r in (await c.get(_p(world, "proofs"))).json()["items"]}
        # An editor never decides a waiver, and is told which permission is missing.
        for row in rows.values():
            assert row["can"]["decide_waiver"] is False
            assert row["can_reason"]["decide_waiver"] == "waive_required"
            assert row["can_reason"]["edit"] == "manage_required"
            decided = await c.post(_p(world, f"proofs/{row['id']}/waiver-decision"), json={"approve": False})
            assert decided.status_code == 403
        listed = (await c.get(_p(world, "standards"))).json()["items"][0]
        assert listed["can"] == {"edit": False, "delete": False}
        assert listed["can_reason"] == {"edit": "manage_required", "delete": "manage_required"}

    async with client_as(world, world.manager, "manager") as c:
        rows = {r["id"]: r for r in (await c.get(_p(world, "proofs"))).json()["items"]}
        # Every flag is what the route answers: yes where it accepts, the same code where it refuses.
        assert rows[asked_by_editor]["can"]["decide_waiver"] is True
        assert rows[asked_by_manager]["can"]["decide_waiver"] is False
        assert rows[asked_by_manager]["can_reason"]["decide_waiver"] == "approver_is_requester"
        refused = await c.post(_p(world, f"proofs/{asked_by_manager}/waiver-decision"), json={"approve": True})
        assert _code(refused) == (403, "approver_is_requester")
        assert rows[asked_by_editor]["can_reason"]["accept"] == "proof_not_delivered"
        assert _code(await c.post(_p(world, f"proofs/{asked_by_editor}/accept"))) == (409, "proof_not_delivered")
        accepted = await c.post(_p(world, f"proofs/{asked_by_editor}/waiver-decision"), json={"approve": True})
        assert accepted.status_code == 200, accepted.text
        after = accepted.json()
        assert after["can"]["decide_waiver"] is False and after["can"]["reopen"] is True
        assert after["can_reason"]["decide_waiver"] == "invalid_transition"

    async with client_as(world, world.decider, "manager") as c:
        # The second manager is the other pair of eyes.
        rows = {r["id"]: r for r in (await c.get(_p(world, "proofs"))).json()["items"]}
        assert rows[asked_by_manager]["can"]["decide_waiver"] is True
        done = await c.post(_p(world, f"proofs/{asked_by_manager}/waiver-decision"), json={"approve": False})
        assert done.status_code == 200, done.text


async def test_the_catalogue_listing_offers_what_a_pin_accepts(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        before = (await c.get(_p(world, "catalogues"))).json()
        assert before["total"] >= 1
        defaults = [i for i in before["items"] if i["default"]]
        assert len(defaults) == 1
        assert not any(i["pinned"] for i in before["items"])
        assert before["can"] == {"pin": False}
        made = (await c.post(_p(world, "concept"))).json()
        # A new concept pins exactly the catalogue the listing calls the default.
        assert (made["catalogue_source"], made["catalogue_id"]) == (defaults[0]["source"], defaults[0]["id"])
        after = (await c.get(_p(world, "catalogues"))).json()
        assert [i["id"] for i in after["items"] if i["pinned"]] == [defaults[0]["id"]]
        assert after["can"] == {"pin": True}
        for item in after["items"]:
            pin = {
                "catalogue_source": item["source"],
                "catalogue_id": item["id"],
                "catalogue_version": item["latest_version"],
            }
            assert (await c.put(_p(world, "concept/catalogue"), json=pin)).status_code == 200, item
    async with client_as(world, world.editor, "editor") as c:
        assert (await c.get(_p(world, "catalogues"))).json()["can"] == {"pin": False}
    async with client_as(world, world.outsider, "manager") as c:
        assert (await c.get(_p(world, "catalogues"))).status_code == 404


async def test_reference_fields_offer_what_the_write_accepts(world: World) -> None:
    own = await _contact(world, world.manager, "Own Surveyors")
    foreign = await _contact(world, world.outsider, "Foreign Experts")
    report = {"subject": "Fire protection inspection", "trigger": "before_concealment", "frequency": "per_floor"}
    async with client_as(world, world.manager, "manager") as c:
        assert (await c.post(_p(world, "concept"))).status_code == 201
        listed = (await c.get(_p(world, "options"), params={"kind": "contact"})).json()
        assert listed["available"] is True
        assert [i["id"] for i in listed["items"]] == [own]
        assert listed["items"][0]["label"] == "Own Surveyors"
        assert (await c.get(_p(world, "options"), params={"kind": "contact", "q": "foreign"})).json()["total"] == 0
        # A contact the listing does not offer is not accepted by the write either.
        refused = await c.post(_p(world, "expert-reports"), json={**report, "expert_contact_id": foreign})
        assert _code(refused) == (404, "contact_not_found")
        made = await c.post(_p(world, "expert-reports"), json={**report, "expert_contact_id": own})
        assert made.status_code == 201, made.text
        assert made.json()["can"] == {"edit": True, "delete": True, "link_evidence": True}
        (listed_report,) = (await c.get(_p(world, "expert-reports"))).json()["items"]
        assert listed_report["expert_contact_label"] == "Own Surveyors"
        patched = await c.patch(_p(world, f"expert-reports/{made.json()['id']}"), json={"expert_contact_id": foreign})
        assert _code(patched) == (404, "contact_not_found")
        free_text = await c.post(_p(world, "expert-reports"), json={**report, "trigger": "Before the ceilings close"})
        assert free_text.status_code == 422
        # A register that offers no list says so; it does not answer an empty list.
        plant = (await c.get(_p(world, "options"), params={"kind": "plant_item"})).json()
        assert (plant["available"], plant["reason"], plant["items"]) == (False, "plant_listing_unavailable", [])
        retest = (await c.get(_p(world, "options"), params={"kind": "retest_of"})).json()
        assert (retest["available"], retest["reason"]) == (False, "owner_required")
        for kind in ("cx_system", "schedule_activity", "handover_package"):
            answer = (await c.get(_p(world, "options"), params={"kind": kind})).json()
            assert answer["available"] is True and answer["items"] == [], kind
        documents = (await c.get(_p(world, "options"), params={"kind": "certificate_document"})).json()
        assert {i["id"] for i in documents["items"]} == {str(v) for v in world.containers.values()}
        assert (await c.get(_p(world, "options"), params={"kind": "user"})).status_code == 422
    async with client_as(world, world.outsider, "manager") as c:
        assert (await c.get(_p(world, "options"), params={"kind": "contact"})).status_code == 404


async def test_a_retest_names_an_earlier_link_of_the_same_record(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        assert (await c.post(_p(world, "concept"))).status_code == 201
        # The concept names its people and its frame document beside the ids.
        concept = (await c.get(_p(world, "concept"))).json()
        assert concept["created_by"] and concept["created_by_name"].startswith("Test ")
        assert (concept["submitted_by"], concept["submitted_by_name"]) == (None, None)
        assert "governance_document" in concept
        # This project hosts quality and has its frame document: the gate can read the concept.
        assert (await c.get(_p(world, "readiness"))).json()["gate_detail"] is None
        report = (await c.post(_p(world, "expert-reports"), json={"subject": "Acoustic measurement"})).json()
        container = world.containers["business_case"]
        link = {
            "owner_kind": "expert_report",
            "owner_id": report["id"],
            "link_kind": "cde_document",
            "link_id": str(container),
        }
        stray = await c.post(_p(world, "evidence-links"), json={**link, "retest_of": str(uuid.uuid4())})
        assert _code(stray) == (404, "retest_link_not_found")
        first = await c.post(_p(world, "evidence-links"), json=link)
        assert first.status_code == 201, first.text
        offered = (
            await c.get(
                _p(world, "options"),
                params={"kind": "retest_of", "owner_kind": "expert_report", "owner_id": report["id"]},
            )
        ).json()
        assert [i["id"] for i in offered["items"]] == [first.json()["id"]]
        # A stored link says what it points to, and whether the record is still there.
        owner = {"owner_kind": "expert_report", "owner_id": report["id"]}
        (stored,) = (await c.get(_p(world, "evidence-links"), params=owner)).json()["items"]
        assert (stored["label"], stored["exists"]) == ("business_case business_case", True)


async def test_a_project_with_gates_never_approves_its_concept_by_hand(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        assert (await c.post(_p(world, "concept"))).status_code == 201
        concept = (await c.get(_p(world, "concept"))).json()
        assert concept["gates_in_use"] is True
        can = concept["can"]
        assert (can["approve"], can["approve_reason"], can["approve_applies"]) == (False, "approved_by_gate", False)
        assert (can["reopen"], can["reopen_reason"], can["reopen_applies"]) == (
            False,
            "reopened_by_change_request",
            False,
        )
        assert _code(await c.post(_p(world, "concept/approve"))) == (409, "approved_by_gate")
        reason = {"rationale": "Scope changed"}
        assert _code(await c.post(_p(world, "concept/reopen"), json=reason)) == (409, "reopened_by_change_request")
    async with client_as(world, world.outsider, "manager") as c:
        assert (await c.post(_p(world, "concept/approve"))).status_code == 404


async def test_a_project_without_gates_approves_and_reopens_its_concept_over_http(world: World) -> None:
    """Rule 26, the same walk as the service test, through the routes and the flags the screen reads."""
    from app.modules.quality_concept import schemas as s
    from app.modules.teams.models import Team, TeamMembership
    from tests.pg.governance_fixtures import add_user
    from tests.pg.test_quality_concept_flow_on_pg import _plan, _units

    async with world.factory() as session:
        p = await _plan(session)
        await _units(p)
        await p.svc.generate_proofs(p.pid, s.ProofGenerateIn(package_ref="P-01", confirm=["om_manual"]))
        second = await add_user(session, "manager")
        team = (await session.execute(select(Team).where(Team.project_id == p.pid))).scalars().first()
        session.add(TeamMembership(team_id=team.id, user_id=second))
        await session.commit()
    base = f"{BASE}/projects/{p.pid}/"

    async with client_as(world, p.manager, "manager") as c:
        concept = (await c.get(base + "concept")).json()
        assert concept["gates_in_use"] is False
        assert (concept["can"]["approve_applies"], concept["can"]["approve_reason"]) == (True, "invalid_transition")
        assert (await c.get(base + "readiness")).json()["gate_detail"] is None
        submitted = await c.post(base + "concept/submit")
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["can"]["approve_reason"] == "approver_is_submitter"
        assert _code(await c.post(base + "concept/approve")) == (403, "approver_is_submitter")
    async with client_as(world, world.outsider, "manager") as c:
        assert (await c.post(base + "concept/approve")).status_code == 404

    async with client_as(world, second, "manager") as c:
        assert (await c.get(base + "concept")).json()["can"]["approve"] is True
        approved = await c.post(base + "concept/approve")
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert (body["state"], body["can"]["approve"], body["can"]["reopen"]) == ("binding", False, True)
        last = (await c.get(base + "concept/revisions")).json()["items"][-1]
        assert (last["reason"], last["created_by"]) == ("approved", str(second))
        assert last["created_at"]
        # In force: the plan is closed until it is reopened, and reopening needs a reason.
        locked = await c.post(base + "proofs", json=_proof("warranty_certificate", package_ref="P-02"))
        assert _code(locked) == (409, "binding_requires_reopen")
        listed = (await c.get(base + "proofs")).json()["items"]
        assert {i["can_reason"].get("edit") for i in listed} == {"binding_requires_reopen"}
        assert (await c.post(base + "concept/reopen", json={})).status_code == 422
        reopened = await c.post(base + "concept/reopen", json={"rationale": "The services package was split in two"})
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["state"] == "revising"
        made = await c.post(base + "proofs", json=_proof("warranty_certificate", package_ref="P-02"))
        assert made.status_code == 201, made.text
        assert _code(await c.post(base + "concept/approve")) == (409, "invalid_transition")
