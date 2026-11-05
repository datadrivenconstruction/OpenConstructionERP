# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Haul​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ ticket arithmetic, status machine and invoice reconciliation.

Pure functions only (no session), so the numbers a site manager signs off can
be tested on their own. Money and weights are ``Decimal`` throughout.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")
MONEY_Q = Decimal("0.01")
QTY_Q = Decimal("0.001")

HAUL_TYPES = ("earthworks", "aggregates", "concrete", "asphalt", "waste", "other")
LOCATION_KINDS = ("quarry", "plant", "site", "dump", "other")
UNITS = ("t", "m3", "load")
RATE_BASES = ("t", "m3", "load", "hour")
STATUSES = ("issued", "loaded", "delivered", "verified", "invoiced", "rejected")

# Forward moves a ticket may make; any open ticket may also be rejected, and a
# rejected one reopened as issued. Invoiced is final.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "issued": ("loaded", "delivered", "rejected"),
    "loaded": ("delivered", "rejected"),
    "delivered": ("verified", "rejected"),
    "verified": ("invoiced", "delivered", "rejected"),
    "invoiced": (),
    "rejected": ("issued",),
}
COUNTED_STATUSES = ("verified", "invoiced")

# Fields a project may declare mandatory (per-project setting).
MANDATORY_CANDIDATES = (
    "ticket_number",
    "time_out",
    "time_in",
    "origin",
    "destination",
    "material_code",
    "plate",
    "driver_name",
    "haulier_name",
    "cost_code",
    "boq_position_id",
    "po_id",
    "rate",
    "receiver_name",
    "photos",
)

# Neutral built-in material list. Codes are stable identifiers; the screen
# translates the names by code.
DEFAULT_MATERIALS: tuple[dict[str, Any], ...] = (
    {"code": "topsoil", "name": "Topsoil", "unit": "m3", "haul_type": "earthworks", "density_t_m3": "1.4"},
    {
        "code": "excavated_soil",
        "name": "Excavated soil",
        "unit": "m3",
        "haul_type": "earthworks",
        "density_t_m3": "1.8",
    },
    {"code": "fill_sand", "name": "Fill sand", "unit": "t", "haul_type": "aggregates", "density_t_m3": "1.6"},
    {"code": "gravel", "name": "Gravel", "unit": "t", "haul_type": "aggregates", "density_t_m3": "1.7"},
    {"code": "crushed_stone", "name": "Crushed stone", "unit": "t", "haul_type": "aggregates", "density_t_m3": "1.6"},
    {"code": "subbase", "name": "Sub-base aggregate", "unit": "t", "haul_type": "aggregates", "density_t_m3": "2.1"},
    {"code": "ready_mix", "name": "Ready-mix concrete", "unit": "m3", "haul_type": "concrete", "density_t_m3": "2.4"},
    {"code": "asphalt", "name": "Asphalt mix", "unit": "t", "haul_type": "asphalt", "density_t_m3": "2.35"},
    {"code": "spoil_inert", "name": "Inert spoil", "unit": "t", "haul_type": "waste", "density_t_m3": "1.8"},
    {"code": "mixed_cd_waste", "name": "Mixed construction waste", "unit": "t", "haul_type": "waste"},
    {"code": "hazardous_waste", "name": "Hazardous waste", "unit": "t", "haul_type": "waste"},
)


