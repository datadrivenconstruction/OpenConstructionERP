"""Commissioning rules: each rule fires, a valid record passes, errors block the write with a code."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.core.validation.engine import ValidationContext
from app.modules.commissioning.schemas import (
    ChecklistCreate,
    IssueCreate,
    IssueUpdate,
    ItemCreate,
    ItemResultRequest,
    SystemCreate,
    SystemUpdate,
)
from app.modules.commissioning.service import CommissioningService
from app.modules.commissioning.validators import (
    COMMISSIONING_RULES,
    FailedTestNeedsNoteRule,
    FunctionalAfterPrefunctionalRule,
    IssueClosedHasResolutionRule,
    SystemTestsCompleteRule,
    register_commissioning_validation_rules,
)
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


def _issue(**kw: object) -> dict:
    return {"issue": {"id": "x1", "severity": "critical", "status": "closed", "resolution": "Valve replaced", **kw}}


def _system(**kw: object) -> dict:
    return {"system": {"id": "s1", "status": "tests_complete", "can_commission": True, **kw}}


def _result(pre_failed: int = 0, pre_pending: int = 0, **kw: object) -> dict:
    return {
        "result": {"id": "r1", "kind": "functional", "status": "pass", "result_note": "ok", **kw},
        "prefunctional": {"failed": pre_failed, "pending": pre_pending},
    }


FIRING = [
    (IssueClosedHasResolutionRule, _issue(resolution=" ")),
    (SystemTestsCompleteRule, _system(can_commission=False)),
    (FunctionalAfterPrefunctionalRule, _result(pre_failed=1)),
    (FunctionalAfterPrefunctionalRule, _result(pre_pending=2)),
    (FailedTestNeedsNoteRule, _result(status="fail", result_note=None)),
]


@pytest.mark.parametrize(("rule_class", "data"), FIRING)
async def test_each_rule_fires(rule_class, data) -> None:
    failed = [r for r in await _run(rule_class(), data) if not r.passed]
    assert failed
    assert "commissioning." not in failed[0].message
    assert failed[0].suggestion


@pytest.mark.parametrize("rule_class", COMMISSIONING_RULES)
async def test_a_valid_record_passes_every_rule(rule_class) -> None:
    for data in (_issue(), _system(), _result()):
        assert all(r.passed for r in await _run(rule_class(), data))


@pytest.mark.parametrize("rule_class", COMMISSIONING_RULES)
async def test_an_open_or_pending_record_is_not_flagged(rule_class) -> None:
    open_issue = _issue(status="open", resolution=None)
    started = _system(status="in_progress", can_commission=False)
    pending = _result(pre_failed=3, status="pending", result_note=None)
    for data in (open_issue, started, pending):
        assert all(r.passed for r in await _run(rule_class(), data))


async def test_severity_decides_whether_a_missing_resolution_blocks() -> None:
    hard = await _run(IssueClosedHasResolutionRule(), _issue(severity="high", resolution=None))
    soft = await _run(IssueClosedHasResolutionRule(), _issue(severity="low", resolution=None))
    assert [str(r.severity) for r in hard] == ["error"]
    assert [str(r.severity) for r in soft] == ["warning"]


async def test_open_prefunctional_items_warn_and_failed_ones_block() -> None:
    open_ = await _run(FunctionalAfterPrefunctionalRule(), _result(pre_pending=1))
    failed = await _run(FunctionalAfterPrefunctionalRule(), _result(pre_failed=1))
    assert [str(r.severity) for r in open_] == ["warning"]
    assert [str(r.severity) for r in failed] == ["error"]


async def test_messages_follow_the_locale() -> None:
    fr = await _run(FailedTestNeedsNoteRule(), _result(status="fail", result_note=None), locale="fr")
    assert "essai" in fr[0].message


@pytest_asyncio.fixture
async def session():
    register_commissioning_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"cx-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _system_with_items(s):
    p = Project(id=uuid.uuid4(), name="Plant", owner_id=OWNER_ID, currency="EUR", country_code="DE")
    s.add(p)
    await s.flush()
    svc = CommissioningService(s)
    system = await svc.create_system(SystemCreate(project_id=p.id, name="AHU-1"))
    pre = await svc.create_checklist(system.id, ChecklistCreate(kind="prefunctional", title="Installation"))
    fun = await svc.create_checklist(system.id, ChecklistCreate(kind="functional", title="Airflow"))
    pre_item = await svc.create_item(pre.id, ItemCreate(description="Fan rotation checked"))
    fun_item = await svc.create_item(fun.id, ItemCreate(description="Design airflow reached"))
    return svc, system, pre_item, fun_item


async def test_closing_a_critical_issue_without_a_resolution_is_refused_with_its_code(session) -> None:
    svc, system, _pre, _fun = await _system_with_items(session)
    with pytest.raises(HTTPException) as exc:
        await svc.create_issue(system.id, IssueCreate(description="Leak", severity="critical", status="closed"))
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "commissioning.issue_closed_has_resolution"

    issue = await svc.create_issue(system.id, IssueCreate(description="Leak", severity="critical"))
    with pytest.raises(HTTPException) as exc:
        await svc.update_issue(issue.id, IssueUpdate(status="closed"))
    assert exc.value.detail["code"] == "commissioning.issue_closed_has_resolution"
    closed = await svc.update_issue(issue.id, IssueUpdate(status="closed", resolution="Gasket replaced"))
    assert closed.status == "closed"


async def test_tests_complete_needs_the_functional_tests_passed(session) -> None:
    svc, system, _pre, fun_item = await _system_with_items(session)
    with pytest.raises(HTTPException) as exc:
        await svc.update_system(system.id, SystemUpdate(status="tests_complete"))
    assert exc.value.detail["code"] == "commissioning.tests_complete_requires_passed_tests"
    await svc.set_item_result(fun_item.id, ItemResultRequest(status="pass"))
    updated = await svc.update_system(system.id, SystemUpdate(status="tests_complete"))
    assert updated.status == "tests_complete"


async def test_a_functional_pass_after_a_failed_prefunctional_check_is_refused(session) -> None:
    svc, _system, pre_item, fun_item = await _system_with_items(session)
    await svc.set_item_result(pre_item.id, ItemResultRequest(status="fail", result_note="Wrong rotation"))
    with pytest.raises(HTTPException) as exc:
        await svc.set_item_result(fun_item.id, ItemResultRequest(status="pass"))
    assert exc.value.detail["code"] == "commissioning.functional_after_prefunctional"


async def test_a_failed_result_without_a_note_is_recorded_with_a_warning(session) -> None:
    svc, _system, pre_item, _fun = await _system_with_items(session)
    item = await svc.set_item_result(pre_item.id, ItemResultRequest(status="fail"))
    assert item.status == "fail"
    assert [f["code"] for f in svc.findings] == ["commissioning.failed_test_needs_note"]


async def test_create_paths_cannot_skip_the_result_and_status_rules(session) -> None:
    svc, system, pre_item, _fun = await _system_with_items(session)
    with pytest.raises(HTTPException) as exc:
        await svc.create_system(SystemCreate(project_id=system.project_id, name="AHU-2", status="tests_complete"))
    assert exc.value.detail["code"] == "commissioning.tests_complete_requires_passed_tests"

    await svc.set_item_result(pre_item.id, ItemResultRequest(status="fail", result_note="Wrong rotation"))
    fun = await svc.create_checklist(system.id, ChecklistCreate(kind="functional", title="Pressure"))
    with pytest.raises(HTTPException) as exc:
        await svc.create_item(fun.id, ItemCreate(description="Held", status="pass"))
    assert exc.value.detail["code"] == "commissioning.functional_after_prefunctional"


async def test_editing_an_unrelated_issue_field_is_not_blocked_by_an_old_gap(session) -> None:
    svc, system, _pre, _fun = await _system_with_items(session)
    issue = await svc.create_issue(system.id, IssueCreate(description="Leak", severity="critical"))
    updated = await svc.update_issue(issue.id, IssueUpdate(description="Leak at flange"))
    assert updated.description == "Leak at flange"
