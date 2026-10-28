# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The quality concept demo seed, run after the seeders it reads from.

The seed goes through the service, so what is asserted here is what a user
would see on the screens: every register filled, the concept free of
completeness errors, stages under way through a real hold gate, and no demo
system that could be commissioned before the seed held back after it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.modules.closeout.seed import seed_closeout_demo
from app.modules.commissioning.models import CxSystem
from app.modules.commissioning.seed import seed_commissioning_demo
from app.modules.construction_control.models import HoldGate
from app.modules.construction_control.seed import seed_construction_control_demo
from app.modules.projects.models import Project
from app.modules.quality_concept import evaluator as ev
from app.modules.quality_concept.models import (
    AcceptanceUnit,
    AppliedStandard,
    CertificationTarget,
    CommissioningStageDef,
    CreditTarget,
    EvidenceLink,
    ExpertReportPlan,
    PreservationSurvey,
    ProofRequirement,
    QualityConcept,
    QualityConceptRevision,
    StageProgress,
)
from app.modules.quality_concept.seed import seed_quality_concept_demo
from app.modules.quality_concept.service import QualityConceptService
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

_REGISTERS = (
    AppliedStandard,
    CertificationTarget,
    CreditTarget,
    ProofRequirement,
    EvidenceLink,
    CommissioningStageDef,
    StageProgress,
    AcceptanceUnit,
    ExpertReportPlan,
    PreservationSurvey,
)


async def _user(session, role: str) -> uuid.UUID:
    uid = uuid.uuid4()
    session.add(
        User(
            id=uid,
            email=f"{role}-{uid.hex[:8]}@example.test",
            hashed_password="x",
            full_name=f"Seed {role}",
            role=role,
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.flush()
    return uid


async def _project(session, owner: uuid.UUID, *, demo: bool) -> uuid.UUID:
    pid = uuid.uuid4()
    session.add(
        Project(
            id=pid,
            name=f"Seed {pid.hex[:6]}",
            description="Quality concept seed fixture",
            currency="EUR",
            status="active",
            owner_id=owner,
            metadata_={"is_demo": True, "demo_id": "fixture"} if demo else {},
        )
    )
    await session.flush()
    return pid


async def _member(session, pid: uuid.UUID, user_id: uuid.UUID) -> None:
    from app.modules.teams.models import Team, TeamMembership

    team = Team(project_id=pid, name="Core")
    session.add(team)
    await session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=user_id))
    await session.flush()


async def _rows_naming(session, pid: uuid.UUID, user_id: uuid.UUID) -> list[str]:
    """Every seeded row of the project that carries this user in any column, as ``Model.column``."""
    wanted = str(user_id)
    found = []
    for model in (*_REGISTERS, QualityConcept, QualityConceptRevision, HoldGate):
        rows = (await session.execute(select(model).where(model.project_id == pid))).scalars()
        for row in rows:
            for column in row.__mapper__.column_attrs:
                value = getattr(row, column.key)
                values = value if isinstance(value, list) else [value]
                if any(str(v) == wanted for v in values):
                    found.append(f"{model.__name__}.{column.key}")
    return sorted(set(found))


async def _counts(session, pid: uuid.UUID) -> dict[str, int]:
    out = {}
    for model in _REGISTERS:
        stmt = select(func.count()).select_from(model).where(model.project_id == pid)
        out[model.__name__] = (await session.execute(stmt)).scalar_one()
    return out


