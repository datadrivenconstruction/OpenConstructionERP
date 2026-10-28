# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the ``submittal`` validation rule set.

Three layers: the pure checks, what the engine makes of them, and whether a
caller passes the set by name at all. The last one is the only guard against a
rule set that is fully implemented, fully translated and never runs.

No database. The clock arrives as data (``as_of``) so none of this rots.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from app.core.validation.engine import Severity, rule_registry, validation_engine
from app.core.validation.rules import (
    SubmittalApproverDistinctFromReviewer,
    SubmittalLinkedScopePresent,
    SubmittalRequiredDateAfterSubmitted,
    SubmittalRequiredDatePresent,
    SubmittalReviewerAssigned,
    SubmittalReviewWindowSufficient,
    SubmittalSpecSectionPresent,
    register_builtin_rules,
)
from app.modules.submittals import validators as checks

SUBMITTAL_RULES = [
    SubmittalReviewerAssigned,
    SubmittalRequiredDatePresent,
    SubmittalRequiredDateAfterSubmitted,
    SubmittalReviewWindowSufficient,
    SubmittalSpecSectionPresent,
    SubmittalApproverDistinctFromReviewer,
    SubmittalLinkedScopePresent,
]

TODAY = "2026-07-26"
REVIEWER = "33333333-3333-3333-3333-333333333333"
APPROVER = "44444444-4444-4444-4444-444444444444"


def _submittal(**overrides: object) -> dict:
    """A clean submittal: every check passes unless a test breaks one."""
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "project_id": "22222222-2222-2222-2222-222222222222",
        "submittal_number": "SUB-004",
        "title": "Curtain wall shop drawings",
        "status": "draft",
        "spec_section": "08 44 13",
        "reviewer_id": REVIEWER,
        "approver_id": APPROVER,
        "date_submitted": TODAY,
        "date_required": "2026-08-20",
        "current_revision": 1,
        "linked_boq_item_ids": ["55555555-5555-5555-5555-555555555555"],
        "as_of": TODAY,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


class TestReviewerAssigned:
    def test_an_assigned_reviewer_passes(self) -> None:
        assert checks.check_reviewer_assigned(_submittal()) == []

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_no_reviewer_is_reported(self, value: str | None) -> None:
        """``submit_submittal`` moves ball-in-court only when a reviewer exists.

        Without one the submittal is submitted into nobody's court, which is the
        exact condition this rule exists to name.
        """
        findings = checks.check_reviewer_assigned(_submittal(reviewer_id=value))
        assert len(findings) == 1
        assert findings[0].element_ref == "SUB-004"

    def test_the_element_ref_falls_back_to_the_title(self) -> None:
        findings = checks.check_reviewer_assigned(_submittal(reviewer_id=None, submittal_number=""))
        assert findings[0].element_ref == "Curtain wall shop drawings"


class TestApproverDistinctFromReviewer:
    def test_two_different_people_pass(self) -> None:
        assert checks.check_approver_distinct_from_reviewer(_submittal()) == []

    def test_one_person_in_both_roles_is_reported(self) -> None:
        findings = checks.check_approver_distinct_from_reviewer(_submittal(approver_id=REVIEWER))
        assert len(findings) == 1
        assert findings[0].params["person"] == REVIEWER

    def test_an_unassigned_approver_is_not_a_collision(self) -> None:
        """Absence is a different finding from a conflict of roles."""
        assert checks.check_approver_distinct_from_reviewer(_submittal(approver_id=None)) == []


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


class TestRequiredDatePresent:
    def test_a_required_date_passes(self) -> None:
        assert checks.check_required_date_present(_submittal()) == []

    @pytest.mark.parametrize("value", [None, "", "not-a-date"])
    def test_a_missing_or_unreadable_date_is_reported(self, value: str | None) -> None:
        assert len(checks.check_required_date_present(_submittal(date_required=value))) == 1


class TestRequiredDateAfterSubmitted:
    def test_a_future_due_date_passes(self) -> None:
        assert checks.check_required_date_after_submitted(_submittal()) == []

    def test_due_on_the_day_of_submission_passes(self) -> None:
        """Tight, but not impossible. The window rule is what flags it."""
        assert checks.check_required_date_after_submitted(_submittal(date_required=TODAY)) == []

    def test_a_due_date_before_submission_is_reported(self) -> None:
        findings = checks.check_required_date_after_submitted(_submittal(date_required="2026-07-01"))
        assert len(findings) == 1
        assert findings[0].params == {"required": "2026-07-01", "submitted": TODAY}

    def test_without_a_submission_date_the_supplied_clock_is_used(self) -> None:
        submittal = _submittal(date_submitted=None, date_required="2026-07-01")
        findings = checks.check_required_date_after_submitted(submittal)
        assert len(findings) == 1
        assert findings[0].params["submitted"] == TODAY

    def test_a_missing_required_date_is_left_to_the_presence_rule(self) -> None:
        assert checks.check_required_date_after_submitted(_submittal(date_required=None)) == []


class TestReviewWindowSufficient:
    def test_a_customary_window_passes(self) -> None:
        assert checks.check_review_window_sufficient(_submittal()) == []

    def test_exactly_the_minimum_passes(self) -> None:
        submittal = _submittal(date_submitted="2026-07-26", date_required="2026-08-09")
        assert (
            checks.parse_date(submittal["date_required"]) - checks.parse_date(submittal["date_submitted"])
        ).days == checks.MIN_REVIEW_DAYS
        assert checks.check_review_window_sufficient(submittal) == []

    def test_a_two_day_turnaround_is_reported(self) -> None:
        findings = checks.check_review_window_sufficient(_submittal(date_required="2026-07-28"))
        assert len(findings) == 1
        assert findings[0].params == {"days": "2", "minimum": str(checks.MIN_REVIEW_DAYS)}

    def test_a_due_date_in_the_past_is_left_to_the_ordering_rule(self) -> None:
        """One problem, one finding.

        A due date before submission is already reported as an ordering error;
        also calling it a short window would report the same date pair twice.
        """
        assert checks.check_review_window_sufficient(_submittal(date_required="2026-07-01")) == []


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
# Filing
# ---------------------------------------------------------------------------


