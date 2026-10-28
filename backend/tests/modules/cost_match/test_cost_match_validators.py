# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The ``cost_match`` rule set, exercised through the core validation engine.

No database: the rules are pure and read plain dicts, so these drive
``evaluate_result`` / ``evaluate_run`` directly. Going through the engine is
also the honest test of the wiring - a rule that is registered but never
requested by rule-set name is dormant, and only a call through the engine
proves it actually runs.

Every test names the rule it is about and asserts on that rule id, so removing
a rule (or breaking its trigger) fails a test rather than quietly reducing a
finding count.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.cost_match.schemas import CostMatchValidationReport
from app.modules.cost_match.validators import (
    COST_MATCH_RULE_SET,
    evaluate_result,
    evaluate_run,
    merge_reports,
    register_cost_match_rules,
)

RUN_ID = "11111111-1111-1111-1111-111111111111"
RESULT_ID = "22222222-2222-2222-2222-222222222222"
REVIEWER_ID = "33333333-3333-3333-3333-333333333333"
ITEM_A = "44444444-4444-4444-4444-444444444444"
ITEM_B = "55555555-5555-5555-5555-555555555555"


@pytest.fixture(autouse=True)
def _rules_registered():
    """Re-register before each test.

    The registry is process-global and another module's suite may have
    replaced a rule set. Re-registering is idempotent and makes this file
    independent of collection order.
    """
    register_cost_match_rules()


def _result(**overrides: Any) -> dict[str, Any]:
    """A clean, confirmed result payload that fires no rule, plus overrides."""
    base: dict[str, Any] = {
        "id": RESULT_ID,
        "run_id": RUN_ID,
        "line_no": 1,
        "source_ref": "SUB-014",
        "source_description": "Reinforced concrete wall C30/37",
        "source_unit": "m3",
        "source_quantity": "44.300",
        "tier": "exact",
        "confidence": "1.0000",
        "tie": False,
        "hint_code": "",
        "suggested_cost_item_id": ITEM_A,
        "suggested_code": "CM-C30-WALL",
        "suggested_unit": "m3",
        "suggested_rate": "185.0000",
        "suggested_currency": "EUR",
        "decision_state": "confirmed",
        "alternative_count": 3,
        "decision_seq": 1,
        "decided_by": REVIEWER_ID,
        "decided_cost_item_id": ITEM_A,
        "decided_code": "CM-C30-WALL",
        "decided_description": "Reinforced concrete wall C30/37",
        "decided_unit": "m3",
        "decided_rate": "185.0000",
        "decided_currency": "EUR",
        "confidence_at_decision": "1.0000",
        "note": None,
    }
    base.update(overrides)
    return base


def _fired(report: CostMatchValidationReport) -> set[str]:
    return {finding.rule_id for finding in report.findings}


def _severity(report: CostMatchValidationReport, rule_id: str) -> str:
    for finding in report.findings:
        if finding.rule_id == rule_id:
            return finding.severity
    raise AssertionError(f"{rule_id} did not fire")


# ── the clean baseline ──────────────────────────────────────────────────────


class TestCleanBaseline:
    async def test_a_well_formed_confirmed_line_fires_nothing(self) -> None:
        report = await evaluate_result({"result": _result()})
        assert _fired(report) == set()
        assert report.error_count == 0
        assert report.warning_count == 0

    async def test_the_rule_set_is_reachable_by_name(self) -> None:
        """A registered rule nobody requests by rule-set name never runs."""
        report = await evaluate_result({"result": _result()})
        assert COST_MATCH_RULE_SET not in report.unsupported_rule_sets
        assert report.passed_count > 0


# ── result-scope rules ──────────────────────────────────────────────────────


