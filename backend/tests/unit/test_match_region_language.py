# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the unified region/catalogue → language map.

The lookup used to live in two separate tables (vector_adapter and
ranker) which drifted silently. These tests pin both the canonical
mapping and the historical-alias resolution so the next addition can't
quietly break the translation cascade.
"""

from __future__ import annotations

import pytest

from app.core.match_service.region_language import (
    REGION_LANGUAGE,
    country_head,
    language_for,
)

# ── Canonical mappings ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("region", "language"),
    [
        ("DE_BERLIN", "de"),
        ("AT_VIENNA", "de"),
        ("CH_ZURICH", "de"),
        ("FR_PARIS", "fr"),
        ("ES_MADRID", "es"),
        ("IT_ROME", "it"),
        ("PT_LISBON", "pt"),
        ("BR_SAOPAULO", "pt"),
        ("GB_LONDON", "en"),
        ("USA_USD", "en"),
        ("CA_TORONTO", "en"),
        ("AU_SYDNEY", "en"),
        ("RU_STPETERSBURG", "ru"),
        ("PL_WARSAW", "pl"),
        ("CZ_PRAGUE", "cs"),
        ("BG_SOFIA", "bg"),
        ("NL_AMSTERDAM", "nl"),
        ("SV_STOCKHOLM", "sv"),
        ("CN_SHANGHAI", "zh"),
        ("JP_TOKYO", "ja"),
        ("KR_SEOUL", "ko"),
        ("HI_MUMBAI", "hi"),
        ("ID_JAKARTA", "id"),
        ("TH_BANGKOK", "th"),
        ("VN_HANOI", "vi"),
        ("AE_DUBAI", "ar"),
        ("TR_ISTANBUL", "tr"),
        ("MX_MEXICO", "es"),
    ],
)
def test_canonical_lookup(region: str, language: str) -> None:
    assert language_for(region) == language


# ── Historical aliases ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("alias", "language"),
    [
        ("UK_GBP", "en"),
        ("ENG_TORONTO", "en"),
        ("SP_BARCELONA", "es"),
        ("CS_PRAGUE", "cs"),
        ("ZH_SHANGHAI", "zh"),
        ("JA_TOKYO", "ja"),
        ("KO_SEOUL", "ko"),
        ("VI_HANOI", "vi"),
        ("AR_DUBAI", "ar"),
    ],
)
def test_alias_resolution(alias: str, language: str) -> None:
    """Old catalogue ids registered before naming convention settled."""
    assert language_for(alias) == language


# ── Edge cases ───────────────────────────────────────────────────────────


def test_unknown_region_falls_back_to_english() -> None:
    assert language_for("CT_NOWHERE") == "en"
    assert language_for("ZZ_TEST") == "en"


def test_none_falls_back_to_english() -> None:
    assert language_for(None) == "en"
    assert language_for("") == "en"
    assert language_for("   ") == "en"


def test_input_is_case_insensitive() -> None:
    """The canonical table stores UPPER but the API accepts any case."""
    assert language_for("de_berlin") == "de"
    assert language_for("De_Berlin") == "de"
    assert language_for("DE_BERLIN") == "de"


# ── Coverage smoke ───────────────────────────────────────────────────────


def test_canonical_table_covers_22_supported_locales() -> None:
    """The platform ships 22 UI languages — the catalogue table should
    cover at least the production-supported subset so the translation
    cascade can fire for every language a customer might select."""
    expected_languages = {
        "de",
        "en",
        "es",
        "fr",
        "it",
        "nl",
        "pt",
        "pl",
        "cs",
        "ru",
        "bg",
        "ro",
        "sv",
        "tr",
        "ar",
        "zh",
        "ja",
        "ko",
        "hi",
        "id",
        "th",
        "vi",
    }
    actual_languages = set(REGION_LANGUAGE.values())
    missing = expected_languages - actual_languages
    assert not missing, f"missing language coverage: {missing}"


# ── Bare-country fallback (v3 collection naming) ─────────────────────────
#
# The v3 ``cwicr_{LANG}_v3`` routing in ``costs/qdrant_adapter.py``
# leans on ``language_for`` resolving bare ISO-3166 codes via the
# auto-built head map. Pin the behaviour so a future addition can't
# regress catalogue routing for installs that store catalogue ids as
# ``"DE"`` instead of ``"DE_BERLIN"``.


@pytest.mark.parametrize(
    ("country", "language"),
    [
        ("DE", "de"),
        ("FR", "fr"),
        ("IT", "it"),
        ("ES", "es"),
        ("PL", "pl"),
        ("RU", "ru"),
        ("CZ", "cs"),
        ("BG", "bg"),
        ("RO", "ro"),
        ("NL", "nl"),
        ("PT", "pt"),
        ("HR", "hr"),
        ("CN", "zh"),
        ("JP", "ja"),
        ("KR", "ko"),
        ("ID", "id"),
        ("TR", "tr"),
        ("AE", "ar"),
        ("SA", "ar"),
        ("AR", "es"),  # Argentina, NOT Arabic
        ("BR", "pt"),
        ("MX", "es"),
        ("GB", "en"),
        ("USA", "en"),
        ("CA", "en"),
        ("AU", "en"),
    ],
)
def test_bare_country_resolves_via_overrides_or_head_fallback(country: str, language: str) -> None:
    assert language_for(country) == language


def test_unknown_locality_within_known_country_uses_head_fallback() -> None:
    """``DE_BREMEN`` isn't in REGION_LANGUAGE but the head ``DE`` is —
    head fallback resolves to German rather than the en fallback."""
    assert language_for("DE_BREMEN") == "de"
    assert language_for("RU_KAZAN") == "ru"
    assert language_for("FR_LYON") == "fr"


# ── country_head ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("region", "head"),
    [
        ("DE_BERLIN", "DE"),
        ("USA_USD", "USA"),
        ("MX_MEXICO", "MX"),
        ("DE", "DE"),  # bare code is its own head
        ("de_berlin", "DE"),  # case-normalisation
        ("  DE_BERLIN  ", "DE"),  # whitespace stripped
    ],
)
def test_country_head_extracts_iso_3166_prefix(region: str, head: str) -> None:
    assert country_head(region) == head


def test_country_head_returns_none_for_empty() -> None:
    assert country_head(None) is None
    assert country_head("") is None
    assert country_head("   ") is None
