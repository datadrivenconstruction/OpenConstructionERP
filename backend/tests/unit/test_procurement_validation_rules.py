# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests - the procurement purchase-order rule set.

Three layers, because each can fail without the others noticing:

1. the pure checks in ``app.modules.procurement.validators`` (Decimal arithmetic,
   no database);
2. the rule classes that wrap them, including that a clean purchase order still
   produces an explicit passing row and that every message key resolves in every
   shipped locale;
3. reachability -- that the ``procurement`` rule set is one a caller actually
   passes. A rule set nobody passes never runs, which is how three ``ai_takeoff``
   rules shipped dead; the guard below fails if this set drifts into the same
   shape.

Pure-Python, no database.
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any

import pytest

from app.core.validation.engine import RuleCategory, Severity, ValidationContext, rule_registry
from app.core.validation.messages import available_locales, is_key_present
from app.core.validation.rules import (
    ProcurementPOCurrencySet,
    ProcurementPODeliveryAfterIssue,
    ProcurementPOHasLines,
    ProcurementPOLineAmount,
    ProcurementPOLineCostCoded,
    ProcurementPONoNegativeLine,
    ProcurementPORetentionWithinBounds,
    ProcurementPOSubtotalMatchesLines,
    ProcurementPOTotalMatchesSubtotal,
    ProcurementPOVendorAssigned,
    register_builtin_rules,
)
from app.modules.procurement import validators as po_checks
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
from app.modules.procurement.service import ProcurementService

PROCUREMENT_RULES = [
    ProcurementPOHasLines,
    ProcurementPOLineAmount,
    ProcurementPOSubtotalMatchesLines,
    ProcurementPOTotalMatchesSubtotal,
    ProcurementPONoNegativeLine,
    ProcurementPOCurrencySet,
    ProcurementPOVendorAssigned,
    ProcurementPORetentionWithinBounds,
    ProcurementPODeliveryAfterIssue,
    ProcurementPOLineCostCoded,
]


def _line(**overrides: Any) -> dict[str, Any]:
    """A clean purchase-order line; overrides replace individual fields."""
    line = {
        "description": "C30/37 ready-mix concrete",
        "quantity": "10",
        "unit": "m3",
        "unit_rate": "120.00",
        "amount": "1200.00",
        "wbs_id": "3.2.1",
        "cost_category": "materials",
        "cost_line_id": None,
        "sort_order": 0,
    }
    line.update(overrides)
    return line


def _po(**overrides: Any) -> dict[str, Any]:
    """A clean purchase order that passes every rule; overrides break one thing."""
    po = {
        "id": "11111111-1111-1111-1111-111111111111",
        "project_id": "22222222-2222-2222-2222-222222222222",
        "po_number": "PO-0042",
        "status": "draft",
        "currency_code": "EUR",
        "amount_subtotal": "1200.00",
        "tax_amount": "228.00",
        "amount_total": "1428.00",
        "retention_percent": "5.00",
        "issue_date": "2026-03-01",
        "delivery_date": "2026-04-15",
        "vendor_contact_id": "33333333-3333-3333-3333-333333333333",
        "items": [_line()],
    }
    po.update(overrides)
    return po


def _ctx(po: dict[str, Any], **metadata: Any) -> ValidationContext:
    return ValidationContext(data=po, metadata=metadata)


# ---------------------------------------------------------------------------
# Pure checks
# ---------------------------------------------------------------------------


class TestParseMoney:
    def test_parses_decimal_strings_and_rejects_junk(self) -> None:
        assert po_checks.parse_money("12.50") is not None
        assert po_checks.parse_money(" 12.50 ") is not None
        assert po_checks.parse_money("") is None
        assert po_checks.parse_money("n/a") is None
        assert po_checks.parse_money(None) is None

    def test_unparseable_amount_is_reported_not_raised(self) -> None:
        """A rule that explodes on bad data hides the row the user needs."""
        findings = po_checks.check_line_amount(_po(items=[_line(unit_rate="tbc")]))
        assert len(findings) == 1
        assert findings[0].details["reason"] == "unparseable_amount"


