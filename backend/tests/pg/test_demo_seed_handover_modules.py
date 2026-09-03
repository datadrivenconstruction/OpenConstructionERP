# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The handover-side demo seeds must fill their registers, once, and coherently.

Closeout, commissioning and construction control all shipped routed,
permissioned and empty. The three seeders that fix that share the same ways of
being wrong, and none of them shows up as a non-zero exit code:

* they write nothing, because the self-gate that keeps a customer's live project
  safe also excludes the demo estate;
* they double the register on the second boot, because idempotency in this
  codebase is per loop rather than per seeder;
* they write rows that are individually valid and collectively nonsense - a
  package reporting a completeness its slots do not support, a system signed off
  while a critical deficiency is open, a lab result that passed on a number
  outside the limit it was judged against.

The third one is what these tests are really for, and each coherence assertion
runs through the module's own judge - ``completeness_pct``, ``compute_readiness``,
``compute_tolerance_result``, ``validate_gates`` - rather than restating the rule
here. A rule restated in a test passes on data the application would reject.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.closeout.completeness import completeness_pct
from app.modules.closeout.models import CloseoutBinding, CloseoutPackage, CloseoutSlot
from app.modules.closeout.seed import seed_closeout_demo
from app.modules.commissioning.models import CxChecklist, CxChecklistItem, CxIssue, CxSystem
from app.modules.commissioning.seed import seed_commissioning_demo
from app.modules.commissioning.validators import compute_readiness
from app.modules.construction_control.asbuilt_service import compute_tolerance_result
from app.modules.construction_control.gating_service import party_role_satisfies
from app.modules.construction_control.handover_service import HandoverService
from app.modules.construction_control.models import (
    AcceptanceCriterion,
    AsBuiltRecord,
    HandoverPackage,
    HoldGate,
    Inspection,
    MaterialRecord,
)

# Aliased on import: pytest tries to collect any module-level name starting with
# "Test" as a test class, and warns that it cannot because the ORM model has a
# constructor. The model is a lab result, not a test case.
from app.modules.construction_control.models import TestResult as LabTestResult
from app.modules.construction_control.seed import seed_construction_control_demo
from app.modules.documents.models import Document
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

# The documents a demo project carries. Named as the generated demo estate names
# them, because the closeout seeder binds a slot to a document by what the
# document is called and a fixture with invented names would not exercise that.
_DOCUMENTS = (
    ("Architectural drawing set.pdf", "drawing"),
    ("Health and safety plan.pdf", "hse"),
    ("Building permit - authority approval.pdf", "permit"),
    ("Structural calculations report.pdf", "engineering"),
    ("Method statement.pdf", "method_statement"),
    ("Mechanical services technical specification.pdf", "specification"),
    ("Mechanical shop drawings.pdf", "drawing"),
    ("Maintenance contracts and O&M manual.pdf", "manual"),
)


async def _make_project(session, name: str, *, is_demo: bool = True) -> uuid.UUID:
    """A demo project with the document register these seeders read from."""
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"{name.lower()}@example.test",
            hashed_password="x",
            full_name=f"{name} Owner",
            role="manager",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    # Flushed on its own: the project's owner FK has no ORM relationship behind
    # it, so nothing orders the two inserts for us.
    await session.flush()

    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=name,
            description="Handover seed fixture",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={"is_demo": True, "demo_id": "fixture"} if is_demo else {},
        )
    )
    await session.flush()

    for doc_name, category in _DOCUMENTS:
        session.add(
            Document(
                id=uuid.uuid4(),
                project_id=project_id,
                name=doc_name,
                description=f"{doc_name} for {name}",
                category=category,
                file_size=1024,
                mime_type="application/pdf",
                file_path=f"fixture/{name}/{doc_name}",
                version=1,
                uploaded_by=str(owner_id),
                tags=[],
                metadata_={},
            )
        )
    await session.flush()
    return project_id


async def _count(session, model, project_id: uuid.UUID) -> int:
    return (
        await session.execute(select(func.count()).select_from(model).where(model.project_id == project_id))
    ).scalar_one()


# ── Closeout ──────────────────────────────────────────────────────────────────


async def _package(session, project_id: uuid.UUID) -> CloseoutPackage:
    return (await session.execute(select(CloseoutPackage).where(CloseoutPackage.project_id == project_id))).scalar_one()


