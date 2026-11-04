# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Post-calculation rule set: each rule has a passing and a failing payload."""

from __future__ import annotations

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.postcalc.validators import (
    POSTCALC_RULE_SET,
    LineValuesInRangeRule,
    PostcalcCurrencyRule,
    PostcalcReferencesRule,
    ProjectRollupMatchesLinesRule,
    register_postcalc_validation_rules,
)


def _line(**kw: object) -> dict:
    base = {
        "ref": "01.001",
        "currency": "EUR",
        "planned_quantity": "10",
        "actual_quantity": "10",
        "planned_hours": "40",
        "actual_hours": "50",
        "planned_labour_cost": "1000.00",
        "productivity_factor": "0.8",
    }
    base.update(kw)
    return base


def _project(**kw: object) -> dict:
    base = {
        "project_id": "p1",
        "currency": "EUR",
        "total_planned_hours": "80",
        "total_actual_hours": "100",
        "total_planned_labour_cost": "2000.00",
        "line_count": 2,
    }
    base.update(kw)
    return base


def _data(project: dict | None = None, lines: list[dict] | None = None) -> dict:
    return {"project": project or _project(), "lines": lines if lines is not None else [_line(), _line(ref="01.002")]}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (ProjectRollupMatchesLinesRule, _data(), _data(_project(total_planned_labour_cost="1500.00"))),
    (LineValuesInRangeRule, _data(), _data(lines=[_line(actual_hours="-1"), _line(ref="2")])),
    (PostcalcCurrencyRule, _data(), _data(_project(currency=""))),
    (PostcalcReferencesRule, _data(), _data(_project(project_id=""))),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES, ids=lambda v: getattr(v, "__name__", ""))
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "money." not in failed[0].message


async def test_line_count_must_match() -> None:
    assert any(not r.passed for r in await _run(ProjectRollupMatchesLinesRule(), _data(_project(line_count=5))))


async def test_implausible_productivity_factor_fails() -> None:
    data = _data(lines=[_line(productivity_factor="75")])
    assert any(not r.passed for r in await _run(LineValuesInRangeRule(), data))


async def test_mixed_line_currency_fails() -> None:
    results = await _run(PostcalcCurrencyRule(), _data(lines=[_line(currency="USD"), _line(ref="2")]))
    assert not results[0].passed


async def test_unpriced_report_needs_no_currency() -> None:
    data = _data(_project(currency=""), [_line(planned_labour_cost="0", currency="")])
    assert (await _run(PostcalcCurrencyRule(), data))[0].passed


async def test_line_without_ref_fails() -> None:
    assert any(not r.passed for r in await _run(PostcalcReferencesRule(), _data(lines=[_line(ref="")])))


async def test_message_follows_locale() -> None:
    fr = await _run(PostcalcCurrencyRule(), _data(_project(currency="")), locale="fr")
    assert "devise" in fr[0].message


def test_registered_under_rule_set() -> None:
    register_postcalc_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([POSTCALC_RULE_SET])}
    assert len(ids) == 4


async def test_rollup_tolerates_rounding_drift_over_many_lines() -> None:
    # 20 lines of 0.005 h each round to 0.01 per line; the total (0.10 unrounded) rounds to 0.10 or 0.1
    lines = [
        _line(ref=str(i), planned_hours="0.01", actual_hours="0.01", planned_labour_cost="0.01") for i in range(20)
    ]
    project = _project(
        total_planned_hours="0.10", total_actual_hours="0.10", total_planned_labour_cost="0.10", line_count=20
    )
    assert all(r.passed for r in await _run(ProjectRollupMatchesLinesRule(), _data(project, lines)))
    project["total_planned_labour_cost"] = "5.00"
    assert not all(r.passed for r in await _run(ProjectRollupMatchesLinesRule(), _data(project, lines)))
