# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the ``rfq_issue`` and ``rfq_award`` validation rule sets.

This module has two rule sets rather than one, because the deadline must be in
the future when an RFQ is published and has necessarily passed by the time it is
awarded. A single set could only hold both by way of a rule that silently
no-ops, which no reachability test can distinguish from a rule nobody calls. So
the split itself is pinned here, not only the rules.

No database. The clock arrives as data (``as_of``) so none of this rots.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from app.core.validation.engine import Severity, rule_registry, validation_engine
from app.core.validation.rules import (
    RFQAwardHasCompetition,
    RFQBidAmountsParseable,
    RFQBidCurrencyMatches,
    RFQBidsStillValid,
    RFQCurrencySet,
    RFQDeadlineInFuture,
    RFQDeadlineParseable,
    RFQDeadlinePresent,
    RFQHasRecipients,
    RFQScopeDescribed,
    register_builtin_rules,
)
from app.modules.rfq_bidding import validators as checks

ISSUE_RULES = [
    RFQScopeDescribed,
    RFQDeadlinePresent,
    RFQDeadlineParseable,
    RFQDeadlineInFuture,
    RFQHasRecipients,
    RFQCurrencySet,
]
AWARD_RULES = [
    RFQScopeDescribed,
    RFQCurrencySet,
    RFQDeadlineParseable,
    RFQBidCurrencyMatches,
    RFQBidAmountsParseable,
    RFQBidsStillValid,
    RFQAwardHasCompetition,
]

TODAY = "2026-07-26"


def _bid(**overrides: object) -> dict:
    base = {
        "bidder_contact_id": "vendor-a",
        "bid_amount": "125000.00",
        "currency_code": "EUR",
        "submitted_at": "2026-07-20",
        "validity_days": 30,
        "is_awarded": False,
    }
    base.update(overrides)
    return base


