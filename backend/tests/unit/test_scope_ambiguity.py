# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure pre-construction scope-ambiguity engine.

Stdlib + pytest only; runs on the local Python 3.11 runner. Table-driven where
the cases share shape, with focused tests for the score arithmetic, band
boundaries, report ordering, the ambiguity-index math and empty input.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.change_intelligence.scope_ambiguity import (
    BAND_ELEVATED,
    BAND_HIGH,
    BAND_LOW,
    ELEVATED_THRESHOLD,
    HIGH_THRESHOLD,
    MAX_SCORE,
    REASON_LABELS,
    REASON_MISSING_QUANTITY,
    REASON_MISSING_UNIT,
    REASON_PROVISIONAL_SUM,
    REASON_UNDERSPECIFIED,
    REASON_VAGUE_LANGUAGE,
    WEIGHT_MISSING_QUANTITY,
    WEIGHT_MISSING_UNIT,
    WEIGHT_PROVISIONAL_SUM,
    WEIGHT_UNDERSPECIFIED,
    WEIGHT_VAGUE_LANGUAGE,
    LineAmbiguity,
    ScopeAmbiguityReport,
    ScopeLine,
    assess,
    band_for_score,
    score_line,
)


def _clean_line(line_id: str = "L1", **overrides) -> ScopeLine:
    """A fully-specified, unambiguous BOQ line; override fields per test.

    Concrete description, a unit, a positive quantity and a rate, not a heading
    and not flagged provisional - so with no overrides it must score 0.
    """
    base = dict(
        line_id=line_id,
        description="Reinforced concrete foundation slab grade C30",
        unit="m3",
        quantity=Decimal("125.50"),
        rate=Decimal("142.00"),
        is_provisional_sum=False,
        is_heading=False,
    )
    base.update(overrides)
    return ScopeLine(**base)


# --------------------------------------------------------------------------- #
# A clean, fully-specified line scores 0 / low with no reasons.
# --------------------------------------------------------------------------- #


def test_clean_line_scores_zero_low_no_reasons() -> None:
    result = score_line(_clean_line())
    assert result.line_id == "L1"
    assert result.score == 0
    assert result.band == BAND_LOW
    assert result.reasons == ()
    assert result.labels == ()


# --------------------------------------------------------------------------- #
# Each signal independently moves the score up by exactly its weight, names its
# reason code, and exposes the matching label.
# --------------------------------------------------------------------------- #

_SINGLE_SIGNAL_CASES = [
    pytest.param(
        _clean_line(is_provisional_sum=True),
        REASON_PROVISIONAL_SUM,
        WEIGHT_PROVISIONAL_SUM,
        id="provisional-flag",
    ),
    pytest.param(
        _clean_line(description="Prime cost sum for ironmongery to all doors"),
        REASON_PROVISIONAL_SUM,
        WEIGHT_PROVISIONAL_SUM,
        id="provisional-wording-prime-cost",
    ),
    pytest.param(
        _clean_line(description="Dayworks for unforeseen ground excavation support"),
        REASON_PROVISIONAL_SUM,
        WEIGHT_PROVISIONAL_SUM,
        id="provisional-wording-dayworks",
    ),
    pytest.param(
        _clean_line(description="Supply and install steel handrail, finish TBC"),
        REASON_VAGUE_LANGUAGE,
        WEIGHT_VAGUE_LANGUAGE,
        id="vague-tbc",
    ),
    pytest.param(
        _clean_line(description="External paving, colour and pattern as directed"),
        REASON_VAGUE_LANGUAGE,
        WEIGHT_VAGUE_LANGUAGE,
        id="vague-as-directed",
    ),
    pytest.param(
        _clean_line(description="Approximately 200 linear metres of edge trim"),
        REASON_VAGUE_LANGUAGE,
        WEIGHT_VAGUE_LANGUAGE,
        id="vague-approximately",
    ),
    pytest.param(
        _clean_line(description="Light fitting type LF-12 or equal approved"),
        REASON_VAGUE_LANGUAGE,
        WEIGHT_VAGUE_LANGUAGE,
        id="vague-or-equal",
    ),
    pytest.param(
        _clean_line(description="Make good surfaces to match existing ???"),
        REASON_VAGUE_LANGUAGE,
        WEIGHT_VAGUE_LANGUAGE,
        id="vague-question-marks",
    ),
    pytest.param(
        _clean_line(quantity=None),
        REASON_MISSING_QUANTITY,
        WEIGHT_MISSING_QUANTITY,
        id="missing-quantity-none",
    ),
    pytest.param(
        _clean_line(quantity=Decimal("0")),
        REASON_MISSING_QUANTITY,
        WEIGHT_MISSING_QUANTITY,
        id="missing-quantity-zero",
    ),
    pytest.param(
        _clean_line(quantity=Decimal("-5")),
        REASON_MISSING_QUANTITY,
        WEIGHT_MISSING_QUANTITY,
        id="missing-quantity-negative",
    ),
    pytest.param(
        _clean_line(unit=""),
        REASON_MISSING_UNIT,
        WEIGHT_MISSING_UNIT,
        id="missing-unit-empty",
    ),
    pytest.param(
        _clean_line(unit="   "),
        REASON_MISSING_UNIT,
        WEIGHT_MISSING_UNIT,
        id="missing-unit-whitespace",
    ),
    pytest.param(
        _clean_line(description="Excavate trench"),
        REASON_UNDERSPECIFIED,
        WEIGHT_UNDERSPECIFIED,
        id="underspecified-two-words",
    ),
]


