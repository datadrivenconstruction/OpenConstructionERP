# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ unit normaliser.

Estimators globally use thousands of locale-specific units that no curated
allowlist can ever cover: Romanian ``Bucat``, Bulgarian ``бр``, Russian
``шт``, German ``Stück``, French ``unité``, CWICR multi-prefix forms like
``100 EA``, plus per-trade slang ("man-day", "lin.m", "MWh", "%").  A
strict allowlist meant every regional CWICR import re-surfaced the same
422.  Policy is now **sanitise, don't gate**:

* canonicalise common synonyms via the alias table so aggregations don't
  fragment ("tonne" / "tonnes" / "mt" → "t"),
* otherwise return the input lowercased and stripped, regardless of
  script (Latin, Cyrillic, Greek, CJK, accented),
* reject only the genuinely unsafe shapes - empty, > 30 chars,
  control characters, HTML / SQL / quote characters, or a non-letter /
  non-digit leading character.

GAEB X83 export still needs a known QU code per row; rows whose unit
isn't in :data:`APPROVED_UNITS` are emitted with QU="StPa" and the
original string preserved in the ``Bezeichnung``.  The exporter, not
this validator, is responsible for that mapping.
"""

from __future__ import annotations

import unicodedata
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
        "m",
        "mm",
        "cm",
        "km",
        "lm",
        "ll",
        "ft",
        "in",
        "yd",
        # area
        "m2",
        "cm2",
        "ft2",
        "yd2",
        # US roofing square (100 sq ft) - GitHub #320
        "sq",
        # volume
        "m3",
        "cm3",
        "l",
        "ft3",
        "gal",
        # US trade volume units - GitHub #320
        "cy",
        "bdft",
        # mass / weight - metric
        "kg",
        "g",
        "t",
        # mass / weight - imperial.  "lb" is the pound (0.45359237 kg
        # exactly) and "ton_us" the US short ton (2000 lb = 907.18474 kg
        # exactly), which is 9.3% lighter than the metric tonne "t" above.
        # They are separate canonicals on purpose: this table used to have no
        # imperial mass unit at all, so every US weight either fell through
        # into its own bucket ("lbs") or, worse, was folded into "t" and read
        # 10.2% heavy.  See the alias table for how "ton" resolves.
        "lb",
        "ton_us",
        # counts / lump
        "pcs",
        "ea",
        "no",
        "set",
        "lsum",
        "ls",
        # time / labour
        "hr",
        "h",
        "hrs",
        "hour",
        "hours",
        "day",
        "days",
        "wk",
        "month",
        # internal sentinel: section header rows have unit="section" - kept
        # in the canonical table so existing section-create paths round-trip
        # cleanly through any future ``PositionResponse`` re-validation.
        "section",
    }
)


# Canonical aliases - common synonyms that should bucket into the same
# canonical unit so aggregations don't fragment.  Locale-specific spellings
# (Cyrillic / CJK / accented) deliberately don't appear here: we keep them
# verbatim so the BOQ shows what the estimator typed.
_UNIT_ALIASES: Final[dict[str, str]] = {
    # mass - metric tonne synonyms.  "ton" / "tons" deliberately do NOT
    # appear here; see the imperial block below.
    "tonne": "t",
    "tonnes": "t",
    "metric ton": "t",
    "metric tons": "t",
    "metric tonne": "t",
    "mt": "t",
    # mass - imperial.  A US estimator who types "ton" means the short ton
    # (2000 lb = 907.18474 kg), not the 1000 kg tonne, so "ton" resolves to
    # "ton_us" and never to "t".  This is the reading the rest of the
    # platform already uses: core/unit_conversion.py, the frontend
    # unitConversion.ts twin, the BOQ unit-system validation rules and the
    # IFC unit parser all treat a bare "ton" as 907.18474 kg.  Anyone who
    # means the tonne has "t", "tonne" or "mt" above, none of which is
    # ambiguous in any market.
    #
    # Migration note: rows stored before this change may carry the literal
    # string "ton" meaning the tonne (the demo catalogue and cost-model
    # seeds do - EU material prices per tonne).  Those strings are inert:
    # units are normalised only on write, through PositionCreate /
    # PositionUpdate, never on read, so no stored quantity changes meaning.
    # A stored "ton" is re-read only if a user edits that row and resubmits
    # the unit, and then the new answer applies.
    "ton": "ton_us",
    "tons": "ton_us",
    "short ton": "ton_us",
    "short tons": "ton_us",
    "shortton": "ton_us",
    "lbs": "lb",
    "pound": "lb",
    "pounds": "lb",
    # length - meter / metre
    "metre": "m",
    "metres": "m",
    "meter": "m",
    "meters": "m",
    # area / volume plurals
    "sqm": "m2",
    "sq.m": "m2",
    "sqft": "ft2",
    "sq.ft": "ft2",
    # "sf" is the everyday US abbreviation and the area default declared by
    # us_pack - without this alias that default never resolved.
    "sf": "ft2",
    "cum": "m3",
    "cu.m": "m3",
    "cuft": "ft3",
    "cu.ft": "ft3",
    # "cf" is the volume half of the same story - the us_pack volume default,
    # which the normaliser passed through verbatim next to canonical ft3.
    "cf": "ft3",
    # US trade units - GitHub #320
    "cuyd": "cy",
    "cu.yd": "cy",
    "yd3": "cy",
    "cubicyard": "cy",
    "bf": "bdft",
    "fbm": "bdft",
    "boardfoot": "bdft",
    "boardfeet": "bdft",
    "board foot": "bdft",
    "board feet": "bdft",
    "sqyd": "yd2",
    "sq.yd": "yd2",
    "square": "sq",
    "squares": "sq",
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


# Running metre written with a prime after the "m": "m'" in Croatian,
# Serbian, Slovenian and Bosnian bills, and the same with a typographic
# apostrophe or prime when the file came out of a word processor.  The
# apostrophe is a forbidden character in the shape check below, so these are
# resolved as whole strings BEFORE that check: only these exact spellings
# pass, and an apostrophe anywhere else is still refused.
_RUNNING_METRE_PRIME_FORMS: Final[frozenset[str]] = frozenset(
    {
        "m'",  # ASCII apostrophe
        "m’",  # right single quotation mark
        "m′",  # prime
        "mʼ",  # modifier letter apostrophe
        "m´",  # acute accent, a common keyboard stand-in
    }
)

# The canonical running-metre token; the frontend shows it as "m'" in hr.
RUNNING_METRE_UNIT: Final[str] = "lm"


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
    "<>&\"'`;\\\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f"
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
      1. canonical alias from :data:`_UNIT_ALIASES` (e.g. "tonne" → "t",
         "ton" → "ton_us", "hour" → "hr") - aliases are checked first so
         synonyms collapse into one bucket regardless of whether they
         happen to also appear in the catalogue
      2. exact match in :data:`APPROVED_UNITS` (case-insensitive)
      3. CWICR-style multi-prefix forms like "100 EA", "1000 m" - returned
         as ``"<N> <unit>"`` with the trailing token canonicalised through
         the alias table when possible
      4. anything else - passed through, lower-cased, with surrounding
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
    if stripped.lower() in _RUNNING_METRE_PRIME_FORMS:
        return RUNNING_METRE_UNIT
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
    # implementation stays Unicode-clean - Python's ``str.split`` already
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


# Lump-sum and complete-set units across markets, in the folded form
# :func:`is_lump_sum_unit` compares ("pauš." -> "paus").  A row priced in one
# of these is a whole piece of work at one price, so its rate is not
# comparable with the per-metre and per-piece rates around it.
LUMP_SUM_UNITS: Final[frozenset[str]] = frozenset(
    {
        # international / English
        "lsum",
        "ls",
        "lump",
        "lump sum",
        "lumpsum",
        "lump-sum",
        "item",
        # German (GAEB "psch")
        "psch",
        "pausch",
        "pauschal",
        # Croatian, Serbian, Bosnian, Slovenian
        "paus",
        "pausal",
        "pausalno",
        # French, Belgian
        "forfait",
        "fft",
        "ens",
        # Spanish, Portuguese, Italian
        "pa",
        "gl",
        "global",
        "vb",
        "verba",
        "a corpo",
        "corpo",
        # Polish
        "rycz",
        "ryczalt",
        # complete sets priced as one ("komplet"), per the brief on P-59
        "kpl",
        "kompl",
        "komplet",
        "compl",
        "cpl",
        "компл",
        "комплект",
        # Japanese, Chinese, Korean "one lot"
        "式",
        "项",
        "식",
    }
)


def is_lump_sum_unit(unit: str | None) -> bool:
    """Return True when ``unit`` is a lump-sum or complete-set unit.

    Case, accents and trailing dots are ignored, so "pauš.", "PAUS", "Psch"
    and "kpl." all count.
    """
    if not unit:
        return False
    decomposed = unicodedata.normalize("NFKD", unit.strip().lower().rstrip("."))
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).replace("ł", "l")
    return unicodedata.normalize("NFC", folded) in LUMP_SUM_UNITS


def is_approved_unit(unit: str | None) -> bool:
    """Return True when ``unit`` has a safe shape (i.e.
    :func:`normalise_unit` doesn't reject it).

    Note: this is *not* membership in :data:`APPROVED_UNITS` - that strict
    test still exists as plain set membership for callers (GAEB exporter,
    aggregations) that need to know whether a unit maps to a canonical
    QU code.  The schema validator uses the looser shape test so locale-
    specific spellings round-trip without 422 errors.
    """
    return normalise_unit(unit) is not None


_SUPERSCRIPT_DIGITS: Final[dict[int, str]] = {ord("²"): "2", ord("³"): "3"}


def unit_identity_key(unit: str) -> str:
    """Return the key two unit spellings are compared by for identity.

    Trimmed, case-folded, with the superscript squared / cubed glyphs folded
    to digits, so ``M3``, ``m3`` and ``m³`` are one unit. Aliases are NOT
    applied here: ``tonne`` and ``t`` stay distinct keys, because this key
    answers "did the user type the same thing", not "do they measure the same
    thing".
    """
    return unit.strip().translate(_SUPERSCRIPT_DIGITS).casefold()


def is_registry_unit(unit: str | None) -> bool:
    """Return True when ``unit`` is one the platform already knows.

    That is a member of :data:`APPROVED_UNITS` or a synonym in the alias
    table, compared through :func:`unit_identity_key`. A user's personal
    custom-unit list never needs such a unit, since every picker offers it.
    """
    if not unit:
        return False
    key = unit_identity_key(unit)
    return key in APPROVED_UNITS or key in _UNIT_ALIASES


# ── Internal unit token → GAEB ``<QU>`` code ──────────────────────────────
#
# GAEB carries the unit as a short code from the market lexicon (GAEB 3.3
# Appendix B): ``Stk`` for a piece, ``psch`` for a lump sum, ``Mo`` for a
# month.  Our internal tokens are not those codes - ``pcs`` and ``lsum``
# in particular appear in no GAEB file - so every writer that emits ``<QU>``
# has to translate, and a writer that skips the translation puts a string
# into the exchange format that the format does not define.
#
# The inverse direction lives in ``importers/gaeb_xml._GAEB_TO_INTERNAL``.
# Keep the two in step: a code added here that maps back to a different
# token there will silently rewrite units on a round-trip.
GAEB_UNIT_CODES: Final[dict[str, str]] = {
    # length
    "m": "m",
    "cm": "cm",
    "mm": "mm",
    "km": "km",
    # area
    "m2": "m2",
    "m²": "m2",
    "sqm": "m2",
    # volume
    "m3": "m3",
    "m³": "m3",
    "cbm": "m3",
    "l": "l",
    "liter": "l",
    # mass
    "kg": "kg",
    "t": "t",
    "g": "g",
    "ton": "t",
    # count
    "pcs": "Stk",
    "piece": "Stk",
    "stk": "Stk",
    "stck": "Stk",
    "st": "Stk",
    "ea": "Stk",
    # lump sum
    "lsum": "psch",
    "psch": "psch",
    "lump": "psch",
    "ls": "psch",
    # time
    "h": "h",
    "hour": "h",
    "d": "d",
    "day": "d",
    "month": "Mo",
    "mo": "Mo",
    "year": "Jahr",
    "a": "Jahr",
    # volume flow
    "m3/h": "m3/h",
}

# GAEB DA XML 3.3 carries the unit as a short code; our own profile schemas
# (``boq/gaeb_profile/oce-gaeb-3.3-x8*.xsd``) cap it at 10 characters.
GAEB_UNIT_MAX_CHARS: Final[int] = 10


def to_gaeb_unit_code(unit: str | None) -> str:
    """Return the GAEB ``<QU>`` code for an internal unit token.

    Falls back to the input, stripped and length-capped, when the token has
    no entry in :data:`GAEB_UNIT_CODES` - a locale-specific label is better
    carried through imperfectly than dropped, and the container/export
    formats accept a free-form short string there. Returns ``""`` for an
    empty input so the caller can omit the element entirely rather than
    write an empty one.

    Args:
        unit: Internal unit token (``"m3"``, ``"lsum"``, ``"pcs"`` ...).

    Returns:
        The GAEB code, or ``""`` when there is nothing to write.
    """
    text = (unit or "").strip()
    if not text:
        return ""
    mapped = GAEB_UNIT_CODES.get(text.lower())
    return (mapped or text)[:GAEB_UNIT_MAX_CHARS]
