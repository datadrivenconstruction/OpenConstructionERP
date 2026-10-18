# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests - requisition approvers, line order progress and the feed cursor (issue #516).

Each check is shown failing on the case it exists for and passing on its
neighbour. Pure Python, no database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.procurement import validators as po_checks
from app.modules.procurement.requisition_feed import decode_cursor, encode_cursor
from app.modules.procurement.requisition_progress import LineProgress, fmt, in_line_unit, order_progress

REQUESTER = "6f1c2d3e-0000-4000-8000-000000000001"
APPROVER = "6f1c2d3e-0000-4000-8000-000000000002"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "req_number": "MR-0009",
        "requester_id": REQUESTER,
        "approval_chain": [APPROVER],
        "items": [
            {
                "description": "Concrete C30/37",
                "unit": "m3",
                "quantity_requested": "71.4000",
                "quantity_ordered": "71.4000",
                "order_unit_mismatches": [],
            }
        ],
    }
    payload.update(overrides)
    return payload


class TestApproverNotRequester:
    def test_a_chain_without_the_requester_passes(self) -> None:
        assert po_checks.check_requisition_approver_not_requester(_payload()) == []

    def test_the_requester_in_the_chain_is_named_with_their_step(self) -> None:
        findings = po_checks.check_requisition_approver_not_requester(_payload(approval_chain=[APPROVER, REQUESTER]))
        assert len(findings) == 1
        assert findings[0].params["step"] == "2"

    def test_no_chain_is_nothing_to_check(self) -> None:
        assert po_checks.check_requisition_approver_not_requester(_payload(approval_chain=[])) == []


class TestOverOrdered:
    def test_exactly_ordered_passes(self) -> None:
        assert po_checks.check_requisition_line_over_ordered(_payload()) == []

    def test_more_on_order_than_requested_is_flagged(self) -> None:
        payload = _payload()
        payload["items"][0]["quantity_ordered"] = "71.5"
        findings = po_checks.check_requisition_line_over_ordered(payload)
        assert len(findings) == 1
        assert findings[0].params["ordered"] == "71.5"


class TestUnitMismatch:
    def test_no_mismatch_passes(self) -> None:
        assert po_checks.check_requisition_order_unit_mismatch(_payload()) == []

    def test_each_mismatched_order_line_is_named(self) -> None:
        payload = _payload()
        payload["items"][0]["order_unit_mismatches"] = [{"ref": "PO-0003", "unit": "pcs"}]
        findings = po_checks.check_requisition_order_unit_mismatch(payload)
        assert [f.params["order"] for f in findings] == ["PO-0003"]
        assert findings[0].params["line_unit"] == "m3"


class TestProgress:
    def test_to_order_never_goes_below_zero_but_outstanding_does(self) -> None:
        line = LineProgress(requested=Decimal("10"), ordered=Decimal("12"), received=Decimal("12"))
        assert line.to_order == 0
        assert line.over_ordered is True
        assert line.outstanding == Decimal("-2")

    def test_order_progress_reads_none_partial_and_full(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        assert order_progress({}) == "none"
        assert order_progress({a: LineProgress(requested=Decimal("5"))}) == "none"
        assert (
            order_progress(
                {
                    a: LineProgress(requested=Decimal("5"), ordered=Decimal("5")),
                    b: LineProgress(requested=Decimal("2")),
                }
            )
            == "partial"
        )
        assert order_progress({a: LineProgress(requested=Decimal("5"), ordered=Decimal("5"))}) == "full"

    def test_a_converted_figure_is_trimmed_and_a_same_unit_one_keeps_its_scale(self) -> None:
        assert fmt(in_line_unit(Decimal("3250"), "kg", "t")) == "3.25"
        assert fmt(in_line_unit(Decimal("71.4000"), "m3", "m3")) == "71.4000"
        assert in_line_unit(Decimal("1"), "pcs", "t") is None


class TestCursor:
    def test_a_cursor_reads_back_to_its_position(self) -> None:
        stamp = datetime(2026, 10, 18, 9, 30, 1, 123456, tzinfo=UTC)
        row = uuid.uuid4()
        assert decode_cursor(encode_cursor(stamp, row)) == (stamp, row)

    def test_another_offset_is_read_as_the_same_instant(self) -> None:
        stamp = datetime(2026, 10, 18, 11, 30, tzinfo=timezone(timedelta(hours=2)))
        row = uuid.uuid4()
        decoded, _ = decode_cursor(encode_cursor(stamp, row))
        assert decoded == stamp
        assert decoded.utcoffset() == timedelta(0)

    @pytest.mark.parametrize("bad", ["not-a-cursor", "", "!!!", "MjAyNg"])
    def test_a_cursor_this_server_did_not_write_is_refused(self, bad: str) -> None:
        with pytest.raises(HTTPException) as exc:
            decode_cursor(bad)
        assert exc.value.status_code == 422