class TestResultScopeRules:
    async def test_source_description_present(self) -> None:
        report = await evaluate_result({"result": _result(source_description="   ")})
        assert "cost_match.source_description_present" in _fired(report)
        assert _severity(report, "cost_match.source_description_present") == "error"

    async def test_source_unit_present(self) -> None:
        report = await evaluate_result({"result": _result(source_unit="")})
        assert "cost_match.source_unit_present" in _fired(report)
        assert _severity(report, "cost_match.source_unit_present") == "warning"

    async def test_unit_dimension_mismatch_is_an_error(self) -> None:
        """An area rate adopted for a volume line is the expensive mistake."""
        report = await evaluate_result({"result": _result(source_unit="m2", decided_unit="m3")})
        assert "cost_match.unit_dimension_matches" in _fired(report)
        assert _severity(report, "cost_match.unit_dimension_matches") == "error"

    async def test_imperial_and_metric_of_one_dimension_do_not_fire(self) -> None:
        """Square feet against square metres is a conversion, not a mismatch."""
        report = await evaluate_result({"result": _result(source_unit="sqft", decided_unit="m2")})
        assert "cost_match.unit_dimension_matches" not in _fired(report)

    async def test_unknown_unit_is_not_asserted_as_a_mismatch(self) -> None:
        """A unit the platform does not recognise is a gap, not a contradiction."""
        report = await evaluate_result({"result": _result(source_unit="ZZZ", decided_unit="m3")})
        assert "cost_match.unit_dimension_matches" not in _fired(report)

    async def test_pending_line_is_not_dimension_checked(self) -> None:
        """Nothing is adopted yet, so there is no pairing to check."""
        report = await evaluate_result(
            {"result": _result(decision_state="pending", source_unit="m2", decided_unit="m3")}
        )
        assert "cost_match.unit_dimension_matches" not in _fired(report)

    async def test_missing_rate_is_an_error(self) -> None:
        report = await evaluate_result({"result": _result(decided_rate=None)})
        assert "cost_match.rate_present" in _fired(report)
        assert _severity(report, "cost_match.rate_present") == "error"

    async def test_zero_rate_is_an_error(self) -> None:
        report = await evaluate_result({"result": _result(decided_rate="0.0000")})
        assert "cost_match.rate_present" in _fired(report)

    async def test_rejected_line_needs_no_rate(self) -> None:
        """A rejection adopts nothing, so the rate rules do not apply to it."""
        report = await evaluate_result(
            {
                "result": _result(
                    decision_state="rejected",
                    decided_cost_item_id=None,
                    decided_code="",
                    decided_unit="",
                    decided_rate=None,
                    decided_currency="",
                )
            }
        )
        fired = _fired(report)
        assert "cost_match.rate_present" not in fired
        assert "cost_match.unit_dimension_matches" not in fired

    async def test_decision_without_a_reviewer_is_an_error(self) -> None:
        """Platform rule 7: a suggestion never applies itself."""
        report = await evaluate_result({"result": _result(decided_by=None)})
        assert "cost_match.decision_has_reviewer" in _fired(report)
        assert _severity(report, "cost_match.decision_has_reviewer") == "error"

    async def test_pending_line_needs_no_reviewer(self) -> None:
        report = await evaluate_result({"result": _result(decision_state="pending", decided_by=None)})
        assert "cost_match.decision_has_reviewer" not in _fired(report)

    async def test_confirming_below_the_review_floor_warns(self) -> None:
        report = await evaluate_result(
            {"result": _result(tier="unmatched", confidence="0.3000", confidence_at_decision="0.3000")}
        )
        assert "cost_match.confidence_above_floor" in _fired(report)
        assert _severity(report, "cost_match.confidence_above_floor") == "warning"

    async def test_overriding_below_the_floor_does_not_warn(self) -> None:
        """An override is the reviewer's own choice; it does not lean on the score."""
        report = await evaluate_result(
            {
                "result": _result(
                    decision_state="overridden",
                    confidence="0.3000",
                    confidence_at_decision="0.3000",
                    decided_cost_item_id=ITEM_B,
                    decided_code="CM-REBAR",
                )
            }
        )
        assert "cost_match.confidence_above_floor" not in _fired(report)

    async def test_confirmed_tie_warns(self) -> None:
        report = await evaluate_result({"result": _result(tie=True)})
        assert "cost_match.tie_resolved_by_reviewer" in _fired(report)
        assert _severity(report, "cost_match.tie_resolved_by_reviewer") == "warning"

    async def test_overridden_tie_does_not_warn(self) -> None:
        """Overriding a tie is exactly how a reviewer settles it."""
        report = await evaluate_result({"result": _result(tie=True, decision_state="overridden")})
        assert "cost_match.tie_resolved_by_reviewer" not in _fired(report)

    async def test_missing_quantity_is_informational(self) -> None:
        report = await evaluate_result({"result": _result(source_quantity=None)})
        assert "cost_match.quantity_present" in _fired(report)
        assert _severity(report, "cost_match.quantity_present") == "info"


