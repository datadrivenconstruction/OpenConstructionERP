# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The module's own validation rules: the scope, the standing, the comparison.

Ten rules for this module live in the core rule file and are covered by
``tests/unit/test_rfq_bidding_validation_rules.py``. The rules here are the
ones the module registers itself, from its startup hook, into the same two
sets. They are checked three ways: that they are registered at all, that each
one fires on the situation it exists for, and that none of them says anything
about an RFQ that predates the data they read. The last one matters as much as
the others - these rules share a registry with everything else in the process,
so a rule that talks when it has nothing to look at becomes noise in every
other module's report.

No database.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.modules.rfq_bidding import comparison as cmp
from app.modules.rfq_bidding import validators as checks
from app.modules.rfq_bidding.service import RFQ_AWARD_RULE_SET, RFQ_ISSUE_RULE_SET

TODAY = "2026-07-10"


@pytest.fixture(autouse=True)
def _registered() -> None:
    """Register the module rules; the startup hook does not run in tests."""
    checks.register_rfq_validation_rules()


def _line(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "line-1",
        "line_no": 1,
        "code": "A1",
        "description": "Ductwork",
        "unit": "m2",
        "quantity": "100",
        "is_optional": False,
    }
    base.update(overrides)
    return base


def _quote(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "bid-a",
        "bidder_contact_id": "alpha",
        "bid_amount": "1000",
        "currency_code": "EUR",
        "status": "received",
        "is_late": False,
        "admitted_at": None,
        "submitted_at": "2026-07-01",
        "validity_days": 60,
        "technical_score": None,
        "exchange_rate": None,
        "lines": [],
        "adjustments": [],
    }
    base.update(overrides)
    return base


def _rfq(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "rfq-1",
        "rfq_number": "RFQ-014",
        "title": "Mechanical fit-out",
        "currency_code": "EUR",
        "evaluation_method": "lowest_price",
        "technical_weight": "0",
        "require_full_scope": True,
        "as_of": TODAY,
        "lines": [],
        "bids": [],
    }
    base.update(overrides)
    return base


def _with_comparison(rfq: dict[str, Any], *, candidate_bid_id: str | None = None) -> dict[str, Any]:
    """Attach the comparison exactly as the service does before validating."""
    payload = dict(rfq)
    payload["comparison"] = cmp.compare(rfq).as_dict()
    payload["candidate_bid_id"] = candidate_bid_id
    return payload


async def _run(rule: Any, payload: dict[str, Any]) -> list[RuleResult]:
    return await rule.validate(ValidationContext(data=payload, project_id="p1"))


def _failures(results: list[RuleResult]) -> list[RuleResult]:
    return [result for result in results if not result.passed]


# ── Reachability ────────────────────────────────────────────────────────────


class TestRegistration:
    def test_the_module_rules_land_in_the_two_sets_the_service_asks_for(self) -> None:
        issue = {rule.rule_id for rule in rule_registry.get_rules_for_sets([RFQ_ISSUE_RULE_SET])}
        award = {rule.rule_id for rule in rule_registry.get_rules_for_sets([RFQ_AWARD_RULE_SET])}
        assert {"rfq.scope_lines_measurable", "rfq.scope_line_codes_unique"} <= issue
        assert {
            "rfq.quote_comparable",
            "rfq.quote_covers_scope",
            "rfq.quote_lines_match_total",
            "rfq.late_quote_in_field",
            "rfq.award_follows_ranking",
            "rfq.exclusions_priced",
        } <= award
        assert "rfq.evaluation_basis_coherent" in issue & award

    def test_no_module_rule_shadows_a_core_rule_id(self) -> None:
        """The registry keys by id, so a clash would silently replace the core rule."""
        core_ids = {
            "rfq.scope_described",
            "rfq.deadline_present",
            "rfq.deadline_parseable",
            "rfq.deadline_in_future",
            "rfq.has_recipients",
            "rfq.currency_set",
            "rfq.bid_currency_matches",
            "rfq.bid_amounts_parseable",
            "rfq.bids_still_valid",
            "rfq.award_has_competition",
        }
        module_ids = {
            rule.rule_id for rule in (*checks._RFQ_ISSUE_RULES, *checks._RFQ_AWARD_RULES, *checks._RFQ_BOTH_RULES)
        }
        assert core_ids.isdisjoint(module_ids)

    def test_registering_twice_is_a_no_op(self) -> None:
        checks.register_rfq_validation_rules()
        ids = [rule.rule_id for rule in rule_registry.get_rules_for_sets([RFQ_AWARD_RULE_SET])]
        assert len(ids) == len(set(ids))


# ── The scope suppliers are asked to price ──────────────────────────────────