class TestHasLines:
    def test_clean_po_passes(self) -> None:
        assert po_checks.check_has_lines(_po()) == []

    def test_empty_po_is_flagged(self) -> None:
        findings = po_checks.check_has_lines(_po(items=[]))
        assert [f.element_ref for f in findings] == ["PO-0042"]

    def test_malformed_items_value_counts_as_empty(self) -> None:
        assert len(po_checks.check_has_lines(_po(items="not-a-list"))) == 1


class TestLineAmount:
    def test_clean_line_passes(self) -> None:
        assert po_checks.check_line_amount(_po()) == []

    def test_amount_that_disagrees_with_quantity_times_rate_is_flagged(self) -> None:
        findings = po_checks.check_line_amount(_po(items=[_line(amount="1500.00")]))
        assert len(findings) == 1
        assert findings[0].params["expected"] == "1,200.00 EUR"
        assert findings[0].params["actual"] == "1,500.00 EUR"

    def test_one_cent_of_rounding_is_tolerated(self) -> None:
        # 3 x 33.333 = 99.999, stored quantised to 100.00.
        po = _po(items=[_line(quantity="3", unit_rate="33.333", amount="100.00")])
        assert po_checks.check_line_amount(po) == []

    def test_two_cents_is_not_tolerated(self) -> None:
        po = _po(items=[_line(quantity="3", unit_rate="33.333", amount="100.02")])
        assert len(po_checks.check_line_amount(po)) == 1

    def test_each_bad_line_is_reported_separately(self) -> None:
        po = _po(items=[_line(amount="1.00"), _line(), _line(amount="2.00")])
        assert len(po_checks.check_line_amount(po)) == 2


class TestSubtotalMatchesLines:
    def test_clean_po_passes(self) -> None:
        assert po_checks.check_subtotal_matches_lines(_po()) == []

    def test_subtotal_that_disagrees_with_the_lines_is_flagged(self) -> None:
        findings = po_checks.check_subtotal_matches_lines(_po(amount_subtotal="999.00"))
        assert len(findings) == 1
        assert findings[0].params["expected"] == "1,200.00 EUR"

    def test_empty_po_defers_to_the_has_lines_check(self) -> None:
        """One problem, one finding: an empty PO is not also a subtotal mismatch."""
        assert po_checks.check_subtotal_matches_lines(_po(items=[], amount_subtotal="500")) == []

    def test_multiple_lines_are_summed(self) -> None:
        po = _po(
            items=[_line(), _line(amount="300.00", quantity="2.5", unit_rate="120.00")],
            amount_subtotal="1500.00",
        )
        assert po_checks.check_subtotal_matches_lines(po) == []


class TestTotalMatchesSubtotalPlusTax:
    def test_clean_po_passes(self) -> None:
        assert po_checks.check_total_matches_subtotal_plus_tax(_po()) == []

    def test_total_that_ignores_tax_is_flagged(self) -> None:
        findings = po_checks.check_total_matches_subtotal_plus_tax(_po(amount_total="1200.00"))
        assert len(findings) == 1
        assert findings[0].params["expected"] == "1,428.00 EUR"

    def test_zero_tax_is_honoured_not_coalesced(self) -> None:
        po = _po(tax_amount="0", amount_total="1200.00")
        assert po_checks.check_total_matches_subtotal_plus_tax(po) == []


class TestNoNegativeLine:
    def test_clean_line_passes(self) -> None:
        assert po_checks.check_no_negative_line(_po()) == []

    def test_zero_quantity_is_flagged(self) -> None:
        findings = po_checks.check_no_negative_line(_po(items=[_line(quantity="0")]))
        assert findings[0].details["reasons"] == ["quantity_not_positive"]

    def test_negative_quantity_is_flagged(self) -> None:
        findings = po_checks.check_no_negative_line(_po(items=[_line(quantity="-10")]))
        assert findings[0].details["reasons"] == ["quantity_not_positive"]

    def test_negative_rate_is_flagged(self) -> None:
        findings = po_checks.check_no_negative_line(_po(items=[_line(unit_rate="-120")]))
        assert findings[0].details["reasons"] == ["rate_negative"]

    def test_zero_rate_is_allowed(self) -> None:
        """A free-issue line is legitimate; a negative one is not."""
        po = _po(items=[_line(unit_rate="0", amount="0")])
        assert po_checks.check_no_negative_line(po) == []


