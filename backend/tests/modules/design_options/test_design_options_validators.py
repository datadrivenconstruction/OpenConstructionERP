"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The six ``design_options`` validation rules, one at a time.

Every rejection test is driven through the core engine rather than by calling a
rule object directly, for two reasons: it is the path production uses, and it is
the only way the removal check below can mean anything. Calling
``rule.validate(context)`` by hand would keep passing with the rule unregistered
or disabled, so it would prove nothing about the rule being wired in.

The removal check is permanent, not a one-off manual experiment: for each rule,
``test_each_rejection_disappears_when_its_rule_is_disabled`` re-runs the exact
payload with that rule switched off in the registry and asserts the finding is
gone while the rest of the report still ran. A rejection that survives its own
rule being removed was never produced by that rule.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.core.validation.engine import (
    RuleResult,
    Severity,
    ValidationReport,
    rule_registry,
    validation_engine,
)
from app.modules.design_options.validators import (
    DESIGN_OPTIONS_RULE_SET,
    evaluate_design_option_set,
    to_validation_position,
)


async def run_rules(data: dict[str, Any]) -> ValidationReport:
    """Run the module's rule set over one payload, as the aggregator does."""
    return await validation_engine.validate(
        data=data,
        rule_sets=[DESIGN_OPTIONS_RULE_SET],
        target_type="design_option_set" if data.get("scope") == "set" else "design_option",
        target_id="t",
    )


def failures(report: ValidationReport, rule_id: str) -> list[RuleResult]:
    """Failing results a single rule produced."""
    return [r for r in report.results if r.rule_id == rule_id and not r.passed]


def results_for(report: ValidationReport, rule_id: str) -> list[RuleResult]:
    """Every result a single rule produced, passing or failing."""
    return [r for r in report.results if r.rule_id == rule_id]


@contextmanager
def rule_disabled(rule_id: str) -> Iterator[None]:
    """Switch one rule off in the registry, then put it back.

    The engine filters on ``rule.enabled``, so this is exactly "the rule is not
    there" from the caller's side, without disturbing the other five. The rule
    instances are process-global singletons and the session-wide registry guard
    restores the registry object, not this flag, so the restore has to happen
    here or a later test would run against a crippled rule set.
    """
    rule = rule_registry.get_rule(rule_id)
    assert rule is not None, f"{rule_id} is not registered, so disabling it proves nothing"
    previous = rule.enabled
    rule.enabled = False
    try:
        yield
    finally:
        rule.enabled = previous


# ── Payloads that each rule is meant to reject ───────────────────────────────


def option_payload(**option: Any) -> dict[str, Any]:
    """A per-option context with sensible, passing defaults."""
    positions = option.pop("positions", [{"unit": "m3", "quantity": "10", "unit_rate": "100"}])
    base = {
        "id": str(uuid.uuid4()),
        "name": "Steel",
        "gfa": "1000",
        "priced": True,
        "is_mixed": False,
        "grand_total": "1000",
    }
    base.update(option)
    return {"scope": "option", "option": base, "positions": positions}


def set_payload(options: list[dict[str, Any]], **meta: Any) -> dict[str, Any]:
    """A set-level context carrying every option summary."""
    data: dict[str, Any] = {"scope": "set", "comparison_currency": "EUR", "options": options}
    data.update(meta)
    return data


def option_summary(**fields: Any) -> dict[str, Any]:
    """One option summary inside a set-level context."""
    base = {
        "id": str(uuid.uuid4()),
        "name": "Steel",
        "gfa": "1000",
        "priced": True,
        "is_mixed": False,
        "trades": [{"key": "300", "label": "Building construction", "unit": "m3", "cost": "1000", "quantity": "10"}],
    }
    base.update(fields)
    return base


