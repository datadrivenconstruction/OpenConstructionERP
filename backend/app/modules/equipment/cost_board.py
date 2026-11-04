# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plant cost board maths: owning vs operating cost per machine against used hours.

Pure functions, no database. ``TelematicsService`` gathers the facts and calls
:func:`build_row`.

* Owning cost: straight-line depreciation over the useful life, limited to the
  days the machine was owned inside the window, plus the monthly holding cost.
  For rented and leased units the holding cost is the rent and there is no
  depreciation.
* Operating cost: fuel and maintenance booked inside the window.
* Used hours are telematics worked hours; billed hours are the working days on
  which the machine was hired out to a project (hire cost booked) times the
  working-day length.
* Suggestion: ``keep``, ``return`` (rented-in unit that stands idle), ``rent``
  (owned unit whose cost per used hour exceeds the market hire rate), ``review``
  (the facts cannot support a call) or ``no_data``. ``reason`` is a stable code
  the client renders in the user's language.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

_ZERO = Decimal("0")
_DAYS_PER_YEAR = Decimal("365.25")
_CENT = Decimal("0.01")
DEFAULT_DAY_HOURS = Decimal("8")
DEFAULT_MIN_UTILISATION_PCT = Decimal("40")


@dataclass(frozen=True)
class MachineFacts:
    """Everything the board needs for one machine over one window."""

    equipment_id: str
    code: str
    name: str
    ownership: str
    currency: str
    purchase_date: date | None
    purchase_value: Decimal | None
    residual_value: Decimal | None
    useful_life_years: int | None
    holding_cost_per_month: Decimal | None
    market_hire_rate_per_day: Decimal | None
    telemetry_days: int
    worked_hours: Decimal
    idle_hours: Decimal
    billed_days: int
    hire_cost: Decimal
    fuel_cost: Decimal
    maintenance_cost: Decimal
    currency_mismatch: bool = False


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENT)


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    if whole <= 0:
        return None
    return (part / whole * 100).quantize(Decimal("0.1"))


def depreciation_days(
    date_from: date, date_to: date, purchase_date: date | None, useful_life_years: int | None
) -> Decimal:
    """Days of the window inside the machine's depreciation period."""
    start = date_from
    end = date_to
    if purchase_date is not None:
        start = max(start, purchase_date)
        if useful_life_years:
            life_end = purchase_date + timedelta(days=int(Decimal(useful_life_years) * _DAYS_PER_YEAR))
            end = min(end, life_end - timedelta(days=1))
    if end < start:
        return _ZERO
    return Decimal((end - start).days + 1)


def owning_cost(f: MachineFacts, date_from: date, date_to: date) -> Decimal:
    """Owning (or renting) cost of the machine over the window."""
    window_days = Decimal((date_to - date_from).days + 1)
    total = _ZERO
    if f.ownership == "owned" and f.purchase_value is not None and f.useful_life_years:
        base = max(f.purchase_value - (f.residual_value or _ZERO), _ZERO)
        per_day = base / (Decimal(f.useful_life_years) * _DAYS_PER_YEAR)
        total += per_day * depreciation_days(date_from, date_to, f.purchase_date, f.useful_life_years)
    if f.holding_cost_per_month is not None:
        held = window_days
        if f.ownership == "owned" and f.purchase_date is not None:
            held = Decimal(max((date_to - max(date_from, f.purchase_date)).days + 1, 0))
        total += f.holding_cost_per_month * 12 / _DAYS_PER_YEAR * held
    return total


def owning_cost_known(f: MachineFacts) -> bool:
    if f.holding_cost_per_month is not None:
        return True
    return f.ownership == "owned" and f.purchase_value is not None and bool(f.useful_life_years)


def suggest(
    f: MachineFacts,
    utilisation_pct: Decimal | None,
    cost_per_used_hour: Decimal | None,
    market_hour_rate: Decimal | None,
    min_utilisation_pct: Decimal,
) -> tuple[str, str]:
    """(action, reason code) for one machine."""
    if f.currency_mismatch:
        return "review", "currency_mismatch"
    if f.telemetry_days == 0:
        return "no_data", "no_telemetry"
    if not owning_cost_known(f):
        return "review", "ownership_cost_unknown"
    util = utilisation_pct or _ZERO
    low = util < min_utilisation_pct
    if f.ownership != "owned":
        return ("return", "underused_rented") if low else ("keep", "well_used")
    if market_hour_rate is not None:
        if f.worked_hours <= 0 or (cost_per_used_hour is not None and cost_per_used_hour > market_hour_rate):
            return "rent", "cost_above_market"
        return "keep", "below_market" if low else "well_used"
    return ("review", "underused_no_rate") if low else ("keep", "well_used")


def build_row(
    f: MachineFacts,
    date_from: date,
    date_to: date,
    day_hours: Decimal = DEFAULT_DAY_HOURS,
    min_utilisation_pct: Decimal = DEFAULT_MIN_UTILISATION_PCT,
) -> dict[str, object]:
    """One board row; money and hours as strings, ratios as strings or None."""
    window_days = (date_to - date_from).days + 1
    available = day_hours * window_days
    owning = _q(owning_cost(f, date_from, date_to))
    operating = _q(f.fuel_cost + f.maintenance_cost)
    total = owning + operating
    engine = f.worked_hours + f.idle_hours
    utilisation = _pct(min(f.worked_hours, available), available)
    cost_per_hour = _q(total / f.worked_hours) if f.worked_hours > 0 else None
    market_hour = _q(f.market_hire_rate_per_day / day_hours) if f.market_hire_rate_per_day is not None else None
    action, reason = suggest(f, utilisation, cost_per_hour, market_hour, min_utilisation_pct)
    billed_hours = day_hours * f.billed_days
    s = lambda v: None if v is None else str(v)  # noqa: E731
    return {
        "equipment_id": f.equipment_id,
        "code": f.code,
        "name": f.name,
        "ownership": f.ownership,
        "currency": f.currency,
        "owning_cost": str(owning),
        "fuel_cost": str(_q(f.fuel_cost)),
        "maintenance_cost": str(_q(f.maintenance_cost)),
        "operating_cost": str(operating),
        "total_cost": str(total),
        "used_hours": str(f.worked_hours),
        "billed_hours": str(billed_hours),
        "idle_hours": str(f.idle_hours),
        "idle_pct": s(_pct(f.idle_hours, engine)),
        "utilisation_pct": s(utilisation),
        "cost_per_used_hour": s(cost_per_hour),
        "market_hour_rate": s(market_hour),
        "hire_cost": str(_q(f.hire_cost)),
        "recovery_pct": s(_pct(f.hire_cost, total)),
        "ownership_cost_known": owning_cost_known(f),
        "currency_mismatch": f.currency_mismatch,
        "suggestion": action,
        "reason": reason,
        "min_utilisation_pct": str(min_utilisation_pct),
    }
