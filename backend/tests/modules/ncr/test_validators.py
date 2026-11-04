# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""NCR rule set: each rule has a passing and a failing payload."""

from __future__ import annotations

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.ncr.validators import (
    NCR_RULE_SET,
    NcrClosureDocumentedRule,
    NcrClosureVerifiedRule,
    NcrCostImpactDescribedRule,
    NcrNotOverdueRule,
    register_ncr_validation_rules,
)


def _ncr(**kw: object) -> dict:
    base = {
        "id": "n1",
        "status": "closed",
        "description": "Cracked slab edge",
        "root_cause": "Early formwork removal",
        "corrective_action": "Epoxy repair",
        "verified_by": "qa-lead",
        "cost_impact": "1500",
        "due_date": "2026-11-01",
    }
    base.update(kw)
    return {"ncr": base}


async def _run(rule: object, data: dict, locale: str = "en", today: str = "2026-11-04"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale, "today": today}))


CASES = [
    (NcrClosureDocumentedRule, _ncr(), _ncr(corrective_action=" ")),
    (NcrClosureVerifiedRule, _ncr(), _ncr(verified_by=None)),
    (NcrNotOverdueRule, _ncr(status="closed"), _ncr(status="corrective_action")),
    (NcrCostImpactDescribedRule, _ncr(), _ncr(description="")),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES, ids=lambda v: getattr(v, "__name__", ""))
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "quality." not in failed[0].message


async def test_open_ncr_needs_no_closure_fields() -> None:
    data = _ncr(status="under_review", root_cause=None, corrective_action=None)
    assert (await _run(NcrClosureDocumentedRule(), data))[0].passed


async def test_missing_root_cause_and_action_report_both() -> None:
    results = await _run(NcrClosureDocumentedRule(), _ncr(root_cause="", corrective_action=""))
    assert [r.details["field"] for r in results if not r.passed] == ["root_cause", "corrective_action"]


async def test_open_ncr_not_overdue_before_due_date_or_without_one() -> None:
    rule = NcrNotOverdueRule()
    assert (await _run(rule, _ncr(status="identified", due_date="2026-11-04")))[0].passed
    assert (await _run(rule, _ncr(status="identified", due_date=None)))[0].passed
    assert (await _run(rule, _ncr(status="void", due_date="2020-01-01")))[0].passed


async def test_zero_cost_needs_no_description() -> None:
    assert (await _run(NcrCostImpactDescribedRule(), _ncr(cost_impact="0", description="")))[0].passed


async def test_message_follows_locale() -> None:
    de = await _run(NcrClosureVerifiedRule(), _ncr(verified_by=""), locale="de")
    assert "fehlt" in de[0].message


def test_registered_under_rule_set() -> None:
    register_ncr_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([NCR_RULE_SET])}
    assert {"ncr.closure_documented", "ncr.closure_verified", "ncr.not_overdue", "ncr.cost_impact_described"} <= ids