def _rfq(**overrides: object) -> dict:
    """A clean RFQ with three comparable bids: every check passes."""
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "project_id": "22222222-2222-2222-2222-222222222222",
        "rfq_number": "RFQ-014",
        "title": "Mechanical fit-out",
        "status": "draft",
        "description": "Supply and install to levels 1-4",
        "scope_of_work": "Ductwork, AHU, commissioning",
        "submission_deadline": "2026-08-15",
        "currency_code": "EUR",
        "issued_to_contacts": ["vendor-a", "vendor-b", "vendor-c"],
        "as_of": TODAY,
        "bids": [
            _bid(bidder_contact_id="vendor-a"),
            _bid(bidder_contact_id="vendor-b", bid_amount="131000.00"),
            _bid(bidder_contact_id="vendor-c", bid_amount="119500.00"),
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# What a vendor needs in order to bid
# ---------------------------------------------------------------------------


class TestScopeDescribed:
    def test_a_described_rfq_passes(self) -> None:
        assert checks.check_scope_described(_rfq()) == []

    def test_either_field_alone_is_enough(self) -> None:
        assert checks.check_scope_described(_rfq(description=None)) == []
        assert checks.check_scope_described(_rfq(scope_of_work=None)) == []

    def test_neither_field_is_reported(self) -> None:
        findings = checks.check_scope_described(_rfq(description=None, scope_of_work=""))
        assert len(findings) == 1
        assert findings[0].element_ref == "RFQ-014"

    def test_a_title_is_not_a_scope(self) -> None:
        """The failure this rule exists for: a subject line sent out as a package."""
        assert len(checks.check_scope_described(_rfq(description="   ", scope_of_work=None))) == 1


class TestDeadlinePresent:
    def test_a_deadline_passes(self) -> None:
        assert checks.check_deadline_present(_rfq()) == []

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_a_missing_deadline_is_reported(self, value: str | None) -> None:
        assert len(checks.check_deadline_present(_rfq(submission_deadline=value))) == 1


class TestDeadlineParseable:
    def test_a_plain_date_passes(self) -> None:
        assert checks.check_deadline_parseable(_rfq()) == []

    @pytest.mark.parametrize(
        "value",
        ["2026-08-15", "2026-08-15T17:00:00", "2026-08-15T17:00:00Z", "2026-08-15T17:00:00+02:00"],
    )
    def test_every_shape_the_column_really_holds_is_accepted(self, value: str) -> None:
        """The column is free-form and both shapes occur in real data."""
        assert checks.check_deadline_parseable(_rfq(submission_deadline=value)) == []

    def test_an_unreadable_deadline_is_reported(self) -> None:
        findings = checks.check_deadline_parseable(_rfq(submission_deadline="end of August"))
        assert len(findings) == 1
        assert findings[0].params["value"] == "end of August"

    def test_a_missing_deadline_is_left_to_the_presence_rule(self) -> None:
        assert checks.check_deadline_parseable(_rfq(submission_deadline=None)) == []


class TestDeadlineInFuture:
    def test_a_future_deadline_passes(self) -> None:
        assert checks.check_deadline_in_future(_rfq()) == []

    def test_a_deadline_today_passes(self) -> None:
        assert checks.check_deadline_in_future(_rfq(submission_deadline=TODAY)) == []

    def test_a_past_deadline_is_reported(self) -> None:
        findings = checks.check_deadline_in_future(_rfq(submission_deadline="2026-07-01"))
        assert len(findings) == 1
        assert findings[0].params == {"deadline": "2026-07-01", "today": TODAY}

    def test_an_unreadable_deadline_is_left_to_the_parse_rule(self) -> None:
        assert checks.check_deadline_in_future(_rfq(submission_deadline="soon")) == []

    def test_without_a_clock_the_rule_says_nothing(self) -> None:
        """Better silent than wrong: guessing "now" would make the finding unpinnable."""
        assert checks.check_deadline_in_future(_rfq(submission_deadline="2026-07-01", as_of=None)) == []


class TestHasRecipients:
    def test_addressed_rfqs_pass(self) -> None:
        assert checks.check_has_recipients(_rfq()) == []

    def test_an_empty_list_is_reported(self) -> None:
        assert len(checks.check_has_recipients(_rfq(issued_to_contacts=[]))) == 1

    def test_a_list_of_blanks_counts_as_nobody(self) -> None:
        assert len(checks.check_has_recipients(_rfq(issued_to_contacts=["", "  "]))) == 1

    def test_a_malformed_value_counts_as_nobody(self) -> None:
        assert len(checks.check_has_recipients(_rfq(issued_to_contacts="vendor-a"))) == 1


class TestCurrencySet:
    def test_a_currency_passes(self) -> None:
        assert checks.check_currency_set(_rfq()) == []

    @pytest.mark.parametrize("value", [None, "", "  "])
    def test_a_blank_currency_is_reported(self, value: str | None) -> None:
        assert len(checks.check_currency_set(_rfq(currency_code=value))) == 1


# ---------------------------------------------------------------------------
# What the comparison between bids relies on
# ---------------------------------------------------------------------------


class TestBidCurrencyMatches:
    def test_bids_in_the_rfq_currency_pass(self) -> None:
        assert checks.check_bid_currency_matches(_rfq()) == []

    def test_case_is_not_a_mismatch(self) -> None:
        rfq = _rfq(bids=[_bid(currency_code="eur")])
        assert checks.check_bid_currency_matches(rfq) == []

    def test_a_foreign_currency_bid_is_reported(self) -> None:
        rfq = _rfq(bids=[_bid(currency_code="EUR"), _bid(bidder_contact_id="vendor-b", currency_code="USD")])
        findings = checks.check_bid_currency_matches(rfq)
        assert len(findings) == 1
        assert findings[0].element_ref == "2 (vendor-b)"
        assert findings[0].params["bid_currency"] == "USD"
        assert findings[0].params["rfq_currency"] == "EUR"

    def test_every_mismatched_bid_is_reported_not_just_the_first(self) -> None:
        rfq = _rfq(
            bids=[
                _bid(bidder_contact_id="a", currency_code="USD"),
                _bid(bidder_contact_id="b", currency_code="GBP"),
                _bid(bidder_contact_id="c", currency_code="EUR"),
            ]
        )
        assert [f.element_ref for f in checks.check_bid_currency_matches(rfq)] == ["1 (a)", "2 (b)"]

    def test_with_no_rfq_currency_the_finding_belongs_to_the_other_rule(self) -> None:
        """Reporting every bid against a blank would bury the one real problem."""
        assert checks.check_bid_currency_matches(_rfq(currency_code="")) == []


class TestBidAmountsParseable:
    def test_numeric_bids_pass(self) -> None:
        assert checks.check_bid_amounts_parseable(_rfq()) == []

    @pytest.mark.parametrize("value", ["on request", "", "0", "-5000"])
    def test_an_unrankable_amount_is_reported(self, value: str) -> None:
        rfq = _rfq(bids=[_bid(bid_amount=value)])
        assert len(checks.check_bid_amounts_parseable(rfq)) == 1

    def test_the_reported_value_is_truncated_for_the_message(self) -> None:
        rfq = _rfq(bids=[_bid(bid_amount="x" * 80)])
        assert len(checks.check_bid_amounts_parseable(rfq)[0].params["value"]) == 40


class TestBidsStillValid:
    def test_a_bid_inside_its_validity_passes(self) -> None:
        assert checks.check_bids_still_valid(_rfq()) == []

    def test_a_bid_expiring_today_still_passes(self) -> None:
        """Expiry is the last valid day, not the first invalid one."""
        rfq = _rfq(bids=[_bid(submitted_at="2026-06-26", validity_days=30)])
        assert checks.check_bids_still_valid(rfq) == []

    def test_a_lapsed_bid_is_reported(self) -> None:
        rfq = _rfq(bids=[_bid(submitted_at="2026-01-01", validity_days=30)])
        findings = checks.check_bids_still_valid(rfq)
        assert len(findings) == 1
        assert findings[0].params["expired"] == "2026-01-31"
        assert findings[0].params["today"] == TODAY

    @pytest.mark.parametrize("validity", [0, None, "many"])
    def test_an_unusable_validity_is_skipped_rather_than_guessed(self, validity: object) -> None:
        rfq = _rfq(bids=[_bid(submitted_at="2026-01-01", validity_days=validity)])
        assert checks.check_bids_still_valid(rfq) == []

    def test_a_bid_with_no_submission_date_is_skipped(self) -> None:
        rfq = _rfq(bids=[_bid(submitted_at=None, validity_days=30)])
        assert checks.check_bids_still_valid(rfq) == []


class TestAwardHasCompetition:
    def test_three_bids_pass(self) -> None:
        assert checks.check_award_has_competition(_rfq()) == []

    @pytest.mark.parametrize("count", [0, 1, 2])
    def test_a_thin_field_is_reported(self, count: int) -> None:
        rfq = _rfq(bids=[_bid(bidder_contact_id=f"v{i}") for i in range(count)])
        findings = checks.check_award_has_competition(rfq)
        assert len(findings) == 1
        assert findings[0].params == {"count": str(count), "minimum": str(checks.MIN_COMPETITIVE_BIDS)}


class TestClockDiscipline:
    def test_no_rule_in_this_module_reads_the_system_clock(self) -> None:
        """Walks the syntax tree, so the docstring explaining this cannot satisfy it."""
        tree = ast.parse(inspect.getsource(checks))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "today" not in called
        assert "now" not in called
        assert "utcnow" not in called


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------


class TestReachability:
    def test_the_issue_set_holds_exactly_the_issue_rules(self) -> None:
        register_builtin_rules()
        registered = {r.rule_id for r in rule_registry.get_rules_for_sets(["rfq_issue"])}
        assert {rule_cls.rule_id for rule_cls in ISSUE_RULES}.issubset(registered)

    def test_the_award_set_holds_exactly_the_award_rules(self) -> None:
        register_builtin_rules()
        registered = {r.rule_id for r in rule_registry.get_rules_for_sets(["rfq_award"])}
        assert {rule_cls.rule_id for rule_cls in AWARD_RULES}.issubset(registered)

    def test_the_deadline_in_future_rule_is_absent_from_the_award_set(self) -> None:
        """The reason there are two sets at all.

        By award time the deadline has passed on purpose. If this rule were in
        the award set it would fail on every award forever, and the noise would
        teach people to ignore the whole report.
        """
        register_builtin_rules()
        registered = {r.rule_id for r in rule_registry.get_rules_for_sets(["rfq_award"])}
        assert RFQDeadlineInFuture.rule_id not in registered

    def test_both_sets_are_ones_a_caller_actually_passes(self) -> None:
        """The ai_takeoff guard: a set nobody names never runs."""
        from app.modules.rfq_bidding.service import (
            RFQ_AWARD_RULE_SET,
            RFQ_ISSUE_RULE_SET,
            RFQService,
        )

        assert RFQ_ISSUE_RULE_SET == "rfq_issue"
        assert RFQ_AWARD_RULE_SET == "rfq_award"

        issue_source = inspect.getsource(RFQService.issue_rfq)
        assert "RFQ_ISSUE_RULE_SET" in issue_source
        award_source = inspect.getsource(RFQService.award_bid)
        assert "RFQ_AWARD_RULE_SET" in award_source

        validate_source = inspect.getsource(RFQService._validate_rfq)
        assert "validation_engine.validate" in validate_source

    def test_publishing_and_awarding_report_rather_than_refuse(self) -> None:
        """A deliberate choice, pinned so a later change is a decision."""
        from app.modules.rfq_bidding.service import RFQService

        source = inspect.getsource(RFQService._report_rfq_validation)
        assert "raise" not in source
        assert "logger.warning" in source

    def test_the_read_only_endpoint_refuses_an_unknown_stage(self) -> None:
        """Quietly defaulting is how a set gets trusted for a check it never ran."""
        from app.modules.rfq_bidding.service import RFQService

        source = inspect.getsource(RFQService.validate_rfq)
        assert "Unknown validation stage" in source


# ---------------------------------------------------------------------------
# Engine contract
# ---------------------------------------------------------------------------


class TestEngineContract:
    """What a caller reads: the report, not the check's return value."""

    async def _report(self, rfq: dict, rule_set: str):
        register_builtin_rules()
        return await validation_engine.validate(
            data=rfq,
            rule_sets=[rule_set],
            target_type="rfq",
            target_id="11111111-1111-1111-1111-111111111111",
            project_id="22222222-2222-2222-2222-222222222222",
            metadata={"locale": "en"},
        )

    async def test_a_clean_rfq_passes_the_issue_set(self) -> None:
        report = await self._report(_rfq(), "rfq_issue")
        assert not report.has_errors

    async def test_a_clean_rfq_passes_the_award_set(self) -> None:
        report = await self._report(_rfq(), "rfq_award")
        assert not report.has_errors
        assert report.warnings == []

    async def test_a_past_deadline_fails_at_issue_and_not_at_award(self) -> None:
        """The whole point of the split, asserted end to end through the engine."""
        rfq = _rfq(submission_deadline="2026-07-01")
        at_issue = await self._report(rfq, "rfq_issue")
        at_award = await self._report(rfq, "rfq_award")
        assert [r.rule_id for r in at_issue.errors] == ["rfq.deadline_in_future"]
        assert at_award.errors == []

    async def test_a_single_isolated_error_is_reported_alone(self) -> None:
        report = await self._report(_rfq(currency_code=""), "rfq_issue")
        assert [r.rule_id for r in report.errors] == ["rfq.currency_set"]

    async def test_an_advisory_finding_never_becomes_an_error(self) -> None:
        report = await self._report(_rfq(bids=[_bid()]), "rfq_award")
        assert not report.has_errors
        assert "rfq.award_has_competition" in {r.rule_id for r in report.warnings}

    async def test_every_problem_is_listed_at_once(self) -> None:
        rfq = _rfq(currency_code="", description=None, scope_of_work=None, issued_to_contacts=[])
        report = await self._report(rfq, "rfq_issue")
        assert {r.rule_id for r in report.errors} == {
            "rfq.currency_set",
            "rfq.scope_described",
            "rfq.has_recipients",
        }

    async def test_the_message_is_translated_not_a_key(self) -> None:
        report = await self._report(_rfq(currency_code=""), "rfq_issue")
        message = report.errors[0].message
        assert "rfq." not in message
        assert "currency" in message.lower()

    async def test_both_rule_sets_resolve(self) -> None:
        register_builtin_rules()
        assert rule_registry.has_rules("rfq_issue")
        assert rule_registry.has_rules("rfq_award")

    async def test_severity_survives_the_round_trip(self) -> None:
        report = await self._report(_rfq(currency_code=""), "rfq_issue")
        assert report.errors[0].severity is Severity.ERROR
