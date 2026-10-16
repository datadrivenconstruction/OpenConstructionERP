# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The quality concept's rules against PostgreSQL, through the service.

Four walks, each over one project: the proof plan and its evidence, a stage
released by its hold gate, an acceptance with reservations and its effects,
and a concept that follows its governance frame document. Each walk asserts
the refusals as well as the passes, with the error code the API returns.

The linked rows (systems, non-conformances, hold gates, handover acts,
warranties, CDE containers) are the real models of their own modules, so a
wrong column, type or constraint fails here the way it would in production.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.modules.quality_concept import schemas as s
from app.modules.quality_concept.errors import QualityConceptError
from app.modules.quality_concept.models import AcceptanceUnit, CommissioningStageDef, ProofRequirement
from app.modules.quality_concept.service import QualityConceptService, commissioning_guard
from tests.pg.governance_fixtures import add_container, add_project, add_user

pytestmark = pytest.mark.asyncio

REGIME = "fidic_taking_over"


@dataclass
class Plan:
    svc: QualityConceptService
    pid: uuid.UUID
    manager: uuid.UUID
    editor: uuid.UUID


async def _plan(session) -> Plan:
    """A draft concept with two packages, one standard and the catalogue stages, each with an owner."""
    manager = await add_user(session, "manager")
    editor = await add_user(session, "editor")
    pid = await add_project(session, manager, [editor])
    svc = QualityConceptService(session)
    await svc.ensure_concept(pid, manager)
    await svc.patch_concept(
        pid,
        s.ConceptPatch(
            packages=[
                s.PackageScopeIn(ref="P-01", title="Structure"),
                s.PackageScopeIn(ref="P-02", title="Services", no_proofs_rationale="Proofs follow with the tender"),
            ]
        ),
    )
    await svc.create_standard(pid, s.StandardIn(code="EN 206"))
    for stage in await svc.apply_catalogue_stages(pid):
        await svc.patch_stage(pid, stage.id, s.StageDefPatch(owner_user_id=editor))
    return Plan(svc, pid, manager, editor)


async def _units(p: Plan) -> dict[str, uuid.UUID]:
    """One unit per package, the total acceptance and the handover to operation."""
    out = {}
    for code, kind, refs in (
        ("AU-1", "partial_package", ["P-01"]),
        ("AU-2", "partial_package", ["P-02"]),
        ("AU-T", "total", []),
        ("AU-H", "handover_to_operation", []),
    ):
        unit = await p.svc.create_unit(
            p.pid, s.AcceptanceUnitIn(code=code, kind=kind, package_refs=refs, regime_code=REGIME)
        )
        out[code] = unit.id
    return out


async def _refused(awaitable) -> QualityConceptError:
    with pytest.raises(QualityConceptError) as caught:
        await awaitable
    return caught.value


async def _system(session, pid: uuid.UUID, tag: str):
    from app.modules.commissioning.models import CxSystem

    row = CxSystem(
        project_id=pid,
        name=f"Air handling unit {tag}",
        system_type="hvac",
        tag=tag,
        location="Plant room",
        description="",
        status="in_progress",
        metadata_={},
    )
    session.add(row)
    await session.flush()
    return row


# ── proof plan, evidence, decisions, frozen revisions ──────────────────────