async def test_closeout_seeds_a_checklist_with_evidence_on_it(pg_session) -> None:
    """The handover checklist is populated, mixed, and bound to real documents."""
    project_id = await _make_project(pg_session, "Quay")

    counts = await seed_closeout_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["packages"] == 1
    # A register, not a template: eight is the floor the module ships with.
    assert counts["slots"] >= 12, f"only {counts['slots']} slot(s) seeded"
    assert counts["bindings"] >= 3, f"only {counts['bindings']} binding(s) seeded"
    assert counts["verified"] >= 1, "nothing was signed off, so the package reads as 0% forever"

    package = await _package(pg_session, project_id)
    slots = (
        (await pg_session.execute(select(CloseoutSlot).where(CloseoutSlot.package_id == package.id))).scalars().all()
    )
    bindings = {
        b.slot_id: b
        for b in (
            (
                await pg_session.execute(
                    select(CloseoutBinding).where(CloseoutBinding.slot_id.in_([s.id for s in slots]))
                )
            )
            .scalars()
            .all()
        )
    }

    # Every binding names a document that really exists in THIS project. A
    # binding to a missing document renders as a bare fallback label on screen.
    doc_ids = set(
        (await pg_session.execute(select(Document.id).where(Document.project_id == project_id))).scalars().all()
    )
    assert bindings, "no evidence was attached at all"
    for binding in bindings.values():
        assert binding.document_id in doc_ids, (
            f"binding points at {binding.document_id}, not a document of this project"
        )

    # One document backs at most one requirement.
    bound_docs = [b.document_id for b in bindings.values()]
    assert len(bound_docs) == len(set(bound_docs)), "the same document was attached to more than one slot"

    # Mixed states: signed off, attached but unchecked, and proposals nobody
    # confirmed. A checklist that is uniformly anything teaches nothing.
    assert any(b.is_verified for b in bindings.values()), "no slot is verified"
    assert any(not b.is_verified for b in bindings.values()), "every slot is verified, which is not a live package"
    assert any(b.suggested_by_ai for b in bindings.values()), "no proposal is shown awaiting human confirmation"
    for binding in bindings.values():
        # AI-suggests-human-confirms: a proposal is never also a sign-off.
        assert not (binding.suggested_by_ai and binding.is_verified)
        assert bool(binding.verified_at) == binding.is_verified
        assert bool(binding.verified_by) == binding.is_verified


async def test_closeout_completeness_is_what_the_slots_support(pg_session) -> None:
    """The percentage on the package equals the module's own arithmetic over its slots.

    Both halves matter. The counters have to agree with the slots that are
    actually delivered, and the percentage has to agree with the counters
    through ``completeness_pct`` - a package claiming a figure its evidence does
    not support is the first thing a reader spots in a screenshot.
    """
    project_id = await _make_project(pg_session, "Wharfside")
    await seed_closeout_demo(pg_session, [project_id])
    await pg_session.flush()

    package = await _package(pg_session, project_id)
    slots = (
        (await pg_session.execute(select(CloseoutSlot).where(CloseoutSlot.package_id == package.id))).scalars().all()
    )
    verified_slot_ids = set(
        (
            await pg_session.execute(
                select(CloseoutBinding.slot_id)
                .where(CloseoutBinding.slot_id.in_([s.id for s in slots]))
                .where(CloseoutBinding.is_verified.is_(True))
            )
        )
        .scalars()
        .all()
    )

    required = [s for s in slots if s.is_required]
    # No build has run, so no generated artifact can count as delivered; the
    # delivered set is exactly the required slots a human verified.
    expected_delivered = sum(1 for s in required if s.id in verified_slot_ids)

    assert package.required_slot_count == len(required)
    assert package.delivered_slot_count == expected_delivered, (
        f"package reports {package.delivered_slot_count} delivered, the slots support {expected_delivered}"
    )
    assert package.completeness_pct == completeness_pct(expected_delivered, len(required))
    # A required count of zero makes the module report 100% complete with no
    # evidence at all, which is the failure mode behind every "is_required"
    # default in this seeder.
    assert package.required_slot_count > 0
    assert 0 < package.completeness_pct < 100, (
        f"completeness is {package.completeness_pct}%, which is either an empty package or a suspiciously perfect one"
    )
    assert package.status == "in_progress"