class TestScopeRules:
    async def test_a_line_without_a_unit_is_reported(self) -> None:
        payload = _rfq(lines=[_line(unit="")])
        failures = _failures(await _run(checks.RFQScopeLinesMeasurable(), payload))
        assert len(failures) == 1
        assert failures[0].severity is Severity.ERROR
        assert "unit" in failures[0].message

    async def test_a_line_with_no_quantity_is_reported(self) -> None:
        payload = _rfq(lines=[_line(quantity="0")])
        assert len(_failures(await _run(checks.RFQScopeLinesMeasurable(), payload))) == 1

    async def test_a_measurable_scope_passes(self) -> None:
        payload = _rfq(lines=[_line(), _line(id="line-2", line_no=2, code="A2")])
        assert _failures(await _run(checks.RFQScopeLinesMeasurable(), payload)) == []

    async def test_a_repeated_reference_code_is_reported(self) -> None:
        payload = _rfq(lines=[_line(), _line(id="line-2", line_no=2, code="A1")])
        failures = _failures(await _run(checks.RFQScopeLineCodesUnique(), payload))
        assert len(failures) == 1
        assert failures[0].element_ref == "a1"

    async def test_lines_without_codes_are_not_duplicates_of_each_other(self) -> None:
        payload = _rfq(lines=[_line(code=None), _line(id="line-2", line_no=2, code="")])
        assert _failures(await _run(checks.RFQScopeLineCodesUnique(), payload)) == []


class TestEvaluationBasis:
    async def test_best_value_with_no_weight_is_reported(self) -> None:
        payload = _rfq(evaluation_method="best_value", technical_weight="0")
        failures = _failures(await _run(checks.RFQEvaluationBasisCoherent(), payload))
        assert len(failures) == 1

    async def test_lowest_price_with_a_weight_is_reported(self) -> None:
        payload = _rfq(evaluation_method="lowest_price", technical_weight="30")
        assert len(_failures(await _run(checks.RFQEvaluationBasisCoherent(), payload))) == 1

    async def test_a_coherent_basis_passes(self) -> None:
        payload = _rfq(evaluation_method="best_value", technical_weight="30")
        assert _failures(await _run(checks.RFQEvaluationBasisCoherent(), payload)) == []


# ── What the comparison found ───────────────────────────────────────────────


class TestComparisonRules:
    async def test_a_quote_kept_out_of_the_ranking_is_reported_with_its_reason(self) -> None:
        payload = _with_comparison(_rfq(bids=[_quote(id="bid-b", bidder_contact_id="beta", currency_code="USD")]))
        failures = _failures(await _run(checks.RFQQuoteComparable(), payload))
        assert len(failures) == 1
        assert failures[0].severity is Severity.ERROR
        assert cmp.REASON_CURRENCY_NOT_CONVERTED in failures[0].details["reasons"]
        assert failures[0].element_ref == "beta"

    async def test_a_field_of_comparable_quotes_passes(self) -> None:
        payload = _with_comparison(_rfq(bids=[_quote(), _quote(id="bid-b", bidder_contact_id="beta")]))
        assert _failures(await _run(checks.RFQQuoteComparable(), payload)) == []

    async def test_a_partial_quote_is_reported_even_when_partial_quotes_are_allowed(self) -> None:
        payload = _with_comparison(
            _rfq(
                require_full_scope=False,
                lines=[_line(), _line(id="line-2", line_no=2, code="A2", description="Commissioning")],
                bids=[
                    _quote(
                        lines=[
                            {
                                "id": "q1",
                                "rfq_line_id": "line-1",
                                "unit": "m2",
                                "quantity": "100",
                                "unit_rate": "10",
                                "amount": "1000",
                                "unit_conversion_factor": None,
                                "is_excluded": False,
                            }
                        ]
                    )
                ],
            )
        )
        failures = _failures(await _run(checks.RFQQuoteCoversScope(), payload))
        assert len(failures) == 1
        assert failures[0].severity is Severity.WARNING
        assert failures[0].details["lines_covered"] == 1
        assert failures[0].details["lines_required"] == 2

    async def test_lines_that_disagree_with_the_headline_are_reported(self) -> None:
        payload = _with_comparison(
            _rfq(
                lines=[_line()],
                bids=[
                    _quote(
                        bid_amount="1000",
                        lines=[
                            {
                                "id": "q1",
                                "rfq_line_id": "line-1",
                                "unit": "m2",
                                "quantity": "100",
                                "unit_rate": "8",
                                "amount": "800",
                                "unit_conversion_factor": None,
                                "is_excluded": False,
                            }
                        ],
                    )
                ],
            )
        )
        failures = _failures(await _run(checks.RFQQuoteLinesMatchTotal(), payload))
        assert len(failures) == 1
        assert failures[0].details["line_total"] == "800.00"

    async def test_a_late_quote_is_reported_whether_or_not_it_was_admitted(self) -> None:
        not_admitted = _with_comparison(_rfq(bids=[_quote(status="late", is_late=True)]))
        failures = _failures(await _run(checks.RFQLateQuoteInField(), not_admitted))
        assert len(failures) == 1
        assert "not in the ranking" in failures[0].message

        admitted = _with_comparison(
            _rfq(bids=[_quote(status="late", is_late=True, admitted_at="2026-07-09T10:00:00Z")])
        )
        failures = _failures(await _run(checks.RFQLateQuoteInField(), admitted))
        assert len(failures) == 1
        assert failures[0].details["admitted"] is True

    async def test_an_award_that_passes_over_the_top_ranked_quote_is_reported(self) -> None:
        rfq = _rfq(
            bids=[
                _quote(id="bid-a", bidder_contact_id="alpha", bid_amount="1200"),
                _quote(id="bid-b", bidder_contact_id="beta", bid_amount="900"),
            ]
        )
        payload = _with_comparison(rfq, candidate_bid_id="bid-a")
        failures = _failures(await _run(checks.RFQAwardFollowsRanking(), payload))
        assert len(failures) == 1
        assert failures[0].details["recommended_bid_id"] == "bid-b"
        assert failures[0].severity is Severity.WARNING

    async def test_awarding_the_top_ranked_quote_passes(self) -> None:
        rfq = _rfq(
            bids=[
                _quote(id="bid-a", bidder_contact_id="alpha", bid_amount="1200"),
                _quote(id="bid-b", bidder_contact_id="beta", bid_amount="900"),
            ]
        )
        payload = _with_comparison(rfq, candidate_bid_id="bid-b")
        assert _failures(await _run(checks.RFQAwardFollowsRanking(), payload)) == []

    async def test_without_a_candidate_the_award_rule_says_nothing(self) -> None:
        payload = _with_comparison(_rfq(bids=[_quote()]))
        assert await _run(checks.RFQAwardFollowsRanking(), payload) == []


