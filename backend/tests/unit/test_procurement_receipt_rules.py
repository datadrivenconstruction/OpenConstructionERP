# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests - material certificates on goods receipts and the payment release rules (BF-01).

Three layers, like the other procurement rule tests: the certificate catalogue
and the pure checks, the rule classes with their messages in every shipped
locale, and reachability (both sets are ones a caller passes). The missing
certificate and the unapproved receipt are errors; the batch mismatch and the
open inspection are warnings.

Pure-Python, no database.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.messages import available_locales, is_key_present
from app.core.validation.rules import (
    ProcurementReceiptCertificateBatch,
    ProcurementReceiptCertificatePresent,
    ProcurementReceiptInspectionClosed,
    ProcurementReceiptRouteApproved,
    register_builtin_rules,
)
from app.modules.procurement import certificates
from app.modules.procurement import validators as po_checks

RECEIPT_RULES = [ProcurementReceiptCertificatePresent, ProcurementReceiptCertificateBatch]
RELEASE_RULES = [ProcurementReceiptRouteApproved, ProcurementReceiptInspectionClosed]


def _line(**overrides: Any) -> dict[str, Any]:
    line: dict[str, Any] = {
        "label": "1 (Rebar B500B 12 mm)",
        "quantity_received": "12.5",
        "batch_lot": "H-20931",
        "required_certificate_type": "en10204_3_1",
        "certificates": [{"certificate_type": "en10204_3_1", "certificate_number": "Z-118", "batch_number": "H-20931"}],
    }
    line.update(overrides)
    return line


def _receipt(*lines: dict[str, Any]) -> dict[str, Any]:
    return {"receipt_ref": "LS-4711", "po_number": "PO-0007", "items": list(lines) or [_line()]}