async def test_closeout_second_pass_adds_nothing(pg_session) -> None:
    """Running the closeout seed twice must not double the checklist."""
    project_id = await _make_project(pg_session, "Basin")

    await seed_closeout_demo(pg_session, [project_id])
    await pg_session.flush()
    package = await _package(pg_session, project_id)
    slots_before = (
        await pg_session.execute(
            select(func.count()).select_from(CloseoutSlot).where(CloseoutSlot.package_id == package.id)
        )
    ).scalar_one()
    assert slots_before > 0

    second = await seed_closeout_demo(pg_session, [project_id])
    await pg_session.flush()

    assert second["packages"] == 0, "the second pass created another package"
    assert second["slots"] == 0
    after = (
        await pg_session.execute(
            select(func.count()).select_from(CloseoutSlot).where(CloseoutSlot.package_id == package.id)
        )
    ).scalar_one()
    assert after == slots_before


# ── Commissioning ─────────────────────────────────────────────────────────────


async def _functional_statuses(session, system_id: uuid.UUID) -> list[str]:
    return list(
        (
            await session.execute(
                select(CxChecklistItem.status)
                .join(CxChecklist, CxChecklistItem.checklist_id == CxChecklist.id)
                .where(CxChecklist.system_id == system_id)
                .where(CxChecklist.kind == "functional")
            )
        )
        .scalars()
        .all()
    )


async def _open_critical(session, system_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(CxIssue)
            .where(CxIssue.system_id == system_id)
            .where(CxIssue.severity == "critical")
            .where(CxIssue.status == "open")
        )
    ).scalar_one()


async def test_commissioning_seeds_a_mixed_system_register(pg_session) -> None:
    """The Cx register is populated and spread across the whole lifecycle."""
    project_id = await _make_project(pg_session, "Terminal")

    counts = await seed_commissioning_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["systems"] >= 8, f"only {counts['systems']} system(s) seeded"
    assert counts["items"] >= 80, f"only {counts['items']} checklist item(s) seeded"
    assert counts["issues"] >= 5, f"only {counts['issues']} deficiency/ies seeded"
    assert await _count(pg_session, CxSystem, project_id) == counts["systems"]

    systems = (await pg_session.execute(select(CxSystem).where(CxSystem.project_id == project_id))).scalars().all()
    lifecycles = {s.status for s in systems}
    assert lifecycles == {"not_started", "in_progress", "tests_complete", "commissioned"}, (
        f"only saw {sorted(lifecycles)}"
    )
    # More than one kind of plant, or the page reads as one trade repeated.
    assert len({s.system_type for s in systems}) >= 4

    for system in systems:
        checklists = (
            (await pg_session.execute(select(CxChecklist).where(CxChecklist.system_id == system.id))).scalars().all()
        )
        assert {c.kind for c in checklists} == {"prefunctional", "functional"}, (
            f"{system.tag} does not carry both checklists"
        )


async def test_a_commissioned_system_passes_the_gate_that_commissions_it(pg_session) -> None:
    """Every signed-off system satisfies ``compute_readiness``, the real gate.

    Asserted through the module's own readiness helper rather than by restating
    its rule: the ``commission`` action refuses a system with an open functional
    item or an open critical deficiency, so a seeded system that reads
    ``commissioned`` while failing that check is a sign-off the application
    itself would never have allowed.
    """
    project_id = await _make_project(pg_session, "Concourse")
    await seed_commissioning_demo(pg_session, [project_id])
    await pg_session.flush()

    systems = (await pg_session.execute(select(CxSystem).where(CxSystem.project_id == project_id))).scalars().all()
    commissioned = [s for s in systems if s.status == "commissioned"]
    assert commissioned, "nothing is commissioned, so the gate is never exercised"

    for system in commissioned:
        readiness = compute_readiness(
            await _functional_statuses(pg_session, system.id),
            await _open_critical(pg_session, system.id),
        )
        assert readiness["can_commission"], (
            f"{system.tag} is commissioned but the readiness gate refuses it: {readiness['blocking_reasons']}"
        )
        assert system.commissioned_at, f"{system.tag} is commissioned with no date"
        assert system.commissioned_by, f"{system.tag} is commissioned by nobody"

    # A system that has not started has nothing recorded against it, and a
    # register where every item carries a result hides what "pending" means.
    not_started = [s for s in systems if s.status == "not_started"]
    for system in not_started:
        assert set(await _functional_statuses(pg_session, system.id)) == {"pending"}

    # The open critical deficiency has to exist somewhere, or the blocked half
    # of the gate is never shown on screen.
    blocked = [s for s in systems if s.status == "tests_complete" and await _open_critical(pg_session, s.id) > 0]
    assert blocked, "no system is held back by an open critical deficiency"

    # A result stamp only where a result exists.
    items = (
        (
            await pg_session.execute(
                select(CxChecklistItem)
                .join(CxChecklist, CxChecklistItem.checklist_id == CxChecklist.id)
                .join(CxSystem, CxChecklist.system_id == CxSystem.id)
                .where(CxSystem.project_id == project_id)
            )
        )
        .scalars()
        .all()
    )
    for item in items:
        recorded = item.status != "pending"
        assert bool(item.verified_at) == recorded, f"item {item.id} stamp disagrees with its status {item.status!r}"
        assert bool(item.verified_by) == recorded

    # A closed deficiency carries its resolution and its closer; an open one
    # carries neither.
    issues = (
        (
            await pg_session.execute(
                select(CxIssue)
                .join(CxSystem, CxIssue.system_id == CxSystem.id)
                .where(CxSystem.project_id == project_id)
            )
        )
        .scalars()
        .all()
    )
    assert any(i.status == "open" for i in issues) and any(i.status == "closed" for i in issues)
    for issue in issues:
        closed = issue.status == "closed"
        assert bool(issue.resolution) == closed
        assert bool(issue.closed_at) == closed
        assert bool(issue.closed_by) == closed


