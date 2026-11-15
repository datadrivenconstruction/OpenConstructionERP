"""Standard VAT rate a demo seed applies to its documents.

A currency shared by several countries (the euro) takes its rate from the demo's
own country, read from the dated tax seed. A currency that names one market
keeps a fixed demo rate below.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.vat_construction import default_vat_rate_percent

# Used for a euro demo whose country is unknown or has no seeded VAT row.
_EURO_FALLBACK = Decimal("0.19")

_RATE_BY_CURRENCY: dict[str, Decimal] = {
    "GBP": Decimal("0.20"),
    "AED": Decimal("0.05"),
    # China construction VAT.
    "CNY": Decimal("0.09"),
    # Ontario HST.
    "CAD": Decimal("0.13"),
    "SAR": Decimal("0.15"),
    # Peru IGV 16% plus 2% municipal promotion tax.
    "PEN": Decimal("0.18"),
    # Simplification: Texas sales tax (8.25 %) falls on the materials share of a
    # job only, and demo documents carry about half of their value as materials,
    # so one effective rate stands in for the split.
    "USD": Decimal("0.04125"),
}


def demo_vat_rate(currency: str | None, country: str | None = None) -> Decimal:
    """Return the VAT rate demo invoices and orders carry (zero when unknown).

    Args:
        currency: ISO 4217 code of the demo.
        country: ISO 3166-1 alpha-2 code of the demo's country; decides the rate
            for the euro, which every euro-area country prices differently.
    """
    code = (currency or "").upper()[:3]
    if code in _RATE_BY_CURRENCY:
        return _RATE_BY_CURRENCY[code]
    if code == "EUR":
        pct = default_vat_rate_percent(country or "", date.today())
        return pct / 100 if pct is not None else _EURO_FALLBACK
    return Decimal("0")