# The payload each rule must reject. Every one of these is also the input to the
# removal check, so a rule that stops firing is caught by the same fixture data.
REJECTED: dict[str, dict[str, Any]] = {
    # A priced option with no floor area cannot show a cost per m2.
    "design_options.gfa_present": option_payload(gfa="0"),
    # A priced option carrying a zero-quantity line understates its own total.
    "design_options.priced_complete": option_payload(
        positions=[
            {"unit": "m3", "quantity": "10", "unit_rate": "100"},
            {"unit": "m2", "quantity": "0", "unit_rate": "50"},
        ]
    ),
    # 100 against 111 diverges by 11 percent, past the 10 percent threshold.
    "design_options.gfa_consistent": set_payload(
        [option_summary(name="Steel", gfa="100"), option_summary(name="Timber", gfa="111")]
    ),
    # Timber prices nothing for a trade Steel does price.
    "design_options.scope_coverage": set_payload(
        [
            option_summary(name="Steel"),
            option_summary(
                name="Timber",
                trades=[{"key": "300", "label": "Building construction", "unit": "m3", "cost": "0"}],
            ),
        ]
    ),
    # One trade measured in m3 by one option and m2 by the other.
    "design_options.unit_consistency": set_payload(
        [
            option_summary(name="Steel"),
            option_summary(
                name="Timber",
                trades=[{"key": "300", "label": "Building construction", "unit": "m2", "cost": "900"}],
            ),
        ]
    ),
    # An option whose own bill blends currencies cannot resolve to one.
    "design_options.currency_consistent": set_payload([option_summary(name="Steel", is_mixed=True)]),
}


# ── Removal check ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rule_id", sorted(REJECTED))
async def test_each_rule_rejects_the_input_it_exists_for(rule_id: str) -> None:
    """Each rule produces a failing result for the case it is meant to catch."""
    report = await run_rules(REJECTED[rule_id])
    found = failures(report, rule_id)
    assert found, f"{rule_id} did not reject the input it exists for"
    assert all(not r.is_engine_error for r in found), "the rule crashed instead of finding something"
    assert found[0].message != "OK"


@pytest.mark.parametrize("rule_id", sorted(REJECTED))
async def test_each_rejection_disappears_when_its_rule_is_disabled(rule_id: str) -> None:
    """The finding must come from this rule and from nothing else.

    Running the identical payload with the rule switched off has to lose the
    finding. If it survived, the assertion above was being satisfied by some
    other rule and the test was not covering this one at all.
    """
    with rule_disabled(rule_id):
        report = await run_rules(REJECTED[rule_id])

    assert results_for(report, rule_id) == []
    # The rest of the set still ran, so the finding vanished because the rule
    # was removed and not because the whole engine stopped working.
    assert report.rule_sets_applied == [DESIGN_OPTIONS_RULE_SET]
    assert report.unsupported_rule_sets == []
    assert report.results, "no rule ran at all - the removal check proves nothing"


# ── design_options.gfa_present ───────────────────────────────────────────────

GFA_PRESENT = "design_options.gfa_present"


async def test_gfa_present_is_a_blocking_error_naming_the_option() -> None:
    """The finding blocks, points at the option and explains what is lost."""
    payload = option_payload(gfa="0", name="Steel frame")
    report = await run_rules(payload)
    finding = failures(report, GFA_PRESENT)[0]
    assert finding.severity == Severity.ERROR
    assert finding.element_ref == payload["option"]["id"]
    assert "Steel frame" in finding.message
    assert "cost per m2" in finding.message
    assert finding.suggestion


async def test_gfa_present_passes_when_the_option_has_an_area() -> None:
    """A priced option with an area is clean."""
    report = await run_rules(option_payload(gfa="1250"))
    assert failures(report, GFA_PRESENT) == []


async def test_gfa_present_does_not_fire_on_an_unpriced_draft() -> None:
    """A draft has no cost per m2 to miss; priced_complete covers it instead."""
    report = await run_rules(option_payload(gfa="0", priced=False))
    assert failures(report, GFA_PRESENT) == []


async def test_gfa_present_stays_out_of_the_set_level_pass() -> None:
    """A per-option rule must return nothing in a set-scope context."""
    report = await run_rules(set_payload([option_summary(gfa="0")]))
    assert results_for(report, GFA_PRESENT) == []


# ── design_options.priced_complete ───────────────────────────────────────────