@pytest.mark.parametrize("line, expected_reason, expected_weight", _SINGLE_SIGNAL_CASES)
def test_single_signal_adds_its_weight(line: ScopeLine, expected_reason: str, expected_weight: int) -> None:
    result = score_line(line)
    assert result.score == expected_weight
    assert result.reasons == (expected_reason,)
    assert result.labels == (REASON_LABELS[expected_reason],)
    # Score sits in the band its single weight implies.
    assert result.band == band_for_score(expected_weight)


def test_allowance_fires_both_provisional_and_vague() -> None:
    # "allowance" is intentionally in both vocabularies: it names a provisional
    # sum and is inherently loose wording. Both reasons firing is by design, and
    # the weights stack.
    result = score_line(_clean_line(description="Allowance for builders work in connection"))
    assert result.reasons == (REASON_PROVISIONAL_SUM, REASON_VAGUE_LANGUAGE)
    assert result.score == WEIGHT_PROVISIONAL_SUM + WEIGHT_VAGUE_LANGUAGE


# --------------------------------------------------------------------------- #
# Vague vocabulary is whole-word: a real word that merely contains a vague token
# must not trip the signal.
# --------------------------------------------------------------------------- #

_NO_FALSE_VAGUE_CASES = [
    pytest.param("Surround to manhole cover, bedded in mortar", id="around-inside-surround"),
    pytest.param("Circadian lighting control module, wall mounted", id="circa-inside-circadian"),
    pytest.param("Approximation method statement is not relevant here", id="approx-inside-approximation"),
    pytest.param("Similarly detailed copings to both parapet walls", id="similar-inside-similarly"),
]


@pytest.mark.parametrize("description", _NO_FALSE_VAGUE_CASES)
def test_vague_signal_is_whole_word_only(description: str) -> None:
    result = score_line(_clean_line(description=description))
    assert REASON_VAGUE_LANGUAGE not in result.reasons


# --------------------------------------------------------------------------- #
# Vague matching is case-insensitive.
# --------------------------------------------------------------------------- #


def test_vague_signal_is_case_insensitive() -> None:
    upper = score_line(_clean_line(description="Steel balustrade, final spec TBD by engineer"))
    mixed = score_line(_clean_line(description="Steel balustrade, final spec tBd by engineer"))
    assert REASON_VAGUE_LANGUAGE in upper.reasons
    assert REASON_VAGUE_LANGUAGE in mixed.reasons
    assert upper.score == mixed.score


# --------------------------------------------------------------------------- #
# Signals stack: several signals on one line sum their weights.
# --------------------------------------------------------------------------- #


def test_signals_stack_sum_of_weights() -> None:
    # Missing unit + missing quantity on an otherwise concrete description.
    line = _clean_line(unit="", quantity=None)
    result = score_line(line)
    assert set(result.reasons) == {REASON_MISSING_QUANTITY, REASON_MISSING_UNIT}
    assert result.score == WEIGHT_MISSING_QUANTITY + WEIGHT_MISSING_UNIT


def test_signals_emit_in_fixed_order() -> None:
    # A short, vague, provisional, unit-less, quantity-less line trips all five.
    line = ScopeLine(
        line_id="X",
        description="allowance TBC",
        unit="",
        quantity=None,
        is_provisional_sum=True,
    )
    result = score_line(line)
    # Fixed order: provisional, vague, missing-quantity, missing-unit, underspecified.
    assert result.reasons == (
        REASON_PROVISIONAL_SUM,
        REASON_VAGUE_LANGUAGE,
        REASON_MISSING_QUANTITY,
        REASON_MISSING_UNIT,
        REASON_UNDERSPECIFIED,
    )
    assert result.labels == tuple(REASON_LABELS[r] for r in result.reasons)


# --------------------------------------------------------------------------- #
# Stacked weights are capped at MAX_SCORE and the line lands in the high band.
# --------------------------------------------------------------------------- #


