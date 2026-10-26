# DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cash-flow forecast: the pure arithmetic.

A project's cash position is what has been paid and received so far plus what
is still expected to come in and go out, month by month. This module takes
those amounts as plain records and returns the monthly table, the cumulative
net position and the peak funding requirement. It knows nothing about the
database: the collector in :mod:`cashflow_forecast_data` turns contracts,
invoices, orders, subcontracts, field time and guarantees into records.

Three series per month:

* ``planned``: what the documents scheduled for that month, paid or not. It is
  the baseline actuals are compared against.
* ``actual``: cash that moved, by payment date.
* ``expected``: cash still to move. Anything overdue sits in the current month.

The position up to the current month is the actual cash. From the current month
on it adds the expected cash. Every amount stays in its own currency; nothing
here converts or adds two currencies together.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Direction = Literal["in", "out"]

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")

#: Sources a cost overrun scenario scales: estimates, not issued invoices.
OVERRUN_SOURCES: frozenset[str] = frozenset(
    {"purchase_order", "subcontract", "subcontract_retention", "payroll", "plan"}
)

SOURCES_IN: tuple[str, ...] = ("billing", "milestone", "claim", "receivable_invoice", "retention_release", "plan")
SOURCES_OUT: tuple[str, ...] = (
    "payable_invoice",
    "purchase_order",
    "subcontract",
    "subcontract_application",
    "subcontract_retention",
    "payroll",
    "guarantee_fee",
    "plan",
)


