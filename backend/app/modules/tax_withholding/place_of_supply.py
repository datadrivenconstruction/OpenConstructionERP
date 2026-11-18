# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tax prepaid at the place of supply.

Some markets make a contractor working away from home prepay part of the output
tax where the site is, and credit it later against the return filed at home.
The arithmetic is the same wherever it applies::

    base     = receipts (gross of tax) - deductible subcontract paid - carried deduction
    prepaid  = base / (1 + tax rate) x prepayment rate      when base > 0
    carried  = -base                                         when base < 0

A negative month prepays nothing and carries its shortfall into the next month,
so a large subcontract payment is never lost to a period that happened to have
small receipts. Rates are arguments: the pack that knows the market passes
them. Computing and reconciling is all this does; the filing is made in the tax
authority's own system.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.core.line_tax import to_decimal

__all__ = ["PrepaymentPeriod", "PrepaymentResult", "prepayment_schedule"]

_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)
_ZERO = Decimal(0)


@dataclass(frozen=True)
class PrepaymentPeriod:
    """One period's receipts and deductible subcontract payments, both gross."""

    period: str
    receipts: Decimal
    subcontract_paid: Decimal = _ZERO
    recorded_prepaid: Decimal | None = None


@dataclass
class PrepaymentResult:
    """The computed prepayment of one period."""

    period: str
    receipts: Decimal
    subcontract_paid: Decimal
    carried_in: Decimal
    base_gross: Decimal
    base_net: Decimal
    prepaid: Decimal
    carried_out: Decimal
    recorded_prepaid: Decimal | None = None
    difference: Decimal | None = None
    details: dict[str, str] = field(default_factory=dict)

    @property
    def matches(self) -> bool | None:
        """Whether a recorded figure agrees with the computed one, if one was recorded."""
        return None if self.difference is None else self.difference == _ZERO


def prepayment_schedule(
    periods: Iterable[PrepaymentPeriod],
    *,
    tax_rate_pct: Decimal,
    prepay_rate_pct: Decimal,
    carried_in: Decimal = _ZERO,
) -> list[PrepaymentResult]:
    """Compute the prepayment of each period in order, carrying shortfalls forward.

    Args:
        periods: The periods in the order they are filed.
        tax_rate_pct: The rate the receipts are gross of (9 for 9%).
        prepay_rate_pct: The prepayment rate on the net base (2 for 2%).
        carried_in: A deduction still unused from before the first period.

    Returns:
        One :class:`PrepaymentResult` per period.
    """
    divisor = Decimal(1) + to_decimal(tax_rate_pct) / _HUNDRED
    prepay = to_decimal(prepay_rate_pct) / _HUNDRED
    carry = to_decimal(carried_in)
    out: list[PrepaymentResult] = []
    for period in periods:
        receipts = to_decimal(period.receipts)
        subcontract = to_decimal(period.subcontract_paid)
        gross = receipts - subcontract - carry
        if gross > _ZERO:
            net = (gross / divisor).quantize(_CENT, rounding=ROUND_HALF_UP)
            prepaid = (gross / divisor * prepay).quantize(_CENT, rounding=ROUND_HALF_UP)
            next_carry = _ZERO
        else:
            net = _ZERO
            prepaid = _ZERO
            next_carry = -gross
        recorded = None if period.recorded_prepaid is None else to_decimal(period.recorded_prepaid)
        out.append(
            PrepaymentResult(
                period=period.period,
                receipts=receipts,
                subcontract_paid=subcontract,
                carried_in=carry,
                base_gross=receipts - subcontract,
                base_net=net,
                prepaid=prepaid,
                carried_out=next_carry,
                recorded_prepaid=recorded,
                difference=None if recorded is None else (recorded - prepaid).quantize(_CENT),
            )
        )
        carry = next_carry
    return out
