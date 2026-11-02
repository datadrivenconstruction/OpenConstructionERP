# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Consolidated e-invoice: N source receipts grouped into one document per period.

Neutral. The period, the due date, who may be grouped, the single-transaction
cap and the country rule ids all come from the ``consolidation`` block of the
country's mandate file. Pure functions, reference date passed in.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.einvoice_clearance.lifecycle import (
    CORE_OUTSIDE_PERIOD,
    SEV_ERROR,
    Finding,
    condition_holds,
)

REASON_OUTSIDE_PERIOD = "outside_period"
REASON_OVER_CAP = "over_cap"
REASON_BUYER_TYPE = "buyer_type"
REASON_ACTIVITY = "activity"

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Receipt:
    """One source sale. ``gross`` defaults to net + tax."""

    number: str
    date: date
    net: Decimal
    tax: Decimal = Decimal("0")
    buyer_type: str = "consumer"
    activity: str = ""
    source_id: str = ""

    @property
    def gross(self) -> Decimal:
        return self.net + self.tax


@dataclass
class Plan:
    period: str
    included: list[Receipt] = field(default_factory=list)
    excluded: list[tuple[Receipt, str]] = field(default_factory=list)
    due_date: date | None = None
    net: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    total: Decimal = Decimal("0")

    def as_dict(self) -> dict[str, Any]:
        def rec(r: Receipt) -> dict[str, Any]:
            return {
                "number": r.number,
                "date": r.date.isoformat(),
                "net": str(r.net),
                "tax": str(r.tax),
                "gross": str(r.gross),
                "source_id": r.source_id,
            }

        return {
            "period": self.period,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "included": [rec(r) for r in self.included],
            "excluded": [rec(r) | {"reason": reason} for r, reason in self.excluded],
            "count": len(self.included),
            "net": str(self.net),
            "tax": str(self.tax),
            "total": str(self.total),
        }


def receipts_to_fields(receipts: list[Receipt]) -> list[dict[str, str]]:
    """Serialise receipts for a document's country_fields['receipts']."""
    return [
        {
            "number": r.number,
            "date": r.date.isoformat(),
            "net": str(r.net),
            "tax": str(r.tax),
            "buyer_type": r.buyer_type,
            "activity": r.activity,
            "source_id": r.source_id,
        }
        for r in receipts
    ]


def receipts_from_fields(fields: dict[str, Any]) -> list[Receipt]:
    """Read receipts back from country_fields; malformed rows are skipped."""
    out: list[Receipt] = []
    for raw in fields.get("receipts") or []:
        try:
            out.append(
                Receipt(
                    number=str(raw.get("number") or ""),
                    date=date.fromisoformat(str(raw["date"])[:10]),
                    net=Decimal(str(raw.get("net") or "0")),
                    tax=Decimal(str(raw.get("tax") or "0")),
                    buyer_type=str(raw.get("buyer_type") or "consumer"),
                    activity=str(raw.get("activity") or ""),
                    source_id=str(raw.get("source_id") or ""),
                )
            )
        except (KeyError, ValueError, ArithmeticError, AttributeError):
            continue
    return out


def period_bounds(period: str) -> tuple[date, date]:
    """``YYYY-MM`` to first and last day of that month."""
    year, month = (int(part) for part in period.split("-", 1))
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def due_date(period: str, rule: dict[str, Any]) -> date:
    _start, end = period_bounds(period)
    return end + timedelta(days=int(rule.get("due_days_after_period", 0)))


def cap_applies(rule: dict[str, Any], receipt: Receipt, settings: dict[str, Any]) -> bool:
    """Whether the single-transaction cap binds this receipt for this seller."""
    if rule.get("single_transaction_cap") in (None, ""):
        return False
    effective = rule.get("cap_effective_from")
    if effective and receipt.date < date.fromisoformat(effective):
        return False
    relief = rule.get("cap_relief") or {}
    return not (
        relief
        and condition_holds(relief, settings)
        and (not relief.get("until") or receipt.date <= date.fromisoformat(relief["until"]))
    )


def exclusion_reason(
    rule: dict[str, Any], receipt: Receipt, period: str, settings: dict[str, Any], activity: str = ""
) -> str | None:
    start, end = period_bounds(period)
    if not (start <= receipt.date <= end):
        return REASON_OUTSIDE_PERIOD
    allowed = rule.get("allowed_buyer_types")
    if allowed and receipt.buyer_type not in allowed:
        return REASON_BUYER_TYPE
    if (receipt.activity or activity) in set(rule.get("excluded_activities") or ()):
        return REASON_ACTIVITY
    if cap_applies(rule, receipt, settings) and receipt.gross > Decimal(str(rule["single_transaction_cap"])):
        return REASON_OVER_CAP
    return None


def plan(rule: dict[str, Any], receipts: list[Receipt], period: str, settings: dict[str, Any] | None = None) -> Plan:
    """Split receipts into included and excluded (with reason) and total the included ones."""
    settings = settings or {}
    out = Plan(period=period, due_date=due_date(period, rule))
    for receipt in receipts:
        reason = exclusion_reason(rule, receipt, period, settings)
        if reason is None:
            out.included.append(receipt)
        else:
            out.excluded.append((receipt, reason))
    out.net = sum((r.net for r in out.included), Decimal("0")).quantize(_CENT, ROUND_HALF_UP)
    out.tax = sum((r.tax for r in out.included), Decimal("0")).quantize(_CENT, ROUND_HALF_UP)
    out.total = out.net + out.tax
    return out


def check(
    rule: dict[str, Any],
    receipts: list[Receipt],
    period: str,
    *,
    settings: dict[str, Any] | None = None,
    today: date | None = None,
    submitted: bool = False,
) -> list[Finding]:
    """Findings for a consolidated document that already holds these receipts."""
    settings = settings or {}
    start, end = period_bounds(period)
    found: list[Finding] = []
    for receipt in receipts:
        if not (start <= receipt.date <= end):
            found.append(
                Finding(
                    CORE_OUTSIDE_PERIOD,
                    SEV_ERROR,
                    f"Consolidated document includes receipt {receipt.number} outside period {period}.",
                    {"p": period, "no": receipt.number},
                )
            )
        elif cap_applies(rule, receipt, settings) and receipt.gross > Decimal(str(rule["single_transaction_cap"])):
            found.append(
                Finding(
                    str(rule.get("cap_rule_id") or CORE_OUTSIDE_PERIOD),
                    SEV_ERROR,
                    f"Receipt {receipt.number} is {receipt.gross} (over {rule['single_transaction_cap']}); "
                    "issue an individual e-invoice.",
                    {"no": receipt.number, "amt": str(receipt.gross), "cap": str(rule["single_transaction_cap"])},
                )
            )
    due = due_date(period, rule)
    if today is not None and not submitted and today > due and rule.get("due_rule_id"):
        found.append(
            Finding(
                str(rule["due_rule_id"]),
                SEV_ERROR,
                f"Consolidated e-invoice for {period} was due by {due.isoformat()}.",
                {"month": period, "date": due.isoformat()},
            )
        )
    return found


__all__ = [
    "REASON_ACTIVITY",
    "REASON_BUYER_TYPE",
    "REASON_OUTSIDE_PERIOD",
    "REASON_OVER_CAP",
    "Plan",
    "Receipt",
    "cap_applies",
    "check",
    "due_date",
    "period_bounds",
    "plan",
    "receipts_from_fields",
    "receipts_to_fields",
]
