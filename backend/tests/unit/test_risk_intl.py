# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the international, DB-free risk helpers (risk/intl.py).

Stdlib + pytest only - no database, no app runtime, no network. The tests lock
in the contract the register's international story depends on:

* risk score = likelihood x impact, validated against any matrix size;
* normalized score always in [0, 1], never NaN / infinity, 1x1 guard;
* rating bands from parameterized thresholds;
* Decimal-exact monetary exposure that never blends currency codes;
* clean ValueError on empty / out-of-range / negative / non-finite inputs;
* localization en / de / ru with an English fallback;
* the whole module and its output stay free of em-dashes, smart quotes and
  zero-width characters (the banned set is built from chr() code points,
  never written as literals).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.risk.intl import (
    CATEGORY_VALUES,
    DEFAULT_SCALE,
    RATING_BANDS,
    MonetaryExposure,
    RiskAssessment,
    assess_risk,
    counts_by_band,
    counts_by_status,
    explain_exposure,
    explain_rating_band,
    explain_risk_score,
    iso_date,
    localize,
    monetary_exposure,
    normalized_score,
    rating_band,
    rating_band_from_score,
    risk_score,
    total_exposure,
    validate_scale_value,
)
from tests._watermark import strip_marks

# Banned characters, assembled from code points so this file never itself
# contains a literal em-dash, smart quote or zero-width character.
_BANNED_CODEPOINTS = (
    0x2013,  # en dash
    0x2014,  # em dash
    0x2018,  # left single quote
    0x2019,  # right single quote
    0x201C,  # left double quote
    0x201D,  # right double quote
    0x200B,  # zero-width space
    0x200C,  # zero-width non-joiner
    0x200D,  # zero-width joiner
    0x2060,  # word joiner
    0xFEFF,  # zero-width no-break space / BOM
)
_BANNED_CHARS = frozenset(chr(cp) for cp in _BANNED_CODEPOINTS)


# ── Scoring ────────────────────────────────────────────────────────────────


def test_default_scale_is_five():
    assert DEFAULT_SCALE == 5


@pytest.mark.parametrize(
    ("likelihood", "impact", "expected"),
    [(1, 1, 1), (2, 3, 6), (5, 5, 25), (4, 5, 20)],
)
def test_risk_score_product(likelihood, impact, expected):
    assert risk_score(likelihood, impact) == expected


def test_risk_score_custom_scale():
    assert risk_score(3, 3, scale=3) == 9
    assert risk_score(10, 10, scale=10) == 100


@pytest.mark.parametrize("bad", [0, -1, 6, 2.5, float("nan"), float("inf")])
def test_risk_score_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        risk_score(bad, 3)


def test_risk_score_rejects_boolean():
    # bool is an int subclass; it must not pose as 1 / 0.
    with pytest.raises(ValueError):
        risk_score(True, 3)


def test_validate_scale_value_returns_int():
    assert validate_scale_value(4, scale=5, name="likelihood") == 4


def test_validate_scale_rejects_zero_scale():
    with pytest.raises(ValueError):
        risk_score(1, 1, scale=0)


# ── Normalized score ────────────────────────────────────────────────────────


def test_normalized_score_bounds():
    assert normalized_score(1, 1) == 0.0
    assert normalized_score(5, 5) == 1.0


def test_normalized_score_always_in_unit_interval():
    for likelihood in range(1, 6):
        for impact in range(1, 6):
            value = normalized_score(likelihood, impact)
            assert 0.0 <= value <= 1.0


def test_normalized_score_one_by_one_matrix_no_zero_division():
    # scale=1 makes the span zero; must return 0.0, not raise.
    assert normalized_score(1, 1, scale=1) == 0.0


def test_normalized_score_never_nan_or_inf():
    value = normalized_score(3, 4)
    assert value == value  # not NaN
    assert value not in (float("inf"), float("-inf"))


# ── Rating bands ────────────────────────────────────────────────────────────


def test_rating_band_low_and_critical():
    assert rating_band(1, 1) == "low"
    assert rating_band(5, 5) == "critical"


def test_rating_band_values_are_known():
    for likelihood in range(1, 6):
        for impact in range(1, 6):
            assert rating_band(likelihood, impact) in RATING_BANDS


def test_rating_band_custom_thresholds():
    thresholds = (("green", 0.5), ("red", 1.0))
    assert rating_band(1, 1, thresholds=thresholds) == "green"
    assert rating_band(5, 5, thresholds=thresholds) == "red"


