# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ rules of the guarantees register: vocabulary, lifecycle, reductions, alerts, exposure.

Nothing here touches the database, so every decision the service makes about a
guarantee (may it move to this status, what is it worth after the advance recovered
so far, which expiry alert is due, how much of a bank credit line is used) can be
tested from plain values.

The vocabulary is neutral on purpose. FIDIC 2017 Sub-Clause 4.2 (Performance
Security) and 14.2 (Advance Payment guarantee) and the usual GCC practice are the
reference points, but national guarantee forms come from country packs, never from here.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

ZERO = Decimal("0")

GUARANTEE_TYPES: tuple[str, ...] = (
    "bid_bond",
    "performance_bond",
    "advance_payment",
    "retention_bond",
    "warranty_bond",
    "parent_company",
)
STATUSES: tuple[str, ...] = (
    "draft",
    "requested",
    "issued",
    "extended",
    "reduced",
    "released",
    "called",
    "expired",
)
# "given": the company is the applicant and a bank issues the guarantee to a client.
# "received": a subcontractor or supplier provides it and the company is the beneficiary.
DIRECTIONS: tuple[str, ...] = ("given", "received")
# A guarantee in one of these statuses is a live liability of the issuing bank.
LIVE_STATUSES: frozenset[str] = frozenset({"issued", "extended", "reduced"})
CLOSED_STATUSES: frozenset[str] = frozenset({"released", "called", "expired"})
ALERT_THRESHOLDS: tuple[int, ...] = (60, 30, 14)

TRANSITIONS: Mapping[str, frozenset[str]] = {
    "draft": frozenset({"requested", "issued"}),
    "requested": frozenset({"draft", "issued"}),
    "issued": frozenset({"extended", "reduced", "released", "called", "expired"}),
    "extended": frozenset({"extended", "reduced", "released", "called", "expired"}),
    "reduced": frozenset({"extended", "reduced", "released", "called", "expired"}),
    "released": frozenset(),
    "called": frozenset(),
    "expired": frozenset({"extended"}),
}

AUDIT_ACTIONS: tuple[str, ...] = (
    "created",
    "updated",
    "status_changed",
    "extended",
    "reduced",
    "released",
    "called",
    "document_linked",
    "document_unlinked",
)

# Contract security status each register status projects onto (contracts keeps
# its own vocabulary; the register is the only writer of linked rows).
CONTRACT_SECURITY_STATUS: Mapping[str, str] = {
    "draft": "required",
    "requested": "required",
    "issued": "active",
    "extended": "active",
    "reduced": "active",
    "released": "released",
    "called": "claimed",
    "expired": "expired",
}
# Contract security types that are bank guarantees or bonds and therefore live in
# the register. Insurance lines stay on the contract.
CONTRACT_SECURITY_TYPE_MAP: Mapping[str, str] = {
    "performance_bond": "performance_bond",
    "payment_bond": "performance_bond",
    "advance_payment_bond": "advance_payment",
    "retention_bond": "retention_bond",
    "parent_company_guarantee": "parent_company",
    "bank_guarantee": "performance_bond",
}
REGISTER_TO_SECURITY_TYPE: Mapping[str, str] = {
    "bid_bond": "bank_guarantee",
    "performance_bond": "performance_bond",
    "advance_payment": "advance_payment_bond",
    "retention_bond": "retention_bond",
    "warranty_bond": "bank_guarantee",
    "parent_company": "parent_company_guarantee",
}


def can_transition(current: str, target: str) -> bool:
    """Whether a guarantee may move from ``current`` to ``target``."""
    return target in TRANSITIONS.get(current, frozenset())


def is_live(status: str | None) -> bool:
    """Whether the status counts as an outstanding bank liability."""
    return (status or "") in LIVE_STATUSES


def add_months(start: date, months: int) -> date:
    """``start`` plus whole calendar months, clamped to the last day of the month."""
    total = start.month - 1 + months
    year, month = start.year + total // 12, total % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def days_to_expiry(expiry: date | None, as_of: date) -> int | None:
    """Whole days from ``as_of`` to ``expiry`` (negative once passed), or ``None``."""
    return None if expiry is None else (expiry - as_of).days


def alert_band(days_left: int | None) -> int | None:
    """The tightest threshold (60, 30, 14) the guarantee has entered, or ``None``."""
    if days_left is None or days_left < 0:
        return None
    band = None
    for threshold in ALERT_THRESHOLDS:
        if days_left <= threshold:
            band = threshold
    return band


def outstanding_advance(advance_amount: Decimal | None, recovered: Decimal | None) -> Decimal:
    """Advance still to be recovered through interim payments, never below zero."""
    advance = advance_amount or ZERO
    return max(advance - (recovered or ZERO), ZERO)