def test_score_is_capped_at_max() -> None:
    line = ScopeLine(
        line_id="cap",
        description="allowance TBC",  # provisional + vague + underspecified
        unit="",  # missing unit
        quantity=None,  # missing quantity
        is_provisional_sum=True,
    )
    # Raw sum of all five weights exceeds 100; result must clamp.
    raw = (
        WEIGHT_PROVISIONAL_SUM
        + WEIGHT_VAGUE_LANGUAGE
        + WEIGHT_MISSING_QUANTITY
        + WEIGHT_MISSING_UNIT
        + WEIGHT_UNDERSPECIFIED
    )
    assert raw > MAX_SCORE
    result = score_line(line)
    assert result.score == MAX_SCORE
    assert result.band == BAND_HIGH


# --------------------------------------------------------------------------- #
# Heading lines are exempt from quantity / unit / under-specification, but still
# read for vague and provisional wording.
# --------------------------------------------------------------------------- #


def test_heading_line_exempt_from_measure_signals() -> None:
    heading = ScopeLine(
        line_id="H",
        description="Substructure",  # one word, no unit, no quantity
        unit="",
        quantity=None,
        is_heading=True,
    )
    result = score_line(heading)
    assert result.score == 0
    assert result.band == BAND_LOW
    assert result.reasons == ()


def test_heading_line_still_reads_provisional_and_vague() -> None:
    heading = ScopeLine(
        line_id="H2",
        description="Provisional allowances section, amounts TBC",
        unit="",
        quantity=None,
        is_heading=True,
    )
    result = score_line(heading)
    # Provisional + vague fire; measure signals stay suppressed.
    assert set(result.reasons) == {REASON_PROVISIONAL_SUM, REASON_VAGUE_LANGUAGE}
    assert REASON_MISSING_QUANTITY not in result.reasons
    assert REASON_MISSING_UNIT not in result.reasons
    assert REASON_UNDERSPECIFIED not in result.reasons


# --------------------------------------------------------------------------- #
# A positive quantity does not trip the missing-quantity signal (Decimal, not
# float).
# --------------------------------------------------------------------------- #


def test_small_positive_quantity_is_not_missing() -> None:
    result = score_line(_clean_line(quantity=Decimal("0.01")))
    assert REASON_MISSING_QUANTITY not in result.reasons
    assert result.score == 0


# --------------------------------------------------------------------------- #
# Under-specification counts meaningful words only: noise words and bare numbers
# do not rescue a thin description; a genuinely descriptive line passes.
# --------------------------------------------------------------------------- #

_UNDERSPECIFIED_CASES = [
    pytest.param("the works 1200", True, id="noise-plus-number-is-thin"),
    pytest.param("Item 42", True, id="filler-plus-number-is-thin"),
    pytest.param("Demolish existing block", False, id="three-meaningful-words-ok"),
    pytest.param("Excavate to reduced level and cart away spoil", False, id="long-description-ok"),
]


@pytest.mark.parametrize("description, expect_underspecified", _UNDERSPECIFIED_CASES)
def test_underspecified_counts_meaningful_words(description: str, expect_underspecified: bool) -> None:
    result = score_line(_clean_line(description=description))
    assert (REASON_UNDERSPECIFIED in result.reasons) is expect_underspecified


# --------------------------------------------------------------------------- #
# Band classification, including the exact boundary cases 29/30/59/60.
# --------------------------------------------------------------------------- #

_BAND_CASES = [
    pytest.param(0, BAND_LOW, id="zero-low"),
    pytest.param(29, BAND_LOW, id="29-low"),
    pytest.param(ELEVATED_THRESHOLD, BAND_ELEVATED, id="30-elevated"),
    pytest.param(30, BAND_ELEVATED, id="30-elevated-literal"),
    pytest.param(59, BAND_ELEVATED, id="59-elevated"),
    pytest.param(HIGH_THRESHOLD, BAND_HIGH, id="60-high"),
    pytest.param(60, BAND_HIGH, id="60-high-literal"),
    pytest.param(100, BAND_HIGH, id="100-high"),
]


@pytest.mark.parametrize("score, expected_band", _BAND_CASES)
def test_band_for_score_boundaries(score: int, expected_band: str) -> None:
    assert band_for_score(score) == expected_band


def test_threshold_constants_are_as_documented() -> None:
    # Guards the boundary contract the UI themes around.
    assert ELEVATED_THRESHOLD == 30
    assert HIGH_THRESHOLD == 60


# --------------------------------------------------------------------------- #
# Report: empty input -> empty report, zero index, zeroed band counts.
# --------------------------------------------------------------------------- #


def test_assess_empty_input() -> None:
    report = assess([])
    assert isinstance(report, ScopeAmbiguityReport)
    assert report.lines == ()
    assert report.ambiguity_index == 0.0
    assert report.counts_by_band == {BAND_HIGH: 0, BAND_ELEVATED: 0, BAND_LOW: 0}
    assert report.top_reasons == ()