def test_rating_band_rejects_empty_thresholds():
    with pytest.raises(ValueError):
        rating_band(3, 3, thresholds=())


def test_rating_band_rejects_descending_thresholds():
    with pytest.raises(ValueError):
        rating_band(3, 3, thresholds=(("a", 0.8), ("b", 0.3)))


def test_rating_band_from_score_matches_factor_version():
    assert rating_band_from_score(25) == rating_band(5, 5)
    assert rating_band_from_score(1) == rating_band(1, 1)


def test_rating_band_from_score_rejects_out_of_range():
    with pytest.raises(ValueError):
        rating_band_from_score(26)
    with pytest.raises(ValueError):
        rating_band_from_score(0)


# ── Monetary exposure ───────────────────────────────────────────────────────


def test_monetary_exposure_decimal_exact():
    exposure = monetary_exposure("0.1", "1000.00", currency="EUR")
    assert isinstance(exposure, MonetaryExposure)
    assert exposure.amount == Decimal("100.00")
    assert exposure.currency == "EUR"
    assert isinstance(exposure.amount, Decimal)


def test_monetary_exposure_zero_probability():
    exposure = monetary_exposure(0, "5000", currency="USD")
    assert exposure.amount == Decimal("0.00")


def test_monetary_exposure_rounds_half_up():
    # 0.3333 x 100 = 33.33 exactly after quantize.
    exposure = monetary_exposure("0.3333", "100")
    assert exposure.amount == Decimal("33.33")


@pytest.mark.parametrize("bad_prob", [-0.1, 1.5, "nan", "inf"])
def test_monetary_exposure_rejects_bad_probability(bad_prob):
    with pytest.raises(ValueError):
        monetary_exposure(bad_prob, "100")


@pytest.mark.parametrize("bad_cost", [-1, "nan", "inf", "1e400"])
def test_monetary_exposure_rejects_bad_cost(bad_cost):
    with pytest.raises(ValueError):
        monetary_exposure("0.5", bad_cost)


def test_monetary_exposure_formula_is_plain_language():
    exposure = monetary_exposure("0.5", "200", currency="GBP")
    assert "probability" in exposure.formula
    assert "cost impact" in exposure.formula


def test_total_exposure_keeps_currencies_separate():
    eur = monetary_exposure("0.5", "1000", currency="EUR")
    usd = monetary_exposure("0.5", "2000", currency="USD")
    eur2 = monetary_exposure("0.25", "400", currency="EUR")
    totals = total_exposure([eur, usd, eur2])
    assert totals["EUR"] == Decimal("600.00")
    assert totals["USD"] == Decimal("1000.00")
    # never blended into a single figure
    assert set(totals) == {"EUR", "USD"}


def test_total_exposure_empty_is_empty_map():
    assert total_exposure([]) == {}


# ── Aggregations ────────────────────────────────────────────────────────────


def test_counts_by_status_seeds_known_statuses():
    counts = counts_by_status(["open", "open", "closed"])
    assert counts["open"] == 2
    assert counts["closed"] == 1
    # a known-but-unused status is present at zero for a stable dashboard
    assert counts["mitigated"] == 0


def test_counts_by_status_empty_is_all_zero_baseline():
    counts = counts_by_status([])
    assert set(counts) >= {"identified", "open", "closed"}
    assert all(v == 0 for v in counts.values())


def test_counts_by_status_from_mappings_and_objects():
    class Risk:
        def __init__(self, status):
            self.status = status

    counts = counts_by_status([{"status": "open"}, Risk("open"), "closed"])
    assert counts["open"] == 2
    assert counts["closed"] == 1


def test_counts_by_status_unknown_value_not_dropped():
    counts = counts_by_status(["totally_new_state"])
    assert counts["totally_new_state"] == 1


def test_counts_by_band_from_pairs():
    counts = counts_by_band([(1, 1), (5, 5), (5, 5)])
    assert counts["low"] == 1
    assert counts["critical"] == 2
    # all bands seeded
    assert set(counts) == set(RATING_BANDS)


def test_counts_by_band_empty_baseline():
    counts = counts_by_band([])
    assert counts == dict.fromkeys(RATING_BANDS, 0)


def test_counts_by_band_rejects_bad_factor():
    with pytest.raises(ValueError):
        counts_by_band([(0, 3)])


# ── ISO 8601 dates ──────────────────────────────────────────────────────────


