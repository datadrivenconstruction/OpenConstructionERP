# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests - suggested supplier and needed-by date per requisition line (issue #516).

The pure checks of the six rules added in the second slice, each with a case it
must find and a case it must pass; the BOQ suggestion helpers (resource beats
position default, the resource key matches the buy list's); the buy list
carrying each source's suggestion; the line date proposal from a schedule
activity; and the latest ordering date no longer posing as a delivery forecast.

Pure-Python, no database.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from app.core.validation.engine import ValidationContext
from app.core.validation.rules import (
    ProcurementRequisitionLineScheduleMoved,
    ProcurementRequisitionSuggestionConflict,
)
from app.modules.boq.supplier_suggestion import (
    ORIGIN_POSITION,
    ORIGIN_RESOURCE,
    effective_suggestion,
    find_resource,
    resource_key_in_split,
)
from app.modules.procurement import validators as po_checks
from app.modules.procurement.requisition_service import RequisitionWorkflowService
from app.modules.procurement.schemas import RequisitionItemIn, ScheduleActivityOption
from app.modules.procurement.service import _latest_order_date
from app.modules.resource_summary.aggregate import _resource_key, aggregate_material_buy_list

V1 = str(uuid.uuid4())
V2 = str(uuid.uuid4())


def _item(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"description": "Concrete", "unit": "m3", "quantity_requested": "10", "sources": []}
    base.update(fields)
    return base


def _payload(*items: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"req_number": "MR-0009", "today": "2026-10-17", "items": list(items)}
    payload.update(overrides)
    return payload


class TestSuggestedSupplierChecks:
    def test_an_unknown_suggestion_is_found_and_a_known_one_is_not(self) -> None:
        known = _item(suggested_vendor_id=V1, suggested_vendor={"id": V1, "name": "Beton Nord", "status": "active"})
        unknown = _item(suggested_vendor_id=V2, suggested_vendor=None)
        none = _item()
        findings = po_checks.check_requisition_suggested_vendor_in_directory(_payload(known, unknown, none))
        assert [f.details["suggested_vendor_id"] for f in findings] == [V2]

    @pytest.mark.parametrize("state", ["suspended", "blacklisted"])
    def test_an_inactive_suggestion_is_found(self, state: str) -> None:
        line = _item(suggested_vendor_id=V1, suggested_vendor={"id": V1, "name": "Kies Sued", "status": state})
        [finding] = po_checks.check_requisition_suggested_vendor_active(_payload(line))
        assert finding.params["vendor"] == "Kies Sued"
        active = _item(suggested_vendor_id=V1, suggested_vendor={"id": V1, "name": "Kies Sued", "status": "active"})
        assert po_checks.check_requisition_suggested_vendor_active(_payload(active)) == []

    def test_sources_that_disagree_are_found_and_agreeing_ones_are_not(self) -> None:
        disagree = _item(source_suggested_vendor_ids=[V1, V2])
        agree = _item(source_suggested_vendor_ids=[V1])
        [finding] = po_checks.check_requisition_suggestion_conflict(_payload(disagree, agree))
        assert finding.params["count"] == "2"

    def test_a_suggestion_other_than_the_chosen_supplier_is_found(self) -> None:
        other = _item(suggested_vendor_id=V2, suggested_vendor={"id": V2, "name": "Kies Sued", "status": "active"})
        same = _item(suggested_vendor_id=V1)
        none = _item()
        [finding] = po_checks.check_requisition_suggested_vendor_differs(_payload(other, same, none, vendor_id=V1))
        assert finding.params["vendor"] == "Kies Sued"
        # Without a chosen supplier there is nothing to differ from.
        assert po_checks.check_requisition_suggested_vendor_differs(_payload(other, vendor_id=None)) == []

    async def test_a_conflict_warns_and_does_not_block(self) -> None:
        rule = ProcurementRequisitionSuggestionConflict()
        results = await rule.validate(
            ValidationContext(
                data=_payload(_item(source_suggested_vendor_ids=[V1, V2])),
                metadata={"locale": "de"},
            )
        )
        assert [r.passed for r in results] == [False]
        assert results[0].severity.value == "warning"


class TestLineDateChecks:
    def test_a_line_date_in_the_past_is_found_today_is_not(self) -> None:
        past = _item(required_date="2026-10-16")
        today = _item(required_date="2026-10-17")
        inherited = _item(required_date=None)
        [finding] = po_checks.check_requisition_line_needed_by_not_past(_payload(past, today, inherited))
        assert finding.params["date"] == "2026-10-16"

    def test_a_moved_activity_is_found_and_an_unmoved_one_is_not(self) -> None:
        aid = str(uuid.uuid4())
        moved = _item(schedule_activity_id=aid, schedule_anchor_date="2026-11-02", schedule_activity_start="2026-11-09")
        still = _item(schedule_activity_id=aid, schedule_anchor_date="2026-11-02", schedule_activity_start="2026-11-02")
        gone = _item(schedule_activity_id=aid, schedule_anchor_date="2026-11-02", schedule_activity_start=None)
        [finding] = po_checks.check_requisition_line_schedule_moved(_payload(moved, still, gone))
        assert finding.params == {"line": finding.params["line"], "anchor": "2026-11-02", "start": "2026-11-09"}

    async def test_a_moved_activity_renders_its_message_in_russian(self) -> None:
        aid = str(uuid.uuid4())
        results = await ProcurementRequisitionLineScheduleMoved().validate(
            ValidationContext(
                data=_payload(
                    _item(
                        schedule_activity_id=aid,
                        schedule_anchor_date="2026-11-02",
                        schedule_activity_start="2026-11-09",
                    )
                ),
                metadata={"locale": "ru"},
            )
        )
        assert results[0].passed is False
        assert "2026-11-09" in results[0].message
        assert "{" not in results[0].message


class TestLineDateProposal:
    def _activity(self, start: str) -> tuple[uuid.UUID, dict[uuid.UUID, ScheduleActivityOption]]:
        aid = uuid.uuid4()
        return aid, {aid: ScheduleActivityOption(id=aid, name="Pour slab", start_date=start)}

    def test_no_date_is_proposed_as_activity_start_minus_buffer(self) -> None:
        aid, acts = self._activity("2026-11-10")
        line = RequisitionItemIn(description="Concrete", schedule_activity_id=aid, schedule_buffer_days=3)
        assert RequisitionWorkflowService._line_dates(line, acts) == ("2026-11-07", "2026-11-10")

    def test_a_date_sent_with_the_activity_is_kept(self) -> None:
        aid, acts = self._activity("2026-11-10")
        line = RequisitionItemIn(
            description="Concrete", schedule_activity_id=aid, schedule_buffer_days=3, required_date=date(2026, 11, 5)
        )
        assert RequisitionWorkflowService._line_dates(line, acts) == ("2026-11-05", "2026-11-10")

    def test_an_echoed_anchor_survives_a_moved_schedule(self) -> None:
        """Saving a draft again must not quietly re-anchor to the moved activity."""
        aid, acts = self._activity("2026-11-17")
        line = RequisitionItemIn(
            description="Concrete",
            schedule_activity_id=aid,
            schedule_buffer_days=3,
            required_date=date(2026, 11, 7),
            schedule_anchor_date=date(2026, 11, 10),
        )
        assert RequisitionWorkflowService._line_dates(line, acts) == ("2026-11-07", "2026-11-10")

    def test_a_line_without_an_activity_keeps_its_own_date_or_none(self) -> None:
        assert RequisitionWorkflowService._line_dates(RequisitionItemIn(description="Sand"), {}) == (None, None)
        line = RequisitionItemIn(description="Sand", required_date=date(2026, 12, 1))
        assert RequisitionWorkflowService._line_dates(line, {}) == ("2026-12-01", None)


class TestLatestOrderDate:
    def test_it_is_the_required_date_minus_the_lead_time(self) -> None:
        assert _latest_order_date("2026-11-10", 14) == "2026-10-27"

    def test_it_is_not_presented_as_a_delivery_forecast(self) -> None:
        """The old name read an ordering deadline as an arrival date (issue #516)."""
        import app.modules.procurement.service as service

        assert not hasattr(service, "_compute_delivery_date")


class TestBOQSuggestion:
    def test_the_resource_suggestion_beats_the_position_default(self) -> None:
        meta = {"suggested_vendor_id": V1}
        assert effective_suggestion(meta, {"suggested_vendor_id": V2}) == (uuid.UUID(V2), ORIGIN_RESOURCE)
        assert effective_suggestion(meta, {}) == (uuid.UUID(V1), ORIGIN_POSITION)
        assert effective_suggestion({}, {}) == (None, None)
        assert effective_suggestion({"suggested_vendor_id": "not-a-uuid"}, {}) == (None, None)

    @pytest.mark.parametrize(
        ("res", "index"),
        [({"id": "res-7", "code": "C30"}, 2), ({"code": "C30"}, 2), ({}, 4), ({"id": " ", "code": " "}, 1)],
    )
    def test_the_resource_key_is_the_one_the_buy_list_uses(self, res: dict[str, Any], index: int) -> None:
        assert resource_key_in_split(res, index) == _resource_key(res, index)

    def test_find_resource_by_key(self) -> None:
        meta = {"resources": [{"code": "A"}, {"id": "r-2"}]}
        assert find_resource(meta, "r-2") == (1, {"id": "r-2"})
        assert find_resource(meta, "0:A") == (0, {"code": "A"})
        assert find_resource(meta, "missing") is None

    def test_the_buy_list_names_each_sources_suggestion_and_does_not_change_quantities(self) -> None:
        resources = [
            {"type": "material", "name": "Concrete", "unit": "m3", "quantity": "1", "code": "C30"},
            {"type": "material", "name": "Concrete", "unit": "m3", "quantity": "1", "suggested_vendor_id": V2},
        ]
        plain = aggregate_material_buy_list([{"id": "p1", "quantity": "10", "metadata_": {"resources": resources}}])
        suggested = aggregate_material_buy_list(
            [{"id": "p1", "quantity": "10", "metadata_": {"resources": resources, "suggested_vendor_id": V1}}]
        )
        [row] = suggested.items
        assert [(s.suggested_vendor_id, s.suggested_vendor_origin) for s in row.sources] == [
            (V1, ORIGIN_POSITION),
            (V2, ORIGIN_RESOURCE),
        ]
        # The suggestion is metadata only: quantities and cost are those of the plain list.
        assert plain.to_dict()["items"][0]["quantity"] == suggested.to_dict()["items"][0]["quantity"]
        assert plain.to_dict()["total_cost"] == suggested.to_dict()["total_cost"]