async def test_proof_plan_coverage_decisions_and_frozen_revisions(pg_session) -> None:
    p = await _plan(pg_session)
    svc, pid = p.svc, p.pid
    await _units(p)

    # A preview writes nothing; a confirm writes the chosen rows once.
    preview = await svc.generate_proofs(pid, s.ProofGenerateIn(package_ref="P-01"))
    assert preview["created"] == []
    assert await svc.repo.list(ProofRequirement, pid) == []
    chosen = ["om_manual", "concrete_conformity_tests"]
    made = (await svc.generate_proofs(pid, s.ProofGenerateIn(package_ref="P-01", confirm=chosen)))["created"]
    assert sorted(m.evidence_type for m in made) == sorted(chosen)
    again = (await svc.generate_proofs(pid, s.ProofGenerateIn(package_ref="P-01", confirm=chosen)))["created"]
    assert again == []
    manual = next(m for m in made if m.evidence_type == "om_manual")
    counted = next(m for m in made if m.evidence_type == "concrete_conformity_tests")
    assert counted.quantity_rule["per_quantity"] == "150"

    # Evidence is a row of this project, of a kind the evidence type accepts.
    document = await add_container(pg_session, pid, "om_manual_a")
    elsewhere = await add_project(pg_session, p.manager, [])
    foreign = await add_container(pg_session, elsewhere, "om_manual_b")

    def link(kind: str, target: uuid.UUID) -> s.EvidenceLinkIn:
        return s.EvidenceLinkIn(owner_kind="proof", owner_id=manual.id, link_kind=kind, link_id=str(target))

    err = await _refused(svc.add_link(pid, link("cde_document", foreign), p.editor))
    assert (err.code, err.status_code) == ("linked_record_not_found", 404)
    err = await _refused(svc.add_link(pid, link("cx_checklist", document), p.editor))
    assert err.code == "evidence_kind_not_allowed"
    await svc.add_link(pid, link("cde_document", document), p.editor)
    err = await _refused(svc.add_link(pid, link("cde_document", document), p.editor))
    assert (err.code, err.status_code) == ("link_exists", 409)
    # A document still in work delivers nothing; sharing it does.
    from app.modules.cde.models import DocumentContainer

    assert (await svc.proof_delivery(pid, [manual]))[manual.id].state != "delivered"
    (await pg_session.get(DocumentContainer, document)).cde_state = "shared"
    await pg_session.flush()
    assert (await svc.proof_delivery(pid, [manual]))[manual.id].state == "delivered"

    coverage = await svc.coverage(pid)
    row = next(r for r in coverage["packages"] if r["package_ref"] == "P-01")
    assert (row["total"], row["done"]) == (2, 1)
    # A counted proof with no result linked yet has nothing placed to count against, so it
    # stays open without asking for the quantity (a site that has not started).
    assert "placed_quantity_missing" not in {f["code"] for f in coverage["findings"]}

    # Four eyes: whoever linked the evidence does not accept it.
    err = await _refused(svc.accept_proof(pid, manual.id, p.editor))
    assert (err.code, err.status_code) == ("approver_added_evidence", 403)
    assert (await svc.accept_proof(pid, manual.id, p.manager)).decision == "accepted"
    err = await _refused(svc.accept_proof(pid, counted.id, p.manager))
    assert (err.code, err.status_code) == ("proof_not_delivered", 409)

    # A waiver is asked by one person and decided by another; a decided one keeps its rationale.
    err = await _refused(svc.decide_waiver(pid, counted.id, True, p.manager))
    assert err.code == "waiver_not_requested"
    await svc.request_waiver(pid, counted.id, "Covered by the supplier's own conformity control", p.editor)
    err = await _refused(svc.decide_waiver(pid, counted.id, True, p.editor))
    assert (err.code, err.status_code) == ("approver_is_requester", 403)
    waived = await svc.decide_waiver(pid, counted.id, True, p.manager)
    assert waived.decision == "waived"
    err = await _refused(svc.decide_waiver(pid, counted.id, False, p.manager))
    assert (err.code, err.status_code) == ("invalid_transition", 409)
    assert waived.decision_rationale == "Covered by the supplier's own conformity control"

    # Submitting freezes the plan; a later change is a new revision and the old one stays as it was.
    concept = await svc.submit(pid, p.manager)
    assert concept.state == "in_review"
    err = await _refused(svc.submit(pid, p.manager))
    assert (err.code, err.status_code) == ("invalid_transition", 409)
    extra = s.ProofIn(
        package_ref="P-02",
        evidence_type="warranty_certificate",
        deliverer_role="contractor",
        required_by_kind="date",
        required_by_ref="2027-03-01",
    )
    err = await _refused(svc.create_proof(pid, extra, p.manager))
    assert (err.code, err.status_code) == ("concept_not_editable", 409)
    await svc.act_on_concept(pid, "return", p.manager)
    await svc.create_proof(pid, extra, p.manager)
    await svc.submit(pid, p.manager)
    revisions = await svc.revisions(pid)
    assert [len(r.snapshot["proofs"]) for r in revisions] == [2, 3]
    assert [r.revision_no for r in revisions] == [1, 2]


