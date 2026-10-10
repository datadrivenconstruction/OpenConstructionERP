# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The register rules of the ``submittal`` rule set.

Same three layers as ``test_submittals_validation_rules.py``: the pure checks
(a passing and a failing case each), what the engine reports in English and
in Turkish, and whether the rules are registered where the module starts.

No database. The clock arrives as data (``as_of``).
"""

from __future__ import annotations

import inspect
import re

import pytest

from app.core.validation.engine import Severity, rule_registry, validation_engine
from app.core.validation.rules import register_builtin_rules
from app.modules import submittals as submittals_module
from app.modules.submittals import validators as checks
from app.modules.submittals.messages import available_locales, is_key_present, translate
from app.modules.submittals.rules import (
    SUBMITTAL_REGISTER_RULES,
    SUBMITTAL_RULE_SET,
    register_submittal_register_rules,
)
from app.modules.submittals.service import SUBMITTAL_RULE_SET as SERVICE_RULE_SET
from app.modules.submittals.service import SubmittalService

TODAY = "2026-10-10"
REVIEWER = "33333333-3333-3333-3333-333333333333"
APPROVER = "44444444-4444-4444-4444-444444444444"

REGISTER_RULE_IDS = {
    "submittal.resubmission_linked",
    "submittal.outcome_matches_status",
    "submittal.required_on_site_after_submitted",
    "submittal.long_lead_has_lead_time",
    "submittal.approval_needed_by_not_passed",
    "submittal.material_has_manufacturer",
}


def _entry(revision: int, outcome: str = "revise_and_resubmit") -> dict:
    return {"revision": revision, "outcome": outcome, "code": "C", "date_returned": "2026-09-28"}


def _submittal(**overrides: object) -> dict:
    """A clean material submittal under review: every check passes unless a test breaks one."""
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "project_id": "22222222-2222-2222-2222-222222222222",
        "submittal_number": "SUB-012",
        "title": "Chiller product data",
        "status": "under_review",
        "submittal_type": "product_data",
        "spec_section": "23 64 00",
        "reviewer_id": REVIEWER,
        "approver_id": APPROVER,
        "date_submitted": "2026-10-01",
        "date_required": "2026-10-20",
        "current_revision": 1,
        "linked_boq_item_ids": ["55555555-5555-5555-5555-555555555555"],
        "manufacturer": "Soğutma Sanayi A.Ş.",
        "review_outcome": None,
        "review_period_days": 14,
        "review_history": [],
        "required_on_site_date": "2027-02-01",
        "long_lead": True,
        "lead_time_weeks": 12,
        "as_of": TODAY,
    }
    base.update(overrides)
    return base


# ── A resubmission is linked to the revision it replaces ──────────────────


class TestResubmissionLinked:
    def test_a_first_revision_has_nothing_to_link_to(self) -> None:
        assert checks.check_resubmission_linked(_submittal()) == []

    def test_a_resubmission_with_the_previous_review_on_record_passes(self) -> None:
        assert checks.check_resubmission_linked(_submittal(current_revision=2, review_history=[_entry(1)])) == []

    def test_a_resubmission_with_no_record_of_the_revision_before_is_flagged(self) -> None:
        findings = checks.check_resubmission_linked(_submittal(current_revision=2))
        assert len(findings) == 1
        assert findings[0].element_ref == "SUB-012"
        assert findings[0].params == {"revision": "2", "previous": "1"}

    def test_the_link_is_to_the_revision_immediately_before(self) -> None:
        """Revision 3 with only revision 1 on record skipped a cycle."""
        findings = checks.check_resubmission_linked(_submittal(current_revision=3, review_history=[_entry(1)]))
        assert findings[0].params["previous"] == "2"
        assert findings[0].details["reviewed_revisions"] == [1]

    def test_a_row_from_before_the_history_existed_does_not_crash(self) -> None:
        legacy = _submittal(current_revision=2)
        del legacy["review_history"]
        assert len(checks.check_resubmission_linked(legacy)) == 1


# ── The stamp agrees with the status ──────────────────────────────────────


class TestOutcomeMatchesStatus:
    @pytest.mark.parametrize(
        "status,outcome",
        [
            ("approved", "approved"),
            ("approved_as_noted", "approved_as_noted"),
            ("revise_and_resubmit", "revise_and_resubmit"),
            ("rejected", "rejected"),
            # Closed keeps the decision it was closed on.
            ("closed", "approved"),
            ("closed", "approved_as_noted"),
            ("closed", "rejected"),
            # Taken back to draft, the answer to this revision still stands.
            ("draft", "revise_and_resubmit"),
            ("draft", "rejected"),
            # No stamp at all: nothing to contradict, including on old rows.
            ("approved", None),
            ("under_review", None),
        ],
    )
    def test_a_consistent_pair_passes(self, status: str, outcome: str | None) -> None:
        assert checks.check_outcome_matches_status(_submittal(status=status, review_outcome=outcome)) == []

    @pytest.mark.parametrize(
        "status,outcome",
        [
            ("approved", "revise_and_resubmit"),
            ("approved_as_noted", "approved"),
            ("rejected", "approved"),
            ("revise_and_resubmit", "rejected"),
            # Still with the reviewer, yet already stamped.
            ("submitted", "approved"),
            ("under_review", "rejected"),
            # The workflow never closes a submittal that is out for revision.
            ("closed", "revise_and_resubmit"),
        ],
    )
    def test_a_contradiction_is_flagged(self, status: str, outcome: str) -> None:
        findings = checks.check_outcome_matches_status(_submittal(status=status, review_outcome=outcome))
        assert len(findings) == 1
        assert findings[0].params == {"outcome": outcome, "status": status}


# ── Required on site against the submission date ──────────────────────────


class TestRequiredOnSiteAfterSubmitted:
    def test_on_site_after_submission_passes(self) -> None:
        assert checks.check_required_on_site_after_submitted(_submittal()) == []

    def test_on_site_on_the_submission_day_passes(self) -> None:
        assert checks.check_required_on_site_after_submitted(_submittal(required_on_site_date="2026-10-01")) == []

    def test_on_site_before_submission_is_flagged(self) -> None:
        findings = checks.check_required_on_site_after_submitted(_submittal(required_on_site_date="2026-09-15"))
        assert findings[0].params == {"on_site": "2026-09-15", "submitted": "2026-10-01"}

    def test_a_draft_with_no_submission_date_is_not_judged(self) -> None:
        draft = _submittal(status="draft", date_submitted=None, required_on_site_date="2026-01-01")
        assert checks.check_required_on_site_after_submitted(draft) == []

    def test_no_on_site_date_is_not_a_finding(self) -> None:
        assert checks.check_required_on_site_after_submitted(_submittal(required_on_site_date=None)) == []


# ── A long-lead item says how long ────────────────────────────────────────


class TestLongLeadHasLeadTime:
    def test_a_long_lead_item_with_a_lead_time_passes(self) -> None:
        assert checks.check_long_lead_has_lead_time(_submittal()) == []

    def test_an_item_that_is_not_long_lead_needs_no_lead_time(self) -> None:
        assert checks.check_long_lead_has_lead_time(_submittal(long_lead=False, lead_time_weeks=None)) == []

    def test_a_long_lead_item_without_a_lead_time_is_flagged(self) -> None:
        findings = checks.check_long_lead_has_lead_time(_submittal(lead_time_weeks=None))
        assert len(findings) == 1
        assert findings[0].details == {"long_lead": True, "lead_time_weeks": None}

    def test_a_row_from_before_the_flag_existed_passes(self) -> None:
        legacy = _submittal()
        del legacy["long_lead"]
        del legacy["lead_time_weeks"]
        assert checks.check_long_lead_has_lead_time(legacy) == []


# ── Approval needed by ────────────────────────────────────────────────────


class TestApprovalNeededByNotPassed:
    def test_before_the_needed_by_date_passes(self) -> None:
        # 2027-02-01 less 12 weeks is 2026-11-09, a month away.
        assert checks.check_approval_needed_by_not_passed(_submittal()) == []

    def test_past_the_needed_by_date_while_under_review_is_flagged_with_the_days(self) -> None:
        # 2026-12-14 less 12 weeks is 2026-09-21, nineteen days before today.
        findings = checks.check_approval_needed_by_not_passed(_submittal(required_on_site_date="2026-12-14"))
        assert len(findings) == 1
        assert findings[0].params == {"days": "19", "needed_by": "2026-09-21"}
        assert findings[0].details["days_late"] == 19

    @pytest.mark.parametrize("status", ["approved", "approved_as_noted", "closed"])
    def test_an_approved_or_closed_item_is_not_late(self, status: str) -> None:
        late = _submittal(status=status, required_on_site_date="2026-12-14")
        assert checks.check_approval_needed_by_not_passed(late) == []

    def test_sent_back_for_revision_past_the_date_is_still_late(self) -> None:
        returned = _submittal(
            status="revise_and_resubmit", review_outcome="revise_and_resubmit", required_on_site_date="2026-12-14"
        )
        assert len(checks.check_approval_needed_by_not_passed(returned)) == 1

    def test_without_a_lead_time_there_is_no_date_to_pass(self) -> None:
        undated = _submittal(required_on_site_date="2026-12-14", lead_time_weeks=None)
        assert checks.check_approval_needed_by_not_passed(undated) == []


# ── A material names its manufacturer ─────────────────────────────────────


class TestMaterialHasManufacturer:
    def test_a_material_with_a_manufacturer_passes(self) -> None:
        assert checks.check_material_has_manufacturer(_submittal()) == []

    @pytest.mark.parametrize("submittal_type", sorted(checks.MATERIAL_TYPES))
    def test_a_material_without_a_manufacturer_is_flagged(self, submittal_type: str) -> None:
        findings = checks.check_material_has_manufacturer(_submittal(submittal_type=submittal_type, manufacturer="  "))
        assert len(findings) == 1

    @pytest.mark.parametrize("submittal_type", ["shop_drawing", "method_statement", "calculation"])
    def test_a_document_that_offers_no_product_needs_no_manufacturer(self, submittal_type: str) -> None:
        assert (
            checks.check_material_has_manufacturer(_submittal(submittal_type=submittal_type, manufacturer=None)) == []
        )


# ── Engine contract ───────────────────────────────────────────────────────


class TestEngineContract:
    """What a caller reads: the report, in the caller's language."""

    async def _report(self, submittal: dict, locale: str = "en"):
        register_builtin_rules()
        register_submittal_register_rules()
        return await validation_engine.validate(
            data=submittal,
            rule_sets=[SUBMITTAL_RULE_SET],
            target_type="submittal",
            target_id="11111111-1111-1111-1111-111111111111",
            project_id="22222222-2222-2222-2222-222222222222",
            metadata={"locale": locale},
        )

    async def test_a_clean_submittal_passes_both_groups_of_rules(self) -> None:
        report = await self._report(_submittal())
        assert report.errors == []
        assert report.warnings == []
        assert {r.rule_id for r in report.results} >= REGISTER_RULE_IDS

    async def test_a_submittal_from_before_the_register_columns_raises_no_register_finding(self) -> None:
        """An existing installation's rows: every new field absent."""
        legacy = {
            key: value
            for key, value in _submittal().items()
            if key
            not in (
                "manufacturer",
                "review_outcome",
                "review_period_days",
                "review_history",
                "required_on_site_date",
                "long_lead",
                "lead_time_weeks",
            )
        }
        legacy["submittal_type"] = "shop_drawing"
        report = await self._report(legacy)
        assert REGISTER_RULE_IDS.isdisjoint({r.rule_id for r in [*report.errors, *report.warnings]})

    async def test_the_severities_are_the_ones_the_register_needs(self) -> None:
        broken = _submittal(
            status="approved",
            review_outcome="rejected",
            current_revision=2,
            manufacturer=None,
            lead_time_weeks=None,
        )
        report = await self._report(broken)
        assert {r.rule_id for r in report.errors} == {
            "submittal.outcome_matches_status",
            "submittal.long_lead_has_lead_time",
        }
        assert {r.rule_id for r in report.warnings} >= {
            "submittal.resubmission_linked",
            "submittal.material_has_manufacturer",
        }
        assert all(r.severity is Severity.ERROR for r in report.errors)

    async def test_the_needed_by_warning_carries_the_days(self) -> None:
        report = await self._report(_submittal(required_on_site_date="2026-12-14"))
        (finding,) = [r for r in report.warnings if r.rule_id == "submittal.approval_needed_by_not_passed"]
        assert "19 days" in finding.message
        assert "2026-09-21" in finding.message
        assert finding.element_ref == "SUB-012"

    async def test_the_messages_come_out_in_turkish(self) -> None:
        report = await self._report(_submittal(required_on_site_date="2026-12-14", manufacturer=None), locale="tr")
        messages = {r.rule_id: r for r in report.warnings}
        late = messages["submittal.approval_needed_by_not_passed"]
        assert "19 gün" in late.message
        assert "onaylanmadı" in late.message
        assert "üretici" in messages["submittal.material_has_manufacturer"].message
        assert "markayı" in messages["submittal.material_has_manufacturer"].suggestion

    async def test_a_status_inside_a_message_is_a_word_not_a_code(self) -> None:
        english = await self._report(_submittal(status="approved", review_outcome="revise_and_resubmit"))
        (finding,) = [r for r in english.errors if r.rule_id == "submittal.outcome_matches_status"]
        assert "Revise and resubmit" in finding.message
        assert "revise_and_resubmit" not in finding.message
        turkish = await self._report(_submittal(status="approved", review_outcome="revise_and_resubmit"), locale="tr")
        (finding_tr,) = [r for r in turkish.errors if r.rule_id == "submittal.outcome_matches_status"]
        assert "Revize edip yeniden sunun" in finding_tr.message
        assert "Onaylandı" in finding_tr.message