def dec(value: Any) -> Decimal | None:
    """Parse a number (str, int, float, Decimal) or return None; accepts a comma decimal."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "," in text:
        text = text.replace(",", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


# ── weights ────────────────────────────────────────────────────────────────


@dataclass
class Weights:
    gross: Decimal | None
    tare: Decimal | None
    net: Decimal | None
    consistent: bool


def resolve_weights(gross: Any, tare: Any, net: Any, *, tolerance: Decimal = Decimal("0.02")) -> Weights:
    """Fill the missing one of gross, tare and net, and check the three agree.

    Two of three are enough: net = gross - tare. With all three given they must
    agree within ``tolerance`` tonnes; a negative net is never consistent.
    """
    g, t, n = dec(gross), dec(tare), dec(net)
    if g is not None and t is not None and n is None:
        n = (g - t).quantize(QTY_Q)
    elif g is not None and n is not None and t is None:
        t = (g - n).quantize(QTY_Q)
    elif t is not None and n is not None and g is None:
        g = (t + n).quantize(QTY_Q)
    consistent = True
    if g is not None and t is not None and n is not None:
        consistent = abs((g - t) - n) <= tolerance and n >= ZERO and t >= ZERO
    elif n is not None and n < ZERO:
        consistent = False
    return Weights(g, t, n, consistent)


def quantity_in_unit(
    unit: str, *, net_t: Decimal | None, volume_m3: Decimal | None, loads: int, density: Decimal | None = None
) -> Decimal:
    """The ticket quantity in its own unit; tonnes and cubic metres convert by density when one is missing."""
    if unit == "load":
        return Decimal(max(loads or 0, 0))
    if unit == "m3":
        if volume_m3 is not None:
            return volume_m3.quantize(QTY_Q)
        if net_t is not None and density:
            return (net_t / density).quantize(QTY_Q)
        return ZERO
    if net_t is not None:
        return net_t.quantize(QTY_Q)
    if volume_m3 is not None and density:
        return (volume_m3 * density).quantize(QTY_Q)
    return ZERO


def billable_quantity(
    basis: str, *, net_t: Decimal | None, volume_m3: Decimal | None, loads: int, hours: Decimal | None
) -> Decimal:
    """Quantity the rate applies to for the given rate basis."""
    if basis == "t":
        return net_t or ZERO
    if basis == "m3":
        return volume_m3 or ZERO
    if basis == "hour":
        return hours or ZERO
    return Decimal(max(loads or 0, 0))


def amount(rate: Decimal | None, qty: Decimal) -> Decimal:
    if rate is None:
        return ZERO
    return (rate * qty).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, ())


# ── waste catalogues (hook for country packs) ──────────────────────────────

WasteCatalogue = Callable[[], list[dict[str, Any]]]
_WASTE_CATALOGUES: dict[str, tuple[str, WasteCatalogue]] = {}


def _generic_catalogue() -> list[dict[str, Any]]:
    return [
        {"code": "INERT", "name": "Inert waste", "hazardous": False},
        {"code": "NON_HAZ", "name": "Non-hazardous waste", "hazardous": False},
        {"code": "HAZ", "name": "Hazardous waste", "hazardous": True},
    ]


def register_waste_catalogue(key: str, label: str, provider: WasteCatalogue) -> None:
    """Register a waste code catalogue. Country packs call this; the platform ships only a generic one."""
    _WASTE_CATALOGUES[key] = (label, provider)


def waste_catalogues() -> dict[str, tuple[str, WasteCatalogue]]:
    return {"generic": ("Generic", _generic_catalogue), **_WASTE_CATALOGUES}


def waste_entry(catalogue: str, code: str) -> dict[str, Any] | None:
    entry = waste_catalogues().get(catalogue or "generic")
    if entry is None or not code:
        return None
    return next((e for e in entry[1]() if str(e.get("code")) == code), None)


# ── invoice reconciliation ─────────────────────────────────────────────────


@dataclass
class ReconLine:
    index: int
    ticket_number: str
    status: str  # matched | missing_ticket | overpriced | quantity_mismatch | duplicate_line
    ticket_id: str | None = None
    invoiced_amount: Decimal = ZERO
    expected_amount: Decimal = ZERO
    message: str = ""


@dataclass
class ReconResult:
    lines: list[ReconLine] = field(default_factory=list)
    extra_tickets: list[dict[str, Any]] = field(default_factory=list)
    invoiced_total: Decimal = ZERO
    expected_total: Decimal = ZERO

    @property
    def difference(self) -> Decimal:
        return (self.invoiced_total - self.expected_total).quantize(MONEY_Q)

    @property
    def clean(self) -> bool:
        return not self.extra_tickets and all(line.status == "matched" for line in self.lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "lines": [
                {
                    "index": r.index,
                    "ticket_number": r.ticket_number,
                    "status": r.status,
                    "ticket_id": r.ticket_id,
                    "invoiced_amount": str(r.invoiced_amount),
                    "expected_amount": str(r.expected_amount),
                    "message": r.message,
                }
                for r in self.lines
            ],
            "extra_tickets": self.extra_tickets,
            "invoiced_total": str(self.invoiced_total),
            "expected_total": str(self.expected_total),
            "difference": str(self.difference),
            "clean": self.clean,
        }


def _norm_number(value: Any) -> str:
    return str(value or "").strip().upper().lstrip("0") or "0"


def reconcile(
    lines: Iterable[dict[str, Any]],
    tickets: Iterable[dict[str, Any]],
    *,
    price_tolerance_pct: Decimal = Decimal("1"),
    qty_tolerance: Decimal = Decimal("0.05"),
) -> ReconResult:
    """Match invoice lines to tickets by ticket number.

    ``tickets`` are this haulier's tickets in the invoice period, each a dict with
    ``id``, ``ticket_number``, ``status``, ``quantity`` (billable), ``rate`` and
    ``amount``. A line with no ticket is ``missing_ticket``; a verified ticket no
    line names is an extra (not invoiced); a line priced above the ticket by more
    than the tolerance is ``overpriced``; a rejected ticket invoiced is flagged too.
    """
    by_number: dict[str, dict[str, Any]] = {}
    for t in tickets:
        by_number.setdefault(_norm_number(t.get("ticket_number")), t)
    result = ResultBuilder(by_number, price_tolerance_pct, qty_tolerance)
    for idx, line in enumerate(lines):
        result.add(idx, line)
    return result.finish()


class ResultBuilder:
    def __init__(self, by_number: dict[str, dict[str, Any]], price_pct: Decimal, qty_tol: Decimal) -> None:
        self.by_number = by_number
        self.price_pct = price_pct
        self.qty_tol = qty_tol
        self.seen: set[str] = set()
        self.out = ReconResult()

    def add(self, idx: int, line: dict[str, Any]) -> None:
        number = str(line.get("ticket_number") or "").strip()
        key = _norm_number(number)
        qty = dec(line.get("quantity"))
        rate = dec(line.get("rate"))
        invoiced = dec(line.get("amount"))
        if invoiced is None:
            invoiced = amount(rate, qty or ZERO)
        self.out.invoiced_total += invoiced
        row = ReconLine(index=idx, ticket_number=number, status="matched", invoiced_amount=invoiced)
        ticket = self.by_number.get(key) if number else None
        if ticket is None:
            row.status = "missing_ticket"
            row.message = "No ticket with this number for this haulier."
        elif key in self.seen:
            row.status = "duplicate_line"
            row.ticket_id = str(ticket.get("id"))
            row.message = "The ticket is invoiced twice."
        else:
            self.seen.add(key)
            row.ticket_id = str(ticket.get("id"))
            expected = dec(ticket.get("amount")) or ZERO
            row.expected_amount = expected
            self.out.expected_total += expected
            t_qty = dec(ticket.get("quantity")) or ZERO
            t_rate = dec(ticket.get("rate"))
            if ticket.get("status") == "rejected":
                row.status = "rejected_ticket"
                row.message = "The ticket was rejected on site."
            elif qty is not None and abs(qty - t_qty) > self.qty_tol:
                row.status = "quantity_mismatch"
                row.message = f"Invoiced {qty}, ticket {t_qty}."
            elif invoiced > expected * (1 + self.price_pct / 100) + MONEY_Q or (
                rate is not None and t_rate is not None and rate > t_rate * (1 + self.price_pct / 100)
            ):
                row.status = "overpriced"
                row.message = f"Invoiced {invoiced}, expected {expected}."
        self.out.lines.append(row)

    def finish(self) -> ReconResult:
        for key, t in self.by_number.items():
            if key not in self.seen and t.get("status") in COUNTED_STATUSES and not t.get("invoice_id"):
                self.out.extra_tickets.append(
                    {
                        "ticket_id": str(t.get("id")),
                        "ticket_number": t.get("ticket_number"),
                        "amount": str(t.get("amount")),
                    }
                )
        self.out.invoiced_total = self.out.invoiced_total.quantize(MONEY_Q)
        self.out.expected_total = self.out.expected_total.quantize(MONEY_Q)
        return self.out
