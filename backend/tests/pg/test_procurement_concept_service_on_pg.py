# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement concept service on PostgreSQL: gate approval, binding, execution, read-back, frameworks, shortlist.

Each test is a SPEC rule or a review finding with the case that would pass if
the rule were missing.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import date

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.procurement_concept import commitments
from app.modules.procurement_concept import plan_source as plan
from app.modules.procurement_concept.errors import ProcurementError
from app.modules.procurement_concept.events import handle_frame_document, handle_read_back
from app.modules.procurement_concept.evidence import concept_ready
from app.modules.procurement_concept.models import AwardPackage, ProcurementConcept
from app.modules.procurement_concept.service import ProcurementConceptService
from app.modules.project_governance.evidence import GateAttempt
from app.modules.project_governance.public import project_areas
from tests._pg import isolated_engine
from tests.pg.procurement_concept_fixtures import (
    AREA,
    HOST_GATE,
    OTHER_AREA,
    OTHER_DOC,
    OTHER_GATE,
    RELEASE_GATE,
    UNGATED_DOC,
    World,
    add_condition,
    add_contract_package,
    add_frame_document,
    add_procurement_area,
    approve,
    bind_frame_document,
    build_world,
    drop_frame_document,
    execute,
    put,
    set_condition,
    set_delivery_form,
    svc_call,
)

TODAY = date(2026, 10, 11)

pytestmark = pytest.mark.asyncio

OPEN_WORKS = {"estimated_value": "900000", "currency": "EUR", "procedure_code": "open"}


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


async def _state(w: World, code: str) -> str:
    async with w.factory() as s:
        return (await s.get(AwardPackage, w.packages[code])).state


async def _concept(w: World) -> tuple[ProcurementConcept, str]:
    async with w.factory() as s:
        svc = ProcurementConceptService(s)
        c = await svc.get_concept(w.project_id)
        return c, await svc.effective_state(c)


async def _submit(w: World, actor: uuid.UUID | None = None, can_manage: bool = True) -> ProcurementConcept:
    return await svc_call(
        w, "transition", w.project_id, "in_review", actor_id=actor or w.manager, can_manage=can_manage
    )


@contextmanager
def _raises(code: str, status: int):
    with pytest.raises(ProcurementError) as exc:
        yield exc
    assert (exc.value.code, exc.value.status_code) == (code, status)


# ── Approval is the governance gate (findings 6, 11) ────────────────────


async def test_three_lots_above_the_threshold_keep_the_gate_closed_until_the_procedure_is_open(world: World) -> None:
    """E2E path (SPEC 8.7): 3 x 2m works lots are 6m together; a direct award is not ready for the gate."""
    for code in ("W1", "W2", "W3"):
        await add_contract_package(world, code, "construction")
        await put(world, code, {"estimated_value": "2000000", "currency": "EUR", "procedure_code": "direct_award"})
    await _submit(world)
    ready = await svc_call(world, "readiness", world.project_id)
    assert (ready["submitted"], ready["ready_for_gate"]) == (True, False)
    assert ready["blocking"] >= 3
    await svc_call(world, "transition", world.project_id, "draft", actor_id=world.manager, can_manage=True)
    for code in ("W1", "W2", "W3"):
        await put(world, code, {"procedure_code": "open"})
    await _submit(world)
    assert (await svc_call(world, "readiness", world.project_id))["ready_for_gate"] is True
    assert await bind_frame_document(world) is True
    concept, state = await _concept(world)
    assert (concept.state, state) == ("approved", "binding")