async def test_commissioning_second_pass_adds_nothing(pg_session) -> None:
    """Running the commissioning seed twice must not double the register."""
    project_id = await _make_project(pg_session, "Depothall")

    await seed_commissioning_demo(pg_session, [project_id])
    await pg_session.flush()
    before = await _count(pg_session, CxSystem, project_id)
    assert before > 0

    second = await seed_commissioning_demo(pg_session, [project_id])
    await pg_session.flush()
    assert second["systems"] == 0, f"the second pass wrote {second['systems']} system(s) again"
    assert await _count(pg_session, CxSystem, project_id) == before


# ── Construction control ──────────────────────────────────────────────────────


def test_the_seeders_result_mapping_still_matches_the_services() -> None:
    """The seeder keeps its own copy of result -> status; pin it to the original.

    The seeder cannot call ``record_result`` (it raises an NCR through the NCR
    service, which mints a notification and publishes a detached event), so it
    restates the mapping. A restatement that drifts would seed inspections whose
    status and result disagree, and every other assertion here would still pass.
    """
    from app.modules.construction_control.seed import _INSPECTION_STATUS_BY_RESULT
    from app.modules.construction_control.service import _RESULT_RULES

    service_mapping = {result: rule[0] for result, rule in _RESULT_RULES.items()}
    assert service_mapping == _INSPECTION_STATUS_BY_RESULT


async def test_construction_control_seeds_all_five_registers(pg_session) -> None:
    """Every section of the page gets rows, spread across their states."""
    project_id = await _make_project(pg_session, "Viaduct")

    counts = await seed_construction_control_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["criteria"] >= 10, f"only {counts['criteria']} criterion/a seeded"
    assert counts["inspections"] >= 10, f"only {counts['inspections']} inspection(s) seeded"
    assert counts["materials"] >= 5
    assert counts["tests"] >= 5
    assert counts["asbuilts"] >= 3
    assert counts["gates"] >= 5
    assert counts["handover_packages"] >= 1
    assert await _count(pg_session, Inspection, project_id) == counts["inspections"]

    inspections = (
        (await pg_session.execute(select(Inspection).where(Inspection.project_id == project_id))).scalars().all()
    )
    statuses = {i.status for i in inspections}
    assert {"scheduled", "failed"} <= statuses, f"only saw {sorted(statuses)}"
    assert statuses & {"passed", "closed"}, "nothing has passed, so the register shows no accepted work"

    for inspection in inspections:
        # Status and result are one decision, not two. The module maps a pass to
        # ``passed`` (or a later ``closed``) and a fail to ``failed``; anything
        # still open has no result at all.
        if inspection.result == "pass":
            assert inspection.status in ("passed", "closed")
            assert inspection.performed_at and inspection.performed_by
        elif inspection.result == "fail":
            assert inspection.status == "failed"
            assert inspection.raised_ncr_id, (
                f"{inspection.inspection_number} failed but raised no non-conformance, "
                "which is a state the module itself cannot produce"
            )
        else:
            assert inspection.status in ("draft", "scheduled", "in_progress")
            assert inspection.performed_at is None

    # An overdue inspection - booked for a date already gone by and still open -
    # is a state every real register has and none of the happy paths produces.
    # Compared against the clock, not against the newest row in the set: the
    # latest scheduled date is a future one, so comparing rows to each other
    # would pass on a register whose bookings are all still ahead.
    now = datetime.now(UTC)
    overdue = [
        i
        for i in inspections
        if i.status == "scheduled" and i.scheduled_at and datetime.fromisoformat(i.scheduled_at) < now
    ]
    assert overdue, "no inspection is overdue"
    ahead = [
        i
        for i in inspections
        if i.status == "scheduled" and i.scheduled_at and datetime.fromisoformat(i.scheduled_at) >= now
    ]
    assert ahead, "every booking is already late, which is not a register either"

    materials = (
        (await pg_session.execute(select(MaterialRecord).where(MaterialRecord.project_id == project_id)))
        .scalars()
        .all()
    )
    assert {m.status for m in materials} & {"accepted"}
    for material in materials:
        reviewed = material.status in ("accepted", "expired")
        assert bool(material.reviewed_at) == reviewed, f"{material.record_number} review stamp disagrees with status"
        assert bool(material.reviewed_by) == reviewed
        # No passport is rejected here, because a rejection raises a material
        # non-conformance through the review action and this seeder puts its
        # failures on the inspection and the lab test instead.
        assert material.status != "rejected"


