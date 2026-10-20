# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for tier-1 drawing-scale detection from the PDF text layer.

These exercise :mod:`app.modules.takeoff.scale_detect` directly with plain
strings, so no PDF, PDF reader or database is needed (mirrors
``test_takeoff_recognize``). They lock in the contract the calibration dialog
relies on: explicit ratio notations and imperial equations are detected and
converted to an equivalent ``1:N`` ratio, a "scale"-adjacent token outranks a
bare one, and the common false positives (page coordinates, timestamps, aspect
ratios, phone-like numbers, dates) are rejected.
"""

from __future__ import annotations

from app.modules.takeoff import scale_detect

# ── Ratio notations ─────────────────────────────────────────────────────────


def test_plain_ratio_detected() -> None:
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "Plan view 1:100"}])
    assert best is not None
    assert best.ratio == 100
    assert best.label == "1:100"
    assert best.source == "ratio"
    assert "1:100" in best.evidence


def test_scale_keyword_outranks_bare_ratio() -> None:
    # Two ratios on the page: a bare 1:200 and a keyword-adjacent SCALE 1:50.
    text = "Drawing index 1:200 elsewhere ... SCALE 1:50"
    best, ranked = scale_detect.detect_best_scale([{"page": 1, "text": text}])
    assert best is not None
    assert best.ratio == 50  # keyword-adjacent wins despite appearing later
    assert best.confidence > 0.9
    # The bare 1:200 is still offered as a secondary candidate.
    assert any(c.ratio == 200 for c in ranked)


def test_scale_with_spaces_and_colon_variants() -> None:
    for raw in ("1 : 200", "Scale 1:200", "scale 1:50 @ A1", "SCALE  1:100"):
        best, _all = scale_detect.detect_best_scale([{"page": 1, "text": raw}])
        assert best is not None, raw
        assert best.ratio in (50, 100, 200), raw


def test_space_grouped_right_side() -> None:
    # Civil sheets sometimes group thousands: "1:1 000".
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "Site plan scale 1:1 000"}])
    assert best is not None
    assert best.ratio == 1000


def test_localized_scale_words() -> None:
    cases = {
        "Echelle 1:50": 50,
        "Massstab 1:100": 100,
        "Escala 1:200": 200,
    }
    for raw, expected in cases.items():
        best, _all = scale_detect.detect_best_scale([{"page": 1, "text": raw}])
        assert best is not None, raw
        assert best.ratio == expected, raw
        assert best.confidence > 0.9, raw  # localized keyword still boosts


# ── Imperial notations ───────────────────────────────────────────────────────


def test_quarter_inch_equals_one_foot() -> None:
    # 1/4" = 1'-0"  ->  12 / 0.25 = 48
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": 'SCALE: 1/4" = 1\'-0"'}])
    assert best is not None
    assert best.ratio == 48
    assert best.source == "imperial"


def test_three_eighths_inch_equals_one_foot() -> None:
    # 3/8" = 1'-0"  ->  12 / 0.375 = 32
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": '3/8" = 1\'-0"'}])
    assert best is not None
    assert best.ratio == 32


def test_one_inch_equals_twenty_feet() -> None:
    # 1" = 20'  ->  240 / 1 = 240
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "Site: 1\" = 20'"}])
    assert best is not None
    assert best.ratio == 240


def test_half_inch_equals_one_foot() -> None:
    # 1/2" = 1'-0"  ->  12 / 0.5 = 24
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": '1/2" = 1\'-0"'}])
    assert best is not None
    assert best.ratio == 24


def test_imperial_with_in_and_ft_words() -> None:
    # "1/4 in = 1 ft" spelled out.
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "1/4 in = 1 ft"}])
    assert best is not None
    assert best.ratio == 48


def test_imperial_with_residual_inches() -> None:
    # 1" = 1'-6"  ->  18 / 1 = 18
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": '1" = 1\'-6"'}])
    assert best is not None
    assert best.ratio == 18


# ── False positives must be rejected ─────────────────────────────────────────


def test_page_coordinate_noise_rejected() -> None:
    # A six-figure "ratio" is map/coordinate noise, never a drawing scale.
    best, ranked = scale_detect.detect_best_scale([{"page": 1, "text": "grid 1:100000 ref"}])
    assert best is None
    assert ranked == []


def test_aspect_ratio_rejected() -> None:
    # 16:9 has a non-unit antecedent -> not a scale.
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "Video aspect 16:9 native"}])
    assert best is None


def test_timestamp_rejected() -> None:
    # "2:34" (a duration / time) has a non-unit antecedent.
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "Render time 2:34 minutes"}])
    assert best is None


def test_mix_ratio_rejected() -> None:
    # A 3:1 mix ratio is not a paper scale (antecedent != 1).
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "Mortar mix 3:1 sand cement"}])
    assert best is None


def test_phone_like_number_rejected() -> None:
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "Tel: 555-1234 Fax 555-5678"}])
    assert best is None


def test_date_rejected() -> None:
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "Issued 2026-06-17 rev A"}])
    assert best is None


def test_decimal_neighbour_not_misread_as_ratio() -> None:
    # "0.1:100.5" style - the lookbehind/ahead guards keep a decimal context
    # from being parsed as a clean integer ratio.
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "value 3.1:100.5 units"}])
    assert best is None


def test_empty_and_missing_text_is_clean() -> None:
    assert scale_detect.detect_scales_in_text("", 1) == []
    assert scale_detect.detect_scales_in_text(None, 1) == []  # type: ignore[arg-type]
    best, ranked = scale_detect.detect_best_scale([])
    assert best is None and ranked == []
    # Scanned page (no text key) contributes nothing.
    best2, ranked2 = scale_detect.detect_best_scale([{"page": 1}, {"page": 2, "text": ""}])
    assert best2 is None and ranked2 == []


# ── Ranking / dedup / multi-page ─────────────────────────────────────────────


def test_repeated_scale_deduped_to_one() -> None:
    text = "SCALE 1:100 ... title block ... SCALE 1:100 ... 1:100"
    best, ranked = scale_detect.detect_best_scale([{"page": 1, "text": text}])
    assert best is not None and best.ratio == 100
    ratios = [c.ratio for c in ranked]
    assert ratios.count(100) == 1  # collapsed, not three entries


def test_first_page_scale_preferred_on_tie() -> None:
    # Same confidence on two pages -> earliest page wins.
    pages = [
        {"page": 3, "text": "SCALE 1:50"},
        {"page": 1, "text": "SCALE 1:100"},
    ]
    best, _all = scale_detect.detect_best_scale(pages)
    assert best is not None
    assert best.page == 1
    assert best.ratio == 100


def test_multiple_distinct_scales_all_offered() -> None:
    pages = [
        {"page": 1, "text": "Plans SCALE 1:100"},
        {"page": 2, "text": "Details SCALE 1:20"},
    ]
    best, ranked = scale_detect.detect_best_scale(pages)
    assert best is not None
    offered = {c.ratio for c in ranked}
    assert {100, 20}.issubset(offered)


def test_one_to_one_detail_scale_allowed() -> None:
    # 1:1 is a legitimate full-size detail callout (lower bound of the band).
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "Detail scale 1:1"}])
    assert best is not None and best.ratio == 1


def test_ratio_zero_rejected() -> None:
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "scale 1:0 broken"}])
    assert best is None


def test_candidate_carries_page_and_evidence() -> None:
    best, _all = scale_detect.detect_best_scale([{"page": 7, "text": "Floor plan SCALE 1:50"}])
    assert best is not None
    assert best.page == 7
    assert "1:50" in best.evidence
    assert best.confidence == scale_detect._CONF_SCALE_KEYWORD


# ── Real-world / robustness edge cases ───────────────────────────────────────


def test_tab_separated_title_block_text() -> None:
    # ``_extract_pdf_pages`` joins table cells with tabs; the scale note often
    # lands in a title-block cell next to its label.
    text = "DRAWING No.\tA-101\nSCALE\t1:50\nDATE\t2026-06-17"
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": text}])
    assert best is not None
    assert best.ratio == 50
    assert best.confidence == scale_detect._CONF_SCALE_KEYWORD


def test_lowercase_scale_keyword() -> None:
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "drawn at scale 1:75"}])
    assert best is not None and best.ratio == 75
    assert best.confidence == scale_detect._CONF_SCALE_KEYWORD


def test_bare_ratio_has_lower_confidence_than_keyword() -> None:
    bare, _ = scale_detect.detect_best_scale([{"page": 1, "text": "see 1:100 below"}])
    keyed, _ = scale_detect.detect_best_scale([{"page": 1, "text": "scale 1:100"}])
    assert bare is not None and keyed is not None
    assert bare.confidence < keyed.confidence
    assert bare.confidence == scale_detect._CONF_BARE_RATIO


def test_imperial_outranks_bare_ratio() -> None:
    # An imperial equation is itself an explicit scale statement; it should
    # outrank a bare unlabeled ratio on the same sheet.
    text = 'index 1:200 ... 1/4" = 1\'-0"'
    best, ranked = scale_detect.detect_best_scale([{"page": 1, "text": text}])
    assert best is not None
    assert best.source == "imperial"
    assert best.ratio == 48
    assert any(c.ratio == 200 and c.source == "ratio" for c in ranked)


def test_engineering_civil_scales_allowed() -> None:
    for raw, expected in (("scale 1:1250", 1250), ("scale 1:2500", 2500), ("scale 1:500", 500)):
        best, _all = scale_detect.detect_best_scale([{"page": 1, "text": raw}])
        assert best is not None, raw
        assert best.ratio == expected, raw


def test_just_above_band_rejected() -> None:
    # 1:10001 is one past the engineering band - treat as noise.
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "scale 1:10001"}])
    assert best is None


def test_drawing_number_with_colon_not_a_scale() -> None:
    # "A-101:2" (sheet:revision) has a non-unit antecedent.
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": "Sheet A-101:2 of 8"}])
    assert best is None


def test_label_preserves_imperial_notation() -> None:
    # The candidate's detail keeps the human imperial form for the badge.
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": '1/4" = 1\'-0"'}])
    assert best is not None
    assert "1/4" in str(best.detail.get("imperial", ""))


def test_rank_is_deterministic() -> None:
    pages = [
        {"page": 2, "text": "1:50"},
        {"page": 1, "text": "1:100"},
        {"page": 3, "text": "scale 1:20"},
    ]
    best1, ranked1 = scale_detect.detect_best_scale(pages)
    best2, ranked2 = scale_detect.detect_best_scale(pages)
    assert best1 is not None and best2 is not None
    assert best1.ratio == best2.ratio == 20  # keyword-adjacent wins
    assert [(c.ratio, c.page) for c in ranked1] == [(c.ratio, c.page) for c in ranked2]


# ── Real unicode glyphs in the text layer ────────────────────────────────────
#
# The patterns escape these glyphs as \uXXXX (so the source carries no literal
# long-dash / prime / NBSP / fullwidth-colon). These tests feed the REAL
# unicode characters - built via chr() so the test source stays ASCII too - to
# prove the escapes still match what a PDF text layer actually contains.

_NBSP = chr(0x00A0)
_ENDASH = chr(0x2013)
_PRIME = chr(0x2032)
_DPRIME = chr(0x2033)
_FW_COLON = chr(0xFF1A)


def test_nbsp_grouped_right_side_matches() -> None:
    text = "scale 1:1" + _NBSP + "000"
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": text}])
    assert best is not None and best.ratio == 1000


def test_endash_imperial_separator_matches() -> None:
    # 1" = 1'-6" rendered with a prime/double-prime and an en-dash separator.
    text = '1" = 1' + _PRIME + _ENDASH + "6" + _DPRIME
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": text}])
    assert best is not None and best.ratio == 18


def test_typographic_prime_marks_match() -> None:
    # 1/4" = 1'-0" with double-prime inch marks and a prime foot mark.
    text = "1/4" + _DPRIME + " = 1" + _PRIME + "-0" + _DPRIME
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": text}])
    assert best is not None and best.ratio == 48


def test_fullwidth_colon_ratio_matches() -> None:
    # CJK title blocks use a fullwidth colon between the 1 and the N.
    text = "scale 1" + _FW_COLON + "100"
    best, _all = scale_detect.detect_best_scale([{"page": 1, "text": text}])
    assert best is not None and best.ratio == 100