async def test_nobody_can_approve_by_hand(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    await _submit(world)
    for target in ("approved", "reopened", "binding"):
        with _raises("invalid_transition", 409):
            await svc_call(world, "transition", world.project_id, target, actor_id=world.manager, can_manage=True)
    assert (await _concept(world))[0].state == "in_review"


async def test_the_gate_decision_approves_once_and_records_who_decided(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    await add_procurement_area(world, world.area_owner)
    await _submit(world, world.area_owner, can_manage=False)
    assert await bind_frame_document(world, by=world.manager) is True
    concept, _ = await _concept(world)
    assert (concept.submitted_by, concept.approved_by) == (world.area_owner, world.manager)
    assert concept.approved_at is not None
    payload = {"project_id": str(world.project_id), "document_id": str(world.document_id), "status": "binding"}
    # A repeated event, an event of another document and a non-binding status change nothing.
    assert await handle_frame_document(payload, session_factory=world.factory) is False
    assert (
        await handle_frame_document({**payload, "document_id": str(uuid.uuid4())}, session_factory=world.factory)
        is False
    )
    assert await handle_frame_document({**payload, "status": "submitted"}, session_factory=world.factory) is False


async def test_a_binding_document_never_makes_a_draft_concept_binding(world: World) -> None:
    """Finding 11: a concept nobody submitted is not approved by a document that became binding."""
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    assert await bind_frame_document(world) is False
    concept, state = await _concept(world)
    assert (concept.state, state) == ("draft", "draft")
    assert (await svc_call(world, "readiness", world.project_id))["approved"] is False
    with _raises("concept_not_approved", 409):
        await execute(world, "W1")
    # The frame is already binding: a new concept version needs a change request, not a plain submit.
    with _raises("binding_requires_change_request", 409):
        await _submit(world)


async def test_a_document_of_another_type_does_not_approve_the_concept(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    other = await add_frame_document(world, status="binding", doc_type=OTHER_DOC)
    await _submit(world)
    payload = {"project_id": str(world.project_id), "document_id": str(other), "status": "binding"}
    assert await handle_frame_document(payload, session_factory=world.factory) is False
    assert (await _concept(world))[1] == "in_review"


async def test_without_a_binding_frame_document_a_submitted_concept_stays_in_review(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    await _submit(world)
    assert (await _concept(world))[1] == "in_review"
    with _raises("concept_not_approved", 409):
        await execute(world, "W1")
    # The project has no row for the host document at all: still in review, and nothing to approve it.
    await drop_frame_document(world)
    assert (await _concept(world))[1] == "in_review"
    with _raises("concept_not_approved", 409):
        await execute(world, "W1")


async def test_binding_concept_is_changed_only_through_a_change_request(world: World) -> None:
    from app.modules.project_governance.models import GovernanceChangeRequest

    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    await approve(world)
    assert (await _concept(world))[1] == "binding"
    with _raises("binding_requires_change_request", 409):
        await put(world, "W1", {"procedure_code": "restricted"})
    async with world.factory() as s:
        s.add(
            GovernanceChangeRequest(
                project_id=world.project_id,
                document_id=world.document_id,
                proposed_revision_id=uuid.uuid4(),
                status="submitted",
            )
        )
        await s.commit()
    assert (await _concept(world))[1] == "reopened"
    row = await put(world, "W1", {"procedure_code": "restricted"})
    assert row.procedure_code == "restricted"
    # What the gate reads stays frozen outside the first state, even for a manager.
    with _raises("gate_fields_frozen", 409):
        await svc_call(
            world,
            "set_concept",
            world.project_id,
            {"release_gate_code": OTHER_GATE},
            actor_id=world.manager,
            can_manage=True,
            tenant_id=str(world.manager),
        )


# ── Concept input (findings 1, 2, 11, 15) ───────────────────────────────


async def _set(w: World, data: dict, *, actor: uuid.UUID | None = None, can_manage: bool = True):
    return await svc_call(
        w,
        "set_concept",
        w.project_id,
        data,
        actor_id=actor or w.manager,
        can_manage=can_manage,
        tenant_id=str(w.manager),
    )


async def test_a_public_client_cannot_sit_on_a_client_type_that_switches_thresholds_off(world: World) -> None:
    with _raises("public_client_needs_client_type", 422):
        await _set(world, {"client_type": "private"})
    with _raises("client_type_not_in_jurisdiction", 422):
        await _set(world, {"client_type": "ministry"})
    with _raises("jurisdiction_not_in_catalogue", 422):
        await _set(world, {"jurisdiction": "uk"})
    concept, _ = await _concept(world)
    assert (concept.jurisdiction, concept.client_type, concept.public_client) == ("eu", "sub_central", True)
    # Declaring the client private is the honest way to no thresholds; the client type follows.
    private = await _set(world, {"public_client": False})
    assert private.client_type == "private"


async def test_a_planned_start_no_threshold_version_covers_blocks(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", {**OPEN_WORKS, "planned_start": date(2028, 3, 1)})
    found = [f for f in await svc_call(world, "findings", world.project_id) if f["ref"] == "W1"]
    gap = next(f for f in found if f["code"] == "threshold_not_available_for_date")
    assert (gap["severity"], gap["blocks_approval"]) == ("error", True)
    await put(world, "W1", {"planned_start": date(2026, 12, 1)})
    codes = {f["code"] for f in await svc_call(world, "findings", world.project_id)}
    assert "threshold_not_available_for_date" not in codes


async def test_the_release_gate_must_be_a_gate_of_the_project_and_needs_the_manage_permission(world: World) -> None:
    with _raises("release_gate_unknown", 422):
        await _set(world, {"release_gate_code": "no_such_gate"})
    await add_procurement_area(world, world.area_owner)
    with _raises("manage_required", 403):
        await _set(world, {"release_gate_code": OTHER_GATE}, actor=world.area_owner, can_manage=False)
    # The area owner still steers everything that is not a gate field.
    assert (await _set(world, {"vat_rate_pct": "19"}, actor=world.area_owner, can_manage=False)).vat_rate_pct == 19
    assert (await _set(world, {"release_gate_code": OTHER_GATE})).release_gate_code == OTHER_GATE


async def test_an_unknown_or_foreign_catalogue_cannot_be_pinned(world: World) -> None:
    with _raises("unknown_catalogue", 404):
        await _set(world, {"catalogue_source": "tenant", "catalogue_id": str(uuid.uuid4())})
    with _raises("unknown_catalogue", 404):
        await _set(world, {"catalogue_source": "shipped", "catalogue_id": "eu", "catalogue_version": 99})


async def test_a_project_whose_model_tags_no_release_gate_says_so() -> None:
    """Nothing is matched by a familiar code: with no tag and no named gate the release is unknown."""
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        await _untagged_model_says_release_unknown(await build_world(factory, tagged=False))


async def _untagged_model_says_release_unknown(world: World) -> None:
    # Same areas, documents and gates as the shipped model, same codes, no procurement tag.
    assert set(world.gates) >= {RELEASE_GATE, OTHER_GATE} and world.document_id is not None
    await add_procurement_area(world, world.area_owner)
    assert await svc_call(world, "can_steer", world.project_id, world.area_owner, False) is False
    gates = await svc_call(world, "gate_options", world.project_id)
    assert [g["tagged_release_gate"] for g in gates["items"]] == [False] * len(gates["items"])
    assert gates["resolved_release_gate_code"] is None
    # The project has gates and none of them is the release gate: that is the gap worth a warning.
    assert gates["gates_in_use"] is True
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    found = await svc_call(world, "findings", world.project_id)
    assert [(f["code"], f["severity"]) for f in found if f["ref"] == "project"] == [
        ("release_gate_unresolved", "warning")
    ]
    await _set(world, {"release_gate_code": RELEASE_GATE})
    assert "release_gate_unresolved" not in {f["code"] for f in await svc_call(world, "findings", world.project_id)}


async def _evidence(w: World, gate_code: str, area_code: str = AREA) -> list:
    async with w.factory() as s:
        area = next(a for a in await project_areas(s, w.project_id) if a.code == area_code)
        return await concept_ready(s, w.project_id, GateAttempt(w.gates[gate_code], gate_code, 1), area)


async def _from_start_world(engine, *, ungated_doc: bool = False) -> World:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    world = await build_world(factory, from_start=True, ungated_doc=ungated_doc)
    # Same areas, documents and gates as the shipped model, same codes; only the first phase enables procurement.
    assert set(world.gates) >= {RELEASE_GATE, HOST_GATE} and world.document_id is not None
    return world


async def test_a_model_that_opens_procurement_in_its_first_phase_has_no_release_gate_to_miss() -> None:
    """No gate leads into the first phase: nothing is waited for and nothing is reported unknown."""
    async with isolated_engine() as engine:
        world = await _from_start_world(engine)
        gates = await svc_call(world, "gate_options", world.project_id)
        assert gates["released_from_start"] is True
        assert gates["resolved_release_gate_code"] is None
        assert not any(g["tagged_release_gate"] or g["selected"] for g in gates["items"])
        await add_contract_package(world, "W1", "construction")
        await put(world, "W1", OPEN_WORKS)
        found = await svc_call(world, "findings", world.project_id)
        assert [f["code"] for f in found if f["ref"] == "project"] == []
        # The concept is asked for where the model asks for its document, on its area, and nowhere else.
        (item,) = await _evidence(world, HOST_GATE)
        assert (item.state, item.code) == ("not_met", f"procurement_concept_ready:{HOST_GATE}")
        assert await _evidence(world, RELEASE_GATE) == []
        assert await _evidence(world, HOST_GATE, OTHER_AREA) == []
        # A manager who names a gate decides to wait for it: the ordinary rules are back.
        await _set(world, {"release_gate_code": RELEASE_GATE})
        gates = await svc_call(world, "gate_options", world.project_id)
        assert (gates["released_from_start"], gates["resolved_release_gate_code"]) == (False, RELEASE_GATE)
        assert await _evidence(world, HOST_GATE) == []
        (item,) = await _evidence(world, RELEASE_GATE)
        assert item.state == "not_met"
        # A named gate the project does not have is "not known", never "open from the start".
        async with world.factory() as s:
            concept = await ProcurementConceptService(s).get_concept(world.project_id)
            concept.release_gate_code = "gate_of_a_model_the_project_left"
            await s.commit()
        (item,) = await _evidence(world, HOST_GATE)
        assert (item.state, item.detail) == ("unknown", "release_gate_unresolved")
        found = await svc_call(world, "findings", world.project_id)
        assert [(f["code"], f["severity"]) for f in found if f["ref"] == "project"] == [
            ("release_gate_unresolved", "warning")
        ]


async def test_open_from_the_start_without_a_host_document_is_unknown_at_whichever_gate_asks() -> None:
    """Without the document there is no gate to report at, and silence would read as "met"."""
    async with isolated_engine() as engine:
        world = await _from_start_world(engine)
        await drop_frame_document(world)
        for code in (HOST_GATE, RELEASE_GATE):
            (item,) = await _evidence(world, code)
            assert (item.state, item.detail) == ("unknown", "frame_document_unresolved")


async def _can(w: World, code: str = "W1") -> dict:
    async with w.factory() as s:
        svc = ProcurementConceptService(s)
        access = await svc.access(w.project_id, w.manager, can_edit=True, can_manage=True)
        rows = await svc.package_views(w.project_id, access=access)
    return next(r for r in rows if r["contract_package"]["code"] == code)["can"]


async def _package_codes(w: World, code: str = "W1") -> set[str]:
    return {f["code"] for f in await svc_call(w, "findings", w.project_id) if f["ref"] == code}


async def test_open_from_the_start_has_no_advance_packages() -> None:
    """Advance means ahead of the release gate. Without one the action does not exist, and a leftover blocks nothing."""
    async with isolated_engine() as engine:
        world = await _from_start_world(engine)
        await add_contract_package(world, "W1", "construction")
        await put(world, "W1", OPEN_WORKS)
        can = await _can(world)
        assert can["edit"] == {"allowed": True, "reason": None, "applies": True}
        assert can["set_advance"] == {"allowed": False, "reason": "advance_not_applicable", "applies": False}
        with pytest.raises(ProcurementError) as exc:
            await put(world, "W1", {"is_advance": True, "advance_reason": "Piling before permit"})
        assert (exc.value.code, exc.value.status_code) == (can["set_advance"]["reason"], 409)
        with pytest.raises(ProcurementError) as exc:
            await put(world, "W1", {"advance_release_kind": "commitment", "advance_release_id": str(uuid.uuid4())})
        assert (exc.value.code, exc.value.status_code) == ("advance_not_applicable", 409)
        assert (await _award(world, "W1")).is_advance is False
        # A row that carries the flag from a phase model that had a release gate.
        async with world.factory() as s:
            row = await s.get(AwardPackage, world.packages["W1"])
            row.is_advance = True
            row.advance_reason = ""
            await s.commit()
        found = await _package_codes(world)
        assert "advance_flag_not_applicable" in found
        assert not found & {"advance_package_not_released", "advance_without_reason"}
        # It can still be edited, and cleared; the note goes with the flag.
        await put(world, "W1", {"procedure_code": "open"})
        await put(world, "W1", {"is_advance": False})
        assert "advance_flag_not_applicable" not in await _package_codes(world)
        # Once a manager names a gate the project waits for it, and an advance package means something again.
        await _set(world, {"release_gate_code": RELEASE_GATE})
        assert (await _can(world))["set_advance"] == {"allowed": True, "reason": None, "applies": True}
        await put(world, "W1", {"is_advance": True, "advance_reason": "Piling before permit"})
        assert "advance_package_not_released" in await _package_codes(world)


async def _award(w: World, code: str) -> AwardPackage:
    async with w.factory() as s:
        return await s.get(AwardPackage, w.packages[code])


async def test_a_concept_carried_by_a_document_no_gate_asks_for_says_so_in_its_validation() -> None:
    """No release gate and no gate that requires the document: no decision would ever look at the concept."""
    async with isolated_engine() as engine:
        world = await _from_start_world(engine, ungated_doc=True)
        # The host document is required at a gate (governance refuses a model where it is not): no warning.
        found = await svc_call(world, "findings", world.project_id)
        assert "concept_required_at_no_gate" not in {f["code"] for f in found}
        # A manager names another document to carry the concept, one the model requires at no gate.
        ungated = await add_frame_document(world, doc_type=UNGATED_DOC)
        await _set(world, {"governance_document_id": ungated})
        found = await svc_call(world, "findings", world.project_id)
        assert [(f["code"], f["severity"], f["blocks_approval"]) for f in found if f["ref"] == "project"] == [
            ("concept_required_at_no_gate", "warning", False)
        ]
        # It is a property of the phase model, said in the validation and not as gate evidence.
        for code in (HOST_GATE, RELEASE_GATE):
            assert await _evidence(world, code) == []
        # Naming a release gate gives the concept a gate to be asked at.
        await _set(world, {"release_gate_code": RELEASE_GATE})
        found = await svc_call(world, "findings", world.project_id)
        assert [f["code"] for f in found if f["ref"] == "project"] == []
        (item,) = await _evidence(world, RELEASE_GATE)
        assert item.state == "not_met"


async def test_a_leftover_advance_flag_never_lets_a_package_start_before_the_concept_is_approved(
    matrix: _Matrix,
) -> None:
    """Even with a released commitment named on it: where no gate releases procurement nothing is in advance."""
    async with isolated_engine() as engine:
        world = await _from_start_world(engine)
        await add_contract_package(world, "S1", "supply")
        await put(world, "S1", {"estimated_value": "50000", "currency": "EUR", "procedure_code": "open"})
        released = matrix.add(world.project_id, "CR-1", released=True, lead=120)
        async with world.factory() as s:
            row = await s.get(AwardPackage, world.packages["S1"])
            row.is_advance = True
            row.advance_reason = "Long lead item"
            row.advance_release_kind, row.advance_release_id = commitments.KIND, released
            await s.commit()
        can = (await _can(world, "S1"))["create_execution"]
        assert (can["allowed"], can["reason"]) == (False, "concept_not_approved")
        with pytest.raises(ProcurementError) as exc:
            await execute(world, "S1")
        assert (exc.value.code, exc.value.status_code) == ("concept_not_approved", 409)


async def test_a_concept_with_a_blocking_finding_is_not_approved_by_hand() -> None:
    """The same bar the gate evidence sets: submitted, and nothing that blocks."""
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        world = await build_world(factory, model=False)
        await add_contract_package(world, "W1", "construction")
        # An advance package nothing released is an error on any project.
        await put(world, "W1", {**OPEN_WORKS, "is_advance": True, "advance_reason": "Piling before permit"})
        await svc_call(world, "transition", world.project_id, "in_review", actor_id=world.manager, can_manage=True)
        with pytest.raises(ProcurementError) as exc:
            await svc_call(world, "approve_by_hand", world.project_id, actor_id=world.editor, can_manage=True)
        assert (exc.value.code, exc.value.status_code) == ("concept_has_blocking_findings", 422)
        assert "advance_package_not_released" in {v["code"] for v in exc.value.violations}
        concept, state = await _concept(world)
        assert (state, concept.approved_by, concept.approved_at) == ("in_review", None, None)
        # Taken back, corrected and submitted again, the second person approves it.
        await svc_call(world, "transition", world.project_id, "draft", actor_id=world.manager, can_manage=True)
        await put(world, "W1", {"is_advance": False})
        await svc_call(world, "transition", world.project_id, "in_review", actor_id=world.manager, can_manage=True)
        await svc_call(world, "approve_by_hand", world.project_id, actor_id=world.editor, can_manage=True)
        concept, state = await _concept(world)
        assert (state, concept.approved_by) == ("approved", world.editor)
        assert concept.approved_at is not None


# ── Plan and steering ───────────────────────────────────────────────────


async def test_every_contract_package_needs_an_award_package_before_review(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    await add_contract_package(world, "PA", "project_agreement")
    with pytest.raises(ProcurementError) as exc:
        await _submit(world)
    assert [v["ref"] for v in exc.value.violations] == ["W1"]
    await put(world, "W1", {"estimated_value": "100000", "currency": "EUR", "procedure_code": "open"})
    with _raises("package_kind_not_procured", 422):
        await put(world, "PA", {"procedure_code": "open"})
    assert (await _submit(world)).state == "in_review"
    with _raises("concept_locked", 409):
        await put(world, "W1", {"procedure_code": "restricted"})
    with _raises("concept_locked", 409):
        await svc_call(
            world,
            "set_package_state",
            world.project_id,
            world.packages["W1"],
            "hold",
            actor_id=world.manager,
            can_manage=True,
        )


async def test_an_editor_who_does_not_own_the_procurement_area_cannot_steer(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    with _raises("not_procurement_owner", 403):
        await put(world, "W1", {"procedure_code": "open"}, actor=world.editor, can_manage=False)
    # Owning another area of the project gives no rights here.
    await add_procurement_area(world, world.editor, code=OTHER_AREA)
    with _raises("not_procurement_owner", 403):
        await put(world, "W1", {"procedure_code": "open"}, actor=world.editor, can_manage=False)
    await add_procurement_area(world, world.area_owner)
    row = await put(
        world,
        "W1",
        {"estimated_value": "1", "currency": "EUR", "procedure_code": "open"},
        actor=world.area_owner,
        can_manage=False,
    )
    assert row.state == "procedure_set"
    with _raises("not_procurement_owner", 403):
        await _submit(world, world.editor, can_manage=False)
    caps = await svc_call(world, "capabilities", world.project_id, world.editor, False)
    assert caps["submit"] == {"allowed": False, "reason": "not_procurement_owner", "applies": True}
    owner_caps = await svc_call(world, "capabilities", world.project_id, world.area_owner, False)
    assert owner_caps["submit"] == {"allowed": True, "reason": None, "applies": True}
    assert owner_caps["set_gate_fields"] == {"allowed": False, "reason": "manage_required", "applies": True}
    assert (await _submit(world, world.area_owner, can_manage=False)).state == "in_review"


async def test_an_amount_needs_a_currency(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    with _raises("currency_required", 422):
        await put(world, "W1", {"estimated_value": "100000", "procedure_code": "open"})
    with _raises("currency_required", 422):
        await put(world, "W1", {"estimated_value": "100000", "currency": "", "procedure_code": "open"})
    async with world.factory() as s:
        assert await s.get(AwardPackage, world.packages["W1"]) is None


async def test_advance_package_without_reason_is_rejected(world: World) -> None:
    await add_contract_package(world, "S1", "supply")
    with _raises("advance_without_reason", 422):
        await put(world, "S1", {"is_advance": True})


# ── Execution (findings 5, 12) ──────────────────────────────────────────


async def test_execution_needs_an_approved_concept(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    with _raises("concept_not_approved", 409):
        await execute(world, "W1")
    await approve(world)
    assert (await execute(world, "W1"))["kind"] == "bid_package"


async def test_only_a_cleared_condition_of_the_release_gate_releases_an_advance_package(world: World) -> None:
    await add_contract_package(world, "S1", "supply")
    foreign = await add_condition(world, OTHER_GATE, status="cleared")
    own = await add_condition(world, RELEASE_GATE, status="open")
    base = {
        "estimated_value": "50000",
        "currency": "EUR",
        "procedure_code": "request_for_quotation",
        "is_advance": True,
        "advance_reason": "Fabrication slot",
        "advance_release_kind": "condition",
    }
    with _raises("advance_release_other_gate", 422):
        await put(world, "S1", {**base, "advance_release_id": foreign})
    with _raises("advance_release_not_found", 404):
        await put(world, "S1", {**base, "advance_release_id": uuid.uuid4()})
    await put(world, "S1", {**base, "advance_release_id": own})
    for status in ("open", "overdue", "waived"):
        await set_condition(world, own, status)
        codes = {f["code"] for f in await svc_call(world, "findings", world.project_id) if f["ref"] == "S1"}
        assert "advance_package_not_released" in codes, status
        with _raises("concept_not_approved", 409):
            await execute(world, "S1")
    await set_condition(world, own, "cleared")
    codes = {f["code"] for f in await svc_call(world, "findings", world.project_id) if f["ref"] == "S1"}
    assert "advance_package_not_released" not in codes
    # The concept is still a draft: the released advance package alone may go out.
    assert (await execute(world, "S1"))["kind"] == "rfq"


async def test_a_package_with_an_error_finding_gets_no_execution_vehicle(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    cond = await add_condition(world, RELEASE_GATE, status="cleared")
    await put(
        world,
        "W1",
        {
            "estimated_value": "6000000",
            "currency": "EUR",
            "procedure_code": "direct_award",
            "is_advance": True,
            "advance_reason": "Enabling works",
            "advance_release_kind": "condition",
            "advance_release_id": cond,
        },
    )
    with pytest.raises(ProcurementError) as exc:
        await execute(world, "W1")
    assert (exc.value.code, exc.value.status_code) == ("package_has_blocking_findings", 422)
    assert "procedure_not_allowed_above_threshold" in {v["code"] for v in exc.value.violations}
    await put(world, "W1", {"procedure_code": "open"})
    assert (await execute(world, "W1"))["kind"] == "bid_package"


async def test_execution_creates_exactly_one_bid_package_and_reads_back_idempotently(world: World) -> None:
    from app.modules.bid_management.models import BidPackage

    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    await approve(world)
    out = await execute(world, "W1")
    assert out["kind"] == "bid_package"
    with _raises("execution_exists", 409):
        await execute(world, "W1")
    async with world.factory() as s:
        n = (
            await s.execute(
                sa.select(sa.func.count()).select_from(BidPackage).where(BidPackage.project_id == world.project_id)
            )
        ).scalar_one()
    assert n == 1
    event = {"package_id": out["id"]}
    for _ in range(2):
        assert (
            await handle_read_back("bid_management.package.published", event, session_factory=world.factory)
            == "in_tender"
        )
    assert await handle_read_back("bid_management.package.awarded", event, session_factory=world.factory) == "awarded"
    # A late publish never moves an awarded package back.
    await handle_read_back("bid_management.package.published", event, session_factory=world.factory)
    assert await _state(world, "W1") == "awarded"


async def test_execution_events_reach_the_package_through_the_event_bus(world: World, monkeypatch) -> None:
    """The subscription itself, not the handler called by hand: publish, and the package moves."""
    import app.modules.procurement_concept.events as pc_events
    from app.core.events import event_bus

    monkeypatch.setattr(pc_events, "async_session_factory", world.factory)
    pc_events.register_procurement_concept_subscribers()
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    await approve(world)
    out = await execute(world, "W1")
    await event_bus.publish("bid_management.package.published", {"package_id": out["id"]})
    assert await _state(world, "W1") == "in_tender"
    # An event about a vehicle this module did not create moves nothing.
    await event_bus.publish("bid_management.package.awarded", {"package_id": str(uuid.uuid4())})
    assert await _state(world, "W1") == "in_tender"
    await event_bus.publish("bid_management.package.awarded", {"package_id": out["id"]})
    assert await _state(world, "W1") == "awarded"


async def test_supply_package_creates_an_rfq_never_a_bid_package(world: World) -> None:
    from app.modules.bid_management.models import BidPackage
    from app.modules.rfq_bidding.models import RFQ

    await add_contract_package(world, "S1", "supply")
    await put(world, "S1", {"estimated_value": "50000", "currency": "EUR", "procedure_code": "request_for_quotation"})
    await approve(world)
    out = await execute(world, "S1")
    assert out["kind"] == "rfq"
    async with world.factory() as s:
        rfqs = (
            await s.execute(sa.select(sa.func.count()).select_from(RFQ).where(RFQ.project_id == world.project_id))
        ).scalar_one()
        bps = (
            await s.execute(
                sa.select(sa.func.count()).select_from(BidPackage).where(BidPackage.project_id == world.project_id)
            )
        ).scalar_one()
        link = (
            await s.execute(
                sa.select(plan.PACKAGE_TABLE.c.link_kind).where(plan.PACKAGE_TABLE.c.id == world.packages["S1"])
            )
        ).scalar_one()
    assert (rfqs, bps, link) == (1, 0, "rfq")
    assert await handle_read_back("rfq.awarded", {"rfq_id": out["id"]}, session_factory=world.factory) == "awarded"


async def test_concurrent_execution_creation_ends_with_one_link(world: World) -> None:
    from app.modules.bid_management.models import BidPackage

    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    await approve(world)

    async def create() -> str:
        try:
            await execute(world, "W1")
            return "ok"
        except ProcurementError as exc:
            return exc.code

    results = sorted(await asyncio.gather(create(), create()))
    assert results == ["execution_exists", "ok"]
    async with world.factory() as s:
        n = (
            await s.execute(
                sa.select(sa.func.count()).select_from(BidPackage).where(BidPackage.project_id == world.project_id)
            )
        ).scalar_one()
    assert n == 1


async def test_an_existing_tender_package_of_the_project_can_be_linked_once(world: World) -> None:
    from app.modules.tendering.models import TenderPackage

    other = await build_world(world.factory, concept=False)
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    async with world.factory() as s:
        own = TenderPackage(project_id=world.project_id, name="Own tender")
        foreign = TenderPackage(project_id=other.project_id, name="Foreign tender")
        s.add_all([own, foreign])
        await s.commit()

    async def link(tender_id: uuid.UUID) -> dict:
        return await svc_call(
            world,
            "link_tender_package",
            world.project_id,
            world.packages["W1"],
            tender_id,
            actor_id=world.manager,
            can_manage=True,
        )

    with _raises("tender_package_not_found", 404):
        await link(foreign.id)
    with _raises("concept_not_approved", 409):
        await link(own.id)
    await approve(world)
    assert (await link(own.id))["kind"] == plan.LINK_TENDER_PACKAGE
    with _raises("execution_exists", 409):
        await execute(world, "W1")


async def test_a_package_already_in_tender_is_not_judged_by_its_planning_dates_again(world: World) -> None:
    """Finding 8: time passing must not turn a tendered package into a blocker of a later re-approval."""
    for code in ("W1", "W2"):
        await add_contract_package(world, code, "construction")
        await put(world, code, {**OPEN_WORKS, "need_date": date(2027, 6, 30)})
    await approve(world)
    out = await execute(world, "W1")
    await handle_read_back("bid_management.package.published", {"package_id": out["id"]}, session_factory=world.factory)
    assert await _state(world, "W1") == "in_tender"
    later = await svc_call(world, "findings", world.project_id, today=date(2030, 1, 1))
    late = {f["ref"] for f in later if f["code"] == "award_schedule_infeasible"}
    assert late == {"W2"}


# ── Races answer 409, never 500 (finding 14) ────────────────────────────


async def test_two_first_writes_of_a_concept_or_a_package_end_with_one_row(world: World) -> None:
    other = await build_world(world.factory, concept=False)
    await add_contract_package(world, "W1", "construction")

    async def first_concept() -> str:
        try:
            await svc_call(
                other,
                "set_concept",
                other.project_id,
                {"catalogue_source": "shipped", "catalogue_id": "neutral"},
                actor_id=other.manager,
                can_manage=True,
                tenant_id=str(other.manager),
            )
            return "ok"
        except ProcurementError as exc:
            return f"{exc.status_code}"

    async def first_package() -> str:
        try:
            await put(world, "W1", OPEN_WORKS)
            return "ok"
        except ProcurementError as exc:
            return f"{exc.status_code}"

    concepts = await asyncio.gather(*(first_concept() for _ in range(4)))
    packages = await asyncio.gather(*(first_package() for _ in range(4)))
    assert set(concepts) <= {"ok", "409"} and "ok" in concepts
    assert set(packages) <= {"ok", "409"} and "ok" in packages
    async with world.factory() as s:
        n = (
            await s.execute(
                sa.select(sa.func.count())
                .select_from(ProcurementConcept)
                .where(ProcurementConcept.project_id == other.project_id)
            )
        ).scalar_one()
    assert n == 1


async def test_moving_a_candidate_onto_a_company_already_listed_is_a_conflict(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    a, b = await _subs(world, 2)
    await _add(world, "W1", {"subcontractor_id": a.id})
    second = await _add(world, "W1", {"subcontractor_id": b.id})
    with _raises("candidate_exists", 409):
        await svc_call(
            world,
            "patch_candidate",
            world.project_id,
            second.id,
            {"subcontractor_id": a.id},
            actor_id=world.manager,
            can_manage=True,
        )


# ── Frameworks (findings 7, 19) ─────────────────────────────────────────


async def _framework(w: World, code: str, *, max_value: str = "500000", currency: str = "EUR", tenant=None):
    tenant = tenant or str(w.manager)
    async with w.factory() as s:
        svc = ProcurementConceptService(s)
        fw = await svc.create_framework(
            tenant,
            {
                "code": code,
                "title": "Rebar",
                "package_kinds": ["supply"],
                "lots": [],
                "max_value": max_value,
                "currency": currency,
                "start_date": date(2026, 1, 1),
                "end_date": date(2028, 12, 31),
            },
            actor_id=w.manager,
        )
        await svc.transition_framework(tenant, fw.id, "active", actor_id=w.manager)
        await s.commit()
        return fw


def _call_off(fw, value: str = "300000", currency: str = "EUR") -> dict:
    return {
        "estimated_value": value,
        "currency": currency,
        "procedure_code": "framework_call_off",
        "framework_agreement_id": fw.id,
    }


async def test_framework_call_off_ledger_and_exhaustion(world: World) -> None:
    tenant = str(world.manager)
    fw = await _framework(world, "FW-1")
    await add_contract_package(world, "S1", "supply")
    await add_contract_package(world, "S2", "supply")
    await put(world, "S1", _call_off(fw))
    with _raises("framework_exhausted", 422):
        await put(world, "S2", _call_off(fw))
    ledger = await svc_call(world, "ledger", tenant, fw.id)
    assert (ledger["call_off_value"], ledger["remaining_value"], ledger["remaining_known"]) == (
        "300000.00",
        "200000.00",
        True,
    )
    # Another company cannot see or call off this framework.
    with _raises("framework_not_found", 404):
        await svc_call(world, "ledger", str(uuid.uuid4()), fw.id)


async def test_a_framework_in_another_currency_cannot_be_called_off(world: World) -> None:
    fw = await _framework(world, "FW-USD", currency="USD")
    await add_contract_package(world, "S1", "supply")
    with _raises("framework_currency_mismatch", 422):
        await put(world, "S1", _call_off(fw, "100"))
    async with world.factory() as s:
        assert await s.get(AwardPackage, world.packages["S1"]) is None


async def test_a_project_member_calls_off_the_framework_of_the_projects_company(world: World) -> None:
    """Finding 19: the tenant is the user on shipped installs; the framework belongs to the project's company."""
    fw = await _framework(world, "FW-1")
    await add_procurement_area(world, world.area_owner)
    await add_contract_package(world, "S1", "supply")
    async with world.factory() as s:
        row = await ProcurementConceptService(s).put_package(
            world.project_id,
            world.packages["S1"],
            _call_off(fw),
            actor_id=world.area_owner,
            can_manage=False,
            tenant_id=str(world.area_owner),
        )
        await s.commit()
    assert row.framework_agreement_id == fw.id
    listed = await svc_call(world, "project_frameworks", world.project_id, str(world.area_owner))
    assert [f.id for f in listed] == [fw.id]
    # Their own company list stays empty, and so does a stranger's view of the project list.
    assert await svc_call(world, "list_frameworks", str(world.area_owner)) == []


async def test_a_purchase_order_of_another_company_does_not_consume_the_framework(world: World) -> None:
    from app.modules.procurement.models import PurchaseOrder

    other = await build_world(world.factory, concept=False)
    fw = await _framework(world, "FW-1")
    meta = {"framework_agreement_id": str(fw.id)}
    async with world.factory() as s:
        s.add(
            PurchaseOrder(
                project_id=other.project_id,
                po_number="PO-FOREIGN",
                amount_subtotal="450000",
                currency_code="EUR",
                metadata_=meta,
            )
        )
        s.add(
            PurchaseOrder(
                project_id=world.project_id,
                po_number="PO-OWN",
                amount_subtotal="120000",
                currency_code="EUR",
                metadata_=meta,
            )
        )
        await s.commit()
    ledger = await svc_call(world, "ledger", str(world.manager), fw.id)
    assert [(e["kind"], e["amount"]) for e in ledger["items"]] == [("purchase_order", "120000")]
    assert ledger["remaining_value"] == "380000.00"


async def test_a_ledger_entry_in_another_currency_makes_the_remainder_unknown(world: World) -> None:
    from app.modules.procurement.models import PurchaseOrder

    fw = await _framework(world, "FW-1")
    async with world.factory() as s:
        s.add(
            PurchaseOrder(
                project_id=world.project_id,
                po_number="PO-USD",
                amount_subtotal="10",
                currency_code="USD",
                metadata_={"framework_agreement_id": str(fw.id)},
            )
        )
        await s.commit()
    ledger = await svc_call(world, "ledger", str(world.manager), fw.id)
    assert (ledger["remaining_value"], ledger["remaining_known"], ledger["unconverted_entries"]) == (None, False, 1)
    await add_contract_package(world, "S1", "supply")
    with _raises("framework_remaining_unknown", 422):
        await put(world, "S1", _call_off(fw, "100"))


async def test_framework_changes_keep_its_ledger_consistent(world: World) -> None:
    tenant = str(world.manager)
    fw = await _framework(world, "FW-1")
    await add_contract_package(world, "S1", "supply")
    await put(world, "S1", _call_off(fw))
    with _raises("framework_max_below_call_off", 422):
        await svc_call(world, "patch_framework", tenant, fw.id, {"max_value": "299999"}, actor_id=world.manager)
    with _raises("framework_dates_inverted", 422):
        await svc_call(world, "patch_framework", tenant, fw.id, {"end_date": date(2025, 1, 1)}, actor_id=world.manager)
    ok = await svc_call(world, "patch_framework", tenant, fw.id, {"max_value": "300000"}, actor_id=world.manager)
    assert ok.max_value == 300000


# ── Prequalification (finding 13) ───────────────────────────────────────


async def _subs(w: World, n: int) -> list:
    from app.modules.subcontractors.models import Subcontractor

    async with w.factory() as s:
        subs = [Subcontractor(legal_name=f"Trade contractor {uuid.uuid4().hex[:6]}") for _ in range(n)]
        s.add_all(subs)
        await s.commit()
    return subs


async def _add(w: World, code: str, data: dict, *, actor: uuid.UUID | None = None, can_manage: bool = True):
    return await svc_call(
        w, "add_candidate", w.project_id, w.packages[code], data, actor_id=actor or w.manager, can_manage=can_manage
    )


async def test_shortlist_needs_min_bidders_and_rationale_for_exclusions(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", {**OPEN_WORKS, "procedure_code": "competitive_negotiated"})
    subs = await _subs(world, 4)
    pkg = world.packages["W1"]
    for sub in subs[:2]:
        await _add(world, "W1", {"subcontractor_id": sub.id, "list": "short"})
    with pytest.raises(ProcurementError) as exc:
        await svc_call(world, "confirm_shortlist", world.project_id, pkg, actor_id=world.manager, can_manage=True)
    assert "shortlist_below_min_bidders" in {v["code"] for v in exc.value.violations}
    with _raises("excluded_candidate_without_rationale", 422):
        await _add(world, "W1", {"subcontractor_id": subs[3].id, "list": "excluded"})
    await _add(world, "W1", {"subcontractor_id": subs[2].id, "list": "short"})
    row = await svc_call(world, "confirm_shortlist", world.project_id, pkg, actor_id=world.manager, can_manage=True)
    assert row.state == "shortlisted"
    # The short list was confirmed for a minimum of three; another procedure has another minimum.
    changed = await put(world, "W1", {"procedure_code": "restricted"})
    assert changed.state == "procedure_set"


async def test_list_changes_and_deletes_need_steering_rights(world: World) -> None:
    from app.modules.procurement_concept.models import BidderCandidate

    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    subs = await _subs(world, 2)
    editor = {"actor": world.editor, "can_manage": False}
    cand = await _add(world, "W1", {"subcontractor_id": subs[0].id, "list": "long"}, **editor)
    with _raises("not_procurement_owner", 403):
        await _add(world, "W1", {"subcontractor_id": subs[1].id, "list": "short"}, **editor)
    for change in ({"list": "short"}, {"list": "excluded", "decision_rationale": "No capacity"}):
        with _raises("not_procurement_owner", 403):
            await svc_call(
                world, "patch_candidate", world.project_id, cand.id, change, actor_id=world.editor, can_manage=False
            )
    with _raises("not_procurement_owner", 403):
        await svc_call(world, "delete_candidate", world.project_id, cand.id, actor_id=world.editor, can_manage=False)
    # Data entry stays open to the editor.
    noted = await svc_call(
        world,
        "patch_candidate",
        world.project_id,
        cand.id,
        {"conflict_note": "None declared"},
        actor_id=world.editor,
        can_manage=False,
    )
    assert noted.conflict_note == "None declared"
    async with world.factory() as s:
        assert (await s.get(BidderCandidate, cand.id)).list_kind == "long"
    moved = await svc_call(
        world, "patch_candidate", world.project_id, cand.id, {"list": "short"}, actor_id=world.manager, can_manage=True
    )
    assert moved.list_kind == "short"


async def test_a_profile_in_use_cannot_be_deleted_and_a_criterion_is_scored_once(world: World) -> None:
    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", OPEN_WORKS)
    profile = await svc_call(
        world,
        "save_profile",
        world.project_id,
        {"name": "Works", "criteria": [{"code": "similar_projects", "weight": "100"}], "pass_mark": "50"},
        actor_id=world.manager,
        can_manage=True,
    )
    await put(world, "W1", {"prequal_profile_id": profile.id})
    with _raises("profile_in_use", 409):
        await svc_call(world, "delete_profile", world.project_id, profile.id, actor_id=world.manager, can_manage=True)
    (sub,) = await _subs(world, 1)
    cand = await _add(world, "W1", {"subcontractor_id": sub.id, "list": "long"})
    score = {"criterion_code": "similar_projects", "score": "70"}
    with _raises("criterion_scored_twice", 422):
        await svc_call(world, "put_scores", world.project_id, cand.id, [score, score], actor_id=world.manager)
    await put(world, "W1", {"prequal_profile_id": None})
    await svc_call(world, "delete_profile", world.project_id, profile.id, actor_id=world.manager, can_manage=True)


# ── Schedule and consistency ────────────────────────────────────────────


async def test_schedule_proposal_is_written_only_on_confirm_and_idempotently(world: World) -> None:
    from app.modules.schedule.models import Activity, Schedule

    await add_contract_package(world, "W1", "construction")
    await put(world, "W1", {**OPEN_WORKS, "need_date": date(2027, 6, 30)})
    view = await svc_call(world, "schedule_view", world.project_id, today=date(2026, 10, 11))
    assert view["items"][0]["proposed_award_date"] == "2027-06-30"
    assert view["items"][0]["proposed_start_date"] == "2027-03-07"

    async def confirm():
        return await svc_call(
            world,
            "confirm_schedule",
            world.project_id,
            [world.packages["W1"]],
            actor_id=world.manager,
            can_manage=True,
        )

    with _raises("no_schedule", 409):
        await confirm()
    async with world.factory() as s:
        s.add(Schedule(project_id=world.project_id, name="Master"))
        await s.commit()
    first = await confirm()
    second = await confirm()
    assert first == second
    async with world.factory() as s:
        acts = (await s.execute(sa.select(Activity))).scalars().all()
    assert len(acts) == 2
    assert {a.metadata_["award_package_id"] for a in acts} == {str(world.packages["W1"])}


async def test_cm_at_risk_main_package_needs_two_stage_procedure(world: World) -> None:
    await set_delivery_form(world, "cm_at_risk")
    await add_contract_package(world, "GMP", "construction")
    await put(world, "GMP", {"estimated_value": "100000", "currency": "EUR", "procedure_code": "open"})
    report = await svc_call(world, "consistency_report", world.project_id)
    assert [f["code"] for f in report] == ["procedure_inconsistent_with_delivery_form"]
    await put(world, "GMP", {"procedure_code": "restricted"})
    assert await svc_call(world, "consistency_report", world.project_id) == []


async def test_bid_package_tender_id_must_name_a_tender_package_of_the_same_project(world: World) -> None:
    """The dead ``oe_tendering_tender`` reference: tender_id is a TenderPackage id, checked per project."""
    from app.modules.bid_management.schemas import BidPackageCreate
    from app.modules.bid_management.service import BidManagementService
    from app.modules.tendering.models import TenderPackage

    other = await build_world(world.factory, concept=False)
    async with world.factory() as s:
        own = TenderPackage(project_id=world.project_id, name="Own tender")
        foreign = TenderPackage(project_id=other.project_id, name="Foreign tender")
        s.add_all([own, foreign])
        await s.commit()
    for tender_id, ok in ((foreign.id, False), (uuid.uuid4(), False), (own.id, True)):
        async with world.factory() as s:
            svc = BidManagementService(s)
            data = BidPackageCreate(
                project_id=world.project_id, tender_id=tender_id, code=f"BP-{uuid.uuid4().hex[:6]}", currency="EUR"
            )
            if ok:
                assert (await svc.create_package(data)).tender_id == own.id
            else:
                with pytest.raises(HTTPException) as exc:
                    await svc.create_package(data)
                assert exc.value.status_code == 404


# ── Advance package released by a commitment (the hook the commitment matrix registers) ──


class _Matrix:
    """A stand-in commitment matrix: items per project, each released or not."""

    def __init__(self) -> None:
        self.items: dict[uuid.UUID, dict[uuid.UUID, commitments.CommitmentOption]] = {}

    def add(self, project_id: uuid.UUID, code: str, *, released: bool, lead: int | None = None) -> uuid.UUID:
        option = commitments.CommitmentOption(
            id=uuid.uuid4(),
            code=code,
            title=f"Item {code}",
            status="released" if released else "planned",
            released=released,
            released_on=TODAY if released else None,
            lead_time_days=lead,
        )
        self.items.setdefault(project_id, {})[option.id] = option
        return option.id

    def release(self, project_id: uuid.UUID, item_id: uuid.UUID) -> None:
        from dataclasses import replace

        self.items[project_id][item_id] = replace(
            self.items[project_id][item_id], status="released", released=True, released_on=TODAY
        )

    async def check(self, _session, project_id: uuid.UUID, item_id: uuid.UUID) -> commitments.CommitmentAnswer:
        option = self.items.get(project_id, {}).get(item_id)
        return commitments.CommitmentAnswer(found=option is not None, released=bool(option and option.released))

    async def listing(self, _session, project_id: uuid.UUID) -> list[commitments.CommitmentOption]:
        return sorted(self.items.get(project_id, {}).values(), key=lambda o: o.code)


@pytest.fixture
def matrix():
    m = _Matrix()
    commitments.register_commitment_checker(m.check)
    commitments.register_commitment_lister(m.listing)
    yield m
    commitments.register_commitment_checker(None)
    commitments.register_commitment_lister(None)


_ADVANCE = {
    "estimated_value": "50000",
    "currency": "EUR",
    "procedure_code": "request_for_quotation",
    "is_advance": True,
    "advance_reason": "Fabrication slot",
    "advance_release_kind": "commitment",
}


async def test_without_a_commitment_matrix_the_commitment_kind_is_refused_by_name(world: World) -> None:
    await add_contract_package(world, "S1", "supply")
    with _raises("commitment_release_unavailable", 409):
        await put(world, "S1", {**_ADVANCE, "advance_release_id": uuid.uuid4()})
    options = await svc_call(world, "advance_release_options", world.project_id)
    assert options["commitments"] == {"available": False, "reason": "commitment_release_unavailable"}
    assert [o for o in options["items"] if o["kind"] == "commitment"] == []
    # A lister without a checker lists nothing either: what is listed must be acceptable.
    commitments.register_commitment_lister(_Matrix().listing)
    try:
        options = await svc_call(world, "advance_release_options", world.project_id)
        assert options["commitments"]["available"] is False
    finally:
        commitments.register_commitment_lister(None)


async def test_a_released_commitment_releases_an_advance_package_before_any_gate_decision(
    world: World, matrix: _Matrix
) -> None:
    """The circle this kind breaks: no decision and no condition of the release gate exists yet."""
    await add_contract_package(world, "S1", "supply")
    other = await build_world(world.factory)
    foreign = matrix.add(other.project_id, "CR-9", released=True)
    planned = matrix.add(world.project_id, "CR-1", released=False, lead=150)
    with _raises("advance_release_not_found", 404):
        await put(world, "S1", {**_ADVANCE, "advance_release_id": foreign})
    with _raises("advance_release_not_found", 404):
        await put(world, "S1", {**_ADVANCE, "advance_release_id": uuid.uuid4()})
    # A commitment that is only planned may be named; it releases nothing yet.
    await put(world, "S1", {**_ADVANCE, "advance_release_id": planned})
    codes = {f["code"] for f in await svc_call(world, "findings", world.project_id) if f["ref"] == "S1"}
    assert "advance_package_not_released" in codes
    with _raises("concept_not_approved", 409):
        await execute(world, "S1")
    options = await svc_call(world, "advance_release_options", world.project_id)
    assert options["commitments"] == {"available": True, "reason": None}
    assert [(o["id"], o["status"], o["releases"], o["gate_code"]) for o in options["items"]] == [
        (str(planned), "planned", False, None)
    ]
    matrix.release(world.project_id, planned)
    codes = {f["code"] for f in await svc_call(world, "findings", world.project_id) if f["ref"] == "S1"}
    assert "advance_package_not_released" not in codes
    # The concept is still a draft and the gate undecided: the released advance package may go to tender.
    assert (await _concept(world))[0].state == "draft"
    assert (await execute(world, "S1"))["id"]
    # The matrix goes away (the module is switched off): nothing is taken on trust.
    commitments.register_commitment_checker(None)
    try:
        codes = {f["code"] for f in await svc_call(world, "findings", world.project_id) if f["ref"] == "S1"}
        assert "advance_package_not_released" in codes
    finally:
        commitments.register_commitment_checker(matrix.check)


async def test_a_package_bound_to_a_schedule_milestone_takes_its_need_date_from_it(world: World) -> None:
    """The framework schedule owns the date: the need date follows the milestone, and a foreign activity is refused."""
    from app.modules.schedule.models import Activity, Schedule

    await add_procurement_area(world, world.area_owner)
    await add_contract_package(world, "S1", "supply", need_date="2027-01-01")
    async with world.factory() as s:
        schedule = Schedule(
            project_id=world.project_id, name="Framework", start_date="2027-01-01", end_date="2027-12-31"
        )
        s.add(schedule)
        await s.flush()
        act = Activity(
            schedule_id=schedule.id,
            name="Construction start",
            start_date="2027-03-15",
            end_date="2027-03-15",
            duration_days=0,
            activity_type="milestone",
        )
        s.add(act)
        await s.commit()
        act_id = act.id
    row = await put(world, "S1", {"need_activity_id": act_id})
    assert row.need_activity_id == act_id and row.need_date == "2027-03-15"
    with pytest.raises(ProcurementError) as err:
        await put(world, "S1", {"need_activity_id": uuid.uuid4()})
    assert err.value.code == "need_activity_unknown"