async def test_a_recorded_lab_result_agrees_with_the_criterion_it_was_judged_against(pg_session) -> None:
    """The headline arithmetic: measured value against tolerance, both ways.

    A pass on a number outside the limit, or a fail on a number inside it, is
    the one incoherence a reader can check straight off a screenshot - the
    criterion's bounds and the measured value sit next to each other on the
    card. Decided here by ``compute_tolerance_result``, the module's own judge,
    so the assertion cannot drift from the rule the application applies.
    """
    project_id = await _make_project(pg_session, "Causeway")
    await seed_construction_control_demo(pg_session, [project_id])
    await pg_session.flush()

    criteria = {
        c.id: c
        for c in (
            (await pg_session.execute(select(AcceptanceCriterion).where(AcceptanceCriterion.project_id == project_id)))
            .scalars()
            .all()
        )
    }
    tests = (
        (await pg_session.execute(select(LabTestResult).where(LabTestResult.project_id == project_id))).scalars().all()
    )
    recorded = [t for t in tests if t.status == "recorded"]
    assert recorded, "no lab result was recorded at all"
    assert any(t.result == "fail" for t in recorded), "every result passed, so the failing branch is never shown"

    for test in recorded:
        criterion = criteria[uuid.UUID(test.criterion_id)]
        judged = compute_tolerance_result(criterion, test.measured_value)
        assert judged != "not_assessed", (
            f"{test.result_number} was recorded against {criterion.code}, which cannot judge it numerically"
        )
        expected = "pass" if judged == "within" else "fail"
        assert test.result == expected, (
            f"{test.result_number} reads {test.result!r} on {test.measured_value} {test.unit}, "
            f"but {criterion.code} judges that {judged}"
        )
        assert test.tested_at, f"{test.result_number} is recorded with no test date"
        if test.result == "fail":
            assert test.raised_ncr_id, f"{test.result_number} failed but raised no non-conformance"

    # A draft result is the sample still with the laboratory: no number, no
    # verdict. A draft carrying a result would be a verdict nobody reached.
    for test in (t for t in tests if t.status == "draft"):
        assert test.result is None
        assert test.measured_value is None

    # As-builts: the tolerance verdict is the judge's, and the legal attestation
    # is never reached without a signature or on an out-of-tolerance survey.
    records = (
        (await pg_session.execute(select(AsBuiltRecord).where(AsBuiltRecord.project_id == project_id))).scalars().all()
    )
    assert records, "no as-built record was seeded"
    for record in records:
        criterion = criteria[uuid.UUID(record.criterion_id)]
        assert record.tolerance_result == compute_tolerance_result(criterion, record.measured_value)
        if record.valid_for_legal_record:
            assert record.status == "recorded"
            assert record.validity_signed_by and record.validity_signed_at
            assert record.tolerance_result == "within", (
                f"{record.record_number} is attested for the legal record while out of tolerance"
            )
        # A free-text column that a person reads. A bare identifier here is the
        # defect that printed a raw UUID under an inspector column elsewhere.
        assert record.surveyed_by and not _looks_like_an_id(record.surveyed_by)
        if record.deviation_value is not None and criterion.nominal_value is not None:
            assert Decimal(record.deviation_value) == Decimal(record.measured_value) - Decimal(criterion.nominal_value)