# ── Messages ──────────────────────────────────────────────────────────────


class TestMessages:
    def test_english_and_turkish_are_both_loaded(self) -> None:
        assert {"en", "tr"} <= set(available_locales())

    @pytest.mark.parametrize("rule_class", SUBMITTAL_REGISTER_RULES, ids=lambda c: c.rule_id)
    @pytest.mark.parametrize("suffix", ["fail", "suggestion"])
    def test_every_rule_has_its_text_in_both_languages_with_the_same_placeholders(
        self, rule_class: type, suffix: str
    ) -> None:
        key = f"{rule_class.rule_id}.{suffix}"
        assert is_key_present(key, "en"), key
        assert is_key_present(key, "tr"), key
        english, turkish = translate(key, locale="en"), translate(key, locale="tr")
        assert english != turkish
        assert sorted(re.findall(r"\{[a-z_]+\}", english)) == sorted(re.findall(r"\{[a-z_]+\}", turkish))

    def test_another_language_reads_the_english(self) -> None:
        key = "submittal.long_lead_has_lead_time.fail"
        assert translate(key, locale="de") == translate(key, locale="en")


# ── Reachability ──────────────────────────────────────────────────────────


class TestReachability:
    def test_the_rules_join_the_set_the_service_asks_for(self) -> None:
        assert SUBMITTAL_RULE_SET == SERVICE_RULE_SET
        register_submittal_register_rules()
        registered = {rule.rule_id for rule in rule_registry.get_rules_for_sets([SUBMITTAL_RULE_SET])}
        assert registered >= REGISTER_RULE_IDS

    def test_the_rule_ids_are_the_six_the_register_needs(self) -> None:
        assert {rule.rule_id for rule in SUBMITTAL_REGISTER_RULES} == REGISTER_RULE_IDS

    def test_every_rule_names_a_check_that_exists(self) -> None:
        for rule_class in SUBMITTAL_REGISTER_RULES:
            assert callable(getattr(checks, rule_class.check_name)), rule_class.rule_id

    def test_the_module_registers_them_when_it_starts(self) -> None:
        """Registered in code but never at startup is a rule that never runs."""
        assert "register_submittal_register_rules()" in inspect.getsource(submittals_module.on_startup)

    def test_the_payload_carries_every_field_the_checks_read(self) -> None:
        """A check that reads a key the service never sends passes forever."""
        payload_source = inspect.getsource(SubmittalService._validation_payload)
        for field in (
            "submittal_type",
            "manufacturer",
            "review_outcome",
            "review_history",
            "required_on_site_date",
            "long_lead",
            "lead_time_weeks",
            "current_revision",
        ):
            assert f'"{field}"' in payload_source, field
