# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contract price adjustment by weighted cost indices. One engine, regimes as data.

Many construction contracts adjust their price for changes in cost by a
weighted index formula. The forms look different and are the same thing:

* the classic indexation formula of a standard form,
  ``Pn = a + b * Ln/Lo + c * En/Eo + d * Mn/Mo`` with ``a + b + c + d = 1``,
  where ``a`` is the fixed, non-adjustable part, so the adjustment is
  ``V * (Pn - 1)``;
* Egypt's public works formula (Executive Regulations of Law 182/2018,
  Art. 97): ``V * sum(c_i * (I_i,t - I_i,0) / I_i,0)``, the coefficients
  stated by the contractor in the technical envelope, each above zero and
  together below one;
* France's revision coefficient (CCAG-Travaux 2021, art. 10.5),
  ``C = a + sum(b_i * I_i / I0_i)`` applied monthly, which the regime rounds
  up to the thousandth before it is applied (``coefficient_rounding``).

Expanding the first gives the second: ``a + sum(b_i * I_n/I_o) - 1`` equals
``sum(b_i * (I_n - I_o) / I_o)`` once ``a = 1 - sum(b_i)``. So one function,
:func:`compute_adjustment`, serves both, and what differs between laws lives
in :data:`PRICE_ADJUSTMENT_REGIMES`: how often the price is adjusted, which
contracts qualify, what the coefficients must satisfy, from which date the
indices run, who publishes them and how long settlement may take.

Index values are not shipped. They change every month and belong to the
tenant: a company keeps each published index as a cost-index series in the
``price_index`` module, and the endpoint reads the point of each period from
there, so the platform holds one store of index numbers.

Rounding: each item's amount ``V * c * change`` is rounded to 0.01 with
``ROUND_HALF_UP`` and the total is the sum of those rounded amounts, so every
printed figure adds up. Change ratios are carried exactly.

Pure Decimal math; no ORM, no I/O, no ``float``.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

MONEY_QUANTUM = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")

#: What the coefficients of a regime must satisfy.
#: ``positive_sum_below_one``: each above zero, their sum strictly below one
#: (a fixed part always remains). ``non_negative_sum_at_most_one``: each zero
#: or more, their sum at most one (a contract may index all of its price).
COEFFICIENT_RULES: tuple[str, ...] = ("positive_sum_below_one", "non_negative_sum_at_most_one")

