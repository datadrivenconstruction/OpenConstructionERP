# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory late payment in commercial transactions: dated interest, term caps, recovery compensation.

Country-neutral engine over ``country_data/late_payment.json``. A country row
states the statute, the reference rate it hangs the interest on and the day
that rate is fixed, the margin per kind of debtor, the reference rate in force
per period, the longest payment term the statute allows per kind of debtor,
and the fixed recovery compensation tiers. Every figure carries its source,
its dates and a confidence.

The interest rate is the reference rate of the period plus the margin of the
debtor kind. Periods are data. A day outside every listed period has no
known rate, and the engine says so instead of carrying the nearest period
forward or back: a rate guessed for a past half-year is a wrong amount on a
claim, and one guessed for a future half-year is a rate nobody has published.

``app.modules.payment_clock`` holds the notice regime of the same statutes
(which day is the final date); this module prices what happens after it.

Standard library only. Nothing here may import from ``app.modules``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "DATA_PATH",
    "DEBTOR_KINDS",
    "RATE_FIXINGS",
    "InterestPeriod",
    "LateInterest",
    "late_interest",
    "margin_percent",
    "payment_term_cap_days",
    "rate_unknown_reason",
    "agreed_rate_floor_percent",
    "rate_fixing",
    "recovery_compensation",
    "statutory_late_interest_rate",
    "term_exceeds_cap",
    "validate_rows",
]

DATA_PATH = Path(__file__).resolve().parent / "country_data" / "late_payment.json"

#: Who owes the money. ``public`` is a public entity under the statute's
#: public-debtor article; ``public_medical`` the public medical entities some
#: statutes treat apart.
DEBTOR_KINDS: tuple[str, ...] = ("commercial", "public", "public_medical")

#: How a margin row prices a delay that spans several reference-rate periods.
#: ``per_period``: each day takes the rate of the period it falls in.
#: ``at_delay_start``: the rate fixed on the first day of the half-year in which
#: the delay started is held for the whole delay.
RATE_FIXINGS: tuple[str, ...] = ("per_period", "at_delay_start")

_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)
_DAYS_IN_YEAR = Decimal(365)
_CONFIDENCES = ("H", "M")


@dataclass(frozen=True)
class InterestPeriod:
    """Days of a delay that share one rate, and the interest they earn."""

    start: date
    end: date
    days: int
    rate_percent: Decimal
    interest: Decimal


@dataclass(frozen=True)
class LateInterest:
    """Interest on one late payment, split by rate period.

    ``unknown_days`` are delay days with no known rate; they are not priced,
    so ``complete`` is false and ``interest`` is a lower bound.
    """

    principal: Decimal
    periods: tuple[InterestPeriod, ...]
    unknown_days: int
    interest: Decimal

    @property
    def complete(self) -> bool:
        return self.unknown_days == 0


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _country(country: str) -> dict[str, Any] | None:
    return _load()["countries"].get((country or "").strip().upper())


def _kind(debtor_kind: str) -> str:
    if debtor_kind not in DEBTOR_KINDS:
        raise ValueError(f"unknown debtor kind {debtor_kind!r}; expected one of {DEBTOR_KINDS}")
    return debtor_kind


def _day(raw: str | None) -> date | None:
    return date.fromisoformat(raw) if raw else None


def _covers(row: dict[str, Any], on: date) -> bool:
    start = _day(row.get("effective_from"))
    end = _day(row.get("effective_to"))
    return (start is None or start <= on) and (end is None or on <= end)


def _margin_row(country: str, debtor_kind: str, on: date) -> dict[str, Any] | None:
    data = _country(country)
    kind = _kind(debtor_kind)
    if data is None:
        return None
    return next((r for r in data.get("margins", []) if r["debtor_kind"] == kind and _covers(r, on)), None)


def margin_percent(country: str, debtor_kind: str, on: date) -> Decimal | None:
    """Points over the reference rate for ``debtor_kind`` on ``on``, or ``None``."""
    row = _margin_row(country, debtor_kind, on)
    return Decimal(row["margin_percent"]) if row else None


def rate_fixing(country: str, debtor_kind: str, on: date) -> str:
    """``per_period`` (default) or ``at_delay_start`` for the margin row in force on ``on``."""
    row = _margin_row(country, debtor_kind, on)
    return (row or {}).get("rate_fixing", "per_period")


def _half_year_start(on: date) -> date:
    return date(on.year, 1 if on.month <= 6 else 7, 1)


def _period(data: dict[str, Any], on: date) -> dict[str, Any] | None:
    return next((p for p in data.get("reference_rate_periods", []) if _covers(p, on)), None)


def _pricing_day(country: str, debtor_kind: str, on: date, delay_start: date | None) -> date:
    """The day whose margin and reference rate price ``on``."""
    if delay_start is not None and rate_fixing(country, debtor_kind, delay_start) == "at_delay_start":
        return _half_year_start(delay_start)
    return on


