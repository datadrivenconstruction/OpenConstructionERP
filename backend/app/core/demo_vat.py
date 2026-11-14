"""Standard VAT rate a demo seed applies to its documents, by currency."""

from __future__ import annotations

from decimal import Decimal

_RATE_BY_CURRENCY: dict[str, Decimal] = {
    "EUR": Decimal("0.19"),
    "GBP": Decimal("0.20"),
    "AED": Decimal("0.05"),
}


def demo_vat_rate(currency: str | None) -> Decimal:
    """Return the VAT rate demo invoices and orders carry in ``currency`` (zero when unknown)."""
    return _RATE_BY_CURRENCY.get((currency or "").upper()[:3], Decimal("0"))
