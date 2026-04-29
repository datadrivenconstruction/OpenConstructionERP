"""Unit tests for CWICR cost-database translation tables.

Covers the small fixed-vocabulary lookup that fills in localized mirror
fields next to CWICR's frozen-German source columns
(``classification.category``, ``metadata.variant_stats.unit / .group``,
per-component ``unit``).

The translations are part of the data-layer contract — frontend components
read ``foo_localized || foo`` — so a regression that drops a key would
silently leak German into a non-German UI.  These tests guard the most
visible tokens (units like ``Stück`` / ``Std.``, the ``Abteilung`` /
``Abschnitt`` / ``Ressource`` short labels, and ``BAUARBEITEN``).
"""

from __future__ import annotations

import pytest

from app.modules.costs.translations import (
    SUPPORTED_LOCALES,
    load_translations,
    localize_cost_row,
    translate_group_list,
    translate_token,
    translate_unit_list,
)


# ── Translation table contents ───────────────────────────────────────────


class TestLoadTranslations:
    """Each shipped locale must load to a non-empty dict and cover the
    short tokens that surface most prominently in the UI."""

    @pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
    def test_locale_file_loads(self, locale: str) -> None:
        table = load_translations(locale)
        assert table, f"Locale {locale!r} produced an empty translation table"
        # At minimum, the four BG-spec tokens must be present.
        for de_token in ("Abteilung", "Abschnitt", "Ressource", "100 Stück"):
            assert de_token in table, (
                f"Locale {locale!r} is missing a translation for {de_token!r}"
            )

    def test_unknown_locale_returns_empty(self) -> None:
        # Defensive: an unsupported locale must not raise — the lookup
        # gracefully falls back to the German source value.
        assert load_translations("xx") == {}
        assert load_translations("") == {}

    def test_de_is_identity(self) -> None:
        table = load_translations("de")
        # German source is its own translation — round-trip stability.
        for k, v in table.items():
            assert k == v, f"de.json mapping {k!r} -> {v!r} should be identity"


# ── Per-locale token spot-checks ─────────────────────────────────────────


class TestBulgarianTokens:
    """The four canonical tokens called out in the bug report."""

    def test_short_labels(self) -> None:
        assert translate_token("Abteilung", "bg") == "Отдел"
        assert translate_token("Abschnitt", "bg") == "Раздел"
        assert translate_token("Ressource", "bg") == "Ресурс"

    def test_unit_token(self) -> None:
        assert translate_token("100 Stück", "bg") == "100 бр"
        assert translate_token("Stück", "bg") == "бр"

    def test_hour_abbreviations(self) -> None:
        assert translate_token("Std.", "bg") == "ч"
        assert translate_token("Masch.-Std.", "bg") == "маш.-ч"


class TestRomanianTokens:
    def test_short_labels(self) -> None:
        assert translate_token("Abteilung", "ro") == "Departament"
        assert translate_token("Abschnitt", "ro") == "Secțiune"
        assert translate_token("Ressource", "ro") == "Resursă"

    def test_unit_token(self) -> None:
        assert translate_token("100 Stück", "ro") == "100 buc"
        assert translate_token("Stück", "ro") == "buc"


class TestSwedishTokens:
    def test_short_labels(self) -> None:
        assert translate_token("Abteilung", "sv") == "Avdelning"
        assert translate_token("Abschnitt", "sv") == "Avsnitt"
        assert translate_token("Ressource", "sv") == "Resurs"

    def test_unit_token(self) -> None:
        assert translate_token("100 Stück", "sv") == "100 st"
        assert translate_token("Stück", "sv") == "st"


# ── Fallback behaviour ───────────────────────────────────────────────────


class TestFallbackToGerman:
    """An unknown German token must round-trip unchanged so the UI never
    blanks out — better wrong than misleading."""

    def test_unknown_token_for_known_locale(self) -> None:
        # Made-up German term that no locale will ever ship a translation for.
        weird = "Irgendwas-Spezialwerkzeug-XYZ"
        for loc in SUPPORTED_LOCALES:
            assert translate_token(weird, loc) == weird

    def test_known_token_for_unknown_locale(self) -> None:
        # The lookup table for "xx" doesn't exist → fall back to source.
        assert translate_token("Stück", "xx") == "Stück"
        assert translate_token("Abteilung", "xx") == "Abteilung"

    def test_empty_input(self) -> None:
        assert translate_token("", "bg") == ""
        assert translate_token("", "xx") == ""


# ── Compound-value splitters ─────────────────────────────────────────────


