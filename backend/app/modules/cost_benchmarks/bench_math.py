# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Benchmark​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ arithmetic: normalisation, element grouping, percentile bands, outliers.

Pure and Decimal-only. A completed project's final cost is brought to one basis
before it is compared with anything:

``normalised = amount x index(base date) / index(cost date)
              x location(base region) / location(project region)
              x fx(reporting currency) / fx(project currency)``

The index ratio and the location ratio reuse :mod:`app.modules.price_index.index_math`.
Exchange quotes are units per one unit of the rate set's base currency, the shape the
fx register stores. A band is P10, P50 and P90 of the normalised cost per m2 GFA (or
per functional unit) by linear interpolation (:func:`app.core.stats.percentile`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.core.stats import percentile
from app.modules.price_index.index_math import location_multiplier, period_for_date, quantize_factor

MONEY_Q = Decimal("0.01")
FUNCTIONAL_UNITS: tuple[str, ...] = ("bed", "seat", "parking_space", "km", "dwelling", "pupil", "room")
STANDARDS: tuple[str, ...] = ("din276", "nrm1", "masterformat", "uniformat")
DEFAULT_MIN_PROJECTS = 5
DEFAULT_STALE_MONTHS = 12


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def element_group(standard: str, code: str) -> str:
    """The element group a classification code rolls up to for benchmarking.

    DIN 276 second level (``331`` -> ``330``), NRM 1 group element (``2.5.1`` -> ``2.5``),
    MasterFormat division (``03 30 00`` -> ``03``), Uniformat level 2 (``B2010`` -> ``B20``).
    """
    raw = (code or "").strip()
    if not raw:
        return ""
    std = (standard or "").lower()
    if std.startswith("din"):
        digits = "".join(ch for ch in raw if ch.isdigit())
        return f"{digits[:2]}0" if len(digits) >= 2 else digits
    if std.startswith("nrm"):
        parts = [p for p in raw.replace(" ", "").split(".") if p]
        return ".".join(parts[:2])
    if std == "masterformat":
        digits = "".join(ch for ch in raw if ch.isdigit())
        return digits[:2]
    if std == "uniformat":
        return raw.replace(" ", "")[:3].upper()
    return raw


def period_value(points: Mapping[str, Decimal], target: str) -> tuple[str, Decimal] | None:
    """The latest point at or before ``target`` (``YYYY-MM``), else the earliest point."""
    if not points:
        return None
    keys = sorted(points)
    earlier = [k for k in keys if k <= target]
    key = earlier[-1] if earlier else keys[0]
    return key, Decimal(points[key])


def months_between(a: str, b: str) -> int:
    """Whole months from period ``a`` to period ``b`` (both ``YYYY-MM``)."""
    ay, am = int(a[:4]), int(a[5:7])
    by, bm = int(b[:4]), int(b[5:7])
    return (by - ay) * 12 + (bm - am)


@dataclass(frozen=True)
class Basis:
    """The single basis every amount is brought to."""

    base_date: date
    base_region: str | None
    reporting_currency: str
    index_points: Mapping[str, Decimal]
    region_factors: Mapping[str, Decimal]
    fx_quotes: Mapping[str, Decimal]
    fx_base: str = "EUR"
    stale_months: int = DEFAULT_STALE_MONTHS


@dataclass(frozen=True)
class Factors:
    temporal: Decimal
    location: Decimal
    fx: Decimal
    index_period_used: str | None
    stale: bool
    missing_fx: bool

    @property
    def combined(self) -> Decimal:
        return self.temporal * self.location * self.fx


def fx_factor(quotes: Mapping[str, Decimal], fx_base: str, source: str, target: str) -> Decimal | None:
    """Multiplier from ``source`` to ``target`` currency, or ``None`` if a quote is missing."""
    src, tgt = (source or "").upper(), (target or "").upper()
    if not src or not tgt or src == tgt:
        return Decimal("1")
    table = {k.upper(): Decimal(v) for k, v in quotes.items()}
    table.setdefault(fx_base.upper(), Decimal("1"))
    if src not in table or tgt not in table or table[src] <= 0:
        return None
    return table[tgt] / table[src]


def factors_for(basis: Basis, *, cost_date: date, region: str | None, currency: str) -> Factors:
    """Temporal, location and currency multipliers for one amount."""
    base_p, target_p = period_for_date(cost_date), period_for_date(basis.base_date)
    temporal = Decimal("1")
    used: str | None = None
    stale = False
    if basis.index_points:
        src, tgt = period_value(basis.index_points, base_p), period_value(basis.index_points, target_p)
        if src and tgt and src[1] > 0:
            temporal = quantize_factor(tgt[1] / src[1])
            used = tgt[0]
            latest = max(basis.index_points)
            stale = (
                months_between(tgt[0], target_p) > basis.stale_months
                or months_between(src[0], base_p) > basis.stale_months
                or months_between(latest, target_p) > basis.stale_months
            )
    else:
        stale = True
    location = location_multiplier(basis.region_factors, region, basis.base_region)
    fx = fx_factor(basis.fx_quotes, basis.fx_base, currency, basis.reporting_currency)
    return Factors(temporal, location, fx if fx is not None else Decimal("1"), used, stale, fx is None)


def normalise(amount: Decimal, f: Factors) -> Decimal:
    return money(Decimal(amount) * f.combined)


@dataclass(frozen=True)
class Band:
    count: int
    p10: Decimal | None
    p50: Decimal | None
    p90: Decimal | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "p10": None if self.p10 is None else str(money(self.p10)),
            "p50": None if self.p50 is None else str(money(self.p50)),
            "p90": None if self.p90 is None else str(money(self.p90)),
        }


def band(values: Iterable[Decimal]) -> Band:
    ordered: Sequence[Decimal] = sorted(Decimal(v) for v in values)
    return Band(len(ordered), percentile(ordered, 10), percentile(ordered, 50), percentile(ordered, 90))


def position(value: Decimal | None, b: Band) -> str:
    """``below`` P10, ``within`` the band, ``above`` P90, or ``unknown``."""
    if value is None or b.p10 is None or b.p90 is None:
        return "unknown"
    if value < b.p10:
        return "below"
    if value > b.p90:
        return "above"
    return "within"


def per_unit(amount: Decimal, quantity: Decimal | None) -> Decimal | None:
    if quantity is None or quantity <= 0:
        return None
    return money(Decimal(amount) / Decimal(quantity))


def gfa_bucket(gfa: Decimal | None) -> str:
    """Coarse size class for the anonymised export, so no project is recognisable by its area."""
    if gfa is None or gfa <= 0:
        return "unknown"
    for upper in (1000, 2500, 5000, 10000, 25000, 50000):
        if gfa < upper:
            return f"<{upper}"
    return ">=50000"
