"""Every cost base card resolves to a file in its own language, or says it has none.

A national base's market card promises two things: the market's prices and the
market's language. Before this matrix existed, an English card on a base that had
been switched to Chinese or French kept that text, and nothing checked that a
French card pointed at a French file. Each card is checked here against the file
the loader would read.
"""

from __future__ import annotations

import pytest

from app.modules.costs import base_registry

_VARIANTS = base_registry.iter_variants()
_MARKET_CARDS = [v for v in _VARIANTS if v.market_catalog]


def _card_id(v: base_registry.BaseVariant) -> str:
    return v.variant_id


@pytest.mark.parametrize("variant", _MARKET_CARDS, ids=_card_id)
def test_market_card_text_source_is_in_the_cards_language(variant: base_registry.BaseVariant) -> None:
    """The file a market card's text comes from is in that card's language."""
    lang = base_registry.normalize_lang_code(variant.lang_code)
    source = base_registry.text_source_region(variant.base_region, lang)
    shown = base_registry.variant_text_lang(variant)
    if source is None:
        # No file holds the base in this language: the card must not claim it.
        assert shown != lang
        assert shown == base_registry.home_language_code(variant.base_region)
        return
    assert shown == lang
    if source == variant.base_region:
        assert base_registry.home_parquet_text_lang(variant.base_region) == lang
    else:
        path = base_registry.national_language_workitems_files()[source]
        assert f"/{lang.upper()}___DDC_CWICR/" in path
        assert path.endswith(f"_{lang}_workitems_costs_resources_DDC_CWICR.parquet")
        # And never the home parquet under another name.
        assert path != base_registry.variant_by_region(variant.base_region).workitems_path


@pytest.mark.parametrize(
    ("base_region", "lang", "expected"),
    [
        # The report: a French card on the Turkish or Chinese base.
        ("TR_NATIONAL", "fr", "TR_NATIONAL_fr"),
        ("ZH_CHINA", "fr", "ZH_CHINA_fr"),
        # English comes from the home parquet, which is English everywhere but Turkiye.
        ("ZH_CHINA", "en", "ZH_CHINA"),
        ("BR_NATIONAL", "en", "BR_NATIONAL"),
        ("TR_NATIONAL", "en", None),
        # A locale served by another language's file.
        ("TR_NATIONAL", "es-MX", "TR_NATIONAL_es"),
        # Global markets are not swapped at all.
        ("FR_PARIS", "fr", None),
    ],
)
def test_text_source_region(base_region: str, lang: str, expected: str | None) -> None:
    assert base_registry.text_source_region(base_region, lang) == expected


def test_only_turkiye_english_cards_fall_back_and_they_say_turkish() -> None:
    """The one gap in the published data is English text for Turkiye."""
    fallbacks = {
        v.variant_id
        for v in _MARKET_CARDS
        if base_registry.variant_text_lang(v) != base_registry.normalize_lang_code(v.lang_code)
    }
    assert fallbacks, "expected the Turkiye English cards to fall back"
    for vid in fallbacks:
        v = next(x for x in _MARKET_CARDS if x.variant_id == vid)
        assert v.base_region == "TR_NATIONAL"
        assert v.lang_code == "en"
        assert base_registry.variant_text_lang(v) == "tr"


def test_public_catalog_carries_the_real_text_language() -> None:
    cat = base_registry.public_catalog()
    by_id = {v["variant_id"]: v for fam in cat["families"] for v in fam["variants"]}
    assert by_id["TR_NATIONAL:FR_PARIS_fr"]["text_lang_code"] == "fr"
    assert by_id["ZH_CHINA:FR_PARIS_fr"]["text_lang_code"] == "fr"
    assert by_id["ZH_CHINA:GB_LONDON_en"]["text_lang_code"] == "en"
    assert by_id["TR_NATIONAL:GB_LONDON_en"]["text_lang_code"] == "tr"
    assert by_id["FR_PARIS"]["text_lang_code"] == "fr"
