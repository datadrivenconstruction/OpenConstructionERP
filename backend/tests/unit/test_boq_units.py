"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the BOQ unit normaliser.

The normaliser used to be a strict allowlist that 422'd anything outside
the curated catalogue.  Locale spellings (Romanian "Bucat", Bulgarian
"бр", Russian "шт", German "Stück") tripped that gate every CWICR import.
The policy is now sanitise-don't-gate: canonicalise common synonyms,
preserve everything else verbatim, reject only genuinely unsafe shapes.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.unit_conversion import convert_between

# ── Canonical catalogue round-trips ────────────────────────────────────
from app.modules.boq.units import (
    _UNIT_ALIASES,  # noqa: E402  (test internal)
    APPROVED_UNITS,
    is_approved_unit,
    normalise_unit,
)


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
        ("ton", "ton_us"),
        ("Tons", "ton_us"),
        ("TONNE", "t"),
        ("tonnes", "t"),
        ("mt", "t"),
        ("lbs", "lb"),
        ("LBS", "lb"),
        ("pound", "lb"),
        ("Pounds", "lb"),
        ("short ton", "ton_us"),
        ("metre", "m"),
        ("Meters", "m"),
        ("sqm", "m2"),
        ("sqft", "ft2"),
        ("sf", "ft2"),
        ("SF", "ft2"),
        ("cum", "m3"),
        ("cf", "ft3"),
        ("CF", "ft3"),
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
        ("100 tons", "100 ton_us"),
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


# ── Imperial mass: a typed "ton" is the short ton, never the tonne ────
#
# The alias table used to fold "ton" / "tons" into "t", so a US estimator
# who typed "ton" (2000 lb = 907.18474 kg) had the quantity read as a
# 1000 kg tonne and every such weight came out 10.2% heavy.  These tests
# pin the factor, not just the token, so the defect cannot come back
# through a plausible-looking rename.


def test_imperial_mass_canonicals_exist() -> None:
    """``APPROVED_UNITS`` carries an imperial mass unit at all.

    Before this fix the catalogue had only kg / g / t, so ``lbs`` - the
    weight default declared by us_pack - never resolved and formed its own
    bucket beside the canonical units.
    """
    assert "lb" in APPROVED_UNITS
    assert "ton_us" in APPROVED_UNITS
    # Neither is a self-alias: an alias entry would drop the new canonical
    # out of test_canonical_units_round_trip, which skips aliased entries.
    assert "lb" not in _UNIT_ALIASES
    assert "ton_us" not in _UNIT_ALIASES


def test_typed_ton_resolves_to_the_short_ton_with_its_factor() -> None:
    """A typed "ton" resolves to ``ton_us``, which weighs 907.18474 kg.

    Asserting the token alone would pass against a canonical wired to the
    wrong factor, so the mass is checked through the dimension table that
    the takeoff and PDF paths actually convert with.
    """
    assert normalise_unit("ton") == "ton_us"
    assert normalise_unit("tons") == "ton_us"
    assert normalise_unit("ton") != "t"

    short_ton_kg = convert_between(Decimal(1), "ton_us", "kg")
    assert short_ton_kg is not None
    # 1 short ton = 907.18474 kg exactly.  The dimension table stores the
    # reciprocal (units per kg), which has no finite decimal expansion, so
    # the round trip is exact only to the precision that table carries.
    assert abs(short_ton_kg - Decimal("907.18474")) < Decimal("0.0001")

    # The reading this replaces: a tonne is 1000 kg, i.e. 10.2% heavier.
    tonne_kg = convert_between(Decimal(1), "t", "kg")
    assert tonne_kg == Decimal(1000)
    assert short_ton_kg < tonne_kg


def test_pound_resolves_with_its_factor() -> None:
    """``lbs`` / ``pound`` / ``pounds`` resolve to ``lb`` at 0.45359237 kg."""
    for spelling in ("lb", "lbs", "LBS", "pound", "pounds", "Pounds"):
        assert normalise_unit(spelling) == "lb", spelling

    pound_kg = convert_between(Decimal(1), "lb", "kg")
    assert pound_kg is not None
    # 1 lb = 0.45359237 kg exactly.  The tolerance is wider than the exact
    # factor deserves because the table's pre-existing "lb": "2.20462" is a
    # 6-significant-figure reciprocal; it is left as it stands so the
    # backend table and its unitConversion.ts twin do not drift apart.
    assert abs(pound_kg - Decimal("0.45359237")) < Decimal("0.000001")


