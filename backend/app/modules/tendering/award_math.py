# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The figures an award turns into: contract sum, contract type, contract lines.

Pure functions, no database. The contract draft and the award panel preview
both call :func:`compute_award`, so the figure an estimator sees before the
award is the figure the contract is drafted with.

Rules:

* Contract sum = final offer x (1 - discount %). The final offer is the agreed
  lump sum when one is set, else the priced lines' sum (or the bid total when
  the bid is a lump sum without priced lines). Retention and the payment
  discount act on invoices, never on the contract sum.
* A lump sum over priced lines is spread pro rata: each line x (sum / lines
  sum), rounded half up to 0.01, the remainder on the last line, so the lines
  add up to the contract sum exactly.
* A lump-sum contract keeps each line's offered unit rate; a unit-price
  contract with a discount carries the discounted rate.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
RATE_QUANTUM = Decimal("0.0001")
HUNDRED = Decimal("100")
ZERO = Decimal("0")

UNIT_PRICE = "unit_price"
LUMP_SUM = "lump_sum"
PRICING_MODES = (UNIT_PRICE, LUMP_SUM)


def to_decimal(value: object) -> Decimal:
    """A JSON number, string or Decimal as Decimal; 0 for empty or unreadable."""
    if value is None or value == "" or isinstance(value, bool):
        return ZERO
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO
    return out if out.is_finite() else ZERO


def money(value: Decimal) -> Decimal:
    """Round half up to cents."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def spread_pro_rata(line_totals: Sequence[Decimal], target: Decimal) -> list[Decimal]:
    """Spread ``target`` over lines in proportion to their totals; the lines add up to it exactly.

    Each line but the last is ``total x target / sum`` rounded half up to cents;
    the last line takes the remainder. Lines summing to zero leave every line at
    zero and the whole target on the last one.
    """
    if not line_totals:
        return []
    base = sum(line_totals, ZERO)
    target = money(target)
    if base == ZERO:
        return [ZERO] * (len(line_totals) - 1) + [target]
    shares = [money(total * target / base) for total in line_totals[:-1]]
    shares.append(target - sum(shares, ZERO))
    return shares


@dataclass(frozen=True)
class OfferLine:
    """One priced line of the offer the award rests on."""

    quantity: Decimal
    unit_rate: Decimal

    @property
    def total(self) -> Decimal:
        return self.quantity * self.unit_rate


@dataclass(frozen=True)
class AwardInputs:
    """What the award is computed from.

    ``pricing_mode`` is the mode of the offer (the final round, else the bid).
    ``offer_lump_sum`` is the lump sum that offer names, if it names one.
    ``terms_lump_sum`` is the lump sum agreed on the award terms and wins over
    the offer's. ``discount_percent`` is in percent.
    """

    lines: tuple[OfferLine, ...] = ()
    pricing_mode: str = UNIT_PRICE
    bid_total: Decimal = ZERO
    offer_lump_sum: Decimal | None = None
    terms_lump_sum: Decimal | None = None
    discount_percent: Decimal = ZERO
    retention_cap_percent: Decimal | None = None


@dataclass
class AwardFigures:
    """The computed award."""

    contract_type: str
    lines_total: Decimal
    offer_total: Decimal
    discount_amount: Decimal
    contract_sum: Decimal
    line_totals: list[Decimal] = field(default_factory=list)
    line_rates: list[Decimal] = field(default_factory=list)
    retention_cap_amount: Decimal | None = None
    lump_sum_source: str | None = None  # terms | offer | bid | None

    @property
    def lines_reconcile(self) -> bool:
        """The contract lines add up to the contract sum (always true for a draft this module made)."""
        return not self.line_totals or sum(self.line_totals, ZERO) == self.contract_sum


def compute_award(inputs: AwardInputs) -> AwardFigures:
    """Contract type, contract sum and contract lines of an award. See the module docstring."""
    lines_total = sum((line.total for line in inputs.lines), ZERO)
    lump_sum: Decimal | None = None
    source: str | None = None
    if inputs.terms_lump_sum is not None:
        lump_sum, source = inputs.terms_lump_sum, "terms"
    elif inputs.offer_lump_sum is not None:
        lump_sum, source = inputs.offer_lump_sum, "offer"
    elif inputs.pricing_mode == LUMP_SUM or lines_total == ZERO:
        lump_sum, source = inputs.bid_total, "bid"

    contract_type = LUMP_SUM if lump_sum is not None else UNIT_PRICE
    offer_total = money(lump_sum if lump_sum is not None else lines_total)
    discount = inputs.discount_percent or ZERO
    contract_sum = money(offer_total * (HUNDRED - discount) / HUNDRED)
    discount_amount = offer_total - contract_sum

    totals = [line.total for line in inputs.lines]
    if not totals:
        line_totals: list[Decimal] = []
    elif money(lines_total) == contract_sum and all(money(t) == t for t in totals):
        line_totals = [money(t) for t in totals]
    else:
        line_totals = spread_pro_rata(totals, contract_sum)

    factor = (HUNDRED - discount) / HUNDRED
    if contract_type == LUMP_SUM or discount == ZERO:
        line_rates = [line.unit_rate for line in inputs.lines]
    else:
        line_rates = [(line.unit_rate * factor).quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP) for line in inputs.lines]

    cap = inputs.retention_cap_percent
    return AwardFigures(
        contract_type=contract_type,
        lines_total=money(lines_total),
        offer_total=offer_total,
        discount_amount=discount_amount,
        contract_sum=contract_sum,
        line_totals=line_totals,
        line_rates=line_rates,
        retention_cap_amount=money(contract_sum * cap / HUNDRED) if cap is not None else None,
        lump_sum_source=source,
    )
