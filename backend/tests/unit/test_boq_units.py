"""Tests for the BOQ unit normaliser.

The normaliser used to be a strict allowlist that 422'd anything outside
the curated catalogue.  Locale spellings (Romanian "Bucat", Bulgarian
"бр", Russian "шт", German "Stück") tripped that gate every CWICR import.
The policy is now sanitise-don't-gate: canonicalise common synonyms,
preserve everything else verbatim, reject only genuinely unsafe shapes.
"""

from __future__ import annotations

import pytest

from app.modules.boq.units import APPROVED_UNITS, is_approved_unit, normalise_unit


# ── Canonical catalogue round-trips ────────────────────────────────────


from app.modules.boq.units import _UNIT_ALIASES  # noqa: E402  (test internal)


@pytest.mark.parametrize(
    "unit",
    sorted(u for u in APPROVED_UNITS if u not in _UNIT_ALIASES),
)
def test_canonical_units_round_trip(unit: str) -> None:
    """Every catalogue entry that *isn't* aliased round-trips unchanged.

    Entries that have aliases (e.g. "hour" → "hr", "hours" → "hr",
    "days" → "day") collapse to the canonical form by design — they
    appeared in the catalogue historically but the alias map is the
    source of truth.
    """
    assert normalise_unit(unit) == unit
    assert normalise_unit(unit.upper()) == unit


# ── Alias canonicalisation ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("ton", "t"),
        ("Tons", "t"),
        ("TONNE", "t"),
        ("tonnes", "t"),
        ("metre", "m"),
        ("Meters", "m"),
        ("sqm", "m2"),
        ("sqft", "ft2"),
        ("cum", "m3"),
        ("each", "ea"),
        ("piece", "pcs"),
        ("nr", "no"),
        ("lump", "lsum"),
        ("hour", "hr"),
        ("weeks", "wk"),
    ],
)
def test_alias_canonicalises(alias: str, canonical: str) -> None:
    assert normalise_unit(alias) == canonical


# ── Locale spellings — the actual user-blocking case ──────────────────


@pytest.mark.parametrize(
    "unit",
    [
        # Romanian
        "Bucat",
        "buc",
        "bucati",
        # Bulgarian (Cyrillic)
        "бр",
        "брой",
        # Russian
        "шт",
        "м3",
        "м²",
        # German
        "Stück",
        "Mörtel",
        # CJK
        "個",
        "件",
        # Greek
        "μ",
        # Accented Latin
        "année",
        "día",
        # Trade slang
        "man-day",
        "lin.m",
        "MWh",
        "kg/m",
        "%",
    ],
)
def test_locale_spellings_pass_through(unit: str) -> None:
    """All of these were rejected pre-v2.6.28 and now must round-trip."""
    result = normalise_unit(unit)
    assert result is not None, f"{unit!r} should be accepted"
    assert result == unit.strip().lower()
    assert is_approved_unit(unit)


# ── CWICR multi-prefix forms ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("input_unit", "expected"),
    [
        ("100 EA", "100 ea"),
        ("1000 m", "1000 m"),
        ("10 kg", "10 kg"),
        ("100 tons", "100 t"),
        ("1000 metres", "1000 m"),
        ("100 Stück", "100 stück"),
        ("100 шт", "100 шт"),
    ],
)
def test_multi_prefix_forms(input_unit: str, expected: str) -> None:
    assert normalise_unit(input_unit) == expected


# ── Whitespace / case handling ────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  m  ", "m"),
        ("\tkg\n", "kg"),
        ("M2", "m2"),
        ("PCS", "pcs"),
    ],
)
def test_whitespace_and_case(raw: str, expected: str) -> None:
    assert normalise_unit(raw) == expected


# ── Empty / overlong / unsafe shapes — must reject ────────────────────


@pytest.mark.parametrize(
    "unit",
    [
        # empty / whitespace-only
        "",
        "   ",
        # overlong
        "a" * 31,
        "x" * 50,
        # leading non-letter / non-digit
        ".m",
        "-kg",
        "/m2",
        # forbidden characters — HTML / SQL / shell injection vectors
        "<script>",
        "m';--",
        'm"',
        "m`",
        "m\\n",
        "m;rm",
        "m&amp;",
        # control characters (embedded — surrounding whitespace is
        # stripped before the shape check, so "m\n" alone would normalise
        # to "m"; we test embedded control bytes that can't be stripped).
        "m\x00",
        "m\x01",
        "m\x07x",
        "m\t" + "x" * 30,  # also overlong after the tab
    ],
)
def test_unsafe_shapes_rejected(unit: str) -> None:
    assert normalise_unit(unit) is None
    assert not is_approved_unit(unit)


def test_none_returns_none() -> None:
    assert normalise_unit(None) is None
    assert not is_approved_unit(None)


# ── Important: "xyz" is now ACCEPTED (was rejected pre-v2.6.28) ───────


def test_xyz_now_accepted() -> None:
    """The pre-v2.6.28 strict allowlist 422'd "xyz".  Under sanitise-don't
    gate it round-trips as a custom unit.  This is intentional: estimators
    coin novel units (project codes, internal labels) and the API must
    not block on a curated catalogue.
    """
    assert normalise_unit("xyz") == "xyz"
    assert is_approved_unit("xyz")


# ── APPROVED_UNITS membership stays a strict test ─────────────────────


def test_approved_units_membership_strict() -> None:
    """``APPROVED_UNITS`` is still a *strict* set — callers that need to
    know whether a unit maps to a canonical GAEB QU code (the exporter,
    aggregations) check membership directly, not via :func:`normalise_unit`.
    """
    assert "m" in APPROVED_UNITS
    assert "Bucat".lower() not in APPROVED_UNITS
    assert "xyz" not in APPROVED_UNITS
