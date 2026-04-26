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


def is_approved_unit(unit: str | None) -> bool:
    """Return True when ``unit`` is in the approved catalogue (case-insensitive)."""
    if not unit:
        return False
    return unit.strip().lower() in APPROVED_UNITS