async def test_the_demo_seed_fills_every_register_once_and_holds_no_system_back(pg_session) -> None:
    manager = await _user(pg_session, "manager")
    # An account that exists in the installation and is not on the project: never part of the demo.
    outsider = await _user(pg_session, "editor")
    colleague = await _user(pg_session, "editor")
    pid = await _project(pg_session, manager, demo=True)
    await _member(pg_session, pid, colleague)
    live = await _project(pg_session, manager, demo=False)
    await seed_construction_control_demo(pg_session, [pid])
    await seed_commissioning_demo(pg_session, [pid])
    await seed_closeout_demo(pg_session, [pid])
    await pg_session.flush()
    systems = list((await pg_session.execute(select(CxSystem).where(CxSystem.project_id == pid))).scalars())
    statuses = {x.id: x.status for x in systems}
    assert {"in_progress", "tests_complete", "commissioned"} <= set(statuses.values())

    totals = await seed_quality_concept_demo(pg_session, [pid, live])
    await pg_session.flush()
    assert totals["projects"] == 1, totals

    # Every list a screen reads has rows.
    counts = await _counts(pg_session, pid)
    assert all(counts.values()), counts
    svc = QualityConceptService(pg_session)
    assert await svc.list_requirements(pid)

    # The plan is complete: nothing the concept screen would show as an error.
    concept = await svc.require_concept(pid)
    errors = [f.as_dict() for f in await svc.completeness(concept) if f.severity == ev.ERROR]
    assert errors == []
    payload = await svc.validation_payload(pid, datetime.now(UTC).date())
    assert payload["partial_scoped"] == []
    assert payload["stage_order_violations"] == []
    assert payload["released_without_gate"] == []
    assert all(stage["owner_user_id"] for stage in payload["stages"])

    # Systems the commissioning demo shows as tested or commissioned are not held back.
    assert payload["commissioned_outside"] == []
    for system in systems:
        if system.status in ("tests_complete", "commissioned"):
            assert await svc.final_stage_blockers(pid, system.id) == [], system.tag
    assert {x.id: x.status for x in systems} == statuses

    # The matrix shows work under way, and the released stage was released by its gate.
    rows = await svc.repo.list(StageProgress, pid)
    states = {r.state for r in rows}
    assert {"released", "in_test", "passed", "blocked"} <= states, states
    released = next(r for r in rows if r.state == "released")
    gate = await pg_session.get(HoldGate, released.hold_gate_id)
    assert (gate.status, gate.attached_kind, gate.attached_id) == ("released", "cx_stage", str(released.id))
    assert released.released_by is not None

    # The people of the demo are the project's own: its owner records, a team member signs off.
    assert await _rows_naming(pg_session, pid, outsider) == []
    assert concept.created_by == manager
    assert str(gate.released_by) == str(colleague)

    # Proofs carry evidence from the project's own records, accepted by someone else than the linker.
    proofs = await svc.repo.list(ProofRequirement, pid)
    assert {p.package_ref for p in proofs} == {"PKG-STR", "PKG-MEP"}
    accepted = [p for p in proofs if p.decision == "accepted"]
    assert accepted
    links = await svc.repo.links_for("proof", [p.id for p in accepted])
    assert all(link.created_by != p.decided_by for p in accepted for link in links if link.owner_id == p.id)
    assert any(p.requested_by is not None and p.decision == "none" for p in proofs)

    # Certification: at least one target registered with a credit achieved.
    targets = await svc.repo.list(CertificationTarget, pid)
    assert "registered" in {t.state for t in targets}
    assert "achieved" in {c.state for c in await svc.repo.list(CreditTarget, pid)}

    # Chronology: what is recorded lies in the past, what is planned for acceptance in the future.
    today = datetime.now(UTC).date().isoformat()
    surveys = await svc.repo.list(PreservationSurvey, pid)
    assert all(x.survey_date <= today for x in surveys if x.survey_date)
    assert any(x.survey_date for x in surveys)
    assert all(u.planned_date > today for u in await svc.repo.list(AcceptanceUnit, pid))

    # A second run adds nothing, and a live project is never written to.
    again = await seed_quality_concept_demo(pg_session, [pid, live])
    await pg_session.flush()
    assert again["projects"] == 0
    assert await _counts(pg_session, pid) == counts
    stmt = select(func.count()).select_from(QualityConcept).where(QualityConcept.project_id == live)
    assert (await pg_session.execute(stmt)).scalar_one() == 0