def rate_unknown_reason(country: str, debtor_kind: str, on: date, delay_start: date | None = None) -> str | None:
    """Why there is no rate on ``on``, or ``None`` when there is one."""
    data = _country(country)
    kind = _kind(debtor_kind)
    if data is None:
        return "no_country_data"
    day = _pricing_day(country, kind, on, delay_start)
    if margin_percent(country, kind, day) is None:
        return "no_margin_for_debtor_kind"
    if _period(data, day) is None:
        return "no_reference_rate_period"
    return None


def statutory_late_interest_rate(
    country: str, debtor_kind: str, on: date, delay_start: date | None = None
) -> Decimal | None:
    """Annual statutory late interest in percent on ``on``, or ``None`` when not known.

    The reference rate of the period holding ``on`` plus the debtor kind's
    margin. Never extrapolated: see :func:`rate_unknown_reason`. When the
    margin row says ``at_delay_start`` and ``delay_start`` is given, the rate
    of the half-year in which the delay started applies to ``on`` as well.
    """
    if rate_unknown_reason(country, debtor_kind, on, delay_start) is not None:
        return None
    data = _country(country)
    assert data is not None
    day = _pricing_day(country, debtor_kind, on, delay_start)
    period = _period(data, day)
    margin = margin_percent(country, debtor_kind, day)
    assert period is not None and margin is not None
    return Decimal(period["reference_rate_percent"]) + margin


def late_interest(
    country: str,
    debtor_kind: str,
    principal: Decimal,
    due_date: date,
    paid_date: date,
) -> LateInterest:
    """Simple interest, actual/365, from the day after ``due_date`` to ``paid_date`` inclusive.

    Consecutive days at the same rate form one period; each period's interest
    is rounded to the cent and the total is their sum.
    """
    _kind(debtor_kind)
    periods: list[InterestPeriod] = []
    unknown = 0
    run: tuple[date, date, Decimal] | None = None

    def close(current: tuple[date, date, Decimal] | None) -> None:
        if current is None:
            return
        start, end, rate = current
        days = (end - start).days + 1
        amount = (principal * rate / _HUNDRED * Decimal(days) / _DAYS_IN_YEAR).quantize(_CENT, ROUND_HALF_UP)
        periods.append(InterestPeriod(start, end, days, rate, amount))

    delay_start = due_date + timedelta(days=1)
    day = delay_start
    while day <= paid_date:
        rate = statutory_late_interest_rate(country, debtor_kind, day, delay_start)
        if rate is None:
            unknown += 1
            close(run)
            run = None
        elif run is not None and run[2] == rate and run[1] + timedelta(days=1) == day:
            run = (run[0], day, rate)
        else:
            close(run)
            run = (day, day, rate)
        day += timedelta(days=1)
    close(run)
    total = sum((p.interest for p in periods), Decimal("0")).quantize(_CENT)
    return LateInterest(principal=principal, periods=tuple(periods), unknown_days=unknown, interest=total)


def agreed_rate_floor_percent(country: str, debtor_kind: str, on: date) -> Decimal | None:
    """Lowest contract late-interest rate the statute allows on ``on``, or ``None``.

    Data: ``agreed_rate_floor`` holds a multiple of the legal interest rate
    (``legal_interest_rates`` periods). ``None`` when the country has no floor
    for that debtor kind or no legal rate is known for ``on``.
    """
    data = _country(country)
    kind = _kind(debtor_kind)
    floor = (data or {}).get("agreed_rate_floor")
    if not floor or kind not in floor.get("debtor_kinds", []):
        return None
    period = next((p for p in data.get("legal_interest_rates", []) if _covers(p, on)), None)
    if period is None:
        return None
    return Decimal(floor["multiple_of_legal_rate"]) * Decimal(period["rate_percent"])


def _in_tier(tier: dict[str, Any], claim: Decimal) -> bool:
    lower, upper = tier.get("lower_pln"), tier.get("upper_pln")
    if lower is not None:
        bound = Decimal(lower)
        if claim < bound or (claim == bound and not tier.get("lower_inclusive")):
            return False
    if upper is not None:
        bound = Decimal(upper)
        if claim > bound or (claim == bound and not tier.get("upper_inclusive")):
            return False
    return True


def recovery_compensation(country: str, claim_amount: Decimal, *, eur_rate: Decimal) -> tuple[Decimal, Decimal] | None:
    """Fixed recovery compensation for a claim: ``(amount in the tier currency, amount in local currency)``.

    ``eur_rate`` is the conversion rate the statute names (for Poland, the NBP
    average euro rate of the last business day of the month before the month
    the payment fell due). It is an input; nothing is fetched. ``None`` when
    the country has no tiers.
    """
    data = _country(country)
    if data is None or not data.get("recovery_compensation"):
        return None
    for tier in data["recovery_compensation"]["tiers"]:
        if _in_tier(tier, claim_amount):
            amount = Decimal(tier["amount"])
            return amount, (amount * eur_rate).quantize(_CENT, ROUND_HALF_UP)
    return None


