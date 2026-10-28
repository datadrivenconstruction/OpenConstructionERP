# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the international, database-free estimating helpers.

These are pure unit tests (no DB, no HTTP, no AI key, no Qdrant). They pin the
international-robustness, edge-case and explainability contracts of
``app.modules.ai_estimator.intl``:

    * Money is Decimal-exact and never blends currencies.
    * Contingency and markup are parameters with documented defaults.
    * Bad input (negative, non-finite, junk, missing currency, out-of-range
      confidence) raises a clean ValueError, never a 500 or a NaN / inf.
    * Empty inputs return a well-defined zero, not an error.
    * The confidence band matches the service thresholds exactly (one source of
      truth) and carries localized en / de / ru labels.
    * Every concept has a one-line explanation in en / de / ru, and the AI figure
      is always framed as a suggestion awaiting human confirmation.

Run:
    cd backend
    python -m pytest tests/unit/test_ai_estimator_intl.py -q
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.ai_estimator import intl
from app.modules.ai_estimator.service import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
    _confidence_band,
)

# ── line_total (Decimal-exact, guarded) ──────────────────────────────────────


@pytest.mark.parametrize(
    ("qty", "rate", "expected"),
    [
        (10, "185.00", Decimal("1850.00")),
        (Decimal("2.5"), Decimal("4"), Decimal("10.0")),
        (1.5, 2, Decimal("3.0")),
        (0, "999.99", Decimal("0")),  # zero quantity -> well-defined zero
        ("3", 0, Decimal("0")),  # zero rate -> well-defined zero
        ("100.5", "0.10", Decimal("10.050")),
    ],
)
def test_line_total_is_decimal_exact(qty, rate, expected):
    out = intl.line_total(qty, rate)
    assert isinstance(out, Decimal)
    assert out == expected


def test_line_total_does_not_round_through_float():
    """A rate that has no exact float representation stays exact via Decimal."""
    out = intl.line_total(3, "0.10")
    assert out == Decimal("0.30")  # 3 * 0.1 through float would be 0.30000000000000004


@pytest.mark.parametrize(
    ("qty", "rate"),
    [
        (-1, "10"),  # negative quantity
        (10, "-5"),  # negative rate
        ("abc", "10"),  # junk quantity
        (10, "not-a-number"),  # junk rate
        (float("inf"), "10"),  # non-finite
        (10, float("nan")),  # non-finite
        (True, "10"),  # bool is not a number here
        (None, "10"),  # missing
    ],
)
def test_line_total_rejects_bad_input(qty, rate):
    with pytest.raises(ValueError):
        intl.line_total(qty, rate)


# ── base_estimate (per-currency, never blends) ───────────────────────────────


def test_base_estimate_sums_per_currency_and_never_blends():
    lines = [
        {"quantity": 10, "unit_rate": "100", "currency": "EUR"},
        {"quantity": 2, "unit_rate": "50", "currency": "EUR"},
        {"quantity": 4, "unit_rate": "25", "currency": "USD"},
    ]
    out = intl.base_estimate(lines)
    assert out == {"EUR": Decimal("1100"), "USD": Decimal("100")}
    # Two distinct currency codes are never merged into one number.
    assert set(out) == {"EUR", "USD"}


def test_base_estimate_normalises_currency_case():
    lines = [
        {"quantity": 1, "unit_rate": "10", "currency": "eur"},
        {"quantity": 1, "unit_rate": "5", "currency": "EUR"},
    ]
    assert intl.base_estimate(lines) == {"EUR": Decimal("15")}


def test_base_estimate_empty_is_well_defined_zero():
    assert intl.base_estimate([]) == {}
    assert intl.base_estimate(None) == {}


def test_base_estimate_requires_explicit_currency():
    with pytest.raises(ValueError):
        intl.base_estimate([{"quantity": 1, "unit_rate": "10", "currency": ""}])
    with pytest.raises(ValueError):
        intl.base_estimate([{"quantity": 1, "unit_rate": "10"}])