def test_iso_date_from_date_and_datetime():
    assert iso_date(date(2026, 7, 5)) == "2026-07-05"
    assert iso_date(datetime(2026, 7, 5, 13, 30)) == "2026-07-05"


def test_iso_date_from_string():
    assert iso_date("2026-07-05T09:00:00") == "2026-07-05"


def test_iso_date_rejects_garbage():
    with pytest.raises(ValueError):
        iso_date("not-a-date")


# ── Localization ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("lang", ["en", "de", "ru"])
def test_localize_status_all_langs(lang):
    label = localize("monitoring", "status", lang)
    assert isinstance(label, str)
    assert label


def test_localize_english_fallback_for_unknown_lang():
    assert localize("critical", "band", "xx") == localize("critical", "band", "en")


def test_localize_unknown_term_is_readable():
    assert localize("very_new_state", "status") == "Very new state"


def test_localize_covers_every_category():
    for category in CATEGORY_VALUES:
        assert localize(category, "category", "de")


def test_localize_resolves_a_regional_code_through_its_base_language():
    # de-AT has no table of its own; it must read the de translation, not
    # silently fall to en the way an exact-string match would.
    assert localize("critical", "band", "de-AT") == localize("critical", "band", "de")
    assert localize("critical", "band", "de-AT") != localize("critical", "band", "en")
    assert localize("monitoring", "status", "ru_RU") == localize("monitoring", "status", "ru")


# ── Explainers ──────────────────────────────────────────────────────────────


def test_explainers_are_nonempty_and_localized():
    for lang in ("en", "de", "ru"):
        assert explain_risk_score(3, 4, lang=lang)
        assert explain_rating_band(3, 4, lang=lang)
        assert explain_exposure("0.5", "1000", currency="EUR", lang=lang)


def test_explain_risk_score_mentions_the_score():
    assert "12" in explain_risk_score(3, 4)


def test_explainers_resolve_a_regional_code_through_its_base_language():
    assert explain_risk_score(3, 4, lang="de-AT") == explain_risk_score(3, 4, lang="de")
    assert explain_rating_band(3, 4, lang="de-AT") == explain_rating_band(3, 4, lang="de")
    assert explain_exposure("0.5", "1000", currency="EUR", lang="de-AT") == explain_exposure(
        "0.5", "1000", currency="EUR", lang="de"
    )


# ── Full assessment ─────────────────────────────────────────────────────────


def test_assess_risk_without_money():
    result = assess_risk(4, 5)
    assert isinstance(result, RiskAssessment)
    assert result.score == 20
    assert result.exposure is None
    assert result.band in RATING_BANDS


def test_assess_risk_with_money_exposes_components():
    result = assess_risk(4, 5, probability="0.4", cost_impact="10000", currency="EUR")
    assert result.exposure is not None
    payload = result.to_dict(lang="en")
    assert payload["score"] == 20
    assert payload["score_formula"] == "likelihood x impact"
    assert payload["exposure_amount"] == Decimal("4000.00")
    assert payload["exposure_currency"] == "EUR"
    assert "explain_exposure" in payload


def test_assess_risk_validates_inputs():
    with pytest.raises(ValueError):
        assess_risk(0, 5)


# ── Banned-character hygiene ─────────────────────────────────────────────────


def test_module_source_has_no_banned_characters():
    source = Path("app/modules/risk/intl.py").read_text(encoding="utf-8")
    found = _BANNED_CHARS.intersection(source)
    assert not found, f"banned characters in intl.py: {[hex(ord(c)) for c in found]}"


def test_test_file_source_has_no_banned_characters():
    source = strip_marks(Path(__file__).read_text(encoding="utf-8"))
    found = _BANNED_CHARS.intersection(source)
    assert not found, f"banned characters in test file: {[hex(ord(c)) for c in found]}"


def test_generated_output_has_no_banned_characters():
    outputs: list[str] = []
    for lang in ("en", "de", "ru"):
        outputs.append(explain_risk_score(3, 4, lang=lang))
        outputs.append(explain_rating_band(3, 4, lang=lang))
        outputs.append(explain_exposure("0.5", "1000", currency="EUR", lang=lang))
        for kind, term in (
            ("status", "monitoring"),
            ("category", "procurement"),
            ("severity", "critical"),
            ("band", "high"),
        ):
            outputs.append(localize(term, kind, lang))
    exposure = monetary_exposure("0.5", "1000", currency="EUR")
    outputs.append(exposure.formula)
    blob = "".join(outputs)
    assert not _BANNED_CHARS.intersection(blob)
