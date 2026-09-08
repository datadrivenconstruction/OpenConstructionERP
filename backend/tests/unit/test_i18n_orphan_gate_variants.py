# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A regional variant is covered by its base language, not by English.

Four locale files here carry only the words that differ from their base:
es-MX, es-CL and es-CO resolve through es, pt-BR through pt. en-US joined
them and carries 1499 keys against English's 33771, which is the whole point
of an overlay. The orphan guard had no concept of any of this and counted
every key a variant does not declare as a hole, so one deliberate overlay
produced 25280 errors and the cheapest way to make them stop would have been
to paste a full copy of English into en-US.ts.

The distinction the guard has to draw: resolving into the base language is
the designed behaviour and the reader gets their own language, while
resolving past the base into English is exactly the silent defect the guard
was written for.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_GATE = Path(__file__).resolve().parents[3] / "scripts" / "check_i18n_orphan_keys.py"
_spec = importlib.util.spec_from_file_location("check_i18n_orphan_keys", _GATE)
assert _spec and _spec.loader, f"gate script not found at {_GATE}"
gate = importlib.util.module_from_spec(_spec)
sys.modules["check_i18n_orphan_keys"] = gate
_spec.loader.exec_module(gate)


def _bases(by_locale: dict[str, set[str]]) -> dict[str, str | None]:
    return {stem: gate._base_of(stem, by_locale) for stem in by_locale}


def test_a_variant_is_covered_by_its_base_language() -> None:
    by_locale = {
        "en": {"boq.title"},
        "es": {"boq.title"},
        "es-MX": set(),
    }

    assert gate.missing_locales("boq.title", by_locale, _bases(by_locale)) == []


def test_a_variant_is_not_covered_when_its_base_is_missing_the_key_too() -> None:
    """es answers nothing, so a Mexican reader lands in English."""
    by_locale = {
        "en": {"boq.title"},
        "es": set(),
        "es-MX": set(),
    }

    assert gate.missing_locales("boq.title", by_locale, _bases(by_locale)) == ["es", "es-MX"]


def test_english_answering_a_key_does_not_cover_anyone_else() -> None:
    """The guard would be worthless otherwise: English always answers."""
    by_locale = {"en": {"boq.title"}, "de": set(), "fr": set()}

    assert gate.missing_locales("boq.title", by_locale, _bases(by_locale)) == ["de", "fr"]


def test_en_us_is_covered_by_english_because_english_is_its_language() -> None:
    by_locale = {"en": {"boq.title"}, "en-US": set(), "de": {"boq.title"}}

    assert gate.missing_locales("boq.title", by_locale, _bases(by_locale)) == []


def test_a_variant_with_no_base_file_resolves_to_english_and_counts_as_missing() -> None:
    """zh-TW beside no zh.ts falls through to English like any other locale."""
    by_locale = {"en": {"boq.title"}, "zh-TW": set()}

    assert gate._base_of("zh-TW", by_locale) is None
    assert gate.missing_locales("boq.title", by_locale, _bases(by_locale)) == ["zh-TW"]


def test_a_plural_form_in_the_base_still_reaches_the_variant() -> None:
    by_locale = {
        "en": {"boq.count_one", "boq.count_other"},
        "es": {"boq.count_one", "boq.count_many", "boq.count_other"},
        "es-CL": set(),
    }

    assert gate.missing_locales("boq.count", by_locale, _bases(by_locale)) == []


def test_the_real_tree_derives_the_bases_the_app_declares() -> None:
    """Not a fixture: the guard has to agree with frontend/src/app/i18n.ts.

    That file resolves es-MX, es-CL and es-CO through es and pt-BR through
    pt, and notes that i18next expands en-GB and en-US into ['en-GB', 'en']
    and ['en-US', 'en'] before it consults the map at all. If a locale file
    is added whose base is derived differently from what the app does, this
    is where it shows; when English (UK) joined the picker it showed here
    first, on three shards, because the list below was a copy of the tree.
    """
    repo = Path(__file__).resolve().parents[3]
    locales = {p.stem for p in (repo / "frontend" / "src" / "app" / "locales").glob("*.ts")}
    locales -= {"index", "types"}
    assert len(locales) > 30, f"only {len(locales)} locale files found, this assertion is not about the tree"

    by_locale = {stem: set() for stem in locales}
    derived = {stem: gate._base_of(stem, by_locale) for stem in locales if gate._base_of(stem, by_locale)}

    assert derived == {
        "es-MX": "es",
        "es-CL": "es",
        "es-CO": "es",
        "pt-BR": "pt",
        "en-GB": "en",
        "en-US": "en",
    }