def test_base_estimate_accepts_object_lines():
    class _Line:
        def __init__(self, quantity, unit_rate, currency):
            self.quantity = quantity
            self.unit_rate = unit_rate
            self.currency = currency

    out = intl.base_estimate([_Line(3, "10", "GBP"), _Line(1, "5", "GBP")])
    assert out == {"GBP": Decimal("35")}


# ── contingency / markup amounts ─────────────────────────────────────────────


def test_contingency_amount_uses_documented_default():
    # Default is 10%.
    assert intl.contingency_amount("1000") == Decimal("100.00")
    assert intl.contingency_amount("1000", 0) == Decimal("0.00")
    assert intl.contingency_amount("1000", "12.5") == Decimal("125.00")


def test_markup_amount_default_is_zero_opt_in():
    # Markup defaults to 0 so it never silently inflates a figure.
    assert intl.markup_amount("1000") == Decimal("0.00")
    assert intl.markup_amount("1000", 15) == Decimal("150.00")


@pytest.mark.parametrize("pct", [-1, "-0.5", float("inf"), "junk", True])
def test_contingency_rejects_bad_percentage(pct):
    with pytest.raises(ValueError):
        intl.contingency_amount("1000", pct)


def test_contingency_rejects_negative_base():
    with pytest.raises(ValueError):
        intl.contingency_amount("-100", 10)


# ── estimate_with_contingency (per-currency breakdown) ───────────────────────


def test_estimate_with_contingency_builds_per_currency_breakdown():
    lines = [
        {"quantity": 10, "unit_rate": "100", "currency": "EUR"},  # 1000 EUR
        {"quantity": 4, "unit_rate": "25", "currency": "USD"},  # 100 USD
    ]
    out = intl.estimate_with_contingency(lines, contingency_pct=10, markup_pct=5)
    assert out["EUR"] == {
        "base": Decimal("1000.00"),
        "contingency": Decimal("100.00"),
        "markup": Decimal("50.00"),
        "total": Decimal("1150.00"),
    }
    assert out["USD"] == {
        "base": Decimal("100.00"),
        "contingency": Decimal("10.00"),
        "markup": Decimal("5.00"),
        "total": Decimal("115.00"),
    }
    # Currencies stay separate: there is no merged grand total across codes.
    assert set(out) == {"EUR", "USD"}


def test_estimate_with_contingency_defaults_are_ten_and_zero():
    out = intl.estimate_with_contingency([{"quantity": 1, "unit_rate": "1000", "currency": "EUR"}])
    block = out["EUR"]
    assert block["contingency"] == Decimal("100.00")  # 10% default
    assert block["markup"] == Decimal("0.00")  # 0% default
    assert block["total"] == Decimal("1100.00")


def test_estimate_with_contingency_empty_lines_returns_empty_map():
    assert intl.estimate_with_contingency([]) == {}


def test_estimate_with_contingency_fails_fast_on_bad_percentage_even_when_empty():
    # A negative percentage is rejected up front, before any per-currency work.
    with pytest.raises(ValueError):
        intl.estimate_with_contingency([], contingency_pct=-1)


# ── confidence_to_band (matches service thresholds; out of range raises) ─────


def test_confidence_to_band_none_is_not_rated():
    assert intl.confidence_to_band(None) == "none"


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, "low"),
        (CONFIDENCE_MEDIUM_THRESHOLD - 0.01, "low"),
        (CONFIDENCE_MEDIUM_THRESHOLD, "medium"),
        (CONFIDENCE_HIGH_THRESHOLD - 0.01, "medium"),
        (CONFIDENCE_HIGH_THRESHOLD, "high"),
        (1.0, "high"),
    ],
)
def test_confidence_to_band_uses_service_thresholds(score, expected):
    assert intl.confidence_to_band(score) == expected


def test_confidence_to_band_matches_service_band_for_real_scores():
    """One source of truth: for every in-range score the intl band equals the
    service band (which the API contract also exposes)."""
    for i in range(0, 101):
        s = i / 100.0
        assert intl.confidence_to_band(s) == _confidence_band(s)