# ── stages: order, hold gate, party role, stale, guard, races ──────────────


async def test_a_stage_is_released_only_by_its_hold_gate(pg_session) -> None:
    from app.core.commissioning_stage_guard import (
        commissioning_blockers,
        register_commissioning_stage_guard,
        unregister_commissioning_stage_guard,
    )
    from app.modules.commissioning.schemas import CommissionRequest
    from app.modules.commissioning.service import CommissioningService
    from app.modules.construction_control.gating_service import GatingService
    from app.modules.construction_control.schemas import HoldGateReleaseIn

    p = await _plan(pg_session)
    svc, pid = p.svc, p.pid
    a, b, c = [await _system(pg_session, pid, tag) for tag in ("AHU-01", "AHU-02", "AHU-03")]
    await svc.sync_progress(pid)
    stages = await svc.repo.list(CommissioningStageDef, pid, CommissioningStageDef.order)
    first, second = stages[0], stages[1]

    async def row(system, stage):
        return next(
            r for r, _ in await svc.evaluate_progress(pid) if r.system_id == system.id and r.stage_code == stage.code
        )

    # No plant item is linked: the delivery limit precondition is not applicable, with its reason.
    results = next(
        res for r, res in await svc.evaluate_progress(pid) if r.system_id == a.id and r.stage_code == first.code
    )
    assert [(x.met, x.reason, x.params) for x in results] == [(True, "no_plant_item_linked", {"not_applicable": True})]
    a0, a1 = await row(a, first), await row(a, second)
    assert (a0.state, a1.state) == ("ready", "blocked")

    # Stage order: the second stage cannot be opened before the first is released.
    err = await _refused(svc.open_test(pid, a1.id, p.editor))
    assert (err.code, err.status_code) == ("invalid_transition", 409)

    async def pass_and_request(progress):
        await svc.open_test(pid, progress.id, p.editor)
        await svc.record_result(pid, progress.id, s.StageResultIn(result="pass"), p.editor)
        return await svc.request_release(pid, progress.id, p.editor)

    async def release(gate, party: str):
        return await GatingService(pg_session).release_gate(
            gate.id, HoldGateReleaseIn(party_role=party), str(p.manager), signature_ip=None
        )

    err = await _refused(svc.request_release(pid, a0.id, p.editor))
    assert (err.code, err.status_code) == ("stage_not_passed", 409)
    gate_a = await pass_and_request(a0)
    assert (gate_a.attached_kind, gate_a.attached_id, gate_a.status) == ("cx_stage", str(a0.id), "pending")
    err = await _refused(svc.request_release(pid, a0.id, p.editor))
    assert (err.code, err.status_code) == ("release_already_requested", 409)

    # The stage names qa as releasing party; a qc signature does not release the gate.
    assert first.release_party_role == "qa"
    with pytest.raises(HTTPException) as denied:
        await release(gate_a, "qc")
    assert denied.value.status_code == 403
    assert a0.state == "passed"
    assert await svc.apply_gate_released(gate_a.id) is False

    await release(gate_a, "qa")
    assert await svc.apply_gate_released(gate_a.id) is True
    assert (a0.state, a0.released_by) == ("released", p.manager)
    assert await svc.apply_gate_released(gate_a.id) is False

    # A gate released while its event never arrived is caught up by the next write.
    b0 = await row(b, first)
    gate_b = await pass_and_request(b0)
    await release(gate_b, "qa")
    assert b0.state == "passed"
    await svc.refresh_ready(pid)
    assert b0.state == "released"
    assert (await row(a, second)).state == "ready"

    # Rule 12: B depends on A; A back in test makes B stale, and B's old gate cannot release it again.
    await svc.set_dependencies(pid, b0.id, [a.id])
    await svc.open_test(pid, a0.id, p.editor)
    assert (a0.state, a0.hold_gate_id) == ("in_test", None)
    assert (b0.state, b0.hold_gate_id) == ("stale", None)
    await svc.refresh_ready(pid)
    assert b0.state == "stale"
    assert await svc.apply_gate_released(gate_b.id) is False

    # A re-tested stage needs a release of its own: the gate of the first test does nothing.
    await svc.record_result(pid, a0.id, s.StageResultIn(result="pass"), p.editor)
    assert await svc.apply_gate_released(gate_a.id) is False
    assert a0.state == "passed"
    gate_a2 = await svc.request_release(pid, a0.id, p.editor)
    assert gate_a2.id != gate_a.id

    # A failed test opens a commissioning issue on the system and stays in test.
    c0 = await row(c, first)
    await svc.open_test(pid, c0.id, p.editor)
    failed = await svc.record_result(pid, c0.id, s.StageResultIn(result="fail", note="Limit not agreed"), p.editor)
    assert failed.state == "in_test"
    assert failed.last_issue_id is not None

    # Rule 11: a system is commissioned only when its final stage is released.
    register_commissioning_stage_guard(commissioning_guard)
    try:
        assert await commissioning_blockers(pg_session, pid, a.id)
        with pytest.raises(HTTPException) as blocked:
            await CommissioningService(pg_session).commission_system(a.id, CommissionRequest(), str(p.manager))
        assert blocked.value.status_code == 409
        # A system the stage model does not apply to is not held back by it.
        for stage in stages:
            scope = {"mode": "systems", "values": [str(a.id), str(b.id)]}
            await svc.patch_stage(pid, stage.id, s.StageDefPatch(applies_to=scope))
        assert await commissioning_blockers(pg_session, pid, c.id) == []
    finally:
        unregister_commissioning_stage_guard()

    # Two writers on one row: the one that lost the race is told so (409), not answered with a 500.
    await release(gate_a2, "qa")
    await pg_session.execute(
        text("UPDATE oe_qconcept_stage_progress SET version = version + 1 WHERE id = :id"), {"id": str(a0.id)}
    )
    err = await _refused(svc.apply_gate_released(gate_a2.id))
    assert (err.code, err.status_code) == ("concurrent_release", 409)