#: The regimes, keyed by code. Every figure carries its source.
PRICE_ADJUSTMENT_REGIMES: dict[str, dict[str, Any]] = {
    "eg_law182_art97": {
        "code": "eg_law182_art97",
        "country_code": "EG",
        "jurisdiction": "Egypt (public works)",
        "statute": "Public Contracts Law No. 182 of 2018, Art. 47; Executive Regulations (Decree 692/2019), Art. 97",
        "source_url": "https://eg.andersen.com/wp-content/uploads/2026/01/Law-No.-182-of-2018.pdf",
        "read_date": "2026-10-19",
        "effective_date": None,
        "mandatory": True,
        "period_months": 3,
        "min_duration_months": 6,
        "coefficient_rule": "positive_sum_below_one",
        "base_date": "technical_envelope_opening",
        "index_publisher": "CAPMAS Producer Price Index bulletins",
        "variable_items_list": "Ministry of Housing list of variable items",
        "settlement_days": 60,
        "note": (
            "Works contracts of six months or more are adjusted at the end of every three contractual months "
            "from the opening of the technical envelopes (or the contracting date of a direct award), for the "
            "increase or decrease in the cost of the variable items. The contractor states the coefficients in "
            "the technical envelope; a bid without them is excluded and an agreement to the contrary is void. "
            "The certificate is paid at contract prices without waiting for the adjustment, which is settled "
            "within 60 days of the claim. Contracts under six months are not adjusted; where the delay is the "
            "entity's, quantities executed after six months are compensated by the CAPMAS inflation rate."
        ),
    },
    "fr_ccag_travaux_2021_art_10_5": {
        "code": "fr_ccag_travaux_2021_art_10_5",
        "country_code": "FR",
        "jurisdiction": "France (public works)",
        "statute": (
            "CCAG-Travaux 2021 (arrêté du 30 mars 2021), art. 10.5; Code de la commande publique, art. R2112-13 "
            "and R2112-14"
        ),
        "source_url": "https://www.economie.gouv.fr/daj/cahiers-clauses-administratives-generales-et-techniques",
        "read_date": "2026-10-19",
        "effective_date": "2021-04-01",
        "mandatory": False,
        "period_months": 1,
        "min_duration_months": 3,
        "coefficient_rule": "non_negative_sum_at_most_one",
        "coefficient_rounding": {"quantum": "0.001", "direction": "up"},
        "base_date": "offer_date",
        "index_publisher": "INSEE BT (building) and TP (public works) indices, base 2010",
        "variable_items_list": None,
        "settlement_days": None,
        "note": (
            "A revisable price is revised each month on the work done in the month by C = a + sum(b x I/I0), "
            "where a is the optional fixed part, I0 the index of the month of the (final) offer and I the index "
            "of the month the work was done. The CCAG rounds C up to the thousandth. A contract longer than three "
            "months whose costs depend substantially on raw materials must carry such a clause (R2112-13, "
            "R2112-14); since 2021 the CCAG no longer falls back to BT01 or TP01 when the contract names no "
            "index. Index values are provisional at first and definitive later; both come from the tenant's "
            "price index series."
        ),
    },
    "contract_indexation": {
        "code": "contract_indexation",
        "country_code": None,
        "jurisdiction": "Any (as the contract states)",
        "statute": "The contract's own indexation clause, for example FIDIC Red Book 1999 Sub-Clause 13.8",
        "source_url": None,
        "read_date": None,
        "effective_date": None,
        "mandatory": False,
        "period_months": None,
        "min_duration_months": None,
        "coefficient_rule": "non_negative_sum_at_most_one",
        "base_date": "contract_base_date",
        "index_publisher": None,
        "variable_items_list": None,
        "settlement_days": None,
        "note": (
            "The weighted index formula of a contract that agrees one: the coefficients and indices the "
            "contract names, adjusted in the payment periods it sets. The fixed part is one minus the sum of "
            "the coefficients."
        ),
    },
}


#: Price adjustment by a threshold test instead of a formula. Some laws do not
#: index the price; they compensate a material price movement only when it
#: crosses a threshold on the item and on the contract, up to a cap, through a
#: claim a committee decides. :func:`assess_trigger_claim` answers whether a
#: claim crosses both thresholds and how much of it the cap lets through. No
#: amount is computed from indices: the committee decides the movement.
PRICE_ADJUSTMENT_TRIGGERS: dict[str, dict[str, Any]] = {
    "sa_gtpl_ir113": {
        "code": "sa_gtpl_ir113",
        "country_code": "SA",
        "jurisdiction": "Saudi Arabia (public works, tenders under the 2019 law)",
        "statute": "Implementing Regulations of the Government Tenders and Procurement Law (2019), Art. 113",
        "source_url": "https://mof.gov.sa/en/Knowledgecenter/newGovTendandProcLow/Documents/Executive%20Regulations.pdf",
        "read_date": "2026-10-19",
        "effective_date": "2020-04-24",
        "materials": ["cement", "steel", "asphalt", "ready_mix_concrete", "timber", "pipes", "cables"],
        "material_change_min_percent": "10",
        "contract_change_above_percent": "3",
        "compensation_cap_percent_of_contract": "20",
        "claim_days": 60,
        "consultant_days": 21,
        "agency_days": 45,
        "committee_days": 45,
        "index_publisher": "Official price indexes; the series the Ministry of Finance accepts is not confirmed",
        "needs_expert_review": True,
        "note": (
            "A listed raw material whose price moves by ten percent or more on the official indexes, and a "
            "resulting change in the contract cost of more than three percent of its value, not caused by the "
            "contractor's delay, entitle the contractor to compensation, and a fall is deducted the same way. "
            "Changes in customs duties, fees, taxes and officially priced items after the bid date are "
            "compensated separately. The claim is made within 60 days of the event; the consultant has 21 days, "
            "the agency 45 and the committee 45. Compensation is capped at twenty percent of the contract value, "
            "the rest goes to the Administrative Court. Fixed profit margin contracts are excluded. The English "
            'text reads "five percent (3%)" for the contract threshold: the figure in brackets is used here '
            "until the Arabic text is checked. A Ministry of Finance decision reported in September 2026 may "
            "have replaced the article; it was not read."
        ),
    },
}