# ── run-scope rules ─────────────────────────────────────────────────────────


def _run_payload(results: list[dict[str, Any]], **run_overrides: Any) -> dict[str, Any]:
    run: dict[str, Any] = {
        "id": RUN_ID,
        "name": "Subcontractor bill",
        "status": "matched",
        "item_count": len(results),
        "cost_source": "cwicr",
        "region": "DE_BERLIN",
    }
    run.update(run_overrides)
    return {"run": run, "results": results}


class TestRunScopeRules:
    async def test_one_currency_fires_nothing(self) -> None:
        report = await evaluate_run(_run_payload([_result(), _result(id=ITEM_B, line_no=2)]))
        assert "cost_match.currency_consistent" not in _fired(report)

    async def test_two_currencies_is_an_error(self) -> None:
        report = await evaluate_run(
            _run_payload(
                [
                    _result(),
                    _result(id=ITEM_B, line_no=2, decided_currency="GBP", decided_cost_item_id=ITEM_B),
                ]
            )
        )
        assert "cost_match.currency_consistent" in _fired(report)
        assert _severity(report, "cost_match.currency_consistent") == "error"

    async def test_repeated_description_priced_two_ways_warns(self) -> None:
        report = await evaluate_run(
            _run_payload(
                [
                    _result(),
                    _result(
                        id=ITEM_B,
                        line_no=2,
                        # Same scope, spelled with different case and spacing.
                        source_description="reinforced   CONCRETE wall c30/37",
                        decided_cost_item_id=ITEM_B,
                        decided_code="CM-REBAR",
                    ),
                ]
            )
        )
        assert "cost_match.duplicate_lines_agree" in _fired(report)
        assert _severity(report, "cost_match.duplicate_lines_agree") == "warning"

    async def test_repeated_description_priced_the_same_way_is_fine(self) -> None:
        report = await evaluate_run(_run_payload([_result(), _result(id=ITEM_B, line_no=2)]))
        assert "cost_match.duplicate_lines_agree" not in _fired(report)

    async def test_pending_lines_keep_the_queue_open(self) -> None:
        report = await evaluate_run(
            _run_payload(
                [
                    _result(),
                    _result(id=ITEM_B, line_no=2, decision_state="pending", decided_by=None),
                ]
            )
        )
        assert "cost_match.review_queue_cleared" in _fired(report)
        assert _severity(report, "cost_match.review_queue_cleared") == "warning"

    async def test_a_fully_reviewed_run_clears_the_queue_rule(self) -> None:
        report = await evaluate_run(_run_payload([_result(), _result(id=ITEM_B, line_no=2)]))
        assert "cost_match.review_queue_cleared" not in _fired(report)

    async def test_result_scope_rules_stay_out_of_the_run_pass(self) -> None:
        """Scope selection is real: a result rule must not report on a run pass."""
        report = await evaluate_run(_run_payload([_result(source_description="")]))
        assert "cost_match.source_description_present" not in _fired(report)

    async def test_run_scope_rules_stay_out_of_the_result_pass(self) -> None:
        report = await evaluate_result({"result": _result(decided_currency="GBP")})
        assert "cost_match.currency_consistent" not in _fired(report)


# ── merging ─────────────────────────────────────────────────────────────────


class TestMergeReports:
    async def test_one_error_anywhere_makes_the_whole_run_an_error(self) -> None:
        clean = await evaluate_result({"result": _result()})
        broken = await evaluate_result({"result": _result(source_unit="m2", decided_unit="m3")})
        merged = merge_reports([clean, broken], target_type="cost_match_run", target_id=RUN_ID)
        assert merged.status == "errors"
        assert merged.error_count == broken.error_count
        assert "cost_match.unit_dimension_matches" in {f.rule_id for f in merged.findings}

    async def test_merging_keeps_every_finding(self) -> None:
        first = await evaluate_result({"result": _result(source_unit="")})
        second = await evaluate_result({"result": _result(id=ITEM_B, source_quantity=None)})
        merged = merge_reports([first, second], target_type="cost_match_run", target_id=RUN_ID)
        assert len(merged.findings) == len(first.findings) + len(second.findings)

    async def test_warnings_only_reports_as_warnings(self) -> None:
        report = await evaluate_result({"result": _result(source_unit="")})
        merged = merge_reports([report], target_type="cost_match_run", target_id=RUN_ID)
        assert merged.status == "warnings"