# ── acceptance: scope, reservations, handover mirror, effects, deemed ──────


async def test_acceptance_reservations_effects_and_the_handover_mirror(pg_session) -> None:
    from app.core.acceptance_effects import register_effect_handler, unregister_effect_handler
    from app.modules.construction_control.models import HandoverPackage
    from app.modules.defects_liability.models import DlpWarranty
    from app.modules.ncr.models import NCR

    p = await _plan(pg_session)
    svc, pid = p.svc, p.pid
    units = await _units(p)
    today = datetime.now(UTC).date()

    def ncr(number: str, severity: str, package: str | None) -> NCR:
        return NCR(
            project_id=pid,
            ncr_number=number,
            title="Surface finish",
            description="Surface finish outside tolerance",
            ncr_type="workmanship",
            severity=severity,
            status="identified",
            package_ref=package,
            metadata_={},
        )

    minor, major = ncr("NCR-001", "minor", "P-01"), ncr("NCR-002", "major", None)
    pg_session.add_all([minor, major])
    await pg_session.flush()

    # Scope: a package unit sees the defects of its package; the total acceptance sees the project.
    unit = await _unit(svc, pid, units["AU-1"])
    assert [(u.kind, u.ref) for u in await svc.unmet_preconditions(pid, unit)] == [("defects", str(minor.id))]
    total = await _unit(svc, pid, units["AU-T"])
    kinds = {u.kind for u in await svc.unmet_preconditions(pid, total)}
    assert {"defects", "material_defects"} <= kinds

    # A minor defect is taken as a reservation when the regime allows it; a material one never is.
    err = await _refused(svc.request_acceptance(pid, unit.id, s.AcceptanceRequestIn(), p.editor))
    assert err.code == "acceptance_preconditions_unmet"
    err = await _refused(svc.request_acceptance(pid, total.id, s.AcceptanceRequestIn(with_reservations=True), p.editor))
    assert err.code == "acceptance_preconditions_unmet"
    assert "precondition_not_reservable" in {v["code"] for v in err.violations}
    asked = await svc.request_acceptance(
        pid, unit.id, s.AcceptanceRequestIn(with_reservations=True, notes={str(minor.id): "Repaint"}), p.editor
    )
    assert asked.state == "requested"
    assert asked.reservations == [{"kind": "defects", "ref": str(minor.id), "note": "Repaint"}]

    # A second unit is refused by the client, then overtaken by the certificate of the same act.
    other = await _unit(svc, pid, units["AU-2"])
    await svc.request_acceptance(pid, other.id, s.AcceptanceRequestIn(), p.editor)
    refusal = s.AcceptanceRefuseIn(rationale="Commissioning records missing", defects=["Records"])
    assert (await svc.refuse(pid, other.id, refusal, p.manager)).state == "refused"

    package = HandoverPackage(project_id=pid, package_number="HP-001", title="Section A", status="draft", metadata_={})
    pg_session.add(package)
    await pg_session.flush()
    for row in (unit, other):
        await svc.patch_unit(pid, row.id, s.AcceptanceUnitPatch(handover_package_id=package.id))
    assert package.regime_code == REGIME

    # Nothing is confirmed before the unit is accepted.
    err = await _refused(svc.confirm_effect(pid, unit.id, s.EffectConfirmIn(effect="risk_transfer"), p.manager))
    assert (err.code, err.status_code) == ("unit_not_accepted", 409)

    package.status, package.issued_at = "issued", datetime.now(UTC).isoformat()
    await pg_session.flush()
    moved = await svc.apply_handover_issued(package.id, None)
    assert {m.id for m in moved} == {unit.id, other.id}
    assert (unit.state, other.state) == ("accepted_with_reservations", "accepted")
    assert unit.accepted_on == today.isoformat()
    assert await svc.apply_handover_issued(package.id, None) == []
    err = await _refused(svc.record_dates(pid, unit.id, s.AcceptanceRecordIn(completion_notice_at=today)))
    assert (err.code, err.status_code) == ("unit_dates_locked", 409)

    # An effect is stored once however often it is confirmed, and says which module acted on it.
    first = await svc.confirm_effect(pid, unit.id, s.EffectConfirmIn(effect="risk_transfer"), p.manager)
    second = await svc.confirm_effect(pid, unit.id, s.EffectConfirmIn(effect="risk_transfer"), p.manager)
    assert first.id == second.id
    assert first.outcome["handled_by"] == {}

    async def note(_session, _project_id, effect):
        return {"noted": effect["effect"]}

    register_effect_handler("test_handler", note)
    try:
        ended = await svc.confirm_effect(pid, unit.id, s.EffectConfirmIn(effect="liquidated_damages_end"), p.manager)
    finally:
        unregister_effect_handler("test_handler")
    assert ended.outcome["handled_by"] == {"test_handler": {"noted": "liquidated_damages_end"}}
    err = await _refused(svc.confirm_effect(pid, unit.id, s.EffectConfirmIn(effect="limitation_starts"), p.manager))
    assert err.code == "effect_not_in_regime"

    # A warranty effect starts the open warranties of the unit's packages and nothing else.
    started = DlpWarranty(
        project_id=pid, reference="W-001", title="Roof", work_package="P-01", warranty_start_date=date(2025, 1, 15)
    )
    waiting = DlpWarranty(project_id=pid, reference="W-002", title="Facade", work_package="P-01")
    pg_session.add_all([started, waiting])
    await pg_session.flush()
    starts = s.EffectConfirmIn(effect="defects_period_starts")
    err = await _refused(svc.confirm_effect(pid, other.id, starts, p.manager))
    assert (err.code, err.status_code) == ("no_warranty_to_start", 422)
    assert await svc.repo.effects(other.id) == []
    period = await svc.confirm_effect(pid, unit.id, starts, p.manager)
    assert period.outcome == {"warranty_ids": [str(waiting.id)]}
    assert (waiting.warranty_start_date, waiting.handover_date) == (today, today)
    assert started.warranty_start_date == date(2025, 1, 15)
    assert len(await svc.repo.effects(unit.id)) == 3

    # The certificate is revoked: the units are requested again and their effects are open again.
    package.status = "revoked"
    await pg_session.flush()
    back = await svc.apply_handover_revoked(package.id)
    assert {m.id for m in back} == {unit.id, other.id}
    assert (unit.state, unit.accepted_on) == ("requested", None)
    assert all("revoked_at" in e.outcome for e in await svc.repo.effects(unit.id))
    assert "risk_transfer" in {e.effect for e in await svc.proposed_effects(pid, unit)}

    # Deemed acceptance: the server's date decides, 28 calendar days after the completion notice.
    err = await _refused(
        svc.record_dates(pid, unit.id, s.AcceptanceRecordIn(completion_notice_at=today + timedelta(days=3)))
    )
    assert (err.code, err.status_code) == ("date_in_future", 422)
    await svc.record_dates(pid, unit.id, s.AcceptanceRecordIn(completion_notice_at=today - timedelta(days=10)))
    err = await _refused(svc.act_on_unit(pid, unit.id, "confirm_deemed", p.manager))
    assert (err.code, err.status_code) == ("deemed_acceptance_not_due", 409)
    noticed = today - timedelta(days=40)
    await svc.record_dates(pid, unit.id, s.AcceptanceRecordIn(completion_notice_at=noticed))
    deemed = await svc.act_on_unit(pid, unit.id, "confirm_deemed", p.manager)
    assert (deemed.state, deemed.accepted_on) == ("deemed_accepted", (noticed + timedelta(days=28)).isoformat())
    err = await _refused(svc.act_on_unit(pid, unit.id, "withdraw", p.manager))
    assert (err.code, err.status_code) == ("invalid_transition", 409)