def trigger_for(code: str | None) -> dict[str, Any] | None:
    """The trigger row for ``code``, or ``None``."""
    return PRICE_ADJUSTMENT_TRIGGERS.get((code or "").strip())


class PriceAdjustmentError(ValueError):
    """The inputs cannot produce an adjustment. ``problem`` names why, for a translated message."""

    def __init__(self, problem: str, message: str, **params: Any) -> None:
        self.problem = problem
        self.params = params
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class AdjustmentItem:
    """One variable item of the formula, as computed."""

    item: str
    coefficient: Decimal
    base_index: Decimal
    current_index: Decimal
    change: Decimal
    amount: Decimal

    def as_dict(self) -> dict[str, str]:
        return {
            "item": self.item,
            "coefficient": str(self.coefficient),
            "base_index": str(self.base_index),
            "current_index": str(self.current_index),
            "change": str(self.change),
            "amount": str(self.amount),
        }


@dataclass(frozen=True, slots=True)
class AdjustmentResult:
    """The adjustment for one settlement: positive is owed to the contractor, negative is deducted."""

    regime: str
    value_subject: Decimal
    fixed_portion: Decimal
    items: tuple[AdjustmentItem, ...] = field(default_factory=tuple)
    total: Decimal = ZERO
    #: Only for a regime that rounds its coefficient (France): the rounded
    #: ``a + sum(b x I/I0)``, and what the rounding added to the items' sum,
    #: so the printed figures still add up to the total.
    revision_coefficient: Decimal | None = None
    rounding_amount: Decimal | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "regime": self.regime,
            "value_subject": str(self.value_subject),
            "fixed_portion": str(self.fixed_portion),
            "items": [i.as_dict() for i in self.items],
            "total": str(self.total),
        }
        if self.revision_coefficient is not None:
            out["revision_coefficient"] = str(self.revision_coefficient)
            out["rounding_amount"] = str(self.rounding_amount)
        return out


def regime_for(code: str | None) -> dict[str, Any] | None:
    """The regime row for ``code``, or ``None``."""
    return PRICE_ADJUSTMENT_REGIMES.get((code or "").strip())


def _decimal(raw: Any, name: str) -> Decimal:
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise PriceAdjustmentError("not_a_number", f"{name} is not a number: {raw!r}", name=name) from exc
    if not value.is_finite():
        raise PriceAdjustmentError("not_a_number", f"{name} is not a finite number", name=name)
    return value


