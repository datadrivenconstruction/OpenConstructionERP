# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What the platform already does for a country, with or without a pack.

A pack does not set VAT, public holidays, e-invoicing or statutory payment
terms. Those come from core registries keyed by the project's country, and a
project located in Germany gets German VAT and German holidays whether or not
the Germany pack is active. The pack preview used to list the pack's
``default_tax_template`` beside a note saying it was "recorded for reference",
which read as if the pack installed tax. This module reads the same registries
the product reads, so the preview can show the real values and say where they
come from.

Every reader is best effort and independent: a registry that cannot be read
reports ``None`` for its own row and never hides the others.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


def _percent(value: Any) -> str:
    """Render a rate fraction (``Decimal('0.19')``) as a percent string (``"19"``)."""
    pct = (value * 100).normalize()
    text = format(pct, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _vat(country: str) -> dict[str, str] | None:
    from app.core.tax import VATNotApplicable, get_vat_rate

    rates: dict[str, str] = {}
    for kind in ("standard", "reduced", "zero"):
        try:
            rates[kind] = _percent(get_vat_rate(country, kind))
        except VATNotApplicable:
            continue
    return rates or None


def _holidays(country: str, year: int) -> dict[str, Any] | None:
    from app.core.calendar import resolve_holidays
    from app.core.provenance import Source

    resolved = resolve_holidays(country, year)
    jurisdiction = resolved.get("jurisdiction")
    source = getattr(jurisdiction, "source", jurisdiction)
    if source != Source.DECLARED:
        # Another country's table, or a bare week, answered. That is not a
        # holiday calendar for this country and must not be shown as one.
        return None
    return {"year": year, "count": len(resolved.get("dates") or ())}


def _einvoice(country: str) -> dict[str, str] | None:
    from app.modules.einvoice_clearance.regimes import COUNTRY_REGIMES

    regime = COUNTRY_REGIMES.get(country)
    if regime is None:
        return None
    return {"platform": regime.platform, "label": regime.label}


def _payment_terms(country: str) -> list[dict[str, Any]] | None:
    from app.modules.payment_clock.data import PAYMENT_REGIMES

    rows = [
        {
            "code": str(r.get("code") or ""),
            "statute": str(r.get("statute") or ""),
            "final_date_days": r.get("final_date_days"),
        }
        for r in PAYMENT_REGIMES
        if r.get("country_code") == country
    ]
    return rows or None


def country_builtins(country: str | None, *, today: date | None = None) -> dict[str, Any] | None:
    """The tax, holiday, e-invoicing and payment-term facts built in for ``country``.

    Args:
        country: ISO 3166-1 alpha-2 code, or None for a pack that names no
            single market (an industry pack).
        today: The date whose year the holiday count is taken for. Defaults to
            today; a parameter so tests do not depend on the clock.

    Returns:
        ``{country, vat, holidays, einvoice, payment_terms}`` where each value
        is None when the registry has no row for the country, or None overall
        when no country is given.
    """
    code = (country or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return None
    year = (today or date.today()).year
    out: dict[str, Any] = {"country": code}
    readers = {
        "vat": lambda: _vat(code),
        "holidays": lambda: _holidays(code, year),
        "einvoice": lambda: _einvoice(code),
        "payment_terms": lambda: _payment_terms(code),
    }
    for key, read in readers.items():
        try:
            out[key] = read()
        except Exception as exc:  # noqa: BLE001 - one unreadable registry must not hide the rest
            logger.debug("country_builtins: %s for %s could not be read: %s", key, code, exc)
            out[key] = None
    return out