async def _unit(svc: QualityConceptService, pid: uuid.UUID, unit_id: uuid.UUID) -> AcceptanceUnit:
    return await svc.get_row(AcceptanceUnit, pid, unit_id)


async def test_an_act_whose_event_never_arrived_is_followed_by_the_next_unit_write(pg_session) -> None:
    from app.modules.construction_control.models import HandoverPackage

    p = await _plan(pg_session)
    svc, pid = p.svc, p.pid
    units = await _units(p)
    today = datetime.now(UTC).date()
    package = HandoverPackage(project_id=pid, package_number="HP-009", title="Section B", status="draft", metadata_={})
    pg_session.add(package)
    await pg_session.flush()
    for code in ("AU-1", "AU-2"):
        await svc.patch_unit(pid, units[code], s.AcceptanceUnitPatch(handover_package_id=package.id))
    first, second = await _unit(svc, pid, units["AU-1"]), await _unit(svc, pid, units["AU-2"])

    # The act is issued and its event is lost: nothing has moved.
    package.status, package.issued_at = "issued", datetime.now(UTC).isoformat()
    await pg_session.flush()
    assert (first.state, second.state) == ("planned", "planned")

    # The next write on any unit of the project catches up; the unit written is not on the act.
    noticed = s.AcceptanceRecordIn(completion_notice_at=today - timedelta(days=1))
    await svc.record_dates(pid, units["AU-T"], noticed)
    assert (first.state, second.state) == ("accepted", "accepted")
    assert first.accepted_on == today.isoformat()
    assert (await _unit(svc, pid, units["AU-T"])).state == "planned"
    assert await svc.reconcile_handover(pid) == 0

    # The act is revoked and that event is lost too: the units are requested again by the next write.
    package.status = "revoked"
    await pg_session.flush()
    await svc.record_dates(pid, units["AU-T"], noticed)
    assert (first.state, first.accepted_on, second.state) == ("requested", None, "requested")
    # A unit decided by a person since then is left alone: nothing is on the act to follow.
    await svc.record_dates(pid, first.id, s.AcceptanceRecordIn(completion_notice_at=today - timedelta(days=40)))
    deemed = await svc.act_on_unit(pid, first.id, "confirm_deemed", p.manager)
    assert deemed.state == "deemed_accepted"
    await svc.record_dates(pid, units["AU-T"], noticed)
    assert (first.state, second.state) == ("deemed_accepted", "requested")