@pytest.mark.parametrize("score", [1.5, -0.2, float("nan"), float("inf"), "high", True])
def test_confidence_to_band_rejects_out_of_range_or_junk(score):
    with pytest.raises(ValueError):
        intl.confidence_to_band(score)


# ── band_label (localized en / de / ru) ──────────────────────────────────────


def test_band_label_localized():
    assert intl.band_label("high", "en") == "High"
    assert intl.band_label("high", "de") == "Hoch"
    assert intl.band_label("high", "ru") == "Высокая"
    assert intl.band_label("none", "de") == "Nicht bewertet"


def test_band_label_unknown_language_falls_back_to_english():
    assert intl.band_label("medium", "zz") == "Medium"


def test_band_label_covers_every_band_in_every_language():
    for lang in ("en", "de", "ru"):
        for band in intl.CONFIDENCE_BANDS:
            assert intl.band_label(band, lang)  # non-empty


def test_band_label_rejects_unknown_band():
    with pytest.raises(ValueError):
        intl.band_label("enormous")


# ── describe_confidence (suggestion-framed, never auto-applied) ──────────────


def test_describe_confidence_carries_band_label_and_suggestion_note():
    out = intl.describe_confidence(0.9, "en")
    assert out["band"] == "high"
    assert out["label"] == "High"
    assert out["score"] == 0.9
    # The figure is always framed as a suggestion for human review.
    assert "suggestion" in out["note"].lower()


def test_describe_confidence_localizes_label_and_note():
    de = intl.describe_confidence(None, "de")
    assert de["band"] == "none"
    assert de["label"] == "Nicht bewertet"
    assert de["note"] == intl.explain("suggestion", "de")


def test_describe_confidence_rejects_out_of_range():
    with pytest.raises(ValueError):
        intl.describe_confidence(2.0)


# ── explain (one-line, every concept, en / de / ru) ──────────────────────────


@pytest.mark.parametrize(
    "concept",
    ["line_total", "base_estimate", "contingency", "markup", "confidence_band", "suggestion"],
)
def test_explain_covers_every_concept_in_every_language(concept):
    for lang in ("en", "de", "ru"):
        sentence = intl.explain(concept, lang)
        assert isinstance(sentence, str)
        assert sentence.strip()
        # A one-line explanation carries no line breaks.
        assert "\n" not in sentence


def test_explain_language_parity_across_en_de_ru():
    """Every language exposes exactly the same concept keys (no drift)."""
    keys_en = set(intl._CONCEPT_EXPLANATIONS["en"])
    assert set(intl._CONCEPT_EXPLANATIONS["de"]) == keys_en
    assert set(intl._CONCEPT_EXPLANATIONS["ru"]) == keys_en


def test_explain_unknown_language_falls_back_to_english():
    assert intl.explain("contingency", "zz") == intl.explain("contingency", "en")


def test_explain_rejects_unknown_concept():
    with pytest.raises(ValueError):
        intl.explain("teleportation")


# ── No em-dash / smart-quote / zero-width characters anywhere in the module ──


def test_module_strings_use_plain_punctuation_only():
    """Guard the platform typography rule on the shipped helper strings."""
    import pathlib

    banned = [
        "".join(map(chr, (0x2014,))),
        "".join(map(chr, (0x2013,))),
        "".join(map(chr, (0x2018,))),
        "".join(map(chr, (0x2019,))),
        "".join(map(chr, (0x201C,))),
        "".join(map(chr, (0x201D,))),
        "".join(map(chr, (0x200B,))),
        "".join(map(chr, (0x200C,))),
        "".join(map(chr, (0x200D,))),
        "".join(map(chr, (0x2060,))),
    ]
    text = pathlib.Path(intl.__file__).read_text(encoding="utf-8")
    for ch in banned:
        assert ch not in text, f"banned character {ch!r} present in intl.py"