class TestCatalogue:
    def test_en10204_types_are_data(self) -> None:
        codes = {t.code for t in certificates.certificate_types()}
        assert {"en10204_2_1", "en10204_2_2", "en10204_3_1", "en10204_3_2"} <= codes

    def test_a_higher_type_of_the_family_covers_a_lower_one(self) -> None:
        assert certificates.satisfies("en10204_3_2", "en10204_3_1")
        assert certificates.satisfies("en10204_3_1", "en10204_2_2")
        assert not certificates.satisfies("en10204_2_2", "en10204_3_1")

    def test_another_family_never_covers(self) -> None:
        assert not certificates.satisfies("third_party_test_report", "en10204_2_1")

    def test_an_unknown_requirement_is_met_only_by_itself(self) -> None:
        assert certificates.satisfies("custom_x", "custom_x")
        assert not certificates.satisfies("en10204_3_2", "custom_x")

    def test_a_dropped_in_file_adds_a_type(self, tmp_path, monkeypatch) -> None:
        (tmp_path / "a.json").write_text(
            (certificates.CATALOGUE_DIR / "certificate_types.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (tmp_path / "z_pack.json").write_text(
            json.dumps({"types": [{"code": "gost_passport", "family": "passport", "rank": 1, "label": "Passport"}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(certificates, "CATALOGUE_DIR", tmp_path)
        certificates.reload_catalogue()
        try:
            assert certificates.is_known_type("gost_passport")
            assert certificates.is_known_type("en10204_3_1")
        finally:
            monkeypatch.undo()
            certificates.reload_catalogue()

    def test_the_schema_refuses_an_unknown_type(self) -> None:
        from pydantic import ValidationError

        from app.modules.procurement.schemas import GRCertificateCreate, POItemCreate

        with pytest.raises(ValidationError):
            GRCertificateCreate(certificate_type="nope")
        with pytest.raises(ValidationError):
            POItemCreate(description="Rebar", required_certificate_type="nope")
        assert POItemCreate(description="Rebar", required_certificate_type="").required_certificate_type is None


class TestCertificatePresent:
    def test_the_required_certificate_is_clean(self) -> None:
        assert po_checks.check_receipt_certificate_present(_receipt()) == []

    def test_a_higher_certificate_is_clean(self) -> None:
        line = _line(certificates=[{"certificate_type": "en10204_3_2", "certificate_number": "Z-1"}])
        assert po_checks.check_receipt_certificate_present(_receipt(line)) == []

    def test_a_missing_certificate_is_a_finding(self) -> None:
        findings = po_checks.check_receipt_certificate_present(_receipt(_line(certificates=[])))
        assert len(findings) == 1
        assert findings[0].element_ref == "1 (Rebar B500B 12 mm)"
        assert findings[0].details["required_certificate_type"] == "en10204_3_1"

    def test_a_lower_certificate_does_not_satisfy(self) -> None:
        line = _line(certificates=[{"certificate_type": "en10204_2_2", "certificate_number": "Z-2"}])
        findings = po_checks.check_receipt_certificate_present(_receipt(line))
        assert len(findings) == 1
        assert findings[0].params["delivered"] == "en10204_2_2"

    def test_a_line_without_a_requirement_needs_nothing(self) -> None:
        assert (
            po_checks.check_receipt_certificate_present(
                _receipt(_line(required_certificate_type=None, certificates=[]))
            )
            == []
        )

    def test_a_fully_rejected_line_needs_no_certificate(self) -> None:
        assert (
            po_checks.check_receipt_certificate_present(_receipt(_line(quantity_received="0", certificates=[]))) == []
        )


class TestCertificateBatch:
    def test_the_same_batch_is_clean_whatever_the_spelling(self) -> None:
        line = _line(batch_lot="h 20931", certificates=[{"certificate_type": "en10204_3_1", "batch_number": "H20931"}])
        assert po_checks.check_receipt_certificate_batch(_receipt(line)) == []

    def test_another_batch_is_a_finding(self) -> None:
        line = _line(
            certificates=[{"certificate_type": "en10204_3_1", "certificate_number": "Z-9", "batch_number": "H-1"}]
        )
        findings = po_checks.check_receipt_certificate_batch(_receipt(line))
        assert len(findings) == 1
        assert findings[0].params == {
            "line": "1 (Rebar B500B 12 mm)",
            "certificate": "Z-9",
            "certificate_batch": "H-1",
            "batch": "H-20931",
        }

    def test_nothing_to_compare_is_silent(self) -> None:
        assert po_checks.check_receipt_certificate_batch(_receipt(_line(batch_lot=None))) == []
        line = _line(certificates=[{"certificate_type": "en10204_3_1", "batch_number": None}])
        assert po_checks.check_receipt_certificate_batch(_receipt(line)) == []


class TestPaymentRelease:
    def _payload(self, **receipt: Any) -> dict[str, Any]:
        return {"po_number": "PO-0007", "receipts": [{"ref": "LS-4711", **receipt}]}

    @pytest.mark.parametrize("status", ["pending", "rejected"])
    def test_an_open_or_refused_route_blocks(self, status: str) -> None:
        findings = po_checks.check_receipt_route_approved(self._payload(approval_status=status))
        assert [f.element_ref for f in findings] == ["LS-4711"]

    @pytest.mark.parametrize("status", ["approved", None])
    def test_an_approved_or_absent_route_is_clean(self, status: str | None) -> None:
        assert po_checks.check_receipt_route_approved(self._payload(approval_status=status)) == []

    @pytest.mark.parametrize("status", ["scheduled", "in_progress", "failed"])
    def test_an_open_inspection_warns(self, status: str) -> None:
        assert len(po_checks.check_receipt_inspection_closed(self._payload(inspection_status=status))) == 1

    @pytest.mark.parametrize("status", ["completed", "cancelled", None])
    def test_a_closed_or_absent_inspection_is_clean(self, status: str | None) -> None:
        assert po_checks.check_receipt_inspection_closed(self._payload(inspection_status=status)) == []


class TestRules:
    def test_severities(self) -> None:
        assert ProcurementReceiptCertificatePresent.severity is Severity.ERROR
        assert ProcurementReceiptCertificateBatch.severity is Severity.WARNING
        assert ProcurementReceiptRouteApproved.severity is Severity.ERROR
        assert ProcurementReceiptInspectionClosed.severity is Severity.WARNING

    def test_every_message_key_is_in_every_shipped_locale(self) -> None:
        missing = [
            f"{locale}:{rule_cls.rule_id}.{suffix}"
            for rule_cls in RECEIPT_RULES + RELEASE_RULES
            for locale in available_locales()
            for suffix in ("fail", "suggestion")
            if not is_key_present(f"{rule_cls.rule_id}.{suffix}", locale)
        ]
        assert missing == []

    def test_every_check_name_resolves(self) -> None:
        for rule_cls in RECEIPT_RULES + RELEASE_RULES:
            assert inspect.isfunction(getattr(po_checks, rule_cls.check_name, None)), rule_cls.__name__

    async def test_a_failing_rule_renders_its_message(self) -> None:
        results = await ProcurementReceiptCertificatePresent().validate(
            ValidationContext(data=_receipt(_line(certificates=[])), metadata={"locale": "en"})
        )
        assert len(results) == 1 and results[0].passed is False
        assert "EN 10204 type 3.1" in results[0].message


class TestReachability:
    def test_registered_under_their_sets(self) -> None:
        register_builtin_rules()
        assert {r.rule_id for r in rule_registry.get_rules_for_sets(["goods_receipt"])} == {
            r.rule_id for r in RECEIPT_RULES
        }
        assert {r.rule_id for r in rule_registry.get_rules_for_sets(["invoice_payment_release"])} == {
            r.rule_id for r in RELEASE_RULES
        }

    def test_the_sets_are_ones_a_caller_passes(self) -> None:
        from app.modules.finance.service import FinanceService
        from app.modules.procurement import receiving
        from app.modules.procurement.service import ProcurementService

        assert receiving.RECEIPT_RULE_SET == "goods_receipt"
        assert receiving.PAYMENT_RELEASE_RULE_SET == "invoice_payment_release"
        assert "validate_receipt_or_raise" in inspect.getsource(ProcurementService.confirm_goods_receipt)
        assert "_check_payment_release" in inspect.getsource(FinanceService.approve_invoice)
        assert "_check_payment_release" in inspect.getsource(FinanceService.pay_invoice)

    async def test_a_missing_certificate_is_an_engine_error_and_a_batch_only_a_warning(self) -> None:
        from app.core.validation.engine import validation_engine

        register_builtin_rules()
        missing = await validation_engine.validate(
            data=_receipt(_line(certificates=[])),
            rule_sets=["goods_receipt"],
            target_type="goods_receipt",
            target_id="x",
            metadata={"locale": "en"},
        )
        assert missing.has_errors is True
        other_batch = _line(certificates=[{"certificate_type": "en10204_3_1", "batch_number": "H-1"}])
        batch = await validation_engine.validate(
            data=_receipt(other_batch),
            rule_sets=["goods_receipt"],
            target_type="goods_receipt",
            target_id="x",
            metadata={"locale": "en"},
        )
        assert batch.has_errors is False
        assert {r.rule_id for r in batch.warnings} == {ProcurementReceiptCertificateBatch.rule_id}