PRICED_COMPLETE = "design_options.priced_complete"


async def test_priced_complete_counts_the_incomplete_lines() -> None:
    """The finding warns and reports how many lines are short."""
    report = await run_rules(
        option_payload(
            positions=[
                {"unit": "m3", "quantity": "10", "unit_rate": "100"},
                {"unit": "m2", "quantity": "0", "unit_rate": "50"},
                {"unit": "m", "quantity": "5", "unit_rate": "0"},
            ]
        )
    )
    finding = failures(report, PRICED_COMPLETE)[0]
    assert finding.severity == Severity.WARNING
    assert finding.details["incomplete_count"] == 2
    assert finding.details["position_count"] == 3


async def test_priced_complete_flags_an_option_that_was_never_priced() -> None:
    """An empty bill must not read as a clean pass, which would look free."""
    report = await run_rules(option_payload(priced=False, positions=[]))
    finding = failures(report, PRICED_COMPLETE)[0]
    assert finding.details == {"priced": False, "position_count": 0}
    assert "not priced yet" in finding.message


async def test_priced_complete_flags_a_priced_option_with_an_empty_bill() -> None:
    """ "Priced" with no positions is still nothing to compare on."""
    report = await run_rules(option_payload(priced=True, positions=[]))
    assert failures(report, PRICED_COMPLETE)


async def test_priced_complete_ignores_section_headers() -> None:
    """A section carries no quantity or rate by design and is not a gap."""
    report = await run_rules(
        option_payload(
            positions=[
                {"type": "section", "unit": "", "quantity": "0", "unit_rate": "0"},
                {"unit": "m3", "quantity": "10", "unit_rate": "100"},
            ]
        )
    )
    assert failures(report, PRICED_COMPLETE) == []


async def test_priced_complete_passes_a_fully_priced_option() -> None:
    """Every line positive is a clean pass."""
    report = await run_rules(option_payload())
    assert failures(report, PRICED_COMPLETE) == []


# ── design_options.gfa_consistent ────────────────────────────────────────────

GFA_CONSISTENT = "design_options.gfa_consistent"


async def test_gfa_consistent_reports_the_spread_it_measured() -> None:
    """The message carries the divergence and the two extremes."""
    report = await run_rules(
        set_payload([option_summary(name="Steel", gfa="100"), option_summary(name="Timber", gfa="150")])
    )
    finding = failures(report, GFA_CONSISTENT)[0]
    assert finding.severity == Severity.WARNING
    assert finding.details == {"min_gfa": "100", "max_gfa": "150", "divergence_pct": "50.0"}


async def test_gfa_consistent_allows_exactly_ten_percent() -> None:
    """The threshold is inclusive: 100 against 110 is still comparable."""
    report = await run_rules(
        set_payload([option_summary(name="Steel", gfa="100"), option_summary(name="Timber", gfa="110")])
    )
    assert failures(report, GFA_CONSISTENT) == []


async def test_gfa_consistent_rejects_just_past_ten_percent() -> None:
    """One unit further and the areas are no longer directly comparable."""
    report = await run_rules(
        set_payload([option_summary(name="Steel", gfa="100"), option_summary(name="Timber", gfa="111")])
    )
    assert failures(report, GFA_CONSISTENT)


async def test_gfa_consistent_needs_two_measured_options() -> None:
    """One area, or none, cannot diverge from anything."""
    report = await run_rules(
        set_payload([option_summary(name="Steel", gfa="100"), option_summary(name="Sketch", gfa="0", priced=False)])
    )
    assert failures(report, GFA_CONSISTENT) == []


# ── design_options.scope_coverage ────────────────────────────────────────────

SCOPE_COVERAGE = "design_options.scope_coverage"