class TestCurrencySet:
    def test_currency_present_passes(self) -> None:
        assert po_checks.check_currency_set(_po()) == []

    def test_empty_currency_is_flagged(self) -> None:
        assert len(po_checks.check_currency_set(_po(currency_code=""))) == 1

    def test_whitespace_currency_is_flagged(self) -> None:
        assert len(po_checks.check_currency_set(_po(currency_code="   "))) == 1


class TestVendorAssigned:
    def test_vendor_present_passes(self) -> None:
        assert po_checks.check_vendor_assigned(_po()) == []

    def test_missing_vendor_is_flagged(self) -> None:
        assert len(po_checks.check_vendor_assigned(_po(vendor_contact_id=None))) == 1


class TestRetentionWithinBounds:
    def test_normal_retention_passes(self) -> None:
        assert po_checks.check_retention_within_bounds(_po()) == []

    def test_zero_retention_passes(self) -> None:
        assert po_checks.check_retention_within_bounds(_po(retention_percent="0.00")) == []

    def test_negative_retention_is_flagged(self) -> None:
        assert len(po_checks.check_retention_within_bounds(_po(retention_percent="-5"))) == 1

    def test_an_amount_typed_as_a_rate_is_flagged(self) -> None:
        findings = po_checks.check_retention_within_bounds(_po(retention_percent="1200"))
        assert findings[0].params["percent"] == "1200.00"

    def test_boundary_is_inclusive(self) -> None:
        assert po_checks.check_retention_within_bounds(_po(retention_percent="50")) == []
        assert len(po_checks.check_retention_within_bounds(_po(retention_percent="50.01"))) == 1


class TestDeliveryNotBeforeIssue:
    def test_delivery_after_issue_passes(self) -> None:
        assert po_checks.check_delivery_not_before_issue(_po()) == []

    def test_same_day_delivery_passes(self) -> None:
        po = _po(issue_date="2026-03-01", delivery_date="2026-03-01")
        assert po_checks.check_delivery_not_before_issue(po) == []

    def test_delivery_before_issue_is_flagged(self) -> None:
        po = _po(issue_date="2026-03-01", delivery_date="2026-02-01")
        findings = po_checks.check_delivery_not_before_issue(po)
        assert findings[0].params == {"issue": "2026-03-01", "delivery": "2026-02-01"}

    def test_a_missing_or_unparseable_date_is_not_a_finding(self) -> None:
        """These columns are free-form strings; this check is about order, not format."""
        assert po_checks.check_delivery_not_before_issue(_po(issue_date=None)) == []
        assert po_checks.check_delivery_not_before_issue(_po(delivery_date="")) == []
        assert po_checks.check_delivery_not_before_issue(_po(issue_date="next spring")) == []

    def test_a_timestamp_prefix_still_parses(self) -> None:
        po = _po(issue_date="2026-03-01T08:00:00Z", delivery_date="2026-02-01T08:00:00Z")
        assert len(po_checks.check_delivery_not_before_issue(po)) == 1


class TestLineCostCoded:
    def test_wbs_alone_is_enough(self) -> None:
        po = _po(items=[_line(cost_category=None, cost_line_id=None)])
        assert po_checks.check_line_cost_coded(po) == []

    def test_cost_category_alone_is_enough(self) -> None:
        po = _po(items=[_line(wbs_id=None, cost_line_id=None)])
        assert po_checks.check_line_cost_coded(po) == []

    def test_cost_line_link_alone_is_enough(self) -> None:
        po = _po(items=[_line(wbs_id=None, cost_category=None, cost_line_id="abc")])
        assert po_checks.check_line_cost_coded(po) == []

    def test_a_wholly_uncoded_line_is_flagged(self) -> None:
        po = _po(items=[_line(wbs_id=None, cost_category=None, cost_line_id=None)])
        assert len(po_checks.check_line_cost_coded(po)) == 1


