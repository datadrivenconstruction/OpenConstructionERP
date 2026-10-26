# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ schedule arithmetic: percentage of completion, cost-to-cost (DB-free, float-free).

One row of a WIP schedule is worked out from five inputs, all exact Decimals:

* ``contract_value``  - client contract value plus approved change orders;
* ``estimated_cost``  - estimated total cost at completion (EAC);
* ``cost_to_date``    - cost incurred to date, accruals included;
* ``billed_to_date``  - gross amount invoiced to the client to date;
* ``previous_gross_profit`` - projected gross profit at the previous close, if any.

From them:

* ``percent_complete`` = cost_to_date / estimated_cost (cost-to-cost), capped at 100 for
  earned revenue; the raw figure is kept so a rule can flag it;
* ``earned_revenue``   = percent_complete x contract_value;
* ``over_billing``     = billed - earned when positive (billings in excess of costs and
  estimated earnings, a liability); ``under_billing`` = earned - billed when positive (an asset);
* ``projected_gross_profit`` = contract_value - estimated_cost;
* ``fade`` = projected_gross_profit - previous_gross_profit (negative is fade, positive gain);
* ``backlog`` = contract_value - earned_revenue (revenue still to earn).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")
HUNDRED = Decimal("100")
_CENTS = Decimal("0.01")
_PCT = Decimal("0.0001")

#: A period-on-period fade above this share of contract value is "large" (rule default).
DEFAULT_FADE_THRESHOLD_PCT = Decimal("2")


def dec(value: Any, default: Decimal = ZERO) -> Decimal:
    """Coerce *value* to Decimal through ``str`` (never through a float), *default* on bad input."""
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        value = repr(value)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def q2(value: Decimal) -> Decimal:
    """Money to two places, half-up."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class WipInputs:
    """The five inputs of one WIP row."""

    contract_value: Decimal
    estimated_cost: Decimal
    cost_to_date: Decimal
    billed_to_date: Decimal
    previous_gross_profit: Decimal | None = None


@dataclass(frozen=True)
class WipFigures:
    """The computed WIP row, every amount a 2dp Decimal and percentages to 2dp."""

    contract_value: Decimal
    estimated_cost: Decimal
    cost_to_date: Decimal
    cost_to_complete: Decimal
    percent_complete: Decimal
    percent_complete_raw: Decimal
    earned_revenue: Decimal
    billed_to_date: Decimal
    over_billing: Decimal
    under_billing: Decimal
    projected_gross_profit: Decimal
    projected_margin_pct: Decimal
    gross_profit_to_date: Decimal
    previous_gross_profit: Decimal | None
    fade: Decimal | None
    backlog: Decimal
    loss_job: bool
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Plain dict for schemas, snapshots and the validation context."""
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def compute(inputs: WipInputs) -> WipFigures:
    """Work out one WIP row from its inputs (see the module docstring for the formulas)."""
    contract = inputs.contract_value
    eac = inputs.estimated_cost
    ctd = inputs.cost_to_date
    billed = inputs.billed_to_date

    raw = (ctd / eac * HUNDRED) if eac > 0 else (HUNDRED if ctd > 0 else ZERO)
    pct = min(max(raw, ZERO), HUNDRED)
    earned = contract * pct / HUNDRED
    diff = billed - earned
    gp = contract - eac
    margin = (gp / contract * HUNDRED) if contract > 0 else ZERO
    prev = inputs.previous_gross_profit
    fade = q2(gp - prev) if prev is not None else None

    flags: list[str] = []
    if eac <= 0 and ctd > 0:
        flags.append("no_estimate")
    if eac > 0 and eac < ctd:
        flags.append("eac_below_cost_to_date")
    if raw > HUNDRED:
        flags.append("percent_over_100")
    if contract > 0 and billed > contract:
        flags.append("billed_exceeds_contract")
    if gp < 0:
        flags.append("loss_job")

    return WipFigures(
        contract_value=q2(contract),
        estimated_cost=q2(eac),
        cost_to_date=q2(ctd),
        cost_to_complete=q2(max(eac - ctd, ZERO)),
        percent_complete=pct.quantize(_PCT, rounding=ROUND_HALF_UP).quantize(_CENTS, rounding=ROUND_HALF_UP),
        percent_complete_raw=raw.quantize(_CENTS, rounding=ROUND_HALF_UP),
        earned_revenue=q2(earned),
        billed_to_date=q2(billed),
        over_billing=q2(diff) if diff > 0 else q2(ZERO),
        under_billing=q2(-diff) if diff < 0 else q2(ZERO),
        projected_gross_profit=q2(gp),
        projected_margin_pct=margin.quantize(_CENTS, rounding=ROUND_HALF_UP),
        gross_profit_to_date=q2(earned - ctd),
        previous_gross_profit=q2(prev) if prev is not None else None,
        fade=fade,
        backlog=q2(max(contract - earned, ZERO)),
        loss_job=gp < 0,
        flags=flags,
    )


def is_large_fade(fade: Decimal | None, contract_value: Decimal, threshold_pct: Decimal) -> bool:
    """A fade (negative change in projected gross profit) larger than *threshold_pct* of contract value."""
    if fade is None or fade >= 0 or contract_value <= 0:
        return False
    return -fade / contract_value * HUNDRED > threshold_pct


_TOTAL_KEYS = (
    "contract_value",
    "estimated_cost",
    "cost_to_date",
    "cost_to_complete",
    "earned_revenue",
    "billed_to_date",
    "over_billing",
    "under_billing",
    "projected_gross_profit",
    "backlog",
)


def totals_by_currency(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sum portfolio rows per currency; amounts in different currencies are never added together."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        ccy = str(row.get("currency") or "")
        bucket = out.setdefault(ccy, {"currency": ccy, "projects": 0, **dict.fromkeys(_TOTAL_KEYS, ZERO), "fade": ZERO})
        bucket["projects"] += 1
        for key in _TOTAL_KEYS:
            bucket[key] += dec(row.get(key))
        bucket["fade"] += dec(row.get("fade"))
    result = []
    for ccy in sorted(out):
        b = out[ccy]
        for key in (*_TOTAL_KEYS, "fade"):
            b[key] = q2(b[key])
        b["percent_complete"] = (
            (b["earned_revenue"] / b["contract_value"] * HUNDRED).quantize(_CENTS, rounding=ROUND_HALF_UP)
            if b["contract_value"] > 0
            else q2(ZERO)
        )
        result.append(b)
    return result


def month_end(period: str) -> Any:
    """Last calendar day of a ``YYYY-MM`` period."""
    import calendar
    from datetime import date

    year, month = (int(p) for p in period.split("-", 1))
    return date(year, month, calendar.monthrange(year, month)[1])


def valid_period(period: str) -> bool:
    """``YYYY-MM`` with a real month."""
    if len(period) != 7 or period[4] != "-":
        return False
    try:
        year, month = int(period[:4]), int(period[5:])
    except ValueError:
        return False
    return 1900 < year < 3000 and 1 <= month <= 12
