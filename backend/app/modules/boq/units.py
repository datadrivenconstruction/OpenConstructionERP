"""Approved BOQ units of measurement (BUG-MATH03).

Position ``unit`` was a free-text field — typos like "tonne" / "tonnes" /
"ton" produced three separate buckets in unit-breakdown statistics and
broke GAEB X83 export which requires a known QU code.

The DB column stays ``String`` so legacy rows (pre-fix imports, section
rows where ``unit="section"``) do not need a backfill migration.
Validation happens at the Pydantic schema layer for new writes only.

Tenants that need a custom unit register it via the ``CUSTOM_UNITS``
extension list (env-driven in a future patch); for now the curated
catalogue covers all SI / imperial units the templates and CWICR seed
data use.
"""

from __future__ import annotations

import re
from typing import Final

# ── Curated unit catalogue ────────────────────────────────────────────
#
# Length / area / volume — SI and imperial.
# Mass — SI only (imperial weights stored via ``lb`` if ever needed).
# Counts / lump-sum / time — universal.
#
# When extending: prefer ISO 80000-1 short forms (lower-case, no period).
APPROVED_UNITS: Final[frozenset[str]] = frozenset(
    {
        # length
        "m", "mm", "cm", "km", "lm", "ll", "ft", "in", "yd",
        # area
        "m2", "cm2", "ft2",
        # volume
        "m3", "cm3", "l", "ft3", "gal",
        # mass / weight
        "kg", "g", "t",
        # counts / lump
        "pcs", "ea", "no", "set", "lsum", "ls",
        # time / labour
        "hr", "h", "hrs", "hour", "hours", "day", "days", "wk", "month",
        # internal sentinel: section header rows have unit="section" — keep
        # it in the allowed list so existing section-create paths (which
        # bypass ``PositionCreate``) round-trip cleanly through any future
        # ``PositionResponse`` re-validation.
        "section",
    }
)


# CWICR and other catalogues commonly price grouped quantities — "100 EA",
# "1000 m", "10 kg" — meaning "rate per N units".  Treat these as approved
# when the trailing token is itself an approved unit; normalisation strips
# the multiplier so downstream stats and GAEB export still see a clean
# ``ea`` / ``m`` / ``kg``.  The numeric prefix is preserved on the
# position via ``unit_multiplier`` (carried in metadata by the import flow)
# so totals stay accurate.
_MULTI_PREFIX_RE: Final = re.compile(r"^\s*(\d{1,6})\s+([A-Za-z][A-Za-z0-9]{0,9})\s*$")

# A unit token's "shape" — used as a permissive fallback so estimators can
# coin custom units (region-specific, internal-coding, novel materials) and
# have them round-trip through the validator. Must start with a letter,
# allow alphanumerics + space + a small set of separators (./-), max 20
# chars. Rejects empty strings, control characters, HTML/SQL payloads, and
# anything obviously non-unit-shaped. Curated catalogue still takes
# priority for canonical forms (e.g. "tonne" → still rejected in favour of
# "t") so existing aggregations stay coherent.
_CUSTOM_UNIT_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9 ._/-]{0,19}$")


# Canonical aliases — common synonyms that should bucket into the same
# canonical unit so aggregations don't fragment. CWICR / RSMeans / SINAPI
# / GAEB seeds use these spellings interchangeably; mapping them at the
# validator preserves both round-trip ergonomics ("ton" works as input)
# and downstream coherence (everything lands in "t"). Keep the map small
# and unambiguous: only include synonyms with universal meaning. Locale-
# specific variants (e.g. "штука", "шт") belong in i18n display, not here.
_UNIT_ALIASES: Final[dict[str, str]] = {
    # mass — metric tonne synonyms
    "ton": "t",
    "tons": "t",
    "tonne": "t",
    "tonnes": "t",
    "mt": "t",
    # length — meter / metre
    "metre": "m",
    "metres": "m",
    "meter": "m",
    "meters": "m",
    # area / volume plurals
    "sqm": "m2",
    "sq.m": "m2",
    "sqft": "ft2",
    "sq.ft": "ft2",
    "cum": "m3",
    "cu.m": "m3",
    "cuft": "ft3",
    "cu.ft": "ft3",
    # counts / lump synonyms
    "piece": "pcs",
    "pieces": "pcs",
    "each": "ea",
    "nr": "no",
    "lump": "lsum",
    "lumpsum": "lsum",
    "lump-sum": "lsum",
    "lump sum": "lsum",
    # time / labour
    "hours": "hr",
    "hour": "hr",
    "h": "hr",
    "hrs": "hr",
    "weeks": "wk",
    "week": "wk",
    "months": "month",
    "mo": "month",
    "days": "day",
}


def normalise_unit(unit: str | None) -> str | None:
    """Return the canonical form of ``unit`` if accepted, else None.

    Accepts (in order of priority):
      - exact match in APPROVED_UNITS (case-insensitive)
      - canonical alias from ``_UNIT_ALIASES`` (e.g. "ton" → "t")
      - CWICR-style multi-prefix forms like "100 EA", "1000 m" — returned
        as ``"<N> <unit>"`` lower-cased; trailing token can itself be an
        alias.
      - any user-coined custom unit matching ``_CUSTOM_UNIT_RE`` — letters
        first, alphanumerics / space / ``._-/`` after, max 20 chars.
        Lower-cased on the way through. Lets estimators register novel
        units without a backend release; aggregations key off the saved
        string so identical custom units bucket together.
    """
    if not unit:
        return None
    stripped = unit.strip()
    if not stripped:
        return None
    lower = stripped.lower()
    if lower in APPROVED_UNITS:
        return lower
    if lower in _UNIT_ALIASES:
        return _UNIT_ALIASES[lower]
    m = _MULTI_PREFIX_RE.match(stripped)
    if m:
        n, base = m.group(1), m.group(2).lower()
        # Trailing token: alias → canonical → custom shape, in that order,
        # so "1000 tons" and "100 each" both round-trip cleanly.
        if base in _UNIT_ALIASES:
            return f"{n} {_UNIT_ALIASES[base]}"
        if base in APPROVED_UNITS or _CUSTOM_UNIT_RE.match(base):
            return f"{n} {base}"
    if _CUSTOM_UNIT_RE.match(stripped):
        return lower
    return None


def is_approved_unit(unit: str | None) -> bool:
    """Return True when ``unit`` is in the approved catalogue (case-insensitive)."""
    return normalise_unit(unit) is not None
