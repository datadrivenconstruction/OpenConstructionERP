# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the guided adoption checklist service (#22).

PostgreSQL, py3.12. Seeds one project's real first-value records - a BOQ, a
takeoff measurement, an approval instance against a project route, a change
order, an AI run with a recorded verdict, the activity-log row an evidence pack
assembly lands, and the row a value-report generation lands - then drives the
thin adoption service over the pure checklist engine, checking that each step is
marked done from project STATE (not event logging), that a run with no recorded
verdict leaves the verdict step open, that a generated value report completes the
path, and that the role lens scopes which steps apply.

These live under tests/modules (the single non-sharded job) on purpose: they are
not part of the pytest-split unit matrix, so adding them never reshuffles the
unit shards.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import ActivityLog
from app.modules.ai_agents.models import AgentRun
from app.modules.approval_routes.models import Instance as ApprovalInstance
from app.modules.approval_routes.models import Route as ApprovalRoute
from app.modules.boq.models import BOQ
from app.modules.changeorders.models import ChangeOrder
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.takeoff.models import TakeoffMeasurement
from app.modules.users.models import User
from app.modules.value.adoption_service import (
    KEY_AI_RUN,
    KEY_AI_VERDICT,
    KEY_APPROVAL,
    KEY_BOQ,
    KEY_CHANGE_ORDER,
    KEY_EVIDENCE_PACK,
    KEY_PROJECT_CREATED,
    KEY_TAKEOFF,
    KEY_VALUE_REPORT,
    build_adoption_checklist,
    gather_observed_action_keys,
)
from tests._pg import transactional_session

