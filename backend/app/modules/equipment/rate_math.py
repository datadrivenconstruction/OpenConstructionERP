# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure Decimal math for internal plant rates (owning cost per month, day and hour).

No framework, ORM or I/O here. Every input is a ``Decimal`` (or coerced to one), no float
touches the pipeline, and the only rounding step is half-up to two decimals on the FINAL
rate, so the intermediate depreciation, interest and repair terms keep full precision.

Model (straight-line ownership cost, per operating month)::

    D = (P - Rv) / (n * v)                        depreciation
    I = (P + Rv) / 2 * i / v                      interest, convention ``average_value``
    I = ((P - Rv) * (n + 1) / (2 * n) + Rv) * i / v    convention ``average_annual_investment``
    R = P * r / (n * v)                           repair
    M = D + I + R                                 monthly internal rate
    H = M / h                                     hourly rate
    daily = M / working_days_per_month            only when that setting is given

``P`` value, ``Rv`` residual, ``n`` life in years, ``v`` operating months per year,
``i`` interest per year and ``r`` repair over life as a fraction of ``P``, ``h`` hours per
month. No national value is defaulted: the caller supplies every one of them.

Sources: straight-line and average-investment conventions from engineering-economy texts,
for example Peurifoy et al., Construction Planning, Equipment, and Methods (equipment cost
chapter); US Army Corps of Engineers EP 1110-1-8 uses the same ownership-cost building blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

AVERAGE_VALUE = "average_value"
AVERAGE_ANNUAL_INVESTMENT = "average_annual_investment"
CONVENTIONS: tuple[str, ...] = (AVERAGE_VALUE, AVERAGE_ANNUAL_INVESTMENT)

_CENTS = Decimal("0.01")
_ZERO = Decimal("0")
_TWO = Decimal("2")


class RateInputError(ValueError):
    """An input the formula cannot use (missing, not a number, or out of range)."""


def to_decimal(value: object) -> Decimal | None:
    """A finite ``Decimal`` from ``value``, or ``None`` when it is empty or not a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        out = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            out = Decimal(text)
        except InvalidOperation:
            return None
    return out if out.is_finite() else None


def money(value: Decimal) -> Decimal:
    """Round half-up to two decimals (the only rounding step)."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RateInputs:
    """The formula inputs of one machine."""

    value: Decimal
    residual: Decimal
    life_years: Decimal
    months_per_year: Decimal
    interest: Decimal
    repair: Decimal
    hours_per_month: Decimal | None = None


@dataclass(frozen=True)
class RateResult:
    """Unrounded building blocks and the rounded rates."""

    depreciation: Decimal
    interest: Decimal
    repair: Decimal
    monthly_raw: Decimal
    monthly: Decimal
    hourly: Decimal | None
    daily: Decimal | None


def depreciation_per_month(p: Decimal, rv: Decimal, n: Decimal, v: Decimal) -> Decimal:
    """``D = (P - Rv) / (n * v)``."""
    return (p - rv) / (n * v)


def interest_per_month(
    p: Decimal, rv: Decimal, n: Decimal, v: Decimal, i: Decimal, convention: str = AVERAGE_VALUE
) -> Decimal:
    """Monthly interest on the capital tied up, by convention."""
    if convention == AVERAGE_ANNUAL_INVESTMENT:
        base = (p - rv) * (n + 1) / (_TWO * n) + rv
    elif convention == AVERAGE_VALUE:
        base = (p + rv) / _TWO
    else:
        raise RateInputError(f"unknown interest convention {convention!r}")
    return base * i / v


def repair_per_month(p: Decimal, r: Decimal, n: Decimal, v: Decimal) -> Decimal:
    """``R = P * r / (n * v)``."""
    return p * r / (n * v)


def compute_rate(
    inputs: RateInputs,
    *,
    convention: str = AVERAGE_VALUE,
    working_days_per_month: Decimal | None = None,
) -> RateResult:
    """Monthly, hourly and (when the setting is given) daily rate of one machine.

    Raises :class:`RateInputError` for a life or operating-months value that makes the
    formula meaningless; the validation rules report the same conditions with messages.
    """
    n, v = inputs.life_years, inputs.months_per_year
    if n <= 0:
        raise RateInputError("life must be greater than 0")
    if not (Decimal(1) <= v <= Decimal(12)):
        raise RateInputError("operating months per year must be between 1 and 12")
    d = depreciation_per_month(inputs.value, inputs.residual, n, v)
    i = interest_per_month(inputs.value, inputs.residual, n, v, inputs.interest, convention)
    r = repair_per_month(inputs.value, inputs.repair, n, v)
    m = d + i + r
    h = inputs.hours_per_month
    hourly = money(m / h) if h is not None and h > 0 else None
    wd = working_days_per_month
    daily = money(m / wd) if wd is not None and wd > 0 else None
    return RateResult(d, i, r, m, money(m), hourly, daily)


def monthly_charge(
    *,
    hourly_rate: Decimal,
    operational_hours: Decimal,
    standby_hours: Decimal = _ZERO,
    breakdown_hours: Decimal = _ZERO,
    standby_factor: Decimal | None = None,
    breakdown_factor: Decimal | None = None,
    operating_cost_per_hour: Decimal | None = None,
) -> dict[str, Decimal]:
    """Charge for logged hours at the (already rounded) hourly rate.

    Standby and breakdown hours bill only when their factor is set; an empty factor means
    those hours are not charged. Operating cost per hour (fuel, wear parts) applies to
    operational hours only. Each line is rounded half-up to two decimals.
    """
    operational = money(operational_hours * hourly_rate)
    standby = money(standby_hours * hourly_rate * standby_factor) if standby_factor is not None else _ZERO
    breakdown = money(breakdown_hours * hourly_rate * breakdown_factor) if breakdown_factor is not None else _ZERO
    operating = money(operational_hours * operating_cost_per_hour) if operating_cost_per_hour is not None else _ZERO
    return {
        "operational": operational,
        "standby": standby,
        "breakdown": breakdown,
        "operating_cost": operating,
        "total": operational + standby + breakdown + operating,
    }
