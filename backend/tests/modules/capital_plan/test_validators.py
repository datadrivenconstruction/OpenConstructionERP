# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One test per capital plan validation rule, plus registration."""

from __future__ import annotations

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.capital_plan import validators as v

PLAN = {"currency": "EUR", "start_year": 2030, "horizon_years": 3}


def _item(i: str, **kw) -> dict:
    base = {
        "id": i,
        "project_id": None,
        "title": f"item {i}",
        "priority": 3,
        "start_year": 2030,
        "duration_years": 1,
        "total_cost": "100",
        "phasing": [],
        "status": "proposed",
        "score": None,
    }
    base.update(kw)
    return base


def _data(items, envelopes=None, **extra) -> dict:
    env = [{"year": y, "amount": 1000, "label": ""} for y in (2030, 2031, 2032)] if envelopes is None else envelopes
    return {"plan": PLAN, "envelopes": env, "items": items, "baseline_count": 1, "project_currencies": {}, **extra}


async def _run(rule, data) -> list:
    return [r for r in await rule().validate(ValidationContext(data=data)) if not r.passed]


async def test_phasing_sums_to_one() -> None:
    bad = _item("a", duration_years=2, phasing=["0.5", "0.6"])
    assert [r.element_ref for r in await _run(v.PhasingSumsToOne, _data([bad]))] == ["a"]
    assert not await _run(v.PhasingSumsToOne, _data([_item("b", duration_years=2, phasing=["0.5", "0.5"])]))
    assert v.PhasingSumsToOne.severity is Severity.ERROR


async def test_phasing_length_matches_duration() -> None:
    bad = _item("a", duration_years=3, phasing=["0.5", "0.5"])
    assert len(await _run(v.PhasingLengthMatchesDuration, _data([bad]))) == 1
    assert not await _run(v.PhasingLengthMatchesDuration, _data([_item("b")]))
    assert v.PhasingLengthMatchesDuration.severity is Severity.ERROR


async def test_item_within_horizon() -> None:
    late = _item("a", start_year=2032, duration_years=2)
    found = await _run(v.ItemWithinHorizon, _data([late]))
    assert found[0].details["year"] == 2033
    assert not await _run(v.ItemWithinHorizon, _data([_item("b")]))
    assert v.ItemWithinHorizon.severity is Severity.WARNING


async def test_year_over_envelope() -> None:
    env = [{"year": 2030, "amount": 50, "label": ""}]
    found = await _run(v.YearOverEnvelope, _data([_item("a")], env))
    assert found[0].details["over"] == "50.00"
    assert not await _run(v.YearOverEnvelope, _data([_item("a", status="deferred")], env))
    assert v.YearOverEnvelope.severity is Severity.ERROR


async def test_year_without_an_envelope_is_not_reported_as_over() -> None:
    assert not await _run(v.YearOverEnvelope, _data([_item("a")], []))


async def test_no_envelope_for_year() -> None:
    env = [{"year": 2030, "amount": 1, "label": ""}]
    assert [r.details["year"] for r in await _run(v.NoEnvelopeForYear, _data([], env))] == [2031, 2032]
    assert v.NoEnvelopeForYear.severity is Severity.WARNING


async def test_item_without_cost() -> None:
    assert len(await _run(v.ItemWithoutCost, _data([_item("a", total_cost="0"), _item("b")]))) == 1
    assert v.ItemWithoutCost.severity is Severity.WARNING


async def test_duplicate_project_in_scenario() -> None:
    items = [_item("a", project_id="p1"), _item("b", project_id="p1"), _item("c", project_id="p2"), _item("d")]
    assert [r.element_ref for r in await _run(v.DuplicateProjectInScenario, _data(items))] == ["b"]
    assert v.DuplicateProjectInScenario.severity is Severity.ERROR


async def test_single_baseline() -> None:
    assert len(await _run(v.SingleBaseline, _data([], baseline_count=2))) == 1
    assert not await _run(v.SingleBaseline, _data([], baseline_count=1))
    assert v.SingleBaseline.severity is Severity.ERROR


async def test_currency_mismatch_with_project() -> None:
    items = [_item("a", project_id="p1"), _item("b", project_id="p2"), _item("c")]
    found = await _run(v.CurrencyMismatchWithProject, _data(items, project_currencies={"p1": "USD", "p2": "eur"}))
    assert [r.element_ref for r in found] == ["a"]
    assert v.CurrencyMismatchWithProject.severity is Severity.WARNING


def test_the_rule_set_registers_nine_rules_idempotently() -> None:
    v.register_capital_plan_rules()
    v.register_capital_plan_rules()
    ids = sorted(r.rule_id for r in rule_registry.get_rules_for_sets([v.CAPITAL_PLAN_RULE_SET]))
    names = (
        "phasing_sums_to_one",
        "phasing_length_matches_duration",
        "item_within_horizon",
        "year_over_envelope",
        "no_envelope_for_year",
        "item_without_cost",
        "duplicate_project_in_scenario",
        "single_baseline",
        "currency_mismatch_with_project",
    )
    assert ids == sorted(f"cp.{n}" for n in names)


async def test_run_rules_returns_only_failures_sorted() -> None:
    findings = await v.run_rules(_data([_item("a", total_cost="0"), _item("b", project_id="p")], []))
    assert [f["rule_id"] for f in findings] == sorted(f["rule_id"] for f in findings)
    assert {f["rule_id"] for f in findings} == {"cp.item_without_cost", "cp.no_envelope_for_year"}