async def test_scope_coverage_names_the_trade_an_option_skipped() -> None:
    """The finding names the option and the trades it prices nothing for."""
    report = await run_rules(
        set_payload(
            [
                option_summary(
                    name="Steel",
                    trades=[
                        {"key": "300", "label": "Building construction", "unit": "m3", "cost": "1000"},
                        {"key": "400", "label": "Building services", "unit": "m2", "cost": "500"},
                    ],
                ),
                option_summary(
                    name="Timber",
                    trades=[{"key": "300", "label": "Building construction", "unit": "m3", "cost": "900"}],
                ),
            ]
        )
    )
    finding = failures(report, SCOPE_COVERAGE)[0]
    assert finding.severity == Severity.WARNING
    assert finding.details["missing_trades"] == ["400"]
    assert finding.details["missing_labels"] == ["Building services"]
    assert "Timber" in finding.message


async def test_scope_coverage_treats_a_zero_cost_trade_as_absent() -> None:
    """A trade listed but priced at zero is not coverage."""
    report = await run_rules(
        set_payload(
            [
                option_summary(name="Steel"),
                option_summary(
                    name="Timber",
                    trades=[{"key": "300", "label": "Building construction", "unit": "m3", "cost": "0"}],
                ),
            ]
        )
    )
    assert failures(report, SCOPE_COVERAGE)


async def test_scope_coverage_passes_when_both_options_price_the_same_trades() -> None:
    """Matching coverage is a clean pass for every option."""
    report = await run_rules(set_payload([option_summary(name="Steel"), option_summary(name="Timber")]))
    assert failures(report, SCOPE_COVERAGE) == []


async def test_scope_coverage_needs_something_to_compare_against() -> None:
    """A single priced option has no other option to be missing a trade from."""
    report = await run_rules(set_payload([option_summary(name="Steel")]))
    assert results_for(report, SCOPE_COVERAGE) == []


# ── design_options.unit_consistency ──────────────────────────────────────────

UNIT_CONSISTENCY = "design_options.unit_consistency"


async def test_unit_consistency_lists_the_conflicting_units() -> None:
    """The finding blocks and reports which option used which unit."""
    report = await run_rules(REJECTED[UNIT_CONSISTENCY])
    finding = failures(report, UNIT_CONSISTENCY)[0]
    assert finding.severity == Severity.ERROR
    assert finding.element_ref == "300"
    assert set(finding.details["units"]) == {"m3", "m2"}
    assert finding.details["units"]["m2"] == ["Timber"]


async def test_unit_consistency_passes_when_one_trade_uses_one_unit() -> None:
    """Agreeing units make the per-trade quantity delta meaningful."""
    report = await run_rules(set_payload([option_summary(name="Steel"), option_summary(name="Timber")]))
    assert failures(report, UNIT_CONSISTENCY) == []


async def test_unit_consistency_ignores_a_trade_with_no_unit() -> None:
    """A bucket that never carried a unit cannot contradict another."""
    report = await run_rules(
        set_payload(
            [
                option_summary(name="Steel"),
                option_summary(
                    name="Timber",
                    trades=[{"key": "300", "label": "Building construction", "unit": "", "cost": "900"}],
                ),
            ]
        )
    )
    assert failures(report, UNIT_CONSISTENCY) == []


async def test_unit_consistency_ignores_an_unpriced_option() -> None:
    """A draft's units are not yet a claim about the comparison."""
    report = await run_rules(
        set_payload(
            [
                option_summary(name="Steel"),
                option_summary(
                    name="Sketch",
                    priced=False,
                    trades=[{"key": "300", "label": "Building construction", "unit": "m2", "cost": "900"}],
                ),
            ]
        )
    )
    assert failures(report, UNIT_CONSISTENCY) == []


# ── design_options.currency_consistent ───────────────────────────────────────

CURRENCY_CONSISTENT = "design_options.currency_consistent"


async def test_currency_consistent_names_the_blended_options() -> None:
    """The finding blocks and names every option whose bill mixes currencies."""
    report = await run_rules(
        set_payload(
            [option_summary(name="Steel", is_mixed=True), option_summary(name="Timber")],
            comparison_currency="CHF",
        )
    )
    finding = failures(report, CURRENCY_CONSISTENT)[0]
    assert finding.severity == Severity.ERROR
    assert finding.details["mixed_options"] == ["Steel"]
    assert finding.details["count"] == 1
    assert finding.details["comparison_currency"] == "CHF"
    assert "CHF" in finding.message


