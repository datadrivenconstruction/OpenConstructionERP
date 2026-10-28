"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free tests for multilingual discipline normalization in clash cost impact."""

from app.modules.clash_cost_impact.service import (
    CANONICAL_DISCIPLINES,
    DEFAULT_TRADE_PAIR_HOURS,
    TRADE_PAIR_HOURS,
    _normalise_discipline,
    explain_trade_pair,
    trade_pair_hours,
)


# ---- English behaviour unchanged -------------------------------------------
def test_english_aliases_still_resolve():
    assert _normalise_discipline("Structural") == "structural"
    assert _normalise_discipline("struct") == "structural"
    assert _normalise_discipline("HVAC") == "mechanical"
    assert _normalise_discipline("elec") == "electrical"
    assert _normalise_discipline(None) == "unknown"
    assert _normalise_discipline("   ") == "unknown"


# ---- multilingual labels ---------------------------------------------------
def test_german_labels_resolve_with_and_without_umlaut():
    assert _normalise_discipline("Tragwerk") == "structural"
    assert _normalise_discipline("Elektro") == "electrical"
    assert _normalise_discipline("Sanitär") == "plumbing"
    assert _normalise_discipline("sanitaer") == "plumbing"
    assert _normalise_discipline("Lüftung") == "mechanical"


def test_french_spanish_italian_labels_resolve():
    assert _normalise_discipline("Électricité") == "electrical"
    assert _normalise_discipline("Plomberie") == "plumbing"
    assert _normalise_discipline("Estructura") == "structural"
    assert _normalise_discipline("Fontanería") == "plumbing"
    assert _normalise_discipline("Struttura") == "structural"
    assert _normalise_discipline("Idraulica") == "plumbing"


def test_russian_labels_resolve():
    assert _normalise_discipline("Конструкции") == "structural"
    assert _normalise_discipline("Сантехника") == "plumbing"
    assert _normalise_discipline("вентиляция") == "mechanical"


def test_every_alias_maps_to_a_canonical_discipline():
    from app.modules.clash_cost_impact.service import DISCIPLINE_ALIASES

    assert set(DISCIPLINE_ALIASES.values()) <= CANONICAL_DISCIPLINES


# ---- pair hours are symmetric and language-agnostic ------------------------
def test_pair_hours_symmetric_across_languages():
    # Tragwerk (structural) vs Lüftung (mechanical) equals the English pair.
    assert trade_pair_hours("Tragwerk", "Lüftung") == trade_pair_hours("structural", "mechanical")
    assert trade_pair_hours("structural", "mechanical") == 8
    # Order does not matter.
    assert trade_pair_hours("Lüftung", "Tragwerk") == 8


def test_unknown_pair_uses_median_fallback():
    assert trade_pair_hours("nonsense", "gibberish") == DEFAULT_TRADE_PAIR_HOURS


# ---- explanation helper ----------------------------------------------------
def test_explain_trade_pair_states_hours_and_basis():
    text = explain_trade_pair("Tragwerk", "Lüftung")
    assert "8 rework hours" in text
    assert "mechanical" in text and "structural" in text
    fallback = explain_trade_pair("nonsense", "gibberish")
    assert "median fallback" in fallback
    # No em-dashes or smart quotes in any produced line.
    for blob in (text, fallback):
        assert not any(
            ch in blob
            for ch in "".join(
                map(
                    chr,
                    (
                        0x2014,
                        0x2013,
                        0x2018,
                        0x2019,
                        0x201C,
                        0x201D,
                    ),
                )
            )
        )


def test_table_only_uses_canonical_keys():
    for left, right in TRADE_PAIR_HOURS:
        assert left in CANONICAL_DISCIPLINES
        assert right in CANONICAL_DISCIPLINES