# ── the concept follows its governance frame document ──────────────────────


async def test_the_concept_follows_its_frame_document(pg_session, monkeypatch) -> None:
    """Rule 22. Which document is the frame document is catalogue data; here it is given directly."""
    p = await _plan(pg_session)
    svc, pid = p.svc, p.pid
    await _units(p)
    await svc.generate_proofs(pid, s.ProofGenerateIn(package_ref="P-01", confirm=["om_manual"]))
    document, stranger = uuid.uuid4(), uuid.uuid4()
    status = {"value": "draft"}

    async def frame_documents(self, project_id):
        return {document: status["value"]}

    monkeypatch.setattr(QualityConceptService, "_frame_documents", frame_documents)

    # A document that is not the frame document moves nothing; a draft concept is not bound unread.
    status["value"] = "binding"
    assert await svc.apply_governance_state(pid, stranger, "binding") is False
    assert await svc.apply_governance_state(pid, document, "binding") is False
    concept = await svc.require_concept(pid)
    assert concept.state == "draft"

    # Submitted after the document is binding, it is approved and bound in the same step.
    await svc.submit(pid, p.manager)
    assert concept.state == "binding"
    assert concept.governance_doc_id == document
    assert [r.reason for r in await svc.revisions(pid)] == ["submitted", "approved"]

    extra = s.ProofIn(
        package_ref="P-02",
        evidence_type="warranty_certificate",
        deliverer_role="contractor",
        required_by_kind="date",
        required_by_ref="2027-03-01",
    )
    err = await _refused(svc.create_proof(pid, extra, p.manager))
    assert (err.code, err.status_code) == ("binding_requires_reopen", 409)
    err = await _refused(svc.act_on_concept(pid, "return", p.manager))
    assert (err.code, err.status_code) == ("invalid_transition", 409)

    # A repeated binding event changes nothing; an approved change request reopens the plan.
    assert await svc.apply_governance_state(pid, document, "binding") is False
    assert await svc.apply_governance_state(pid, document, "binding", change_request=True) is True
    assert concept.state == "revising"
    assert [r.reason for r in await svc.revisions(pid)] == ["submitted", "approved", "change_request"]
    await svc.create_proof(pid, extra, p.manager)
    await svc.submit(pid, p.manager)
    assert concept.state == "binding"
    revisions = await svc.revisions(pid)
    assert [len(r.snapshot["proofs"]) for r in revisions][-3:] == [1, 2, 2]