def coefficient_problems(regime: dict[str, Any], coefficients: list[tuple[str, Any]]) -> list[dict[str, str]]:
    """Everything wrong with a coefficient set under ``regime``, as ``{problem, item}`` entries.

    An empty list means the set is valid. Problems: ``no_coefficients``,
    ``duplicate_item``, ``coefficient_not_a_number``,
    ``coefficient_not_positive``, ``coefficient_negative``,
    ``coefficient_sum_not_below_one``, ``coefficient_sum_above_one``.
    """
    rule = regime.get("coefficient_rule")
    if rule not in COEFFICIENT_RULES:
        raise ValueError(f"regime {regime.get('code')!r} has an unknown coefficient rule {rule!r}")
    if not coefficients:
        return [{"problem": "no_coefficients", "item": ""}]
    problems: list[dict[str, str]] = []
    seen: set[str] = set()
    total = ZERO
    for item, raw in coefficients:
        key = str(item or "").strip()
        if key.lower() in seen:
            problems.append({"problem": "duplicate_item", "item": key})
        seen.add(key.lower())
        try:
            value = _decimal(raw, f"coefficient of {key}")
        except PriceAdjustmentError:
            problems.append({"problem": "coefficient_not_a_number", "item": key})
            continue
        total += value
        if rule == "positive_sum_below_one" and value <= ZERO:
            problems.append({"problem": "coefficient_not_positive", "item": key})
        elif rule == "non_negative_sum_at_most_one" and value < ZERO:
            problems.append({"problem": "coefficient_negative", "item": key})
    if rule == "positive_sum_below_one" and total >= ONE:
        problems.append({"problem": "coefficient_sum_not_below_one", "item": str(total)})
    elif rule == "non_negative_sum_at_most_one" and total > ONE:
        problems.append({"problem": "coefficient_sum_above_one", "item": str(total)})
    return problems