# --------------------------------------------------------------------------- #
# Report: lines ordered highest-score-first, ties broken by line_id ascending.
# --------------------------------------------------------------------------- #


def test_assess_orders_highest_score_first() -> None:
    lines = [
        _clean_line("low", description="Reinforced concrete column to detail 14"),  # 0
        ScopeLine(line_id="high", description="allowance TBC", unit="", quantity=None),  # large
        _clean_line("mid", unit=""),  # missing unit only
    ]
    report = assess(lines)
    ordered_ids = [line.line_id for line in report.lines]
    assert ordered_ids == ["high", "mid", "low"]
    # Descending by score.
    scores = [line.score for line in report.lines]
    assert scores == sorted(scores, reverse=True)


def test_assess_tie_break_is_line_id_ascending() -> None:
    # Two lines with the identical single signal (same score) tie on score; the
    # lower line_id must come first.
    lines = [
        _clean_line("B", unit=""),
        _clean_line("A", unit=""),
    ]
    report = assess(lines)
    assert [line.line_id for line in report.lines] == ["A", "B"]
    assert report.lines[0].score == report.lines[1].score


# --------------------------------------------------------------------------- #
# Report: band counts and the ambiguity-index arithmetic.
# --------------------------------------------------------------------------- #


def test_assess_band_counts_and_index_math() -> None:
    lines = [
        _clean_line("clean"),  # score 0 -> low
        _clean_line("u", unit=""),  # 20 -> low
        ScopeLine(line_id="big", description="allowance TBC", unit="", quantity=None),  # 100 (capped) -> high
    ]
    report = assess(lines)

    by_id = {line.line_id: line for line in report.lines}
    assert by_id["clean"].score == 0
    assert by_id["u"].score == WEIGHT_MISSING_UNIT
    assert by_id["big"].score == MAX_SCORE

    assert report.counts_by_band[BAND_LOW] == 2  # 0 and 20 both below 30
    assert report.counts_by_band[BAND_ELEVATED] == 0
    assert report.counts_by_band[BAND_HIGH] == 1

    expected_index = round((0 + WEIGHT_MISSING_UNIT + MAX_SCORE) / 3, 2)
    assert report.ambiguity_index == expected_index


def test_assess_index_rounds_to_two_dp() -> None:
    # Three lines scoring 0, 20, 20 -> mean 13.333... -> 13.33.
    lines = [
        _clean_line("a"),
        _clean_line("b", unit=""),
        _clean_line("c", unit=""),
    ]
    report = assess(lines)
    assert report.ambiguity_index == 13.33


# --------------------------------------------------------------------------- #
# Report: top_reasons ranked by frequency, fixed reason order as the tie-break.
# --------------------------------------------------------------------------- #


def test_assess_top_reasons_ranked_by_frequency() -> None:
    lines = [
        _clean_line("a", unit=""),  # missing unit
        _clean_line("b", unit=""),  # missing unit
        _clean_line("c", quantity=None),  # missing quantity
    ]
    report = assess(lines)
    # missing-unit fires twice, missing-quantity once -> unit first.
    assert report.top_reasons[0] == REASON_MISSING_UNIT
    assert REASON_MISSING_QUANTITY in report.top_reasons


def test_assess_top_reasons_tie_break_is_fixed_order() -> None:
    # One line trips provisional + missing-quantity (each frequency 1). Fixed
    # order places provisional before missing-quantity.
    lines = [
        ScopeLine(line_id="one", description="Concrete works to foundations", quantity=None, is_provisional_sum=True),
    ]
    report = assess(lines)
    assert report.top_reasons.index(REASON_PROVISIONAL_SUM) < report.top_reasons.index(REASON_MISSING_QUANTITY)


# --------------------------------------------------------------------------- #
# Determinism: identical input yields an identical result.
# --------------------------------------------------------------------------- #


def test_score_line_is_deterministic() -> None:
    line = _clean_line(description="Allowance for TBC builders work", unit="", quantity=None)
    assert score_line(line) == score_line(line)


def test_assess_is_deterministic() -> None:
    lines = [
        _clean_line("a", unit=""),
        ScopeLine(line_id="b", description="allowance TBC", unit="", quantity=None),
        _clean_line("c"),
    ]
    assert assess(lines) == assess(lines)


# --------------------------------------------------------------------------- #
# Result objects are frozen / hashable (mirrors the sibling engines).
# --------------------------------------------------------------------------- #


def test_result_dataclasses_are_frozen() -> None:
    result = score_line(_clean_line())
    assert isinstance(result, LineAmbiguity)
    with pytest.raises(Exception):
        result.score = 99  # type: ignore[misc]