class TestLineLabel:
    def test_label_carries_the_row_number_and_description(self) -> None:
        assert po_checks.line_label(0, _line()) == "1 (C30/37 ready-mix concrete)"

    def test_label_falls_back_to_the_row_number(self) -> None:
        assert po_checks.line_label(4, _line(description="")) == "5"

    def test_long_description_is_trimmed(self) -> None:
        label = po_checks.line_label(0, _line(description="x" * 200))
        assert len(label) <= 48
        assert label.endswith("...)")


# ---------------------------------------------------------------------------
# Rule classes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRuleBodies:
    async def test_clean_po_yields_one_passing_row_per_rule(self) -> None:
        """Silence would be indistinguishable from "the rule did not run"."""
        for rule_cls in PROCUREMENT_RULES:
            results = await rule_cls().validate(_ctx(_po()))
            assert len(results) == 1, rule_cls.__name__
            assert results[0].passed is True, rule_cls.__name__

    async def test_broken_po_yields_a_failing_row_with_an_anchor(self) -> None:
        results = await ProcurementPOSubtotalMatchesLines().validate(_ctx(_po(amount_subtotal="1")))
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].element_ref == "PO-0042"
        assert results[0].suggestion

    async def test_message_is_rendered_not_left_as_a_key(self) -> None:
        results = await ProcurementPOLineAmount().validate(_ctx(_po(items=[_line(amount="9")])))
        message = results[0].message
        assert "procurement.po_line_amount" not in message
        assert "{" not in message
        assert "1,200.00 EUR" in message

    async def test_locale_reaches_the_message(self) -> None:
        results = await ProcurementPOVendorAssigned().validate(_ctx(_po(vendor_contact_id=None), locale="de"))
        english = await ProcurementPOVendorAssigned().validate(_ctx(_po(vendor_contact_id=None)))
        assert results[0].message != english[0].message

    async def test_non_dict_payload_yields_nothing(self) -> None:
        for rule_cls in PROCUREMENT_RULES:
            assert await rule_cls().validate(ValidationContext(data=[], metadata={})) == []

    async def test_every_line_gets_its_own_row(self) -> None:
        po = _po(
            items=[_line(amount="1"), _line(), _line(amount="2")],
            amount_subtotal="1202.00",
        )
        results = await ProcurementPOLineAmount().validate(_ctx(po))
        assert [r.passed for r in results] == [False, False]
        # Row numbers are 1-based and keep their position, so the clean middle
        # line is visibly skipped rather than renumbering the ones after it.
        assert [r.element_ref for r in results] == [
            "1 (C30/37 ready-mix concrete)",
            "3 (C30/37 ready-mix concrete)",
        ]


class TestSeverities:
    def test_money_rules_block_and_advisory_rules_do_not(self) -> None:
        """Severity is the whole gate contract: ERROR refuses approval, WARNING does not."""
        blocking = {
            ProcurementPOHasLines,
            ProcurementPOLineAmount,
            ProcurementPOSubtotalMatchesLines,
            ProcurementPOTotalMatchesSubtotal,
            ProcurementPONoNegativeLine,
            ProcurementPOCurrencySet,
            ProcurementPOVendorAssigned,
            ProcurementPORetentionWithinBounds,
        }
        advisory = {ProcurementPODeliveryAfterIssue, ProcurementPOLineCostCoded}
        for rule_cls in blocking:
            assert rule_cls.severity is Severity.ERROR, rule_cls.__name__
        for rule_cls in advisory:
            assert rule_cls.severity is Severity.WARNING, rule_cls.__name__

    def test_every_rule_declares_a_real_category(self) -> None:
        for rule_cls in PROCUREMENT_RULES:
            assert isinstance(rule_cls.category, RuleCategory)
            assert rule_cls.category is not RuleCategory.DIAGNOSTIC