def _looks_like_an_id(value: str) -> bool:
    """The same cheap shape test ``app.core.party_names`` uses for a UUID."""
    return len(value) == 36 and value[8] == value[13] == value[18] == value[23] == "-"


async def test_a_released_gate_was_released_by_someone_who_could_release_it(pg_session) -> None:
    """A gate that is closed while its criterion is unmet is the nonsense to catch."""
    project_id = await _make_project(pg_session, "Embankment")
    await seed_construction_control_demo(pg_session, [project_id])
    await pg_session.flush()

    inspections = {
        i.id: i
        for i in (
            (await pg_session.execute(select(Inspection).where(Inspection.project_id == project_id))).scalars().all()
        )
    }
    gates = (await pg_session.execute(select(HoldGate).where(HoldGate.project_id == project_id))).scalars().all()
    assert gates, "no gate was seeded"
    assert any(g.status == "released" for g in gates), "no gate is released"
    assert any(g.status == "pending" for g in gates), "every gate is released, which is not a live project"

    for gate in gates:
        if gate.status == "released":
            assert gate.released_by and gate.released_at and gate.released_party_role
            assert party_role_satisfies(gate.released_party_role, gate.required_party_role), (
                f"{gate.gate_number} requires {gate.required_party_role} and was released by "
                f"{gate.released_party_role}, which the module would refuse"
            )
            # The gate's whole purpose: it is not released until the inspection
            # that satisfies it has actually passed.
            satisfied_by = inspections[uuid.UUID(gate.inspection_id)]
            assert satisfied_by.result == "pass", (
                f"{gate.gate_number} was released against inspection "
                f"{satisfied_by.inspection_number}, whose result is {satisfied_by.result!r}"
            )
        if gate.status == "waived":
            # A hold point can never be waived - the module refuses it outright.
            assert gate.point_type != "hold", f"{gate.gate_number} is a waived hold point"
            assert gate.waived_by and gate.waived_reason


async def test_the_handover_gate_is_the_modules_own_gate(pg_session) -> None:
    """The completion gate on the package is what ``validate_gates`` recomputes.

    Recomputing rather than restating is the point: the seeder never writes
    ``gating_state`` itself, it lets ``assemble`` derive it, so this test proves
    the derived value survived and still agrees with the evidence underneath it.
    """
    project_id = await _make_project(pg_session, "Foreshore")
    await seed_construction_control_demo(pg_session, [project_id])
    await pg_session.flush()

    packages = (
        (await pg_session.execute(select(HandoverPackage).where(HandoverPackage.project_id == project_id)))
        .scalars()
        .all()
    )
    assert packages, "no handover package was seeded"

    pending_blocking = (
        await pg_session.execute(
            select(func.count())
            .select_from(HoldGate)
            .where(HoldGate.project_id == project_id)
            .where(HoldGate.blocks_progress.is_(True))
            .where(HoldGate.status == "pending")
        )
    ).scalar_one()

    service = HandoverService(pg_session)
    for package in packages:
        assert package.assembled_at, f"{package.package_number} was never assembled"
        assert package.unreleased_hold_count == pending_blocking, (
            f"{package.package_number} reports {package.unreleased_hold_count} unreleased holds, "
            f"the project has {pending_blocking}"
        )
        expected_state = "clear" if package.open_ncr_count == 0 and package.unreleased_hold_count == 0 else "blocked"
        assert package.gating_state == expected_state
        # An unissued certificate is not a decoration: a package may only reach
        # ``issued`` from a gate that is clear or overridden.
        if package.status == "issued":
            assert service.can_issue(package)
        else:
            assert package.certificate_no is None and package.issued_at is None

        # And the gate holds when recomputed from scratch, not only as stored.
        revalidated, _blocking = await service.validate_gates(package.id)
        assert revalidated.gating_state == package.gating_state
        assert revalidated.unreleased_hold_count == package.unreleased_hold_count