NOW = datetime(2026, 6, 25, tzinfo=UTC)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"adopt-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Adopt",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Adopt {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


async def _seed_approval(session: AsyncSession, project_id: uuid.UUID) -> None:
    """A project route with one running instance (the 'approval started' signal)."""
    route = ApprovalRoute(project_id=project_id, name="R", target_kind="change_order")
    session.add(route)
    await session.flush()
    session.add(
        ApprovalInstance(
            route_id=route.id,
            target_kind="change_order",
            target_id=uuid.uuid4(),
            started_at=NOW,
        )
    )


def _evidence_pack_row(project_id: uuid.UUID) -> ActivityLog:
    """The activity-log row an evidence-pack assembly already lands."""
    return ActivityLog(
        entity_type="claims_evidence.pack",
        entity_id=str(uuid.uuid4()),
        action="evidence_pack_assembled",
        module="claims_evidence",
        parent_entity_type="project",
        parent_entity_id=str(project_id),
        created_at=NOW,
    )


def _value_report_row(project_id: uuid.UUID) -> ActivityLog:
    """The activity-log row the value router's POST .../report lands."""
    return ActivityLog(
        entity_type="value.report",
        entity_id=str(project_id),
        action="report_generated",
        module="value",
        parent_entity_type="project",
        parent_entity_id=str(project_id),
        created_at=NOW,
    )


@pytest.mark.asyncio
async def test_empty_project_only_has_project_created(session: AsyncSession) -> None:
    pid = await _project(session)

    observed = await gather_observed_action_keys(session, pid)
    assert observed == frozenset({KEY_PROJECT_CREATED})

    checklist = await build_adoption_checklist(session, pid, "manager")
    done = {s.step.key for s in checklist.steps if s.done}
    assert done == {"create_project"}
    # A just-created project is at the very start of the path, so the score is low
    # and the engine nudges the next concrete steps.
    assert checklist.adoption_score < 50
    assert len(checklist.next_actions) > 0


@pytest.mark.asyncio
async def test_all_core_milestones_marked_done(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add(BOQ(project_id=pid, name="Main BOQ"))
    session.add(TakeoffMeasurement(project_id=pid, type="area"))
    await _seed_approval(session, pid)
    session.add(ChangeOrder(project_id=pid, code="CO-1", title="Change", status="submitted"))
    session.add(
        AgentRun(
            agent_name="estimator",
            user_id=uuid.uuid4(),
            project_id=pid,
            status="completed",
            trust={"confidence": 0.8, "actual_outcome": True},
        )
    )
    session.add(_evidence_pack_row(pid))
    await session.flush()

    observed = await gather_observed_action_keys(session, pid)
    assert observed == frozenset(
        {
            KEY_PROJECT_CREATED,
            KEY_BOQ,
            KEY_TAKEOFF,
            KEY_APPROVAL,
            KEY_CHANGE_ORDER,
            KEY_AI_RUN,
            KEY_AI_VERDICT,
            KEY_EVIDENCE_PACK,
        }
    )

    checklist = await build_adoption_checklist(session, pid, "manager")
    done = {s.step.key for s in checklist.steps if s.done}
    # Every milestone except the value report is done; this project has not had a
    # value report generated yet, so it is the single honest nudge.
    assert "generate_value_report" not in done
    assert {s.step.key for s in checklist.steps if not s.done} == {"generate_value_report"}
    assert [a.key for a in checklist.next_actions] == ["generate_value_report"]
    assert checklist.adoption_score >= 80


@pytest.mark.asyncio
async def test_generated_value_report_completes_the_path(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add(BOQ(project_id=pid, name="Main BOQ"))
    session.add(TakeoffMeasurement(project_id=pid, type="area"))
    await _seed_approval(session, pid)
    session.add(ChangeOrder(project_id=pid, code="CO-1", title="Change", status="submitted"))
    session.add(
        AgentRun(
            agent_name="estimator",
            user_id=uuid.uuid4(),
            project_id=pid,
            status="completed",
            trust={"confidence": 0.8, "actual_outcome": True},
        )
    )
    session.add(_evidence_pack_row(pid))
    session.add(_value_report_row(pid))
    await session.flush()

    observed = await gather_observed_action_keys(session, pid)
    assert KEY_VALUE_REPORT in observed

    checklist = await build_adoption_checklist(session, pid, "manager")
    # With a value report generated on top of every other milestone, every step
    # the manager is asked to do is done and there is nothing left to nudge.
    assert all(s.done for s in checklist.steps)
    # ``next_actions`` is a tuple on the frozen dataclass, and ``() == []`` is
    # False whatever it holds, so comparing against a list could never pass.
    assert checklist.next_actions == ()
    assert checklist.adoption_score == 100


@pytest.mark.asyncio
async def test_ai_run_without_recorded_verdict_leaves_verdict_open(session: AsyncSession) -> None:
    pid = await _project(session)
    # A run with a trust envelope but no recorded outcome: the run counts, the
    # verdict does not.
    session.add(
        AgentRun(
            agent_name="estimator",
            user_id=uuid.uuid4(),
            project_id=pid,
            status="completed",
            trust={"confidence": 0.7},
        )
    )
    await session.flush()

    observed = await gather_observed_action_keys(session, pid)
    assert KEY_AI_RUN in observed
    assert KEY_AI_VERDICT not in observed


@pytest.mark.asyncio
async def test_run_with_null_trust_is_a_run_but_no_verdict(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add(
        AgentRun(
            agent_name="estimator",
            user_id=uuid.uuid4(),
            project_id=pid,
            status="running",
            trust=None,
        )
    )
    await session.flush()

    observed = await gather_observed_action_keys(session, pid)
    assert KEY_AI_RUN in observed
    assert KEY_AI_VERDICT not in observed


@pytest.mark.asyncio
async def test_role_lens_scopes_applicable_steps(session: AsyncSession) -> None:
    pid = await _project(session)

    manager = await build_adoption_checklist(session, pid, "manager")
    field = await build_adoption_checklist(session, pid, "field")

    manager_keys = {s.step.key for s in manager.steps}
    field_keys = {s.step.key for s in field.steps}

    # The field role is not asked to do the office-heavy steps, so its path is a
    # strict subset of the manager's and excludes the value report.
    assert field_keys < manager_keys
    assert "generate_value_report" in manager_keys
    assert "generate_value_report" not in field_keys


@pytest.mark.asyncio
async def test_detection_is_project_scoped(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    # State on another project must never count for this one - neither a table row
    # (a BOQ) nor an activity-log milestone (an evidence pack, a value report),
    # which exercises the scoping of both detection paths.
    session.add(BOQ(project_id=other, name="Other BOQ"))
    session.add(_evidence_pack_row(other))
    session.add(_value_report_row(other))
    await session.flush()

    observed = await gather_observed_action_keys(session, pid)
    assert KEY_BOQ not in observed
    assert KEY_EVIDENCE_PACK not in observed
    assert KEY_VALUE_REPORT not in observed
    assert observed == frozenset({KEY_PROJECT_CREATED})