class TestMessageCoverage:
    def test_every_rule_has_fail_and_suggestion_in_every_shipped_locale(self) -> None:
        locales = available_locales()
        assert "en" in locales
        missing: list[str] = []
        for rule_cls in PROCUREMENT_RULES:
            for locale in locales:
                for suffix in ("fail", "suggestion"):
                    key = f"{rule_cls.rule_id}.{suffix}"
                    if not is_key_present(key, locale):
                        missing.append(f"{locale}:{key}")
        assert missing == []

    def test_every_check_name_resolves_to_a_function(self) -> None:
        """A typo in ``check_name`` would surface only as a runtime engine error."""
        for rule_cls in PROCUREMENT_RULES:
            check = getattr(po_checks, rule_cls.check_name, None)
            assert check is not None, rule_cls.__name__
            assert inspect.isfunction(check), rule_cls.__name__


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------


class TestReachability:
    def test_all_ten_rules_are_registered_under_the_procurement_set(self) -> None:
        register_builtin_rules()
        registered = {r.rule_id for r in rule_registry.get_rules_for_sets(["procurement"])}
        assert {rule_cls.rule_id for rule_cls in PROCUREMENT_RULES}.issubset(registered)

    def test_the_procurement_set_is_one_a_caller_actually_passes(self) -> None:
        """The ai_takeoff guard, applied here.

        Three ai_takeoff rules shipped with full i18n and never ran, because no
        caller passed their rule set. This asserts the service still names this
        set; if the call site is deleted or renamed, the rules go dead and this
        goes red.
        """
        from app.modules.procurement.service import PROCUREMENT_RULE_SET, ProcurementService

        assert PROCUREMENT_RULE_SET == "procurement"
        source = inspect.getsource(ProcurementService._validate_po)
        assert "PROCUREMENT_RULE_SET" in source
        assert "validation_engine.validate" in source

    def test_approval_runs_the_gate(self) -> None:
        """Approval must consult validation, not merely offer a validate endpoint."""
        from app.modules.procurement.service import ProcurementService

        source = inspect.getsource(ProcurementService.approve_po)
        assert "_validate_po_or_raise" in source

    def test_patch_into_approved_runs_the_gate_too(self) -> None:
        """``approve_po`` is not the only door into ``approved``.

        ``_PO_STATUS_TRANSITIONS`` allows ``draft -> approved``, so a plain
        PATCH reaches the committed state. If only the approve endpoint were
        gated, the rules would be enforced on one of two paths to the same
        state, which is a gate in name only.
        """
        from app.modules.procurement.service import _PO_STATUS_TRANSITIONS, ProcurementService

        # The premise: PATCH really can reach ``approved``. If the FSM is ever
        # tightened so it cannot, this test should be revisited, not deleted.
        assert "approved" in _PO_STATUS_TRANSITIONS["draft"]

        source = inspect.getsource(ProcurementService.update_po)
        assert "_validate_po_or_raise" in source


# ---------------------------------------------------------------------------
# Engine contract
# ---------------------------------------------------------------------------