class TestUnitListTranslation:
    def test_compound_unit_list_ro(self) -> None:
        # Real CWICR variant_stats.unit value seen in RO_BUCHAREST.
        result = translate_unit_list("100 Stück, kg, t, St", "ro")
        # Each comma-separated token is translated independently;
        # `kg`/`t` map to themselves.
        assert result == "100 buc, kg, t, buc"

    def test_compound_unit_list_bg(self) -> None:
        result = translate_unit_list("100 Stück, kg, t", "bg")
        assert result == "100 бр, кг, т"

    def test_compound_unit_list_sv(self) -> None:
        result = translate_unit_list("Komplett, Stück", "sv")
        assert result == "komplett, st"

    def test_empty_input(self) -> None:
        assert translate_unit_list("", "ro") == ""

    def test_unknown_token_preserved(self) -> None:
        # Unknown leading token stays German; known trailing one translates.
        result = translate_unit_list("MysteriousUnit, Stück", "ro")
        assert result == "MysteriousUnit, buc"


class TestGroupListTranslation:
    def test_kv_pair_split_ro(self) -> None:
        # Real CWICR variant_stats.group value: "key=value, key=value"
        result = translate_group_list(
            "m²=Geonetze und Geogitter, Stück=Geotextilien",
            "ro",
        )
        assert result == "m²=Geoplase și geogrile, buc=Geotextile"

    def test_kv_pair_split_bg(self) -> None:
        result = translate_group_list("Stück=Geotextilien", "bg")
        assert result == "бр=Геотекстил"

    def test_passthrough_when_no_eq(self) -> None:
        # No `=` separator → behaves like translate_token on the whole string.
        result = translate_group_list("Stahlseile", "ro")
        assert result == "Cabluri de oțel"

    def test_unknown_value_preserves_german(self) -> None:
        # The KEY translates, the unknown VALUE stays German.
        result = translate_group_list("Stück=Phantasiematerial", "ro")
        assert result == "buc=Phantasiematerial"


# ── localize_cost_row integration ────────────────────────────────────────


class TestLocalizeCostRow:
    """Composite helper called from the API router. Mutates and returns
    the dict-shaped cost row, adding ``*_localized`` mirror keys without
    touching the originals."""

    def test_classification_category_is_mirrored(self) -> None:
        cls = {"category": "BAUARBEITEN", "collection": "Lucrări de terasament"}
        cls2, _, _ = localize_cost_row(
            classification=cls,
            metadata=None,
            components=None,
            locale="ro",
        )
        # Original stays put.
        assert cls2["category"] == "BAUARBEITEN"
        # New mirror key with localized value.
        assert cls2["category_localized"] == "LUCRĂRI DE CONSTRUCȚII"
        # Untouched siblings.
        assert cls2["collection"] == "Lucrări de terasament"

    def test_variant_stats_unit_and_group_are_mirrored(self) -> None:
        meta = {
            "variant_stats": {
                "unit": "100 Stück, kg, t, St",
                "group": "m²=Geonetze und Geogitter, Stück=Geotextilien",
                "min": 1.0,
                "max": 5.0,
            }
        }
        _, meta2, _ = localize_cost_row(
            classification=None,
            metadata=meta,
            components=None,
            locale="ro",
        )
        vs = meta2["variant_stats"]
        # Originals preserved.
        assert vs["unit"] == "100 Stück, kg, t, St"
        assert vs["group"] == "m²=Geonetze und Geogitter, Stück=Geotextilien"
        # Localized mirrors added.
        assert vs["unit_localized"] == "100 buc, kg, t, buc"
        assert vs["group_localized"] == "m²=Geoplase și geogrile, buc=Geotextile"
        # Numeric stats untouched.
        assert vs["min"] == 1.0
        assert vs["max"] == 5.0

    def test_components_unit_is_mirrored(self) -> None:
        comps = [
            {"name": "Bulldozer", "unit": "Masch.-Std.", "cost": 100.0},
            {"name": "Worker", "unit": "Std.", "cost": 60.0},
            {"name": "Steel", "unit": "kg", "cost": 1.5},
        ]
        _, _, comps2 = localize_cost_row(
            classification=None,
            metadata=None,
            components=comps,
            locale="ro",
        )
        assert comps2[0]["unit_localized"] == "ora-mașină"
        assert comps2[1]["unit_localized"] == "ora"
        assert comps2[2]["unit_localized"] == "kg"  # identity for known unit
        # Originals preserved.
        assert comps2[0]["unit"] == "Masch.-Std."

    def test_unknown_locale_does_not_crash(self) -> None:
        cls = {"category": "BAUARBEITEN"}
        meta = {"variant_stats": {"unit": "Stück", "group": "m²=Geotextilien"}}
        comps = [{"unit": "Std."}]
        cls2, meta2, comps2 = localize_cost_row(
            classification=cls,
            metadata=meta,
            components=comps,
            locale="xx",
        )
        # Mirror keys are still added, but they hold the German source.
        assert cls2["category_localized"] == "BAUARBEITEN"
        assert meta2["variant_stats"]["unit_localized"] == "Stück"
        assert comps2[0]["unit_localized"] == "Std."

    def test_none_inputs_are_safe(self) -> None:
        cls, meta, comps = localize_cost_row(
            classification=None,
            metadata=None,
            components=None,
            locale="bg",
        )
        # Empty placeholder dicts/list — no localization to perform.
        assert cls == {}
        assert meta == {}
        assert comps == []
