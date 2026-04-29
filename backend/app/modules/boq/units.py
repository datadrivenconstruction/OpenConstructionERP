"""BOQ unit normaliser.

Estimators globally use thousands of locale-specific units that no curated
allowlist can ever cover: Romanian ``Bucat``, Bulgarian ``бр``, Russian
``шт``, German ``Stück``, French ``unité``, CWICR multi-prefix forms like
``100 EA``, plus per-trade slang ("man-day", "lin.m", "MWh", "%").  A
strict allowlist meant every regional CWICR import re-surfaced the same
422.  Policy is now **sanitise, don't gate**:

* canonicalise common synonyms via the alias table so aggregations don't
  fragment ("ton" / "tonne" / "tonnes" → "t"),
* otherwise return the input lowercased and stripped, regardless of
  script (Latin, Cyrillic, Greek, CJK, accented),
* reject only the genuinely unsafe shapes — empty, > 30 chars,
  control characters, HTML / SQL / quote characters, or a non-letter /
  non-digit leading character.

GAEB X83 export still needs a known QU code per row; rows whose unit
isn't in :data:`APPROVED_UNITS` are emitted with QU="StPa" and the
original string preserved in the ``Bezeichnung``.  The exporter, not
this validator, is responsible for that mapping.
"""

from __future__ import annotations

from typing import Final

# ── Curated unit catalogue ────────────────────────────────────────────
#
# This used to be a strict allowlist that *rejected* anything outside.
# It now serves only as a **canonical-form table**: when the user types a
# spelling that already appears here, normalisation lower-cases it and
# returns the canonical form.  Inputs outside this set still pass through
# (lowercased) so locale-specific labels survive round-trips.
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
        # internal sentinel: section header rows have unit="section" — kept
        # in the canonical table so existing section-create paths round-trip
        # cleanly through any future ``PositionResponse`` re-validation.
        "section",
    }
)


# Canonical aliases — common synonyms that should bucket into the same
# canonical unit so aggregations don't fragment.  Locale-specific spellings
# (Cyrillic / CJK / accented) deliberately don't appear here: we keep them
# verbatim so the BOQ shows what the estimator typed.
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


# Maximum acceptable unit length.  Anything longer is almost certainly an
# accidentally pasted description, not a unit of measurement.
_MAX_UNIT_LEN: Final[int] = 30

# Characters allowed in the body of a unit (after the leading letter or
# digit).  Lets locale-specific spellings, percentages, and superscript
# squared/cubed glyphs ("m²", "ft³") pass through cleanly.
_BODY_EXTRA_CHARS: Final[frozenset[str]] = frozenset(" ._-/²³%")

# Characters explicitly rejected anywhere in the unit string.  Keeps unit
# values out of HTML / SQL / shell injection vectors regardless of context
# the value is later concatenated into.
_FORBIDDEN_CHARS: Final[frozenset[str]] = frozenset(
    '<>&"\'`;\\\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f'
)


def _is_safe_unit_shape(unit: str) -> bool:
    """Return True iff ``unit`` is non-empty, ≤ ``_MAX_UNIT_LEN``, and free
    of forbidden characters.  The first character must be a letter or a
    digit (so "100 ea" / "lin.m" / "м3" / "個" all pass; ";rm" / "<x>" do
    not).
    """
    if not unit or len(unit) > _MAX_UNIT_LEN:
        return False
    head = unit[0]
    # Letters / digits cover every script; "%" is the one symbolic unit
    # (percentage) common enough to allow as a standalone label.
    if not (head.isalpha() or head.isdigit() or head == "%"):
        return False
    for ch in unit:
        if ch in _FORBIDDEN_CHARS:
            return False
        if ch.isalnum():
            continue
        if ch in _BODY_EXTRA_CHARS:
            continue
        return False
    return True


def normalise_unit(unit: str | None) -> str | None:
    """Return the canonical form of ``unit`` if it has a safe shape, else
    None.

    Resolution order:
      1. canonical alias from :data:`_UNIT_ALIASES` (e.g. "ton" → "t",
         "hour" → "hr") — aliases are checked first so synonyms collapse
         into one bucket regardless of whether they happen to also appear
         in the catalogue
      2. exact match in :data:`APPROVED_UNITS` (case-insensitive)
      3. CWICR-style multi-prefix forms like "100 EA", "1000 m" — returned
         as ``"<N> <unit>"`` with the trailing token canonicalised through
         the alias table when possible
      4. anything else — passed through, lower-cased, with surrounding
         whitespace stripped (Cyrillic, CJK, Greek, accented Latin,
         percent / squared / cubed glyphs all preserved verbatim)

    Returns ``None`` only when the input is empty, longer than 30 chars,
    contains forbidden characters, or starts with something that isn't a
    letter or a digit.  Callers that previously relied on this returning
    ``None`` for unknown labels (the old strict-allowlist behaviour) must
    use :data:`APPROVED_UNITS` directly instead.
    """
    if not unit:
        return None
    stripped = unit.strip()
    if not _is_safe_unit_shape(stripped):
        return None
    lower = stripped.lower()
    # Aliases first: "hour" / "hours" / "h" all collapse to "hr" even
    # though each is in APPROVED_UNITS, fixing the original BUG-MATH03
    # complaint that synonyms produced separate buckets in unit-breakdown
    # statistics.
    if lower in _UNIT_ALIASES:
        return _UNIT_ALIASES[lower]
    if lower in APPROVED_UNITS:
        return lower
    # Multi-prefix form: "100 EA" / "1000 m" / "10 kg".  Detect by
    # splitting on the first whitespace run rather than a regex so the
    # implementation stays Unicode-clean — Python's ``str.split`` already
    # respects every Unicode whitespace code point.
    parts = stripped.split(None, 1)
    if len(parts) == 2 and parts[0].isdigit() and 1 <= len(parts[0]) <= 6:
        head, tail = parts
        tail_lower = tail.strip().lower()
        if not tail_lower:
            return None
        if tail_lower in _UNIT_ALIASES:
            return f"{head} {_UNIT_ALIASES[tail_lower]}"
        return f"{head} {tail_lower}"
    return lower


def is_approved_unit(unit: str | None) -> bool:
    """Return True when ``unit`` has a safe shape (i.e.
    :func:`normalise_unit` doesn't reject it).

    Note: this is *not* membership in :data:`APPROVED_UNITS` — that strict
    test still exists as plain set membership for callers (GAEB exporter,
    aggregations) that need to know whether a unit maps to a canonical
    QU code.  The schema validator uses the looser shape test so locale-
    specific spellings round-trip without 422 errors.
    """
    return normalise_unit(unit) is not None
