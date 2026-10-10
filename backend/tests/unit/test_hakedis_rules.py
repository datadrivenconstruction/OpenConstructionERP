# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ``hakedis`` rule set: every rule with a context it passes and one it fails.

The rules read a plain dict, so no database is involved. Every amount and
percent here is synthetic.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.contracts import hakedis_rules
from app.modules.contracts.hakedis_document import HAKEDIS_RULE_SET
from app.modules.contracts.messages import translate


def _line(key: str, letter: str, amount: str | None, **extra: Any) -> dict[str, Any]:
    line = {
        "key": key,
        "letter": letter,
        "status": "value" if amount is not None else "held",
        "amount": amount,
        "reason": "",
        "base": None,
        "rate_pct": None,
        "labels": {"tr": f"TR {key}", "en": f"EN {key}"},
        "reason_texts": {},
    }
    line.update(extra)
    return line


def _context() -> dict[str, Any]:
    """A lump-sum second certificate in which nothing is wrong."""
    return {
        "currency": "EUR",
        "country_code": "XX",
        "document": {
            "kind": "progress_claim",
            "id": "doc-2",
            "reference": "2",
            "flavour": "lump_sum",
            "is_final": False,
            "stored_gross": "30000.00",
            "stored_retention": "1500.00",
        },
        "contract": {"value": "100000.00", "start": "2026-01-10", "end": "2027-06-30", "advance_amount": "10000.00"},
        "previous": {
            "line_key": "previous_certificates",
            "exists": True,
            "reference": "1",
            "frozen_total": "20000.00",
            "frozen_work_cumulative": "20000.00",
            "advance_recovered": "2000.00",
        },
        "work": {
            "previous_total": "20000.00",
            "period_total": "30000.00",
            "cumulative_total": "50000.00",
            "lines": [
                {
                    "index": 1,
                    "code": "A1",
                    "description": "Pipework",
                    "status": "value",
                    "weight_pct": "60",
                    "period_quantity": None,
                    "period_pct": "30",
                    "period_amount": "18000.00",
                    "cumulative_amount": "30000.00",
                    "computed_cumulative_amount": "30000.00",
                    "over_measured": False,
                },
                {
                    "index": 2,
                    "code": "A2",
                    "description": "Ductwork",
                    "status": "value",
                    "weight_pct": "40",
                    "period_quantity": None,
                    "period_pct": "30",
                    "period_amount": "12000.00",
                    "cumulative_amount": "20000.00",
                    "computed_cumulative_amount": "20000.00",
                    "over_measured": False,
                },
            ],
        },
        "summary": [
            _line("work_done", "A", "50000.00"),
            _line("total", "C", "50000.00"),
            _line("previous_certificates", "D", "20000.00"),
            _line("this_certificate", "E", "30000.00"),
            _line("vat", "F", "6000.00"),
            _line("advance_recovery", "g", "3000.00"),
            _line("retention", "i", "1500.00", base="30000.00", rate_pct="5"),
            _line("payable", "", "31500.00"),
        ],
        "tax_lines": ["vat"],
        "taxes": {
            "available": True,
            "stored": True,
            "status": "confirmed",
            "stale": False,
            "income_withholding": "not_applicable",
        },
    }


def _set(context: dict[str, Any], key: str, **changes: Any) -> None:
    for line in context["summary"]:
        if line["key"] == key:
            line.update(changes)
            return
    raise KeyError(key)


async def _run(rule_class: type, context: dict[str, Any], locale: str = "en"):
    return await rule_class().validate(ValidationContext(data=context, metadata={"locale": locale}))


def _over_contract(c: dict[str, Any]) -> None:
    c["work"]["cumulative_total"] = "100000.50"


def _previous_total_differs(c: dict[str, Any]) -> None:
    c["previous"]["frozen_total"] = "19000.00"


def _previous_work_differs(c: dict[str, Any]) -> None:
    c["previous"]["frozen_work_cumulative"] = "21000.00"


def _previous_held(c: dict[str, Any]) -> None:
    _set(c, "previous_certificates", status="held", amount=None, reason="previous_unknown")