def payment_term_cap_days(country: str, debtor_kind: str, on: date | None = None) -> int | None:
    """The longest payment term the statute allows for ``debtor_kind``, or ``None``."""
    data = _country(country)
    kind = _kind(debtor_kind)
    if data is None:
        return None
    on = on or date.today()
    for row in data.get("term_caps", []):
        if row["debtor_kind"] == kind and _covers(row, on):
            return int(row["max_days"])
    return None


def term_exceeds_cap(country: str, debtor_kind: str, term_days: int, on: date | None = None) -> bool:
    """Whether ``term_days`` is longer than the statutory cap. No cap known means no."""
    cap = payment_term_cap_days(country, debtor_kind, on)
    return cap is not None and term_days > cap


def _dated_problems(where: str, row: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if not row.get("source_url"):
        problems.append(f"{where}: no source_url")
    if row.get("confidence") not in _CONFIDENCES:
        problems.append(f"{where}: confidence must be one of {_CONFIDENCES}")
    if "effective_from" not in row:
        problems.append(f"{where}: no effective_from")
    else:
        start, end = _day(row.get("effective_from")), _day(row.get("effective_to"))
        if start is not None and end is not None and end < start:
            problems.append(f"{where}: effective_to before effective_from")
    return problems


def validate_rows(data: dict[str, Any] | None = None) -> list[str]:
    """Problems in the catalogue, empty when it is sound.

    Every dated row has a source, a confidence and an effective_from; periods
    of one country do not overlap; a published rate stated beside a period
    equals that period's reference rate plus the margin in force on its first
    day; recovery tiers do not overlap.
    """
    data = data if data is not None else _load()
    problems: list[str] = []
    for code, country in data.get("countries", {}).items():
        for i, row in enumerate(country.get("margins", [])):
            problems += _dated_problems(f"{code}.margins[{i}]", row)
            if row.get("rate_fixing", "per_period") not in RATE_FIXINGS:
                problems.append(f"{code}.margins[{i}]: unknown rate_fixing {row.get('rate_fixing')!r}")
            if row.get("debtor_kind") not in DEBTOR_KINDS:
                problems.append(f"{code}.margins[{i}]: unknown debtor kind {row.get('debtor_kind')!r}")
        for i, row in enumerate(country.get("legal_interest_rates", [])):
            problems += _dated_problems(f"{code}.legal_interest_rates[{i}]", row)
        for i, row in enumerate(country.get("term_caps", [])):
            problems += _dated_problems(f"{code}.term_caps[{i}]", row)
        periods = sorted(country.get("reference_rate_periods", []), key=lambda p: p.get("effective_from") or "")
        for i, row in enumerate(periods):
            problems += _dated_problems(f"{code}.reference_rate_periods[{i}]", row)
            if not row.get("effective_to"):
                problems.append(f"{code}.reference_rate_periods[{i}]: a rate period must end")
            if i and periods[i - 1].get("effective_to") and row.get("effective_from"):
                if _day(row["effective_from"]) <= _day(periods[i - 1]["effective_to"]):  # type: ignore[operator]
                    problems.append(f"{code}.reference_rate_periods[{i}]: overlaps the period before it")
            start = _day(row.get("effective_from"))
            for kind, published in (row.get("published_rates") or {}).items():
                margin = next(
                    (
                        Decimal(m["margin_percent"])
                        for m in country.get("margins", [])
                        if m.get("debtor_kind") == kind and start is not None and _covers(m, start)
                    ),
                    None,
                )
                expected = Decimal(row["reference_rate_percent"]) + margin if margin is not None else None
                if expected is None or Decimal(published) != expected:
                    problems.append(
                        f"{code}.reference_rate_periods[{i}]: published {kind} rate {published} is not "
                        f"reference plus margin ({expected})"
                    )
        compensation = country.get("recovery_compensation")
        if compensation:
            problems += _dated_problems(f"{code}.recovery_compensation", compensation)
            probes = [Decimal(t[k]) for t in compensation["tiers"] for k in ("lower_pln", "upper_pln") if t.get(k)]
            for probe in {p + d for p in probes for d in (Decimal("-0.01"), Decimal(0), Decimal("0.01"))}:
                hits = sum(1 for t in compensation["tiers"] if _in_tier(t, probe))
                if hits != 1:
                    problems.append(f"{code}.recovery_compensation: {hits} tiers match {probe}")
    return problems