async def test_a_frame_document_whose_event_never_arrived_is_followed_by_the_next_write(
    pg_session, monkeypatch
) -> None:
    p = await _plan(pg_session)
    svc, pid = p.svc, p.pid
    await _units(p)
    await svc.generate_proofs(pid, s.ProofGenerateIn(package_ref="P-01", confirm=["om_manual"]))
    document = uuid.uuid4()
    status, in_force = {"value": "draft"}, {"value": None}

    async def frame_documents(self, project_id):
        return {document: status["value"]}

    async def bound_revision(self, project_id, document_id):
        return in_force["value"]

    monkeypatch.setattr(QualityConceptService, "_frame_documents", frame_documents)
    monkeypatch.setattr(QualityConceptService, "_bound_revision", bound_revision)

    await svc.submit(pid, p.manager)
    concept = await svc.require_concept(pid)
    assert concept.state == "in_review"

    # The gate approves the document and the event is lost: the next write binds the concept first.
    status["value"], in_force["value"] = "binding", "revision-1"
    extra = s.ProofIn(
        package_ref="P-02",
        evidence_type="warranty_certificate",
        deliverer_role="contractor",
        required_by_kind="date",
        required_by_ref="2027-03-01",
    )
    err = await _refused(svc.create_proof(pid, extra, p.manager))
    assert (err.code, concept.state) == ("binding_requires_reopen", "binding")
    assert [r.reason for r in await svc.revisions(pid)] == ["submitted", "approved"]

    # A change request puts another revision in force and that event is lost: the plan write reopens it.
    in_force["value"] = "revision-2"
    (existing,) = await svc.repo.list(ProofRequirement, pid)
    await svc.patch_proof(pid, existing.id, s.ProofPatch(title="Operation and maintenance manual, as built"))
    assert concept.state == "revising"
    await svc.create_proof(pid, extra, p.manager)
    assert [r.reason for r in await svc.revisions(pid)] == ["submitted", "approved", "change_request"]

    # Bound again under the new revision, neither the late event nor a further write reopens it.
    await svc.submit(pid, p.manager)
    assert concept.state == "binding"
    assert await svc.apply_governance_state(pid, document, "binding", change_request="revision-2") is False
    assert await svc.reconcile_governance(pid, reopen=True) is False
    assert concept.state == "binding"


