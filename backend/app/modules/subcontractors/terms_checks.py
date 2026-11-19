# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure checks on a deduction statement and on a bidder list.

The payload of the statement checks is the dict :func:`terms.build_deductions`
returns (money as Decimal or Decimal strings). A stored or imported statement
whose lines do not add up is an error: the amount paid could not be explained.
The bidder check reads ``{"radius_km": ..., "recipients": [{"name", "distance_km"}]}``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.modules.subcontractors.terms import money, opt_decimal, percent_of
from app.modules.subcontractors.validators import Finding

TOLERANCE = Decimal("0.005")


def _ref(payload: dict[str, Any]) -> str:
    return str(payload.get("element_ref") or payload.get("application_number") or "statement")


def _fmt(value: Decimal) -> str:
    return f"{value:.2f}"


def check_levies_reconcile(payload: dict[str, Any]) -> list[Finding]:
    """Work value less levies and retention must equal the payable amount."""
    if "payable" not in payload:
        return []
    work = money(payload.get("work_value"))
    lines_total = sum((money(line.get("amount")) for line in payload.get("levies") or []), Decimal("0"))
    levies_total = money(payload.get("levies_total"))
    retention = money(payload.get("retention_amount"))
    payable = money(payload.get("payable"))
    expected = work - lines_total - retention
    if abs(lines_total - levies_total) <= TOLERANCE and abs(expected - payable) <= TOLERANCE:
        return []
    return [
        Finding(
            element_ref=_ref(payload),
            params={"expected": _fmt(expected), "payable": _fmt(payable)},
            details={"work_value": str(work), "levies": str(lines_total), "retention": str(retention)},
        )
    ]


def check_discount_reconciles(payload: dict[str, Any]) -> list[Finding]:
    """The payment discount must be its rate of the payable amount, and come off it."""
    rate = opt_decimal(payload.get("payment_discount_percent"))
    if rate is None or "payable" not in payload:
        return []
    payable = money(payload.get("payable"))
    discount = money(payload.get("payment_discount_amount"))
    expected = percent_of(payable, rate)
    after = money(payload.get("payable_with_discount"))
    if abs(discount - expected) <= TOLERANCE and abs(payable - discount - after) <= TOLERANCE:
        return []
    return [
        Finding(
            element_ref=_ref(payload),
            params={"expected": _fmt(expected), "discount": _fmt(discount)},
            details={"payable": str(payable), "rate_percent": str(rate)},
        )
    ]


def check_recipient_outside_radius(payload: dict[str, Any]) -> list[Finding]:
    """A firm on the bidder list lies farther from the site than the search radius."""
    radius = opt_decimal(payload.get("radius_km"))
    if radius is None:
        return []
    findings: list[Finding] = []
    for row in payload.get("recipients") or []:
        distance = opt_decimal(row.get("distance_km"))
        if distance is None or distance <= radius:
            continue
        findings.append(
            Finding(
                element_ref=str(row.get("name") or row.get("id") or ""),
                params={"distance": f"{distance:.0f}", "radius": f"{radius:.0f}"},
                details={"subcontractor_id": str(row.get("id") or ""), "distance_km": str(distance)},
            )
        )
    return findings


__all__ = ["check_discount_reconciles", "check_levies_reconcile", "check_recipient_outside_radius"]