async def test_currency_consistent_passes_a_single_currency_set() -> None:
    """No blended bill means every option resolves to the one currency."""
    report = await run_rules(set_payload([option_summary(name="Steel"), option_summary(name="Timber")]))
    assert failures(report, CURRENCY_CONSISTENT) == []


async def test_currency_consistent_ignores_an_unpriced_blended_draft() -> None:
    """An option with no price yet is covered by priced_complete, not here."""
    report = await run_rules(set_payload([option_summary(name="Sketch", priced=False, is_mixed=True)]))
    assert failures(report, CURRENCY_CONSISTENT) == []


async def test_set_level_rules_stay_out_of_the_per_option_pass() -> None:
    """All four cross-option rules self-select away from an option context."""
    report = await run_rules(option_payload())
    for rule_id in (GFA_CONSISTENT, SCOPE_COVERAGE, UNIT_CONSISTENCY, CURRENCY_CONSISTENT):
        assert results_for(report, rule_id) == [], rule_id


# ── Orchestration used by the comparison hook ────────────────────────────────


def _clean_position(ordinal: str = "01.001", **fields: Any) -> dict[str, Any]:
    """A leaf position the ``boq_quality`` rules also read as complete.

    The per-option pass runs ``design_options`` alongside ``boq_quality``, so a
    position has to satisfy both rule sets before an option's traffic light can
    come out green.
    """
    position = {
        "id": str(uuid.uuid4()),
        "parent_id": None,
        "ordinal": ordinal,
        "description": "Reinforced concrete wall C30/37",
        "unit": "m3",
        "quantity": "10",
        "unit_rate": "100",
        "total": "1000",
        "classification": {"din276": "330"},
        "source": "manual",
        "type": "position",
        "currency": "EUR",
        "metadata": {},
    }
    position.update(fields)
    return position


