# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests - the requisition rules added for approval and conversion (issue #516).

The supplier must come from the Vendor directory and be active, a conversion
needs one, a requisition is priced in one currency, and a line without a cost
line is flagged because its order would not commit budget. Each check is shown
failing on the case it exists for and passing on its neighbour, so a check that
answered the same either way would be caught.

Pure-Python, no database.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.core.validation.rules import (
    ProcurementRequisitionLineCostLine,
    ProcurementRequisitionVendorActive,
    ProcurementRequisitionVendorChosen,
)
from app.modules.procurement import validators as po_checks
from app.modules.procurement.models import MaterialRequisition, MaterialRequisitionItem
from app.modules.procurement.requisition_service import RequisitionWorkflowService, VendorInfo
from app.modules.procurement.service import _MR_STATUS_TRANSITIONS

VENDOR_ID = "6f1c2d3e-0000-4000-8000-000000000001"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "req_number": "MR-0007",
        "required_date": "2026-11-02",
        "today": "2026-10-16",
        "operation": "submit",
        "vendor_id": VENDOR_ID,
        "vendor": {"id": VENDOR_ID, "name": "Beton Nord", "status": "active"},
        "items": [
            {
                "description": "Concrete C30/37",
                "unit": "m3",
                "quantity_requested": "12",
                "currency_code": "EUR",
                "cost_line_id": "6f1c2d3e-0000-4000-8000-0000000000aa",
                "sources": [],
            }
        ],
    }
    payload.update(overrides)
    return payload


class TestVendorChecks:
    def test_an_active_directory_vendor_passes_every_vendor_check(self) -> None:
        payload = _payload(operation="convert")
        assert po_checks.check_requisition_vendor_in_directory(payload) == []
        assert po_checks.check_requisition_vendor_active(payload) == []
        assert po_checks.check_requisition_vendor_chosen(payload) == []

    def test_a_vendor_id_the_directory_does_not_know_is_found(self) -> None:
        [finding] = po_checks.check_requisition_vendor_in_directory(_payload(vendor=None))
        assert finding.params == {"vendor": VENDOR_ID}
        # Unknown is not the same statement as inactive: the active check stays silent.
        assert po_checks.check_requisition_vendor_active(_payload(vendor=None)) == []

    @pytest.mark.parametrize("state", ["suspended", "blacklisted", ""])
    def test_a_vendor_that_is_not_active_is_found(self, state: str) -> None:
        vendor = {"id": VENDOR_ID, "name": "Beton Nord", "status": state}
        [finding] = po_checks.check_requisition_vendor_active(_payload(vendor=vendor))
        assert finding.params == {"vendor": "Beton Nord"}
        assert finding.details["vendor_status"] == state

    def test_no_vendor_is_fine_until_the_conversion(self) -> None:
        for operation in ("submit", "approve"):
            assert (
                po_checks.check_requisition_vendor_chosen(_payload(vendor_id=None, vendor=None, operation=operation))
                == []
            )
        [finding] = po_checks.check_requisition_vendor_chosen(
            _payload(vendor_id=None, vendor=None, operation="convert")
        )
        assert finding.params == {"req": "MR-0007"}


class TestCurrencyAndBudget:
    def test_one_currency_and_unpriced_lines_pass(self) -> None:
        items = [
            dict(_payload()["items"][0]),
            dict(_payload()["items"][0], currency_code="eur "),
            dict(_payload()["items"][0], currency_code=""),
        ]
        assert po_checks.check_requisition_single_currency(_payload(items=items)) == []

    def test_two_currencies_are_found(self) -> None:
        items = [dict(_payload()["items"][0]), dict(_payload()["items"][0], currency_code="CHF")]
        [finding] = po_checks.check_requisition_single_currency(_payload(items=items))
        assert finding.params == {"req": "MR-0007", "currencies": "CHF, EUR"}

    def test_a_line_without_a_cost_line_is_flagged_and_a_linked_one_is_not(self) -> None:
        items = [dict(_payload()["items"][0]), dict(_payload()["items"][0], description="Rebar", cost_line_id=None)]
        findings = po_checks.check_requisition_line_cost_line(_payload(items=items))
        assert [f.element_ref for f in findings] == ["2 (Rebar)"]


class TestRuleClasses:
    def test_the_budget_link_warns_and_does_not_block(self) -> None:
        assert ProcurementRequisitionLineCostLine.severity == Severity.WARNING
        assert ProcurementRequisitionVendorActive.severity == Severity.ERROR
        assert ProcurementRequisitionVendorChosen.severity == Severity.ERROR

    async def test_an_inactive_vendor_renders_its_message_in_german(self) -> None:
        vendor = {"id": VENDOR_ID, "name": "Beton Nord", "status": "blacklisted"}
        [result] = await ProcurementRequisitionVendorActive().validate(
            ValidationContext(data=_payload(vendor=vendor), metadata={"locale": "de"})
        )
        assert result.passed is False
        assert "Beton Nord" in result.message
        assert "Lieferantenverzeichnis" in result.message


class TestPayloadAndFsm:
    def _req(self) -> MaterialRequisition:
        req = MaterialRequisition(project_id=None, req_number="MR-0009", status="submitted", required_date=None)
        req.items = [
            MaterialRequisitionItem(
                description="Sand",
                unit="t",
                quantity_requested="4",
                currency_code="EUR",
                cost_line_id=None,
                sort_order=0,
                sources=[],
            )
        ]
        return req

    def test_the_payload_carries_operation_vendor_currency_and_cost_line(self) -> None:
        vendor = VendorInfo(VENDOR_ID, "Beton Nord", "active", None, "EUR")  # type: ignore[arg-type]
        payload = RequisitionWorkflowService.validation_payload(
            self._req(),
            operation="convert",
            vendor=vendor,
            vendor_id=VENDOR_ID,  # type: ignore[arg-type]
        )
        assert payload["operation"] == "convert"
        assert payload["vendor"] == {"id": VENDOR_ID, "name": "Beton Nord", "status": "active"}
        assert payload["items"][0]["currency_code"] == "EUR"
        assert payload["items"][0]["cost_line_id"] is None

    def test_an_ordered_requisition_can_return_to_approved_and_nothing_skips_approval(self) -> None:
        assert "approved" in _MR_STATUS_TRANSITIONS["ordered"]
        assert "ordered" not in _MR_STATUS_TRANSITIONS["submitted"]
        assert "ordered" not in _MR_STATUS_TRANSITIONS["draft"]
