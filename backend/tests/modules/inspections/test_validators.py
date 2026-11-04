# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Inspection rule set: each rule has a passing and a failing payload."""

from __future__ import annotations

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.inspections.validators import (
    INSPECTIONS_RULE_SET,
    InspectionCompletedHasInspectorRule,
    InspectionCompletedHasResultRule,
    InspectionNotOverdueRule,
    InspectionResultMatchesChecklistRule,
    register_inspections_validation_rules,
)


def _insp(**kw: object) -> dict:
    base = {
        "id": "i1",
        "status": "completed",
        "result": "pass",
        "inspector_id": "u1",
        "inspection_date": "2026-11-01",
        "checklist_data": [{"response": "yes"}, {"response": "pass"}],
    }
    base.update(kw)
    return {"inspection": base}


async def _run(rule: object, data: dict, locale: str = "en", today: str = "2026-11-04"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale, "today": today}))


CASES = [
    (InspectionResultMatchesChecklistRule, _insp(), _insp(checklist_data=[{"response": "yes"}, {"response": "FAIL"}])),
    (InspectionCompletedHasInspectorRule, _insp(), _insp(inspector_id=None)),
    (InspectionCompletedHasResultRule, _insp(), _insp(result="")),
    (InspectionNotOverdueRule, _insp(status="in_progress"), _insp(status="scheduled")),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES, ids=lambda v: getattr(v, "__name__", ""))
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "quality." not in failed[0].message


async def test_failed_result_with_failed_items_is_consistent() -> None:
    data = _insp(result="fail", checklist_data=[{"response": "no"}])
    assert (await _run(InspectionResultMatchesChecklistRule(), data))[0].passed


async def test_failed_item_count_in_message() -> None:
    data = _insp(checklist_data=[{"response": "no"}, {"response": "false"}, {"response": "yes"}])
    result = (await _run(InspectionResultMatchesChecklistRule(), data))[0]
    assert result.details["count"] == "2"


async def test_scheduled_today_or_undated_is_not_overdue() -> None:
    rule = InspectionNotOverdueRule()
    assert (await _run(rule, _insp(status="scheduled", inspection_date="2026-11-04")))[0].passed
    assert (await _run(rule, _insp(status="scheduled", inspection_date=None)))[0].passed
    assert (await _run(rule, _insp(status="scheduled", inspection_date="garbage")))[0].passed


async def test_datetime_date_is_accepted() -> None:
    data = _insp(status="scheduled", inspection_date="2026-10-30T08:00:00Z")
    assert not (await _run(InspectionNotOverdueRule(), data))[0].passed


async def test_message_follows_locale() -> None:
    de = await _run(InspectionCompletedHasInspectorRule(), _insp(inspector_id=""), locale="de")
    assert "fehlt" in de[0].message


def test_registered_under_rule_set() -> None:
    register_inspections_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([INSPECTIONS_RULE_SET])}
    assert len(ids) == 4