class TestEngineContract:
    """What the gate actually reads: ``report.has_errors`` through the engine.

    The rule bodies above are called directly, which proves what they return but
    not what the engine makes of it. Every rule here carries a severity even on
    success, so a passing row is an ``ERROR``-severity row with ``passed=True``.
    If ``errors`` ever filtered on severity alone, every approval would 422 on a
    clean purchase order and the detail would list "OK" messages. No database.
    """

    async def _report(self, po: dict[str, Any]) -> Any:
        from app.core.validation.engine import validation_engine

        register_builtin_rules()
        return await validation_engine.validate(
            data=po,
            rule_sets=["procurement"],
            target_type="purchase_order",
            target_id=po["id"],
            project_id=po["project_id"],
            metadata={"locale": "en", "operation": "approve"},
        )

    async def test_clean_po_has_no_errors(self) -> None:
        report = await self._report(_po())
        assert report.errors == []
        assert report.has_errors is False
        # All ten ran: silence here would pass the gate for the wrong reason.
        assert len(report.results) >= len(PROCUREMENT_RULES)

    async def test_arithmetic_mismatch_reaches_errors(self) -> None:
        """One wrong subtotal fails two rules, and the report carries both.

        A broken ``amount_subtotal`` disagrees with the line sum *and* with
        ``amount_total`` (which was computed from the correct subtotal), so both
        rules are genuinely violated. Asserting the exact pair is what pins the
        promise ``_validate_po_or_raise`` makes: the 422 lists every failing
        rule, so the buyer fixes the purchase order once rather than
        rediscovering the next problem on the next attempt.
        """
        report = await self._report(_po(amount_subtotal="1"))
        assert report.has_errors is True
        assert {r.rule_id for r in report.errors} == {
            "procurement.po_subtotal_matches_lines",
            "procurement.po_total_matches_subtotal",
        }

    async def test_a_single_isolated_error_is_reported_alone(self) -> None:
        """No blanket failure: an unrelated clean rule stays out of ``errors``."""
        report = await self._report(_po(vendor_contact_id=None))
        assert {r.rule_id for r in report.errors} == {"procurement.po_vendor_assigned"}

    async def test_advisory_finding_never_lands_in_errors(self) -> None:
        """The WARNING tier must not block approval.

        An uncoded line is a real finding and shows up in the report, but plenty
        of legitimate purchase orders are raised before the coding is decided,
        so it must not reach ``errors`` and refuse the approval.
        """
        report = await self._report(_po(items=[_line(wbs_id=None, cost_category=None, cost_line_id=None)]))
        assert report.has_errors is False
        assert {r.rule_id for r in report.warnings} == {"procurement.po_line_cost_coded"}

    async def test_the_rule_set_resolves(self) -> None:
        """An unimplemented rule set would read as a clean pass, not a failure."""
        report = await self._report(_po())
        assert report.unsupported_rule_sets == []
        assert report.supported_rule_sets == ["procurement"]


# ---------------------------------------------------------------------------
# 4. The payload builder: does the cost link actually reach the rule?
# ---------------------------------------------------------------------------


class TestTheCostLinkReachesTheRule:
    """Every test above hands the rule a dict written by hand in this file.

    ``check_line_cost_coded`` counts ``cost_line_id`` as one of three codings,
    but the dict it reads is built by ``ProcurementService._validation_payload``
    from an explicit field list, and no test in this file can see that list. If
    the field were dropped there, ``test_cost_line_link_alone_is_enough`` above
    would keep passing while a line correctly attributed to a cost line carried
    a permanent uncoded warning.

    That failure is worse than the noise the rule was written to remove. A
    warning nobody can clear is a warning the reader learns to skip, and the
    rule then stops working for the lines that really are uncoded.

    The control comes first. Asserting that a linked line is clean proves
    nothing on its own, because a payload carrying no lines at all is also
    clean.
    """

    @staticmethod
    def _payload(**item_fields: Any) -> dict[str, Any]:
        """The dict the service really builds, for a PO with one line.

        No database. The builder only reads attributes off the instances, and a
        repository constructor only stores the session it is handed, so an
        unsaved order and no session are enough.
        """
        item = PurchaseOrderItem(
            description="C30/37 ready-mix concrete",
            quantity="10",
            unit="m3",
            unit_rate="120.00",
            amount="1200.00",
            sort_order=0,
            **item_fields,
        )
        po = PurchaseOrder(
            project_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            po_number="PO-0042",
            status="draft",
            currency_code="EUR",
        )
        po.items = [item]
        return ProcurementService(None)._validation_payload(po)  # type: ignore[arg-type]

    def test_a_line_with_no_coding_at_all_is_flagged_through_the_real_payload(self) -> None:
        """The control: the rule does reach a line built this way."""
        payload = self._payload(wbs_id=None, cost_category=None, cost_line_id=None)

        assert len(po_checks.check_line_cost_coded(payload)) == 1

    def test_a_line_coded_only_by_its_cost_link_is_clean(self) -> None:
        """The one that fails if the builder stops copying the column out."""
        payload = self._payload(
            wbs_id=None,
            cost_category=None,
            cost_line_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
        )

        assert payload["items"][0]["cost_line_id"] == "44444444-4444-4444-4444-444444444444"
        assert po_checks.check_line_cost_coded(payload) == []
