"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Home-language resolution and locale aliasing for the national cost bases."""

from app.modules.costs import base_registry


def test_home_language_code_returns_the_bases_own_language() -> None:
    """A national base resolves to its own language so it opens translated."""
    assert base_registry.home_language_code("ZH_CHINA") == "zh"
    assert base_registry.home_language_code("BR_NATIONAL") == "pt"
    assert base_registry.home_language_code("ID_NATIONAL") == "id"


def test_home_language_code_is_none_without_a_translation() -> None:
    """Greek is not an app language, so the Greek base has no home parquet."""
    assert base_registry.home_language_code("GR_NATIONAL") is None


def test_home_language_code_is_none_for_non_national_regions() -> None:
    """Global market regions keep their own text and must not be swapped."""
    assert base_registry.home_language_code("RU_MOSCOW_ru") is None
    assert base_registry.home_language_code("nonexistent") is None


def test_home_language_parquet_is_a_real_registered_path() -> None:
    """Every home language resolves to a path in the language file map."""
    files = base_registry.national_language_workitems_files()
    for family in base_registry._NATIONAL_FAMILIES:
        region = family.variants[0].region
        lang = base_registry.home_language_code(region)
        if lang is None:
            continue
        assert base_registry.national_language_region(region, lang) in files


def test_es_mx_is_served_by_the_spanish_parquet() -> None:
    """es-MX has no translation of its own and must not fall back to English."""
    assert base_registry.normalize_lang_code("es-MX") == "es"
    assert base_registry.national_language_region("ZH_CHINA", "es-MX") == base_registry.national_language_region(
        "ZH_CHINA", "es"
    )
    assert (
        base_registry.national_language_region("ZH_CHINA", "es-MX") in base_registry.national_language_workitems_files()
    )


def test_unaliased_and_unknown_languages_are_unchanged() -> None:
    """Aliasing must not disturb ordinary codes or invent missing ones."""
    assert base_registry.normalize_lang_code("de") == "de"
    assert base_registry.national_language_region("ZH_CHINA", "ky") is None


def test_language_file_map_is_unchanged_by_aliasing() -> None:
    """The published map stays at 8 national bases times 26 languages."""
    assert len(base_registry.national_language_workitems_files()) == 208
