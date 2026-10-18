# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests - material requisition rules, line merging and buy-list sources.

The pure checks, the rule classes with their messages in every shipped locale,
and reachability: the ``procurement_requisition`` set is one the submit path
actually passes. Then the two pieces of the BOQ handoff that need no database:
lines merge only on a catalogue item, and every buy-list row names its sources.

Pure-Python, no database.
"""

from __future__ import annotations

import inspect
import uuid
from decimal import Decimal
from typing import Any

from app.core.validation.engine import ValidationContext, rule_registry
from app.core.validation.messages import available_locales, is_key_present
from app.core.validation.rules import (
    ProcurementRequisitionApproverNotRequester,
    ProcurementRequisitionLineCostLine,
    ProcurementRequisitionLineNeededByNotPast,
    ProcurementRequisitionLineOverOrdered,
    ProcurementRequisitionLineScheduleMoved,
    ProcurementRequisitionNeededByNotPast,
    ProcurementRequisitionOrderUnitMismatch,
    ProcurementRequisitionQuantityPositive,
    ProcurementRequisitionSingleCurrency,
    ProcurementRequisitionSourceUnit,
    ProcurementRequisitionSuggestedVendorActive,
    ProcurementRequisitionSuggestedVendorDiffers,
    ProcurementRequisitionSuggestedVendorInDirectory,
    ProcurementRequisitionSuggestionConflict,
    ProcurementRequisitionVendorActive,
    ProcurementRequisitionVendorChosen,
    ProcurementRequisitionVendorInDirectory,
    register_builtin_rules,
)
from app.modules.procurement import validators as po_checks
from app.modules.procurement.requisition_service import (
    REQUISITION_RULE_SET,
    RequisitionWorkflowService,
    merge_lines_by_catalog_item,
)
from app.modules.procurement.schemas import RequisitionItemIn, RequisitionItemSourceIn
from app.modules.resource_summary.aggregate import aggregate_material_buy_list

RULES = [
    ProcurementRequisitionQuantityPositive,
    ProcurementRequisitionSourceUnit,
    ProcurementRequisitionNeededByNotPast,
    # Issue #516: supplier, currency and budget link.
    ProcurementRequisitionVendorInDirectory,
    ProcurementRequisitionVendorActive,
    ProcurementRequisitionVendorChosen,
    ProcurementRequisitionSingleCurrency,
    ProcurementRequisitionLineCostLine,
    # Issue #516, second slice: suggested supplier and line dates.
    ProcurementRequisitionSuggestedVendorInDirectory,
    ProcurementRequisitionSuggestedVendorActive,
    ProcurementRequisitionSuggestionConflict,
    ProcurementRequisitionSuggestedVendorDiffers,
    ProcurementRequisitionLineNeededByNotPast,
    ProcurementRequisitionLineScheduleMoved,
    # Issue #516, third slice: designated approvers and orders per line.
    ProcurementRequisitionApproverNotRequester,
    ProcurementRequisitionLineOverOrdered,
    ProcurementRequisitionOrderUnitMismatch,
]


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "req_number": "MR-0003",
        "required_date": "2026-11-02",
        "today": "2026-10-15",
        "items": [
            {
                "description": "Concrete C30/37",
                "unit": "m3",
                "quantity_requested": "71.4",
                "sources": [
                    {"unit": "m3", "quantity": "51", "resource_key": "0:C30"},
                    {"unit": "M3 ", "quantity": "20.4", "resource_key": "0:C30"},
                ],
            }
        ],
    }
    payload.update(overrides)
    return payload


class TestChecks:
    def test_a_clean_requisition_has_no_findings(self) -> None:
        payload = _payload()
        assert po_checks.check_requisition_quantity_positive(payload) == []
        assert po_checks.check_requisition_source_unit(payload) == []
        assert po_checks.check_requisition_needed_by_not_past(payload) == []

    def test_zero_negative_and_garbage_quantities_are_found(self) -> None:
        items = [
            {"description": "a", "quantity_requested": "0"},
            {"description": "b", "quantity_requested": "-1"},
            {"description": "c", "quantity_requested": "lots"},
            {"description": "d", "quantity_requested": "0.001"},
        ]
        findings = po_checks.check_requisition_quantity_positive(_payload(items=items))
        assert [f.element_ref for f in findings] == ["1 (a)", "2 (b)", "3 (c)"]

    def test_a_source_in_another_unit_is_found_and_not_converted(self) -> None:
        item = dict(_payload()["items"][0], unit="t")
        findings = po_checks.check_requisition_source_unit(_payload(items=[item]))
        assert len(findings) == 2
        assert findings[0].params["source_unit"] == "m3"

    def test_a_line_without_sources_has_nothing_to_match(self) -> None:
        item = {"description": "Sand", "unit": "t", "quantity_requested": "4", "sources": []}
        assert po_checks.check_requisition_source_unit(_payload(items=[item])) == []

    def test_needed_by_in_the_past_is_found_today_is_not(self) -> None:
        assert po_checks.check_requisition_needed_by_not_past(_payload(required_date="2026-10-15")) == []
        assert po_checks.check_requisition_needed_by_not_past(_payload(required_date=None)) == []
        [finding] = po_checks.check_requisition_needed_by_not_past(_payload(required_date="2026-10-14"))
        assert finding.params == {"date": "2026-10-14", "today": "2026-10-15"}


class TestRules:
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
        results = await ProcurementRequisitionNeededByNotPast().validate(
            ValidationContext(data=_payload(required_date="2026-10-01"), metadata={"locale": "en"})
        )
        assert len(results) == 1 and results[0].passed is False
        assert "2026-10-01" in results[0].message

    def test_registered_under_the_requisition_set(self) -> None:
        register_builtin_rules()
        registered = {r.rule_id for r in rule_registry.get_rules_for_sets([REQUISITION_RULE_SET])}
        assert {rule_cls.rule_id for rule_cls in RULES} == registered

    def test_the_set_is_one_submit_passes(self) -> None:
        assert REQUISITION_RULE_SET == "procurement_requisition"
        assert "self.validate(" in inspect.getsource(RequisitionWorkflowService.submit)
        assert "REQUISITION_RULE_SET" in inspect.getsource(RequisitionWorkflowService.validate)


class TestMerge:
    def _line(self, description: str, qty: str, unit: str = "t", catalog: uuid.UUID | None = None) -> RequisitionItemIn:
        return RequisitionItemIn(
            description=description,
            unit=unit,
            quantity_requested=qty,
            catalog_item_id=catalog,
            sources=[RequisitionItemSourceIn(resource_key=description, quantity=qty, unit=unit)],
        )

    def test_same_catalogue_item_and_unit_merge_with_all_sources(self) -> None:
        cat = uuid.uuid4()
        merged = merge_lines_by_catalog_item(
            [self._line("Rebar", "2", catalog=cat), self._line("Rebar 12", "1.5", catalog=cat)]
        )
        assert len(merged) == 1
        assert merged[0].description == "Rebar"
        assert Decimal(merged[0].quantity_requested) == Decimal("3.5")
        assert [s.resource_key for s in merged[0].sources] == ["Rebar", "Rebar 12"]

    def test_same_description_and_unit_without_a_catalogue_item_stay_apart(self) -> None:
        merged = merge_lines_by_catalog_item([self._line("Sand", "4"), self._line("Sand", "6")])
        assert [m.quantity_requested for m in merged] == ["4", "6"]

    def test_same_catalogue_item_in_another_unit_stays_apart(self) -> None:
        cat = uuid.uuid4()
        merged = merge_lines_by_catalog_item(
            [self._line("Rebar", "2", "t", cat), self._line("Rebar", "300", "kg", cat)]
        )
        assert len(merged) == 2


class TestBuyListSources:
    def test_each_row_names_its_contributing_resources(self) -> None:
        positions = [
            {
                "id": "p1",
                "quantity": "50",
                "metadata_": {
                    "resources": [
                        {"type": "labor", "name": "Mason", "unit": "h", "quantity": "3.5"},
                        {"type": "material", "name": "Concrete", "unit": "m3", "quantity": "1.02", "code": "C30"},
                    ]
                },
            },
            {
                "id": "p2",
                "quantity": "20",
                "metadata_": {
                    "resources": [
                        {
                            "id": "res-7",
                            "type": "material",
                            "name": "concrete",
                            "unit": "M3",
                            "quantity": "1",
                            "catalog_item_id": "cat-1",
                        }
                    ]
                },
            },
        ]
        bl = aggregate_material_buy_list(positions, currency="EUR")
        # A catalogue item and an uncoded line never share a row because their
        # names agree: being called "concrete" is not proof of being the same
        # material (issue #516).
        rows = {row.sources[0].catalog_item_id: row for row in bl.items}
        assert set(rows) == {None, "cat-1"}
        uncoded, coded = rows[None], rows["cat-1"]
        assert (uncoded.position_count, uncoded.quantity) == (1, Decimal("51.00"))
        assert (coded.position_count, coded.quantity) == (1, Decimal("20"))
        assert [(s.position_id, s.resource_key, s.quantity, s.unit, s.catalog_item_id) for s in uncoded.sources] == [
            ("p1", "1:C30", Decimal("51.00"), "m3", None),
        ]
        assert [(s.position_id, s.resource_key, s.quantity, s.unit, s.catalog_item_id) for s in coded.sources] == [
            ("p2", "res-7", Decimal("20"), "M3", "cat-1"),
        ]
        row = uncoded
        # The serialised row keeps its old keys and adds the sources.
        as_dict = row.to_dict()
        assert {"name", "unit", "quantity", "cost", "position_count"} <= set(as_dict)
        assert as_dict["sources"][0]["quantity"] == "51.0000"
