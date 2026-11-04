# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The one 422 body of every rule gate, and the "only errors the edit introduces" filter."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationReport
from app.core.validation.failure import introduced_errors, raise_rule_failure, rule_failure_detail


def _result(rule_id: str, message: str, severity: Severity = Severity.ERROR) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        rule_name=rule_id,
        severity=severity,
        category=RuleCategory.CONSISTENCY,
        passed=False,
        message=message,
        details={"field": "x"},
    )


def _report(*results: RuleResult) -> ValidationReport:
    return ValidationReport(target_type="t", target_id="1", rule_sets_applied=["demo"], results=list(results))


def test_body_shape_is_complete_and_coded_by_first_rule() -> None:
    report = _report(_result("demo.a", "A broke"), _result("demo.b", "B warns", Severity.WARNING))
    detail = rule_failure_detail(report, error="demo_rules_failed")
    assert detail["error"] == "demo_rules_failed"
    assert detail["code"] == "demo.a"
    assert detail["message"] == "A broke"
    assert detail["rule_sets"] == ["demo"] and detail["rule_set"] == "demo"
    assert detail["status"] == report.status.value
    assert [r["rule_id"] for r in detail["results"]] == ["demo.a", "demo.b"]
    assert detail["results"][0]["code"] == "demo.a"
    assert detail["results"][0]["params"] == {"field": "x"}
    assert [r["rule_id"] for r in detail["errors"]] == ["demo.a"]
    assert [r["rule_id"] for r in detail["warnings"]] == ["demo.b"]


def test_raise_is_a_422_and_a_no_op_without_errors() -> None:
    raise_rule_failure(_report(_result("demo.w", "warn", Severity.WARNING)), error="demo_rules_failed")
    with pytest.raises(HTTPException) as caught:
        raise_rule_failure(_report(_result("demo.a", "A broke")), error="demo_rules_failed")
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "demo.a"


@pytest.mark.asyncio
async def test_only_errors_the_edit_introduces_block() -> None:
    legacy = _result("demo.legacy", "already broken")
    fresh = _result("demo.fresh", "new break")
    after = _report(legacy, fresh)

    async def stored() -> ValidationReport:
        return _report(legacy)

    assert [r.rule_id for r in await introduced_errors(after, stored)] == ["demo.fresh"]
    assert len(await introduced_errors(after, None)) == 2
    assert await introduced_errors(_report(legacy), stored) == []
