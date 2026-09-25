# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests - supplier invoice against its purchase order (simple three-way match).

Same three layers as the purchase-order rule tests: the pure checks, the rule
classes with their messages in every shipped locale, and reachability (the
``invoice_po_match`` set is one a caller actually passes). Both rules are
warnings, and the engine must keep them out of ``errors``.

Pure-Python, no database.
"""

from __future__ import annotations

import inspect
from decimal import Decimal
from typing import Any

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.messages import available_locales, is_key_present
from app.core.validation.rules import (
    ProcurementInvoiceQuantityReceived,
    ProcurementInvoiceValueReceived,
    ProcurementInvoiceWithinOrder,
    register_builtin_rules,
)
from app.modules.procurement import validators as po_checks

RULES = [ProcurementInvoiceWithinOrder, ProcurementInvoiceQuantityReceived, ProcurementInvoiceValueReceived]


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "po_number": "PO-0007",
        "currency_code": "EUR",
        "po_net": "50000.00",
        "invoiced_before_net": "0",
        "invoice_net": "40000.00",
        "invoice_ref": "R-2026-118",
        "has_receipts": True,
        "received_net": "40000.00",
        "lines": [
            {
                "label": "1 (Reinforcement B500B)",
                "unit": "kg",
                "ordered": "20000",
                "received": "16000",
                "invoiced_before": "0",
                "invoiced": "16000",
            }
        ],
    }
    payload.update(overrides)
    return payload


class TestInvoiceWithinOrder:
    def test_within_the_open_amount_is_clean(self) -> None:
        assert po_checks.check_invoice_within_order(_payload()) == []

    def test_exactly_the_open_amount_is_clean(self) -> None:
        assert po_checks.check_invoice_within_order(_payload(invoice_net="50000.00")) == []

    def test_above_what_is_still_open_after_earlier_invoices_warns(self) -> None:
        findings = po_checks.check_invoice_within_order(_payload(invoiced_before_net="40000", invoice_net="12000"))
        assert len(findings) == 1
        assert findings[0].element_ref == "R-2026-118"
        assert Decimal(findings[0].details["remaining_net"]) == Decimal("10000")
        assert "EUR" in findings[0].params["excess"] and "2" in findings[0].params["excess"]

    def test_an_order_already_fully_invoiced_reports_zero_open_not_a_negative(self) -> None:
        findings = po_checks.check_invoice_within_order(_payload(invoiced_before_net="60000", invoice_net="100"))
        assert findings and "-" not in findings[0].params["remaining"]


class TestInvoiceQuantityReceived:
    def test_invoiced_up_to_the_received_quantity_is_clean(self) -> None:
        assert po_checks.check_invoice_quantity_received(_payload()) == []

    def test_invoiced_beyond_received_warns_with_both_quantities(self) -> None:
        line = dict(_payload()["lines"][0], invoiced_before="16000", invoiced="4000")
        findings = po_checks.check_invoice_quantity_received(_payload(lines=[line]))
        assert len(findings) == 1
        assert findings[0].params == {"line": "1 (Reinforcement B500B)", "invoiced": "20000 kg", "received": "16000 kg"}

    def test_no_goods_receipt_means_nothing_to_match(self) -> None:
        line = dict(_payload()["lines"][0], received="0", invoiced="20000")
        assert po_checks.check_invoice_quantity_received(_payload(has_receipts=False, lines=[line])) == []

    def test_a_line_this_invoice_does_not_bill_is_skipped(self) -> None:
        line = dict(_payload()["lines"][0], invoiced_before="30000", invoiced="0")
        assert po_checks.check_invoice_quantity_received(_payload(lines=[line])) == []


class TestInvoiceValueReceived:
    """For an invoice entered as one amount, with no quantity per order line."""

    @staticmethod
    def _lump(**overrides: Any) -> dict[str, Any]:
        line = dict(_payload()["lines"][0], invoiced="0")
        return _payload(lines=[line], **overrides)

    def test_up_to_the_value_received_is_clean(self) -> None:
        assert po_checks.check_invoice_value_received(self._lump()) == []

    def test_beyond_the_value_received_warns(self) -> None:
        findings = po_checks.check_invoice_value_received(self._lump(invoiced_before_net="30000", invoice_net="12000"))
        assert len(findings) == 1
        assert Decimal(findings[0].details["invoiced_total_net"]) == Decimal("42000")

    def test_silent_when_the_invoice_names_quantities(self) -> None:
        assert po_checks.check_invoice_value_received(_payload(invoice_net="90000")) == []

    def test_silent_before_anything_is_received(self) -> None:
        assert po_checks.check_invoice_value_received(self._lump(has_receipts=False, invoice_net="90000")) == []


class TestRules:
    def test_both_are_warnings_never_blocking(self) -> None:
        for rule_cls in RULES:
            assert rule_cls.severity is Severity.WARNING

    def test_every_message_key_is_in_every_shipped_locale(self) -> None:
        missing = [
            f"{locale}:{rule_cls.rule_id}.{suffix}"
            for rule_cls in RULES
            for locale in available_locales()
            for suffix in ("fail", "suggestion")
            if not is_key_present(f"{rule_cls.rule_id}.{suffix}", locale)
        ]
        assert missing == []

    def test_every_check_name_resolves(self) -> None:
        for rule_cls in RULES:
            assert inspect.isfunction(getattr(po_checks, rule_cls.check_name, None)), rule_cls.__name__

    async def test_a_failing_rule_renders_its_message(self) -> None:
        results = await ProcurementInvoiceWithinOrder().validate(
            ValidationContext(data=_payload(invoice_net="60000"), metadata={"locale": "en"})
        )
        assert len(results) == 1 and results[0].passed is False
        assert "PO-0007" in results[0].message


class TestReachability:
    def test_registered_under_the_invoice_po_match_set(self) -> None:
        register_builtin_rules()
        registered = {r.rule_id for r in rule_registry.get_rules_for_sets(["invoice_po_match"])}
        assert {rule_cls.rule_id for rule_cls in RULES} == registered

    def test_the_set_is_one_a_caller_passes(self) -> None:
        from app.modules.procurement.service import INVOICE_PO_MATCH_RULE_SET, ProcurementService

        assert INVOICE_PO_MATCH_RULE_SET == "invoice_po_match"
        source = inspect.getsource(ProcurementService.check_invoice_against_po)
        assert "INVOICE_PO_MATCH_RULE_SET" in source

    async def test_warnings_stay_out_of_errors_in_the_engine(self) -> None:
        from app.core.validation.engine import validation_engine

        register_builtin_rules()
        line = dict(_payload()["lines"][0], invoiced="20000")
        report = await validation_engine.validate(
            data=_payload(invoice_net="60000", lines=[line]),
            rule_sets=["invoice_po_match"],
            target_type="invoice",
            target_id="x",
            project_id="p",
            metadata={"locale": "en"},
        )
        assert report.has_errors is False
        assert {r.rule_id for r in report.warnings} == {
            ProcurementInvoiceWithinOrder.rule_id,
            ProcurementInvoiceQuantityReceived.rule_id,
        }