def compute_adjustment(
    regime_code: str,
    value_subject: Any,
    coefficients: list[tuple[str, Any]],
    base_indices: dict[str, Any],
    current_indices: dict[str, Any],
) -> AdjustmentResult:
    """The compensation (positive) or deduction (negative) for one settlement.

    Args:
        regime_code: A key of :data:`PRICE_ADJUSTMENT_REGIMES`.
        value_subject: The value of the work subject to adjustment in the
            period, at the contract (bid) prices.
        coefficients: ``(item, coefficient)`` pairs as the contract states them.
        base_indices: Index of each item at the regime's base date.
        current_indices: Index of each item at the settlement date.

    Raises:
        PriceAdjustmentError: An unknown regime, an invalid coefficient set,
            a missing index, or a base index of zero or less.
    """
    regime = regime_for(regime_code)
    if regime is None:
        raise PriceAdjustmentError("unknown_regime", f"unknown price adjustment regime {regime_code!r}")
    problems = coefficient_problems(regime, coefficients)
    if problems:
        first = problems[0]
        raise PriceAdjustmentError(first["problem"], f"invalid coefficients: {problems}", item=first["item"])
    value = _decimal(value_subject, "value_subject")
    items: list[AdjustmentItem] = []
    weights = ZERO
    for item, raw in coefficients:
        key = str(item).strip()
        coefficient = _decimal(raw, f"coefficient of {key}")
        if key not in base_indices or key not in current_indices:
            raise PriceAdjustmentError("missing_index", f"no index for {key!r}", item=key)
        base = _decimal(base_indices[key], f"base index of {key}")
        current = _decimal(current_indices[key], f"current index of {key}")
        if base <= ZERO:
            raise PriceAdjustmentError("base_index_not_positive", f"base index of {key!r} must be above zero", item=key)
        change = (current - base) / base
        amount = (value * coefficient * change).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        items.append(AdjustmentItem(key, coefficient, base, current, change, amount))
        weights += coefficient
    items_total = sum((i.amount for i in items), ZERO)
    rounding = regime.get("coefficient_rounding")
    if not rounding:
        return AdjustmentResult(
            regime=str(regime["code"]),
            value_subject=value,
            fixed_portion=ONE - weights,
            items=tuple(items),
            total=items_total,
        )
    # The coefficient is rounded before it is applied, so the total is
    # V x (C - 1) on the rounded C and the difference to the items' sum is
    # printed as its own line.
    exact = ONE + sum((i.coefficient * i.change for i in items), ZERO)
    mode = ROUND_CEILING if rounding["direction"] == "up" else ROUND_FLOOR
    coefficient = exact.quantize(Decimal(str(rounding["quantum"])), rounding=mode)
    total = (value * (coefficient - ONE)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    return AdjustmentResult(
        regime=str(regime["code"]),
        value_subject=value,
        fixed_portion=ONE - weights,
        items=tuple(items),
        total=total,
        revision_coefficient=coefficient,
        rounding_amount=total - items_total,
    )


def assess_trigger_claim(
    code: str,
    material_change_percent: Any,
    contract_change_percent: Any,
    claimed_percent_of_contract: Any,
) -> dict[str, Any]:
    """Whether a price movement crosses a trigger regime's thresholds, and what the cap lets through.

    Args:
        code: A key of :data:`PRICE_ADJUSTMENT_TRIGGERS`.
        material_change_percent: The listed material's price movement, signed.
        contract_change_percent: The resulting change in contract cost as a
            percent of the contract value, signed.
        claimed_percent_of_contract: The compensation claimed, as a percent of
            the contract value.

    Returns:
        ``triggered`` (both thresholds crossed, in either direction),
        ``payable_percent_of_contract`` (the claim up to the cap, ``0`` when
        not triggered), ``excess_percent_of_contract`` (what the cap leaves to
        the court) and ``needs_expert_review`` from the row.

    Raises:
        PriceAdjustmentError: An unknown regime or an input that is not a number.
    """
    row = trigger_for(code)
    if row is None:
        raise PriceAdjustmentError("unknown_regime", f"unknown price adjustment trigger {code!r}")
    material = abs(_decimal(material_change_percent, "material_change_percent"))
    contract = abs(_decimal(contract_change_percent, "contract_change_percent"))
    claimed = abs(_decimal(claimed_percent_of_contract, "claimed_percent_of_contract"))
    triggered = material >= Decimal(row["material_change_min_percent"]) and contract > Decimal(
        row["contract_change_above_percent"]
    )
    cap = Decimal(row["compensation_cap_percent_of_contract"])
    payable = min(claimed, cap) if triggered else ZERO
    return {
        "code": row["code"],
        "triggered": triggered,
        "payable_percent_of_contract": payable,
        "excess_percent_of_contract": (claimed - payable) if triggered else ZERO,
        "needs_expert_review": bool(row.get("needs_expert_review")),
    }


def add_months(start: date, months: int) -> date:
    """``start`` plus whole months, clamped to the last day of a shorter month."""
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def qualifies(regime_code: str, start: date | None, end: date | None) -> bool | None:
    """Whether a contract running from ``start`` to ``end`` is adjusted under the regime.

    ``None`` when the regime sets no minimum duration or a date is missing,
    so the caller cannot mistake "unknown" for "no".
    """
    regime = regime_for(regime_code)
    if regime is None or regime.get("min_duration_months") is None or start is None or end is None:
        return None
    return add_months(start, int(regime["min_duration_months"])) <= end


def adjustment_dates(regime_code: str, base_date: date, start: date | None, end: date | None) -> list[date]:
    """The settlement dates: every period from ``base_date`` up to and including ``end``.

    Empty when the contract does not qualify (shorter than the regime's
    minimum) or the regime sets no period.
    """
    regime = regime_for(regime_code)
    if regime is None or not regime.get("period_months") or end is None:
        return []
    if qualifies(regime_code, start, end) is False:
        return []
    period = int(regime["period_months"])
    dates: list[date] = []
    step = 1
    while True:
        when = add_months(base_date, period * step)
        if when > end:
            return dates
        dates.append(when)
        step += 1


__all__ = [
    "COEFFICIENT_RULES",
    "PRICE_ADJUSTMENT_REGIMES",
    "PRICE_ADJUSTMENT_TRIGGERS",
    "AdjustmentItem",
    "AdjustmentResult",
    "PriceAdjustmentError",
    "add_months",
    "adjustment_dates",
    "assess_trigger_claim",
    "coefficient_problems",
    "compute_adjustment",
    "qualifies",
    "regime_for",
    "trigger_for",
]