def test_metric_tonne_is_untouched() -> None:
    """Existing metric users keep "t", and every tonne spelling still folds
    into it - the fix must not have moved the metric side.
    """
    for spelling in ("t", "T", "tonne", "tonnes", "TONNE", "mt", "metric ton", "metric tonne"):
        assert normalise_unit(spelling) == "t", spelling
    assert convert_between(Decimal(1), "t", "kg") == Decimal(1000)


def test_short_ton_and_tonne_are_different_buckets() -> None:
    """The two must never collapse into one another in either direction."""
    assert convert_between(Decimal(1), "ton_us", "t") != Decimal(1)
    converted = convert_between(Decimal(1), "t", "ton_us")
    assert converted is not None
    # 1 tonne = 1.10231 short tons.
    assert abs(converted - Decimal("1.10231")) < Decimal("0.0001")


# ── Regional pack default units all resolve ───────────────────────────
#
# Each regional pack declares ``default_units``; the quantity ones become
# BOQ position units, so a default that does not resolve to a canonical
# silently forms its own bucket.  That is exactly how us_pack's "lbs" hid
# the missing imperial mass unit until now.

# Dimensions whose default becomes a BOQ position unit.  "temperature" and
# "pressure" are project metadata, never a quantity on a BOQ line, and
# "°C" / "°F" are not even valid unit shapes (they start with a symbol, so
# normalise_unit rejects them outright).  They are excluded by name rather
# than by skipping rows, so the gate below still covers every pack.
_QUANTITY_DIMENSIONS: frozenset[str] = frozenset({"length", "area", "volume", "weight"})

# The declared defaults that deliberately do NOT fold to a canonical token.
# units.py preserves squared / cubed glyphs and non-Latin scripts verbatim
# on purpose (module docstring, resolution rule 4) so a BOQ shows what the
# estimator typed.  This maps each such spelling to the canonical it is the
# regional writing of, so the gate stays a gate instead of an exemption.
_SCRIPT_EQUIVALENTS: dict[str, str] = {
    "m²": "m2",
    "m³": "m3",
    # russia_pack writes its defaults in Cyrillic.
    "м": "m",
    "м²": "m2",
    "м³": "m3",
    "кг": "kg",
    # china_pack writes its defaults as Chinese words, which is what a
    # GB 50500 bill contains. Same situation as the Cyrillic block above: the
    # spellings are deliberately preserved verbatim by units.py, so the gate
    # needs to know which canonical each one is the regional writing of.
    "米": "m",
    "平方米": "m2",
    "立方米": "m3",
    "千克": "kg",
}


def _pack_default_units() -> list[tuple[str, str, str]]:
    """Return ``(pack, dimension, declared unit)`` for every regional pack.

    Discovered from the filesystem rather than listed, so a pack added
    later is covered by the gate without anyone remembering to add it.
    """
    import importlib
    from pathlib import Path

    modules_dir = Path(__file__).resolve().parents[2] / "app" / "modules"
    rows: list[tuple[str, str, str]] = []
    for pack_dir in sorted(modules_dir.glob("*_pack")):
        if not (pack_dir / "config.py").is_file():
            continue
        config = importlib.import_module(f"app.modules.{pack_dir.name}.config")
        declared = getattr(config, "PACK_CONFIG", {}).get("default_units") or {}
        rows.extend((pack_dir.name, dimension, unit) for dimension, unit in sorted(declared.items()))
    return rows


_PACK_DEFAULT_UNITS = _pack_default_units()


def test_pack_discovery_found_the_packs() -> None:
    """Guard the gate itself: a discovery that silently found nothing would
    make every parametrized case below vacuous.
    """
    packs = {pack for pack, _, _ in _PACK_DEFAULT_UNITS}
    assert len(packs) >= 10, f"expected every regional pack, found {sorted(packs)}"
    assert "us_pack" in packs
    quantity_rows = [row for row in _PACK_DEFAULT_UNITS if row[1] in _QUANTITY_DIMENSIONS]
    assert len(quantity_rows) == 4 * len(packs)


def test_pack_dimensions_are_all_accounted_for() -> None:
    """Every declared dimension is either gated as a quantity or knowingly
    excluded.  A pack inventing a new one (say "density") fails here rather
    than slipping past the gate unnoticed.
    """
    declared = {dimension for _, dimension, _ in _PACK_DEFAULT_UNITS}
    excluded = {"temperature", "pressure"}
    assert declared <= (_QUANTITY_DIMENSIONS | excluded), f"unclassified dimension in {sorted(declared)}"