def q2(value: Decimal) -> Decimal:
    """Round to cents, half up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def month_end(day: date) -> date:
    nxt = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def months_between(start: date, end: date) -> list[date]:
    """Month ends from ``start``'s month to ``end``'s month, inclusive."""
    if end < start:
        return []
    out: list[date] = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        out.append(month_end(cur))
        cur = month_end(cur) + timedelta(days=1)
    return out


@dataclass(frozen=True)
class CashLine:
    """One amount expected or scheduled to move on ``on``.

    ``planned`` is what the document scheduled; ``open`` the part still to move.
    ``due`` is set on issued documents, for the overdue rule.
    """

    direction: Direction
    source: str
    on: date
    planned: Decimal
    open: Decimal
    currency: str
    ref: str = ""
    label: str = ""
    due: date | None = None


@dataclass(frozen=True)
class ActualLine:
    """Cash that moved."""

    direction: Direction
    on: date
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class Scenario:
    """What-if knobs: receipts later by N days, open costs up by a percentage."""

    receipt_delay_days: int = 0
    cost_overrun_pct: Decimal = ZERO

    @property
    def is_base(self) -> bool:
        return self.receipt_delay_days == 0 and self.cost_overrun_pct == ZERO


@dataclass
class Month:
    period: str
    is_past: bool
    planned_in: Decimal = ZERO
    planned_out: Decimal = ZERO
    actual_in: Decimal = ZERO
    actual_out: Decimal = ZERO
    expected_in: Decimal = ZERO
    expected_out: Decimal = ZERO
    net: Decimal = ZERO
    cumulative: Decimal = ZERO

    @property
    def variance_in(self) -> Decimal:
        return self.actual_in - self.planned_in if self.is_past else ZERO

    @property
    def variance_out(self) -> Decimal:
        return self.actual_out - self.planned_out if self.is_past else ZERO


@dataclass(frozen=True)
class Peak:
    """The lowest cumulative position, as the cash needed to cover it."""

    amount: Decimal
    period: str


@dataclass
class CurrencyForecast:
    currency: str
    months: list[Month] = field(default_factory=list)
    sources: dict[tuple[str, str], Decimal] = field(default_factory=dict)
    closing_position: Decimal = ZERO
    peak: Peak | None = None

    def total(self, name: str) -> Decimal:
        return sum((getattr(m, name) for m in self.months), ZERO)


def apply_scenario(lines: list[CashLine], scenario: Scenario) -> list[CashLine]:
    """Shift open receipts later and scale open estimated costs."""
    if scenario.is_base:
        return list(lines)
    delay = timedelta(days=max(scenario.receipt_delay_days, 0))
    factor = Decimal(1) + scenario.cost_overrun_pct / HUNDRED
    out: list[CashLine] = []
    for line in lines:
        if line.open <= ZERO:
            out.append(line)
        elif line.direction == "in" and delay:
            out.append(replace(line, on=line.on + delay))
        elif line.direction == "out" and line.source in OVERRUN_SOURCES and factor != 1:
            out.append(replace(line, open=q2(line.open * factor)))
        else:
            out.append(line)
    return out


def _peak(months: list[Month]) -> Peak | None:
    low: Month | None = None
    for m in months:
        if m.cumulative < ZERO and (low is None or m.cumulative < low.cumulative):
            low = m
    return Peak(amount=-low.cumulative, period=low.period) if low else None


def build_currency(currency: str, lines: list[CashLine], actuals: list[ActualLine], *, today: date) -> CurrencyForecast:
    """The monthly table of one currency."""
    current = month_key(today)
    buckets: dict[str, Month] = {}

    def bucket(period: str) -> Month:
        if period not in buckets:
            buckets[period] = Month(period=period, is_past=period < current)
        return buckets[period]

    sources: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    bucket(current)
    for line in lines:
        if line.planned:
            m = bucket(month_key(line.on))
            if line.direction == "in":
                m.planned_in += line.planned
            else:
                m.planned_out += line.planned
        if line.open > ZERO:
            m = bucket(max(month_key(line.on), current))
            if line.direction == "in":
                m.expected_in += line.open
            else:
                m.expected_out += line.open
            sources[(line.source, line.direction)] += line.open
    for act in actuals:
        if act.on > today:
            continue
        m = bucket(month_key(act.on))
        if act.direction == "in":
            m.actual_in += act.amount
        else:
            m.actual_out += act.amount

    periods = sorted(buckets)
    # Fill gaps so the chart has a continuous axis.
    if periods:
        first = date(int(periods[0][:4]), int(periods[0][5:]), 1)
        last = date(int(periods[-1][:4]), int(periods[-1][5:]), 1)
        for end in months_between(first, last):
            bucket(month_key(end))
    months = [buckets[p] for p in sorted(buckets)]
    running = ZERO
    for m in months:
        for name in ("planned_in", "planned_out", "actual_in", "actual_out", "expected_in", "expected_out"):
            setattr(m, name, q2(getattr(m, name)))
        if m.is_past:
            m.net = m.actual_in - m.actual_out
        else:
            m.net = m.actual_in - m.actual_out + m.expected_in - m.expected_out
        running += m.net
        m.cumulative = running
    return CurrencyForecast(
        currency=currency,
        months=months,
        sources={k: q2(v) for k, v in sources.items() if v},
        closing_position=running,
        peak=_peak(months),
    )


def build_forecast(
    lines: list[CashLine],
    actuals: list[ActualLine],
    *,
    today: date,
    scenario: Scenario | None = None,
) -> list[CurrencyForecast]:
    """One table per currency, in currency order."""
    lines = apply_scenario(lines, scenario or Scenario())
    by_ccy: dict[str, tuple[list[CashLine], list[ActualLine]]] = defaultdict(lambda: ([], []))
    for line in lines:
        by_ccy[line.currency][0].append(line)
    for act in actuals:
        by_ccy[act.currency][1].append(act)
    return [build_currency(c, ls, acts, today=today) for c, (ls, acts) in sorted(by_ccy.items())]


def aggregate(forecasts: list[CurrencyForecast]) -> CurrencyForecast:
    """Sum the tables of several projects in ONE currency, month by month.

    Raises:
        ValueError: when the tables are in more than one currency.
    """
    currencies = {f.currency for f in forecasts}
    if len(currencies) > 1:
        raise ValueError(f"cannot aggregate across currencies: {sorted(currencies)}")
    currency = next(iter(currencies), "")
    merged: dict[str, Month] = {}
    sources: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    for f in forecasts:
        for m in f.months:
            t = merged.setdefault(m.period, Month(period=m.period, is_past=m.is_past))
            for name in ("planned_in", "planned_out", "actual_in", "actual_out", "expected_in", "expected_out", "net"):
                setattr(t, name, getattr(t, name) + getattr(m, name))
        for k, v in f.sources.items():
            sources[k] += v
    months = [merged[p] for p in sorted(merged)]
    running = ZERO
    for m in months:
        running += m.net
        m.cumulative = running
    return CurrencyForecast(
        currency=currency, months=months, sources=dict(sources), closing_position=running, peak=_peak(months)
    )


def spread(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split ``total`` by ``weights`` in cents; the last share takes the rounding."""
    if not weights:
        return []
    wsum = sum(weights, ZERO)
    if wsum <= ZERO:
        weights = [Decimal(1)] * len(weights)
        wsum = Decimal(len(weights))
    shares = [q2(total * w / wsum) for w in weights[:-1]]
    shares.append(q2(total) - sum(shares, ZERO))
    return shares


def parse_terms_days(value: object, default: int = 30) -> int:
    """Days from text such as ``"30"``, ``"Net 45"`` or ``"60 days"``; ``default`` when none."""
    if isinstance(value, int) and not isinstance(value, bool):
        return max(value, 0)
    digits = ""
    for ch in str(value or ""):
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else default