def _previous_pending(c: dict[str, Any]) -> None:
    _set(c, "previous_certificates", status="held", amount=None, reason="previous_not_certified")


def _weights_short(c: dict[str, Any]) -> None:
    c["work"]["lines"][1]["weight_pct"] = "39"


def _negative_period(c: dict[str, Any]) -> None:
    c["work"]["lines"][0]["period_pct"] = "-5"


def _single_year_withholding(c: dict[str, Any]) -> None:
    c["taxes"]["income_withholding"] = "selected"
    c["contract"]["end"] = "2026-11-30"


def _advance_over(c: dict[str, Any]) -> None:
    _set(c, "advance_recovery", amount="8000.01")


def _retention_differs(c: dict[str, Any]) -> None:
    c["document"]["stored_retention"] = "1400.00"


def _negative_payable(c: dict[str, Any]) -> None:
    _set(c, "payable", amount="-0.01")


def _stale(c: dict[str, Any]) -> None:
    c["taxes"]["stale"] = True
    _set(c, "vat", status="held", amount=None, reason="taxes_stale")


def _draft_taxes(c: dict[str, Any]) -> None:
    c["taxes"]["status"] = "draft"


def _line_not_entered(c: dict[str, Any]) -> None:
    _set(
        c,
        "advance_recovery",
        status="held",
        amount=None,
        reason="not_entered",
        reason_texts={"tr": "Tutar girilmedi.", "en": "No amount has been entered."},
    )


def _value_differs(c: dict[str, Any]) -> None:
    c["work"]["lines"][0]["computed_cumulative_amount"] = "29999.00"


CASES = [
    (hakedis_rules.CumulativeWithinContractRule, _over_contract, Severity.ERROR),
    (hakedis_rules.PreviousMatchesLastCertifiedRule, _previous_total_differs, Severity.ERROR),
    (hakedis_rules.PreviousMatchesLastCertifiedRule, _previous_work_differs, Severity.ERROR),
    (hakedis_rules.PreviousKnownRule, _previous_held, Severity.ERROR),
    (hakedis_rules.PreviousKnownRule, _previous_pending, Severity.ERROR),
    (hakedis_rules.WeightsSumRule, _weights_short, Severity.ERROR),
    (hakedis_rules.PercentRegressedRule, _negative_period, Severity.WARNING),
    (hakedis_rules.IncomeWithholdingSingleYearRule, _single_year_withholding, Severity.WARNING),
    (hakedis_rules.AdvanceRecoveryWithinAdvanceRule, _advance_over, Severity.ERROR),
    (hakedis_rules.RetentionMatchesConfigRule, _retention_differs, Severity.WARNING),
    (hakedis_rules.NetPayableNotNegativeRule, _negative_payable, Severity.ERROR),
    (hakedis_rules.TaxesNotStaleRule, _stale, Severity.ERROR),
    (hakedis_rules.TaxesConfirmedRule, _draft_taxes, Severity.ERROR),
    (hakedis_rules.LinesCompleteRule, _line_not_entered, Severity.ERROR),
    (hakedis_rules.WorkValueMatchesMeasureRule, _value_differs, Severity.WARNING),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("rule_class", hakedis_rules.HAKEDIS_RULES, ids=lambda rule: rule.rule_id)
async def test_every_rule_passes_a_certificate_with_nothing_wrong(rule_class: type) -> None:
    results = await _run(rule_class, _context())
    assert results, "a rule that returns nothing cannot be told from one that never ran"
    assert all(result.passed for result in results), [result.message for result in results]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rule_class", "breakage", "severity"), CASES, ids=lambda item: getattr(item, "__name__", None)
)
async def test_every_rule_fails_on_the_one_thing_it_checks(rule_class: type, breakage, severity: Severity) -> None:
    context = _context()
    breakage(context)
    failed = [result for result in await _run(rule_class, context) if not result.passed]
    assert failed, f"{rule_class.rule_id} did not notice {breakage.__name__}"
    for result in failed:
        assert result.severity == severity
        assert result.rule_id == rule_class.rule_id
        assert "{" not in result.message, result.message
        assert result.suggestion