async def test_construction_control_second_pass_adds_nothing(pg_session) -> None:
    """Running the construction-control seed twice must not double the register."""
    project_id = await _make_project(pg_session, "Slipway")

    await seed_construction_control_demo(pg_session, [project_id])
    await pg_session.flush()
    before = {
        model.__name__: await _count(pg_session, model, project_id)
        for model in (Inspection, AcceptanceCriterion, MaterialRecord, LabTestResult, HoldGate, HandoverPackage)
    }
    assert before["Inspection"] > 0

    second = await seed_construction_control_demo(pg_session, [project_id])
    await pg_session.flush()

    assert second["inspections"] == 0, f"the second pass wrote {second['inspections']} inspection(s) again"
    assert second["handover_packages"] == 0
    for model in (Inspection, AcceptanceCriterion, MaterialRecord, LabTestResult, HoldGate, HandoverPackage):
        assert await _count(pg_session, model, project_id) == before[model.__name__]


# ── The self-gate the three share ─────────────────────────────────────────────


async def test_none_of_the_three_writes_to_a_project_that_is_not_a_demo(pg_session) -> None:
    """``enrich_all`` hands these seeders a customer's live project too.

    Every one of them selects every project in the database, so the only thing
    standing between a paying installation and a register of invented pile caps
    is the demo marker each seeder checks for itself.
    """
    live_id = await _make_project(pg_session, "Livework", is_demo=False)

    closeout = await seed_closeout_demo(pg_session, [live_id])
    commissioning = await seed_commissioning_demo(pg_session, [live_id])
    control = await seed_construction_control_demo(pg_session, [live_id])
    await pg_session.flush()

    assert closeout["packages"] == 0
    assert commissioning["systems"] == 0
    assert control["inspections"] == 0
    assert await _count(pg_session, CloseoutPackage, live_id) == 0
    assert await _count(pg_session, CxSystem, live_id) == 0
    assert await _count(pg_session, Inspection, live_id) == 0


async def test_one_unseedable_project_does_not_cost_the_others(pg_session) -> None:
    """The per-project SAVEPOINT, which a plain try/except cannot give on PostgreSQL.

    A failed statement aborts the whole transaction, so without the savepoint a
    single bad project would leave every later project failing on a poisoned
    session rather than on anything wrong with itself. Forced here by handing
    the seeders a project id that does not exist alongside real ones.
    """
    first = await _make_project(pg_session, "Northgate")
    second = await _make_project(pg_session, "Southgate")
    ghost = uuid.uuid4()

    counts = await seed_commissioning_demo(pg_session, [first, ghost, second])
    await pg_session.flush()

    assert counts["projects"] == 2, "a project was lost to its neighbour's failure"
    assert await _count(pg_session, CxSystem, first) > 0
    assert await _count(pg_session, CxSystem, second) > 0


async def test_no_two_projects_get_the_same_register(pg_session) -> None:
    """A reader flipping between demo projects must see a different picture each time.

    Six projects, not two. The per-project sizes are drawn from short tuples,
    and a wrap that adds too little would put a later project back onto an
    earlier one's register while a two-project test stayed green.
    """
    names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]
    projects = [await _make_project(pg_session, name) for name in names]

    await seed_commissioning_demo(pg_session, projects)
    await seed_construction_control_demo(pg_session, projects)
    await seed_closeout_demo(pg_session, projects)
    await pg_session.flush()

    async def _shape(project_id: uuid.UUID) -> tuple:
        systems = (
            await pg_session.execute(
                select(func.count()).select_from(CxSystem).where(CxSystem.project_id == project_id)
            )
        ).scalar_one()
        inspections = await _count(pg_session, Inspection, project_id)
        template = (
            await pg_session.execute(
                select(CloseoutPackage.checklist_template).where(CloseoutPackage.project_id == project_id)
            )
        ).scalar_one()
        types = sorted(
            (await pg_session.execute(select(CxSystem.system_type).where(CxSystem.project_id == project_id).distinct()))
            .scalars()
            .all()
        )
        return (systems, inspections, template, tuple(types))

    seen: dict[tuple, str] = {}
    for name, project_id in zip(names, projects, strict=True):
        shape = await _shape(project_id)
        assert shape[0] > 0 and shape[1] > 0, f"{name} got no register at all"
        clash = seen.get(shape)
        assert clash is None, f"{name} and {clash} rendered the same register"
        seen[shape] = name