@pytest.mark.parametrize(
    ("pack", "dimension", "declared"),
    [row for row in _PACK_DEFAULT_UNITS if row[1] in _QUANTITY_DIMENSIONS],
    ids=[f"{row[0]}-{row[1]}" for row in _PACK_DEFAULT_UNITS if row[1] in _QUANTITY_DIMENSIONS],
)
def test_pack_default_quantity_units_resolve(pack: str, dimension: str, declared: str) -> None:
    """Every pack's declared quantity default resolves to a canonical unit.

    us_pack's ``weight: "lbs"`` is the case this was written for: it passed
    through verbatim and formed its own bucket beside the canonical units
    because the catalogue had no imperial mass entry.
    """
    normalised = normalise_unit(declared)
    assert normalised is not None, f"{pack}.{dimension} = {declared!r} has an unsafe shape"
    canonical = _SCRIPT_EQUIVALENTS.get(normalised, normalised)
    assert canonical in APPROVED_UNITS, f"{pack}.{dimension} = {declared!r} resolves to {normalised!r}, not a canonical"


def test_us_pack_weight_default_resolves_to_the_pound() -> None:
    """The specific regression: us_pack declares its weight default as
    "lbs", which must now land on the pound canonical.
    """
    from app.modules.us_pack.config import PACK_CONFIG

    assert normalise_unit(PACK_CONFIG["default_units"]["weight"]) == "lb"


# ── A pack's own units must satisfy the rule that judges that pack ─────
#
# The gate above proves a declared default is a *well-formed* unit. It does
# not prove anything reads it as the measurement system the pack claims, and
# those are different questions. ``BOQUnitSystemConsistencyRule`` decides
# whether a position belongs to the other system by set membership, and a
# unit in neither set is silently ignored rather than flagged. So a pack
# whose own declared units were missing from its own system's set made the
# rule blind on exactly that market: us_pack's "sf" / "cf" and russia_pack's
# Cyrillic spellings were all absent.
#
# Written as a property over every pack rather than as literals for the six
# that were wrong, so a pack added later cannot reintroduce the defect.


def _pack_measurement_systems() -> dict[str, str]:
    """Return ``{pack module name: declared measurement_system}``."""
    import importlib
    from pathlib import Path

    modules_dir = Path(__file__).resolve().parents[2] / "app" / "modules"
    systems: dict[str, str] = {}
    for pack_dir in sorted(modules_dir.glob("*_pack")):
        if not (pack_dir / "config.py").is_file():
            continue
        config = importlib.import_module(f"app.modules.{pack_dir.name}.config")
        declared = getattr(config, "PACK_CONFIG", {}).get("measurement_system")
        if isinstance(declared, str) and declared.strip():
            systems[pack_dir.name] = declared.strip().lower()
    return systems


_PACK_MEASUREMENT_SYSTEMS = _pack_measurement_systems()


def test_every_pack_declares_a_measurement_system() -> None:
    """Guard the property below: a pack missing the field would be skipped.

    The property is parametrized over declared units, so a pack whose
    ``measurement_system`` is absent would quietly drop out of the check
    rather than fail it.
    """
    packs = {pack for pack, _, _ in _PACK_DEFAULT_UNITS}
    missing = packs - set(_PACK_MEASUREMENT_SYSTEMS)
    assert not missing, f"packs declaring units but no measurement_system: {sorted(missing)}"
    assert set(_PACK_MEASUREMENT_SYSTEMS.values()) <= {"metric", "imperial"}


@pytest.mark.parametrize(
    ("pack", "dimension", "declared"),
    [row for row in _PACK_DEFAULT_UNITS if row[1] in _QUANTITY_DIMENSIONS],
    ids=[f"{row[0]}-{row[1]}" for row in _PACK_DEFAULT_UNITS if row[1] in _QUANTITY_DIMENSIONS],
)
def test_pack_default_units_are_recognised_by_the_unit_system_rule(pack: str, dimension: str, declared: str) -> None:
    """Every declared quantity default belongs to its own pack's system.

    Membership, not absence, is what is asserted: the unit has to be *in* the
    set for the system the pack declares. Being in neither set is the failure
    this exists to catch, because the rule treats an unknown unit as nothing
    to say rather than as a mismatch.
    """
    from app.core.validation.rules import _IMPERIAL_BOQ_UNITS, _METRIC_BOQ_UNITS

    system = _PACK_MEASUREMENT_SYSTEMS[pack]
    expected = _IMPERIAL_BOQ_UNITS if system == "imperial" else _METRIC_BOQ_UNITS
    other = _METRIC_BOQ_UNITS if system == "imperial" else _IMPERIAL_BOQ_UNITS
    unit = declared.strip().lower()

    assert unit in expected, f"{pack}.{dimension} = {declared!r} is not a recognised {system} unit"
    # The two sets must not overlap on this unit either, or the rule would
    # flag a pack's own default as belonging to the opposite system.
    assert unit not in other, f"{pack}.{dimension} = {declared!r} counts as both systems"