class TestSpecSectionPresent:
    def test_a_spec_section_passes(self) -> None:
        assert checks.check_spec_section_present(_submittal()) == []

    @pytest.mark.parametrize("value", [None, "", "  "])
    def test_a_blank_spec_section_is_reported(self, value: str | None) -> None:
        assert len(checks.check_spec_section_present(_submittal(spec_section=value))) == 1


class TestLinkedScopePresent:
    def test_a_linked_submittal_passes(self) -> None:
        assert checks.check_linked_scope_present(_submittal()) == []

    def test_no_links_are_reported(self) -> None:
        assert len(checks.check_linked_scope_present(_submittal(linked_boq_item_ids=[]))) == 1

    def test_a_list_of_blanks_counts_as_no_links(self) -> None:
        """A stored ``[""]`` is not a link, and would otherwise pass silently."""
        assert len(checks.check_linked_scope_present(_submittal(linked_boq_item_ids=["", "  "]))) == 1

    def test_a_malformed_value_counts_as_no_links(self) -> None:
        assert len(checks.check_linked_scope_present(_submittal(linked_boq_item_ids="oops"))) == 1


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------


class TestReachability:
    def test_all_seven_rules_are_registered_under_the_submittal_set(self) -> None:
        register_builtin_rules()
        registered = {r.rule_id for r in rule_registry.get_rules_for_sets(["submittal"])}
        assert {rule_cls.rule_id for rule_cls in SUBMITTAL_RULES}.issubset(registered)

    def test_the_submittal_set_is_one_a_caller_actually_passes(self) -> None:
        """The ai_takeoff guard: a set nobody names never runs."""
        from app.modules.submittals.service import SUBMITTAL_RULE_SET, SubmittalService

        assert SUBMITTAL_RULE_SET == "submittal"
        source = inspect.getsource(SubmittalService._validate_submittal)
        assert "SUBMITTAL_RULE_SET" in source
        assert "validation_engine.validate" in source

    def test_submission_consults_validation(self) -> None:
        """Filing must run the checks, not merely offer an endpoint."""
        from app.modules.submittals.service import SubmittalService

        source = inspect.getsource(SubmittalService.submit_submittal)
        assert "_collect_submission_findings" in source

    def test_submission_reports_rather_than_refuses(self) -> None:
        """A deliberate choice, pinned so a later change is a decision.

        Submission is already gated by the state machine. These rules report;
        promoting them to a refusal is a change in
        ``_collect_submission_findings`` and should be made knowingly.
        """
        from app.modules.submittals.service import SubmittalService

        source = inspect.getsource(SubmittalService._collect_submission_findings)
        assert "raise" not in source

    def test_the_findings_reach_the_structured_log(self) -> None:
        """A report nobody can see is the same as no report."""
        from app.modules.submittals.service import SubmittalService

        source = inspect.getsource(SubmittalService._collect_submission_findings)
        assert "validation_errors" in source
        assert "validation_warnings" in source

    def test_the_read_only_endpoint_exists_for_the_same_set(self) -> None:
        from app.modules.submittals.service import SubmittalService

        source = inspect.getsource(SubmittalService.validate_submittal)
        assert "_validate_submittal" in source


# ---------------------------------------------------------------------------
# Engine contract
# ---------------------------------------------------------------------------


class TestEngineContract:
    """What a caller reads: the report, not the check's return value."""

    async def _report(self, submittal: dict):
        register_builtin_rules()
        return await validation_engine.validate(
            data=submittal,
            rule_sets=["submittal"],
            target_type="submittal",
            target_id="11111111-1111-1111-1111-111111111111",
            project_id="22222222-2222-2222-2222-222222222222",
            metadata={"locale": "en"},
        )

    async def test_a_clean_submittal_has_no_errors(self) -> None:
        report = await self._report(_submittal())
        assert not report.has_errors
        assert report.errors == []

    async def test_a_single_isolated_error_is_reported_alone(self) -> None:
        report = await self._report(_submittal(reviewer_id=None))
        assert [r.rule_id for r in report.errors] == ["submittal.reviewer_assigned"]

    async def test_an_advisory_finding_never_becomes_an_error(self) -> None:
        report = await self._report(_submittal(spec_section=None))
        assert not report.has_errors
        assert "submittal.spec_section_present" in {r.rule_id for r in report.warnings}

    async def test_every_problem_is_listed_at_once(self) -> None:
        report = await self._report(_submittal(reviewer_id=None, date_required=None))
        assert {r.rule_id for r in report.errors} == {
            "submittal.reviewer_assigned",
            "submittal.required_date_present",
        }

    async def test_the_message_is_translated_not_a_key(self) -> None:
        report = await self._report(_submittal(reviewer_id=None))
        message = report.errors[0].message
        assert "submittal." not in message
        assert "reviewer" in message.lower()

    async def test_the_rule_set_resolves(self) -> None:
        register_builtin_rules()
        assert rule_registry.has_rules("submittal")

    async def test_severity_survives_the_round_trip(self) -> None:
        report = await self._report(_submittal(reviewer_id=None))
        assert report.errors[0].severity is Severity.ERROR
