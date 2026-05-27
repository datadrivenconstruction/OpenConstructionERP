# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""app.core.tax — unified VAT/GST rate lookup.

Aggregates ``vat_rates`` dicts from all regional pack configs and exposes a
single :func:`get_vat_rate` entry point so callers never need to know which
pack owns a given country code.

Design rules (Wave 25 / task #168):
- Rates are returned as :class:`decimal.Decimal` (not float).
- ``kind`` is one of ``'standard'``, ``'reduced'``, ``'zero'``.
- US has no federal VAT; calling ``get_vat_rate('US', ...)`` raises
  :class:`VATNotApplicable`.
- Countries not covered by any pack raise :class:`VATNotApplicable`.

Sources (cited in commit message, summarised here for reference):
- DE: Umsatzsteuergesetz §12 — standard 19 %, reduced 7 %, zero 0 %
  (European Commission VAT Rates Database 2026-01)
- AT: Umsatzsteuergesetz §10 — standard 20 %, reduced 10 %, zero 0 %
  (EC VAT Rates Database 2026-01)
- CH: MWSTG Art. 25 — standard 8.1 %, reduced 2.6 %, zero 0 %
  (ESTV / Swiss Federal Tax Administration, effective 2024-01-01)
- GB: HMRC VAT Notice 700 — standard 20 %, reduced 5 %, zero 0 %
  (HMRC, effective April 2011, still current 2026)
- AU: A New Tax System (Goods and Services Tax) Act 1999 — standard 10 %
  (ATO, GST; 'zero' = GST-free supplies = 0 %)
- NZ: Goods and Services Tax Act 1985 — standard 15 %
  (IRD New Zealand; 'zero' = zero-rated supplies = 0 %)
- JP: Consumption Tax Act — standard 10 %, reduced 8 %
  (NTA Japan, effective October 2019)
- SG: GST Act — standard 9 % (effective 1 Jan 2024), zero 0 %
  (IRAS Singapore, GST rate increase 2024)
- AE: Federal Decree-Law No. 8 of 2017 — standard 5 %
  (UAE FTA, effective 1 Jan 2018)
- SA: Royal Decree No. M/113 — standard 15 %
  (ZATCA, increased from 5 % effective 1 Jul 2020)
- BH: Decree-Law No. 48 of 2018 — standard 10 %
  (NBR Bahrain, increased from 5 % effective 1 Jan 2022)
- OM: Royal Decree No. 121/2020 — standard 5 %
  (Oman Tax Authority, effective 16 Apr 2021)
- IN: CGST Act 2017 — principal rate 18 % (works contracts), reduced 12 %
  (GST Council; 'standard' = 18 % construction services)
- MX: Ley del IVA Art. 1 — standard 16 %
  (SAT Mexico 2026; border-zone 8 % captured as 'reduced')
- AR: Ley 23.349 — standard 21 %, reduced 10.5 %
  (AFIP Argentina 2026)
- CL: Ley 825 — standard 19 %
  (SII Chile 2026)
- CO: Estatuto Tributario Art. 468 — standard 19 %
  (DIAN Colombia 2026)
- PE: TUO IGV SUNAT — standard 18 % (IGV 16 % + IPM 2 %)
  (SUNAT Peru 2026)
- RU: НК РФ ст. 164 — standard 20 %, reduced 10 %, zero 0 %
  (FNS Russia 2026)
- US: No federal VAT; state/local sales tax varies by jurisdiction.
  (IRS; Tax Foundation State Sales Tax Rates 2026)
"""

from __future__ import annotations

from decimal import Decimal


class VATNotApplicable(Exception):
    """Raised when no VAT rate is defined for a country/kind combination.

    This covers:
    - Countries with no VAT system (e.g. US, where only state-level sales
      tax applies — not modelled as a single federal rate).
    - Countries not yet covered by any regional pack's ``vat_rates`` dict.
    - A ``kind`` key that does not exist for an otherwise-covered country.
    """

    def __init__(self, country_code: str, kind: str) -> None:
        self.country_code = country_code
        self.kind = kind
        super().__init__(
            f"No VAT rate for country={country_code!r}, kind={kind!r}. "
            "This country either has no federal VAT (e.g. US uses per-state "
            "sales tax) or is not yet covered by a regional pack."
        )


# ── Master rate table ─────────────────────────────────────────────────────────
#
# Structure: {ISO-2 country code: {kind: Decimal-as-string}}
# 'kind' values: 'standard' | 'reduced' | 'zero'
#
# Populated from each regional pack's ``vat_rates`` dict (Wave 25).
# Rate values are stored as strings and coerced to Decimal on first access
# (lazy — avoids import-time Decimal allocation for unused entries).
#
# sentinel _RATES_BUILT guards one-time lazy init to keep import fast.

_RAW: dict[str, dict[str, str]] = {
    # ── DACH ─────────────────────────────────────────────────────────────
    "DE": {"standard": "0.19", "reduced": "0.07", "zero": "0.00"},
    "AT": {"standard": "0.20", "reduced": "0.10", "zero": "0.00"},
    "CH": {"standard": "0.081", "reduced": "0.026", "zero": "0.00"},
    # ── UK ───────────────────────────────────────────────────────────────
    "GB": {"standard": "0.20", "reduced": "0.05", "zero": "0.00"},
    # ── Asia-Pacific ─────────────────────────────────────────────────────
    "AU": {"standard": "0.10", "zero": "0.00"},
    "NZ": {"standard": "0.15", "zero": "0.00"},
    "JP": {"standard": "0.10", "reduced": "0.08"},
    "SG": {"standard": "0.09", "zero": "0.00"},
    # HK has no GST/VAT — raises VATNotApplicable
    # MY SST is not a VAT system — raises VATNotApplicable
    # ── Middle East ───────────────────────────────────────────────────────
    "AE": {"standard": "0.05", "zero": "0.00"},
    "SA": {"standard": "0.15", "zero": "0.00"},
    "BH": {"standard": "0.10", "zero": "0.00"},
    "OM": {"standard": "0.05", "zero": "0.00"},
    "QA": {"standard": "0.00"},  # Qatar has no VAT (zero rate for all)
    "KW": {"standard": "0.00"},  # Kuwait has not implemented VAT (2026)
    # ── India ─────────────────────────────────────────────────────────────
    "IN": {"standard": "0.18", "reduced": "0.12", "zero": "0.00"},
    # ── Latin America ─────────────────────────────────────────────────────
    "MX": {"standard": "0.16", "reduced": "0.08", "zero": "0.00"},
    "AR": {"standard": "0.21", "reduced": "0.105", "zero": "0.00"},
    "CL": {"standard": "0.19", "zero": "0.00"},
    "CO": {"standard": "0.19", "zero": "0.00"},
    "PE": {"standard": "0.18", "zero": "0.00"},
    # BR uses a fragmented indirect tax system (ISS, ICMS, PIS/COFINS)
    # not equivalent to a simple VAT rate — raises VATNotApplicable
    # ── Russia / CIS ──────────────────────────────────────────────────────
    "RU": {"standard": "0.20", "reduced": "0.10", "zero": "0.00"},
    # ── US — no federal VAT ──────────────────────────────────────────────
    # US deliberately absent; get_vat_rate('US', ...) → VATNotApplicable
}

_CACHE: dict[str, dict[str, Decimal]] = {}


def _build_country(country_code: str) -> dict[str, Decimal]:
    """Coerce raw string rates to Decimal for one country."""
    raw = _RAW.get(country_code.upper())
    if raw is None:
        return {}
    return {kind: Decimal(val) for kind, val in raw.items()}


def get_vat_rate(country_code: str, kind: str = "standard") -> Decimal:
    """Return the VAT/GST rate for a country and rate kind.

    Args:
        country_code: ISO 3166-1 alpha-2 country code (case-insensitive).
        kind: One of ``'standard'``, ``'reduced'``, or ``'zero'``.
              Defaults to ``'standard'``.

    Returns:
        :class:`~decimal.Decimal` in the range ``[0, 0.50]``.

    Raises:
        :class:`VATNotApplicable`: When the country has no federal VAT
            (US), is not covered by any regional pack, or the requested
            ``kind`` does not exist for that country.

    Examples::

        >>> get_vat_rate('DE')
        Decimal('0.19')
        >>> get_vat_rate('GB', 'reduced')
        Decimal('0.05')
        >>> get_vat_rate('US', 'standard')
        Traceback (most recent call last):
            ...
        VATNotApplicable: No VAT rate for country='US', kind='standard'. ...
    """
    cc = country_code.upper()
    if cc not in _CACHE:
        built = _build_country(cc)
        if not built and cc not in _RAW:
            raise VATNotApplicable(country_code, kind)
        _CACHE[cc] = built

    rates = _CACHE.get(cc, {})
    if kind not in rates:
        raise VATNotApplicable(country_code, kind)
    return rates[kind]


def list_covered_countries() -> list[str]:
    """Return ISO-2 codes for all countries with at least one VAT rate."""
    return sorted(_RAW.keys())