async def test_evaluate_returns_a_light_per_option_and_set_level_notices() -> None:
    """Two passes: an option traffic light each, plus the fairness notices."""
    good = str(uuid.uuid4())
    bad = str(uuid.uuid4())
    outcome = await evaluate_design_option_set(
        [
            {
                "id": good,
                "name": "Steel",
                "gfa": "100",
                "priced": True,
                "is_mixed": False,
                "grand_total": "1000",
                "positions": [_clean_position()],
                "trades": [{"key": "300", "label": "Building construction", "unit": "m3", "cost": "1000"}],
            },
            {
                "id": bad,
                "name": "Timber",
                "gfa": "0",
                "priced": True,
                "is_mixed": True,
                "grand_total": "900",
                "positions": [_clean_position(unit="m2", quantity="0", unit_rate="0", total="0")],
                "trades": [{"key": "300", "label": "Building construction", "unit": "m2", "cost": "900"}],
            },
        ],
        {"set_id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()), "comparison_currency": "EUR"},
    )

    # The clean option must not be reported as errors; the broken one must be.
    assert outcome.per_option_status[good] in ("passed", "warnings", "info")
    assert outcome.per_option_status[bad] == "errors"
    keys = {w.key for w in outcome.fairness}
    assert "designOptions.validation.design_options.unit_consistency" in keys
    assert "designOptions.validation.design_options.currency_consistent" in keys


async def test_evaluate_carries_the_rule_message_into_the_notice() -> None:
    """A fairness notice keeps the rule's message, ref and suggestion."""
    outcome = await evaluate_design_option_set(
        [
            {
                "id": str(uuid.uuid4()),
                "name": "Steel",
                "gfa": "100",
                "priced": True,
                "is_mixed": False,
                "trades": [{"key": "300", "label": "Building construction", "unit": "m3", "cost": "1000"}],
                "positions": [],
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Timber",
                "gfa": "100",
                "priced": True,
                "is_mixed": False,
                "trades": [{"key": "300", "label": "Building construction", "unit": "m2", "cost": "900"}],
                "positions": [],
            },
        ],
        {"set_id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()), "comparison_currency": "EUR"},
    )

    notice = next(w for w in outcome.fairness if w.key.endswith("unit_consistency"))
    assert notice.severity == "error"
    assert notice.context["ref"] == "300"
    assert "different units" in notice.context["message"]
    assert notice.context["suggestion"]


async def test_evaluate_reports_nothing_unfair_about_a_clean_set() -> None:
    """A consistent, fully priced set produces no fairness notices at all."""
    outcome = await evaluate_design_option_set(
        [
            {
                "id": str(uuid.uuid4()),
                "name": name,
                "gfa": "100",
                "priced": True,
                "is_mixed": False,
                "positions": [{"unit": "m3", "quantity": "10", "unit_rate": "100"}],
                "trades": [{"key": "300", "label": "Building construction", "unit": "m3", "cost": "1000"}],
            }
            for name in ("Steel", "Timber")
        ],
        {"set_id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()), "comparison_currency": "EUR"},
    )
    assert outcome.fairness == []


async def test_evaluate_survives_a_rule_set_that_is_not_registered() -> None:
    """With the rules gone, options read pending instead of a clean pass.

    This is the honest degradation the comparison banner depends on: never a
    green light produced by nothing having run.
    """
    removed = rule_registry.unregister_rule_set(DESIGN_OPTIONS_RULE_SET)
    try:
        outcome = await evaluate_design_option_set(
            [
                {
                    "id": "opt-1",
                    "name": "Steel",
                    "gfa": "0",
                    "priced": True,
                    "is_mixed": True,
                    "positions": [],
                    "trades": [],
                }
            ],
            {"set_id": "set-1", "project_id": "p", "comparison_currency": "EUR"},
        )
        assert outcome.per_option_status["opt-1"] == "pending"
        assert outcome.fairness == []
    finally:
        from app.modules.design_options.validators import register_design_options_rules

        register_design_options_rules()
    assert removed == 6
    assert rule_registry.list_rule_sets()[DESIGN_OPTIONS_RULE_SET] == 6


# ── Position adapter ─────────────────────────────────────────────────────────


class _FakePosition:
    """The subset of a BOQ position the adapter reads."""

    def __init__(self, **fields: Any) -> None:
        self.id = fields.get("id", uuid.uuid4())
        self.parent_id = fields.get("parent_id")
        self.ordinal = fields.get("ordinal", "01.001")
        self.description = fields.get("description", "Concrete wall")
        self.unit = fields.get("unit", "m3")
        self.quantity = fields.get("quantity", "10")
        self.unit_rate = fields.get("unit_rate", "100")
        self.total = fields.get("total", "1000")
        self.classification = fields.get("classification", {"din276": "330"})
        self.source = fields.get("source", "manual")
        self.metadata_ = fields.get("metadata_", {})


def test_the_adapter_passes_money_through_as_stored_strings() -> None:
    """Stored decimal strings must reach the rules untouched, never as floats."""
    adapted = to_validation_position(_FakePosition(quantity="1 234,50", unit_rate="99.95"))
    assert adapted["quantity"] == "1 234,50"
    assert adapted["unit_rate"] == "99.95"
    assert adapted["type"] == "position"


def test_the_adapter_marks_a_section_header() -> None:
    """A header row is typed as a section so leaf rules skip it."""
    adapted = to_validation_position(_FakePosition(unit="", quantity="0", unit_rate="0"))
    assert adapted["type"] == "section"


def test_the_adapter_resolves_the_position_currency() -> None:
    """The per-position currency comes from its metadata, upper-cased."""
    adapted = to_validation_position(_FakePosition(metadata_={"currency": "usd"}))
    assert adapted["currency"] == "USD"


def test_the_adapter_turns_an_empty_value_into_a_zero_string() -> None:
    """An empty stored value becomes "0", not ``None``."""
    adapted = to_validation_position(_FakePosition(quantity="", unit_rate=None, total=""))
    assert adapted["quantity"] == "0"
    assert adapted["unit_rate"] == "0"
    assert adapted["total"] == "0"