def test_every_rule_of_the_set_has_a_failing_case_here() -> None:
    """A rule added without a failing case would be a rule nobody has seen fire."""
    assert {case[0] for case in CASES} == set(hakedis_rules.HAKEDIS_RULES)


@pytest.mark.asyncio
async def test_only_the_broken_rule_fires_for_each_breakage() -> None:
    """The breakages are independent, so a finding names its own cause and no other.

    That includes the two places where one cause holds a line: stale taxes
    hold the tax line, and an unknown previous total holds line D. Each is
    reported by its own rule and not a second time as an open line.
    """
    for rule_class, breakage, _severity in CASES:
        context = _context()
        breakage(context)
        fired = set()
        for other in hakedis_rules.HAKEDIS_RULES:
            if any(not result.passed for result in await _run(other, context)):
                fired.add(other)
        assert fired == {rule_class}, (breakage.__name__, sorted(rule.rule_id for rule in fired))


@pytest.mark.asyncio
async def test_the_advance_rule_only_remarks_when_the_contract_states_no_advance() -> None:
    context = _context()
    context["contract"]["advance_amount"] = None
    (result,) = await _run(hakedis_rules.AdvanceRecoveryWithinAdvanceRule, context)
    assert (result.passed, result.severity) == (False, Severity.WARNING)

    context["previous"]["advance_recovered"] = "0"
    _set(context, "advance_recovery", status="not_applicable", amount=None)
    (nothing_recovered,) = await _run(hakedis_rules.AdvanceRecoveryWithinAdvanceRule, context)
    assert nothing_recovered.passed


@pytest.mark.asyncio
async def test_a_contract_sum_raised_by_an_approved_change_covers_the_work() -> None:
    context = _context()
    _over_contract(context)
    context["contract"]["value"] = "120000.00"
    (result,) = await _run(hakedis_rules.CumulativeWithinContractRule, context)
    assert result.passed


@pytest.mark.asyncio
async def test_income_withholding_over_two_calendar_years_is_not_questioned() -> None:
    context = _context()
    context["taxes"]["income_withholding"] = "selected"
    (result,) = await _run(hakedis_rules.IncomeWithholdingSingleYearRule, context)
    assert result.passed


@pytest.mark.asyncio
async def test_a_held_line_is_named_in_the_readers_language() -> None:
    context = _context()
    _line_not_entered(context)
    (turkish,) = [r for r in await _run(hakedis_rules.LinesCompleteRule, context, "tr") if not r.passed]
    (english,) = [r for r in await _run(hakedis_rules.LinesCompleteRule, context, "en-GB") if not r.passed]
    assert "TR advance_recovery" in turkish.message
    assert "Tutar girilmedi." in turkish.message
    assert "EN advance_recovery" in english.message
    assert turkish.message != english.message
    assert turkish.element_ref == "advance_recovery"


@pytest.mark.asyncio
async def test_a_malformed_context_is_a_finding_or_a_pass_never_an_exception() -> None:
    """The engine swallows a rule that raises, and silence would read as a pass."""
    for garbage in ({}, {"summary": "nonsense", "work": 3, "taxes": None}, {"summary": [{"key": None, "amount": "x"}]}):
        for rule_class in hakedis_rules.HAKEDIS_RULES:
            results = await _run(rule_class, copy.deepcopy(garbage))
            assert results


def test_registration_puts_every_rule_in_the_set() -> None:
    hakedis_rules.register_hakedis_rules()
    registered = {rule["rule_id"] for rule in rule_registry.list_rules(HAKEDIS_RULE_SET)}
    assert registered == {rule.rule_id for rule in hakedis_rules.HAKEDIS_RULES}


@pytest.mark.parametrize("locale", ["en", "tr"])
def test_every_finding_has_its_sentence_in_english_and_turkish(locale: str) -> None:
    for rule_class in hakedis_rules.HAKEDIS_RULES:
        for suffix in ("fail", "suggestion"):
            key = f"{rule_class.rule_id}.{suffix}"
            assert translate(key, locale=locale) != key, f"{locale} has no {key}"
    assert translate("hakedis.taxes_stale.fail", locale="tr") != translate("hakedis.taxes_stale.fail", locale="en")
