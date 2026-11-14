"""Standard VAT rate a demo seed applies to its documents, by currency."""

from __future__ import annotations

from decimal import Decimal

_RATE_BY_CURRENCY: dict[str, Decimal] = {
    "EUR": Decimal("0.19"),
    "GBP": Decimal("0.20"),
    "AED": Decimal("0.05"),
    # China construction VAT.
    "CNY": Decimal("0.09"),
    # Ontario HST.
    "CAD": Decimal("0.13"),
    "SAR": Decimal("0.15"),
    # Simplification: Texas sales tax (8.25 %) falls on the materials share of a
    # job only, and demo documents carry about half of their value as materials,
    # so one effective rate stands in for the split.
    "USD": Decimal("0.04125"),
}


def demo_vat_rate(currency: str | None) -> Decimal:
    """Return the VAT rate demo invoices and orders carry in ``currency`` (zero when unknown)."""
    return _RATE_BY_CURRENCY.get((currency or "").upper()[:3], Decimal("0"))