async def test_a_project_with_nobody_but_its_owner_is_seeded_without_a_warning(pg_session, caplog) -> None:
    """Two-person steps are left out, said at info level; no account from outside the project stands in."""
    owner = await _user(pg_session, "manager")
    outsider = await _user(pg_session, "editor")
    pid = await _project(pg_session, owner, demo=True)
    await seed_construction_control_demo(pg_session, [pid])
    await seed_commissioning_demo(pg_session, [pid])
    await seed_closeout_demo(pg_session, [pid])
    await pg_session.flush()

    with caplog.at_level(logging.INFO, logger="app.modules.quality_concept"):
        totals = await seed_quality_concept_demo(pg_session, [pid])
    await pg_session.flush()
    assert totals["projects"] == 1, totals
    loud = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING and "quality_concept" in r.name]
    assert loud == []

    svc = QualityConceptService(pg_session)
    assert await _rows_naming(pg_session, pid, outsider) == []
    assert "accepted" not in {p.decision for p in await svc.repo.list(ProofRequirement, pid)}
    assert "released" not in {r.state for r in await svc.repo.list(StageProgress, pid)}


async def test_a_project_before_its_construction_gate_gets_the_plan_and_nothing_delivered(pg_session) -> None:
    """The story is chosen by the state of the project: the gate into construction exists and is undecided."""
    from datetime import timedelta

    from app.modules.project_governance.service import GovernanceService

    manager = await _user(pg_session, "manager")
    pid = await _project(pg_session, manager, demo=True)
    await GovernanceService(pg_session).set_model(
        pid,
        source="shipped",
        catalogue_id="neutral",
        version=None,
        four_eyes=True,
        actor_id=manager,
        tenant_id=str(manager),
    )
    await seed_commissioning_demo(pg_session, [pid])
    await pg_session.flush()

    totals = await seed_quality_concept_demo(pg_session, [pid])
    await pg_session.flush()
    assert totals["projects"] == 1, totals

    svc = QualityConceptService(pg_session)
    concept = await svc.require_concept(pid)
    assert concept.state == "draft"
    assert [f.as_dict() for f in await svc.completeness(concept) if f.severity == ev.ERROR] == []
    counts = await _counts(pg_session, pid)
    for register in ("AppliedStandard", "CertificationTarget", "ProofRequirement", "CommissioningStageDef"):
        assert counts[register], register
    # Nothing is built: no evidence, no decision, no system tested, no survey or report carried out.
    assert counts["EvidenceLink"] == 0
    assert {p.decision for p in await svc.repo.list(ProofRequirement, pid)} == {"none"}
    assert {r.state for r in await svc.repo.list(StageProgress, pid)} <= {"blocked", "ready"}
    assert {t.state for t in await svc.repo.list(CertificationTarget, pid)} == {"planned"}
    assert {c.state for c in await svc.repo.list(CreditTarget, pid)} == {"targeted"}
    assert all(stage.owner_user_id for stage in await svc.repo.list(CommissioningStageDef, pid))

    today = datetime.now(UTC).date()
    start = (today + timedelta(days=190)).isoformat()
    units = await svc.repo.list(AcceptanceUnit, pid)
    assert {u.regime_code for u in units} == {"de_vob_b"}
    assert {u.state for u in units} == {"planned"}
    assert all(u.planned_date > start for u in units)
    reports = await svc.repo.list(ExpertReportPlan, pid)
    assert {r.state for r in reports} == {"planned"}
    assert all(due > start for r in reports for due in r.due_dates)
    surveys = await svc.repo.list(PreservationSurvey, pid)
    assert {x.subject_kind for x in surveys} >= {"neighbour_building"}
    assert all(x.state == "planned" and x.survey_date is None for x in surveys)
    # Planned shortly before the start of construction, not after it.
    assert all((today + timedelta(days=150)).isoformat() < x.planned_date < start for x in surveys)