async def test_a_project_without_gates_takes_its_concept_from_draft_to_in_force_and_back(pg_session) -> None:
    """Rule 26: no phase model, no gates. A second manager approves; a manager reopens with a reason."""
    p = await _plan(pg_session)
    svc, pid = p.svc, p.pid
    await _units(p)
    await svc.generate_proofs(pid, s.ProofGenerateIn(package_ref="P-01", confirm=["om_manual"]))
    second = await add_user(pg_session, "manager")
    assert await svc.gates_in_use(pid) is False

    err = await _refused(svc.approve_by_hand(pid, second))
    assert (err.code, err.status_code) == ("invalid_transition", 409)
    await svc.submit(pid, p.manager)
    concept = await svc.require_concept(pid)
    assert concept.state == "in_review"
    # Four eyes is on where no model says otherwise: the submitter does not approve.
    err = await _refused(svc.approve_by_hand(pid, p.manager))
    assert (err.code, err.status_code) == ("approver_is_submitter", 403)

    await svc.approve_by_hand(pid, second)
    assert concept.state == "binding"
    approved = (await svc.revisions(pid))[-1]
    assert (approved.reason, approved.created_by) == ("approved", second)
    assert approved.created_at is not None

    # What approval gives: the plan is in force and closed, until a manager reopens it with a reason.
    extra = s.ProofIn(
        package_ref="P-02",
        evidence_type="warranty_certificate",
        deliverer_role="contractor",
        required_by_kind="date",
        required_by_ref="2027-03-01",
    )
    err = await _refused(svc.create_proof(pid, extra, p.manager))
    assert (err.code, err.status_code) == ("binding_requires_reopen", 409)
    await svc.reopen_by_hand(pid, "The services package was split in two", p.manager)
    assert concept.state == "revising"
    reopened = (await svc.revisions(pid))[-1]
    assert (reopened.reason, reopened.created_by) == ("reopened", p.manager)
    assert reopened.snapshot["reopen_reason"] == "The services package was split in two"
    await svc.create_proof(pid, extra, p.manager)
    err = await _refused(svc.reopen_by_hand(pid, "Again", p.manager))
    assert (err.code, err.status_code) == ("invalid_transition", 409)

    # The changed plan goes the same way again.
    await svc.submit(pid, second)
    await svc.approve_by_hand(pid, p.manager)
    assert concept.state == "binding"
    assert [r.reason for r in await svc.revisions(pid)] == [
        "submitted",
        "approved",
        "reopened",
        "submitted",
        "approved",
    ]


# ── the documentation set becomes closeout slots and FM data deliverables ───


async def test_the_documentation_set_seeds_closeout_slots_and_fm_data_once(pg_session) -> None:
    from app.modules.closeout.service import CloseoutService

    p = await _plan(pg_session)
    svc, pid = p.svc, p.pid
    units = await _units(p)
    err = await _refused(svc.apply_documentation_set(pid, p.manager))
    assert err.code == "documentation_set_missing"
    err = await _refused(svc.patch_concept(pid, s.ConceptPatch(documentation_set_code="no_such_set")))
    assert err.code == "documentation_set_unknown"

    await svc.patch_concept(pid, s.ConceptPatch(documentation_set_code="building_standard"))
    concept = await svc.require_concept(pid)
    wanted = (await svc.catalogue_for(concept)).documentation_set("building_standard")
    first = await svc.apply_documentation_set(pid, p.manager)
    # The template brings its own slots; the set adds the ones the template does not have.
    assert {"training_record", "authority_acceptance"} <= set(first["slots_added"])
    assert first["fm_data_added"] == [fm.code for fm in wanted.fm_data]
    closeout = CloseoutService(pg_session)
    package = await closeout.repo.get_package_for_project(pid)
    keys = [slot.slot_key for slot in await closeout.repo.list_slots(package.id)]
    assert set(wanted.slot_keys) <= set(keys)
    assert len(keys) == len(set(keys))

    # The FM data is now owed: the handover to operation waits for it.
    handover = await _unit(svc, pid, units["AU-H"])
    owed = [u for u in await svc.unmet_preconditions(pid, handover) if u.kind == "fm_data"]
    assert len(owed) == len(wanted.fm_data)

    again = await svc.apply_documentation_set(pid, p.manager)
    assert again == {"slots_added": [], "fm_data_added": []}