def reduced_advance_amount(
    original_amount: Decimal, advance_amount: Decimal | None, recovered: Decimal | None
) -> Decimal:
    """The advance guarantee value after recoveries (FIDIC 14.2: reduced by the amount repaid).

    The guarantee never needs to exceed the advance still outstanding, and a recovery
    never raises it above its original face value.
    """
    if advance_amount is None or advance_amount <= ZERO:
        return original_amount
    return min(original_amount, outstanding_advance(advance_amount, recovered))


def expected_amount(contract_value: Decimal | None, percent: Decimal | None) -> Decimal | None:
    """Face value the contract percentage implies, or ``None`` when either side is missing."""
    if contract_value is None or percent is None or contract_value <= ZERO:
        return None
    return (contract_value * percent / Decimal("100")).quantize(Decimal("0.01"))


def amount_matches_percent(
    amount: Decimal,
    contract_value: Decimal | None,
    percent: Decimal | None,
    tolerance: Decimal = Decimal("0.005"),
) -> bool | None:
    """Whether ``amount`` agrees with the percentage of contract value (0.5 percent tolerance)."""
    expected = expected_amount(contract_value, percent)
    if expected is None:
        return None
    return abs(amount - expected) <= max(Decimal("0.01"), expected * tolerance)


def required_until(contract_completion: date | None, defects_months: int | None) -> date | None:
    """The date a performance or warranty security must outlive: completion plus the defects period."""
    if contract_completion is None:
        return None
    return add_months(contract_completion, defects_months or 0)


def commission_for(amount: Decimal, annual_rate_pct: Decimal | None, days: int) -> Decimal:
    """Bank commission for ``days`` at an annual percentage rate on ``amount`` (actual/365)."""
    if not annual_rate_pct or days <= 0:
        return ZERO
    return (amount * annual_rate_pct / Decimal("100") * Decimal(days) / Decimal("365")).quantize(Decimal("0.01"))


def parse_date(value: Any) -> date | None:
    """Coerce a date, an ISO string or a timestamp string to a date, else ``None``."""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class ExposureRow:
    """The few facts the exposure rollup needs from one guarantee."""

    guarantee_type: str
    status: str
    direction: str
    issuer_bank: str
    currency: str
    amount: Decimal
    facility_id: str | None = None


def _bucket(totals: dict[tuple[str, str], Decimal], key: tuple[str, str], amount: Decimal) -> None:
    totals[key] = totals.get(key, ZERO) + amount


def exposure(rows: Iterable[ExposureRow], facilities: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Company exposure: live amounts by bank and by type, and the credit lines they use.

    Amounts are summed per currency and never converted, because adding two
    currencies without a stated rate gives a number nobody can sign. Only guarantees
    the company gave count against its banks; ones it received are reported
    separately as security held.
    """
    by_bank: dict[tuple[str, str], Decimal] = {}
    by_type: dict[tuple[str, str], Decimal] = {}
    by_facility: dict[str, Decimal] = {}
    held: dict[tuple[str, str], Decimal] = {}
    totals: dict[str, Decimal] = {}
    live_count = 0
    for row in rows:
        if not is_live(row.status):
            continue
        live_count += 1
        if row.direction == "received":
            _bucket(held, (row.guarantee_type, row.currency), row.amount)
            continue
        _bucket(by_bank, (row.issuer_bank or "", row.currency), row.amount)
        _bucket(by_type, (row.guarantee_type, row.currency), row.amount)
        totals[row.currency] = totals.get(row.currency, ZERO) + row.amount
        if row.facility_id:
            by_facility[row.facility_id] = by_facility.get(row.facility_id, ZERO) + row.amount
    lines = []
    for facility in facilities:
        fid = str(facility["id"])
        limit = Decimal(str(facility.get("limit_amount") or 0))
        used = by_facility.get(fid, ZERO)
        lines.append(
            {
                "facility_id": fid,
                "bank_name": facility.get("bank_name", ""),
                "currency": facility.get("currency", ""),
                "limit_amount": limit,
                "used_amount": used,
                "available_amount": limit - used,
                "utilisation_pct": (used / limit * Decimal("100")).quantize(Decimal("0.1")) if limit > ZERO else None,
            }
        )
    return {
        "live_count": live_count,
        "totals": [{"currency": c, "amount": a} for c, a in sorted(totals.items())],
        "by_bank": [{"bank": b, "currency": c, "amount": a} for (b, c), a in sorted(by_bank.items())],
        "by_type": [{"guarantee_type": t, "currency": c, "amount": a} for (t, c), a in sorted(by_type.items())],
        "held": [{"guarantee_type": t, "currency": c, "amount": a} for (t, c), a in sorted(held.items())],
        "credit_lines": lines,
    }
