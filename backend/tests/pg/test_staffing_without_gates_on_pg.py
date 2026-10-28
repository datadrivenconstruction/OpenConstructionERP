# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A staffing plan on a project that uses no gates is walked to the end by hand.

Without gates nothing binds a frame document, so the plan is approved through
the module's own service by a second person holding the manage right. Where
gates exist that route refuses by name and the gate decision approves.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.staffing import rules
from app.modules.staffing.errors import StaffingError
from app.modules.staffing.permissions import register_staffing_permissions
from app.modules.staffing.service import Actor, StaffingService
from tests._pg import isolated_engine
from tests.pg.staffing_fixtures import build_world, call, position, submittable_plan

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory():
    register_staffing_permissions()
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _plan(w):
    from app.modules.staffing.models import StaffingPlan

    async with w.factory() as s:
        return (await s.execute(select(StaffingPlan).where(StaffingPlan.project_id == w.project_id))).scalar_one()


def _manager(user_id) -> Actor:
    return Actor(user_id, manage=True, edit=True)


async def test_a_plan_without_gates_goes_from_draft_to_binding_by_hand_and_can_be_revised(factory) -> None:
    w = await build_world(factory, governance=False)
    await submittable_plan(w)

    view = await call(w, "plan_view", _manager(w.manager))
    assert view["gates_in_use"] is False
    assert view["can"]["submit"]["allowed"] is True
    assert view["can"]["approve"] == {"allowed": False, "reason": "plan_not_in_review", "applies": False}

    await call(w, "submit", w.manager)
    plan = await _plan(w)
    assert (plan.status, plan.governance_document_id, plan.submitted_by) == ("in_review", None, w.manager)

    # Four eyes: whoever submitted does not approve, and the view says so before the click.
    own = await call(w, "plan_view", _manager(w.manager))
    assert own["can"]["approve"] == {"allowed": False, "reason": "approver_is_submitter", "applies": True}
    with pytest.raises(StaffingError) as err:
        await call(w, "approve_by_hand", w.manager)
    assert (err.value.code, err.value.status_code) == ("approver_is_submitter", 403)
    assert (await _plan(w)).status == "in_review"

    other = await call(w, "plan_view", _manager(w.decider))
    assert other["can"]["approve"] == {"allowed": True, "reason": None, "applies": True}
    without_right = await call(w, "plan_view", Actor(w.decider, edit=True))
    assert without_right["can"]["approve"]["reason"] == "approval_permission_required"

    await call(w, "approve_by_hand", w.decider)
    plan = await _plan(w)
    assert (plan.status, plan.approved_by, plan.approval_source) == ("binding", w.decider, "hand")
    assert plan.approved_at is not None and plan.bound_snapshot["positions"]
    assert (await call(w, "plan_view", _manager(w.decider)))["can"]["approve"]["applies"] is False

    # What approval unlocks: the bound plan is the baseline, and an edit opens a revision that is approved again.
    bound = len(plan.bound_snapshot["positions"])
    await position(w, "site_manager", fte="0.50")
    assert (await _plan(w)).status == "revising"
    await call(w, "submit", w.decider)
    await call(w, "approve_by_hand", w.manager)
    plan = await _plan(w)
    assert (plan.status, plan.approved_by) == ("binding", w.manager)
    assert len(plan.bound_snapshot["positions"]) == bound + 1


async def test_hand_approval_is_refused_on_the_findings_a_submission_is_refused_on(factory, monkeypatch) -> None:
    w = await build_world(factory, governance=False)
    await submittable_plan(w)
    await call(w, "submit", w.manager)

    async def broken(self, project_id):
        return [rules.Finding("key_role_missing", "project_manager")]

    monkeypatch.setattr(StaffingService, "submission_findings", broken)
    with pytest.raises(StaffingError) as err:
        await call(w, "approve_by_hand", w.decider)
    assert (err.value.code, err.value.status_code) == ("key_role_missing", 422)
    assert [v["code"] for v in err.value.violations] == ["key_role_missing"]
    assert (await _plan(w)).status == "in_review"


async def test_where_gates_are_in_use_the_plan_is_not_approved_by_hand(factory) -> None:
    w = await build_world(factory)
    await submittable_plan(w, fill_key_roles=True)
    await call(w, "submit", w.manager)

    view = await call(w, "plan_view", _manager(w.decider))
    assert view["gates_in_use"] is True
    assert view["can"]["approve"] == {"allowed": False, "reason": "approved_by_gate_decision", "applies": False}
    with pytest.raises(StaffingError) as err:
        await call(w, "approve_by_hand", w.decider)
    assert (err.value.code, err.value.status_code) == ("approved_by_gate_decision", 409)
    assert (await _plan(w)).status == "in_review"