class TestExclusionsPriced:
    async def test_an_exclusion_with_no_amount_is_reported(self) -> None:
        payload = _rfq(
            bids=[
                _quote(
                    adjustments=[{"kind": "freight", "amount": "0", "included_in_bid": False, "currency_code": "EUR"}]
                )
            ]
        )
        failures = _failures(await _run(checks.RFQExclusionsPriced(), payload))
        assert len(failures) == 1
        assert failures[0].details["kinds"] == ["freight"]

    async def test_a_priced_exclusion_passes(self) -> None:
        payload = _rfq(
            bids=[
                _quote(
                    adjustments=[{"kind": "freight", "amount": "250", "included_in_bid": False, "currency_code": "EUR"}]
                )
            ]
        )
        assert _failures(await _run(checks.RFQExclusionsPriced(), payload)) == []

    async def test_an_item_already_in_the_price_needs_no_amount(self) -> None:
        payload = _rfq(
            bids=[
                _quote(
                    adjustments=[{"kind": "freight", "amount": "0", "included_in_bid": True, "currency_code": "EUR"}]
                )
            ]
        )
        assert _failures(await _run(checks.RFQExclusionsPriced(), payload)) == []


# ── Silence where there is nothing to see ───────────────────────────────────


class TestLegacyPayloadsStaySilent:
    """An RFQ from before this register existed must produce no new findings.

    These rules share one process-wide registry with every other module, and an
    RFQ with no scope lines, no quoted detail and no comparison attached is not
    a faulty RFQ - it is the shape the register had until now. A rule that
    reported on it would turn every existing report amber for no defect.
    """

    @staticmethod
    def _legacy() -> dict[str, Any]:
        return {
            "id": "rfq-legacy",
            "rfq_number": "RFQ-001",
            "title": "Concrete works",
            "status": "published",
            "description": "C30/37 to foundations",
            "scope_of_work": "See attached drawings",
            "submission_deadline": "2026-08-15",
            "currency_code": "EUR",
            "issued_to_contacts": ["alpha", "beta", "gamma"],
            "as_of": TODAY,
            "bids": [
                {
                    "bidder_contact_id": "alpha",
                    "bid_amount": "125000.00",
                    "currency_code": "EUR",
                    "submitted_at": "2026-07-01",
                    "validity_days": 30,
                    "is_awarded": False,
                }
            ],
        }

    @pytest.mark.parametrize(
        "rule",
        [*checks._RFQ_ISSUE_RULES, *checks._RFQ_AWARD_RULES, *checks._RFQ_BOTH_RULES],
        ids=lambda rule: rule.rule_id,
    )
    async def test_no_module_rule_reports_on_a_legacy_rfq(self, rule: Any) -> None:
        assert _failures(await _run(rule, self._legacy())) == []
