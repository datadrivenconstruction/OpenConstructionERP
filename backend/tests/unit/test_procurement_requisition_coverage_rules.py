# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests - requisition source reconciliation and over-allocation (issue #516).

Pure Python, no database. Each check is shown failing on the case it exists for
and passing on its neighbour.
"""

from __future__ import annotations

from typing import Any

from app.modules.procurement import validators as po_checks


def _line(quantity: str, sources: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "description": "Rebar B500B",
        "unit": "t",
        "quantity_requested": quantity,
        "sources": sources,
        **extra,
    }


def _src(quantity: str, unit: str = "t", **extra: Any) -> dict[str, Any]:
    return {"unit": unit, "quantity": quantity, "resource_key": "0", **extra}


def _payload(*lines: dict[str, Any], operation: str = "submit") -> dict[str, Any]:
    return {"req_number": "MR-0001", "operation": operation, "items": list(lines)}


class TestSourcesReconcile:
    def test_sources_adding_up_to_the_line_pass(self) -> None:
        payload = _payload(_line("12.5", [_src("10"), _src("2.5")]))
        assert po_checks.check_requisition_sources_reconcile(payload) == []

    def test_a_line_above_its_sources_is_flagged_as_error_on_submit(self) -> None:
        findings = po_checks.check_requisition_sources_reconcile(_payload(_line("13", [_src("10"), _src("2.5")])))
        assert len(findings) == 1
        assert findings[0].severity is None
        assert findings[0].params["sources"] == "12.5"
        assert findings[0].params["quantity"] == "13"

    def test_a_line_below_its_sources_is_flagged_too(self) -> None:
        findings = po_checks.check_requisition_sources_reconcile(_payload(_line("9", [_src("10")])))
        assert len(findings) == 1

    def test_on_a_draft_the_finding_is_a_warning(self) -> None:
        findings = po_checks.check_requisition_sources_reconcile(_payload(_line("9", [_src("10")]), operation="draft"))
        assert [f.severity for f in findings] == ["warning"]

    def test_decimal_strings_are_compared_exactly(self) -> None:
        payload = _payload(_line("0.3", [_src("0.1"), _src("0.2")]))
        assert po_checks.check_requisition_sources_reconcile(payload) == []

    def test_a_line_without_sources_is_not_reconciled(self) -> None:
        assert po_checks.check_requisition_sources_reconcile(_payload(_line("5", []))) == []

    def test_sources_in_another_unit_are_left_to_the_unit_rule(self) -> None:
        payload = _payload(_line("12", [_src("12000", unit="kg")]))
        assert po_checks.check_requisition_sources_reconcile(payload) == []


class TestOverAllocated:
    def test_within_demand_passes(self) -> None:
        source = _src("6", demand="10", covered_other="4")
        assert po_checks.check_requisition_over_allocated(_payload(_line("6", [source]))) == []

    def test_covered_plus_this_above_demand_warns_and_names_the_excess(self) -> None:
        source = _src("6", demand="10", covered_other="5")
        findings = po_checks.check_requisition_over_allocated(_payload(_line("6", [source])))
        assert len(findings) == 1
        assert findings[0].params["excess"] == "1"
        assert findings[0].params["demand"] == "10"

    def test_a_reason_on_the_line_acknowledges_it(self) -> None:
        source = _src("6", demand="10", covered_other="5")
        line = _line("6", [source], over_allocation_reason="Spare for the second pour")
        assert po_checks.check_requisition_over_allocated(_payload(line)) == []

    def test_a_blank_reason_does_not_count(self) -> None:
        source = _src("6", demand="10", covered_other="5")
        line = _line("6", [source], over_allocation_reason="   ")
        assert len(po_checks.check_requisition_over_allocated(_payload(line))) == 1

    def test_an_unknown_demand_is_not_judged(self) -> None:
        source = _src("6", demand=None, covered_other="5")
        assert po_checks.check_requisition_over_allocated(_payload(_line("6", [source]))) == []

    def test_a_shrunk_boq_shows_as_over_allocation_without_touching_the_line(self) -> None:
        source = _src("6", demand="3", covered_other="0")
        assert len(po_checks.check_requisition_over_allocated(_payload(_line("6", [source])))) == 1
