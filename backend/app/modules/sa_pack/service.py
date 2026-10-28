# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Stateless business logic for the South Africa regional pack.

Pure functions with no transport or database dependencies, so they are unit
testable in isolation. The router wraps these and translates ``ValueError`` and
``VATNotApplicable`` into HTTP 422. Money is Decimal in, strings out.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.tax import get_vat_rate
from app.modules.sa_pack.config import PPPFA_THRESHOLD_ZAR

_CENTS = Decimal("0.01")
_THRESHOLD = Decimal(PPPFA_THRESHOLD_ZAR)


def score_pppfa(
    bid_price: Decimal,
    lowest_acceptable_price: Decimal,
    preference_points: Decimal = Decimal("0"),
    estimated_value: Decimal | None = None,
    system: str | None = None,
) -> dict:
    """Score a bid with the official PPPFA price-points formula.

    ``Ps = W * (1 - (Pt - P_min) / P_min)`` where ``W`` is the price weight
    (80 or 90), ``Pt`` is the bid price and ``P_min`` is the lowest acceptable
    tender price. The lowest bid earns the full price weight; higher bids earn
    proportionally fewer points. The award goes to the highest total of price
    points plus preference points.

    Raises:
        ValueError: on non-positive prices, a bid below the lowest price, or
            negative preference points.
    """
    if bid_price <= 0 or lowest_acceptable_price <= 0:
        raise ValueError("bid_price and lowest_acceptable_price must be greater than zero.")
    if bid_price < lowest_acceptable_price:
        raise ValueError("bid_price cannot be below the lowest acceptable price.")
    if preference_points < 0:
        raise ValueError("preference_points cannot be negative.")

    chosen = system if system in ("80/20", "90/10") else None
    if chosen is None:
        reference = estimated_value if estimated_value is not None else bid_price
        chosen = "80/20" if reference <= _THRESHOLD else "90/10"

    price_weight = Decimal("80") if chosen == "80/20" else Decimal("90")
    preference_cap = Decimal("100") - price_weight
    awarded_preference = min(preference_points, preference_cap)

    raw_price_points = price_weight * (Decimal("1") - (bid_price - lowest_acceptable_price) / lowest_acceptable_price)
    # A bid more than double the lowest acceptable price would otherwise score
    # negative; PPPFA awards no fewer than zero price points.
    price_points = max(Decimal("0"), raw_price_points).quantize(_CENTS)
    total = (price_points + awarded_preference).quantize(_CENTS)

    return {
        "system": chosen,
        "price_weight": str(price_weight),
        "preference_weight": str(preference_cap),
        "bid_price": str(bid_price),
        "lowest_acceptable_price": str(lowest_acceptable_price),
        "price_points": str(price_points),
        "preference_points": str(awarded_preference.quantize(_CENTS)),
        "total_points": str(total),
        "formula": "Ps = W * (1 - (Pt - P_min) / P_min)",
    }


def calculate_vat(amount: Decimal, kind: str = "standard") -> dict:
    """Return the VAT breakdown for an amount using the core SA VAT rate.

    Raises:
        ValueError: if ``amount`` is negative.
        VATNotApplicable: if no ZA rate exists for ``kind`` (from app.core.tax).
    """
    if amount < 0:
        raise ValueError("amount cannot be negative.")
    rate = get_vat_rate("ZA", kind)
    exclusive = amount.quantize(_CENTS)
    vat = (amount * rate).quantize(_CENTS)
    return {
        "country": "ZA",
        "kind": kind,
        "vat_rate": str(rate),
        "exclusive": str(exclusive),
        "vat": str(vat),
        "inclusive": str((exclusive + vat).quantize(_CENTS)),
    }
