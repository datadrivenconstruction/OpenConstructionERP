# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure provability scoring engine (runs on py3.11).

These exercise :mod:`app.modules.claims_evidence.provability` directly with
plain dataclass inputs - no database, FastAPI or ORM - exactly like the other
pure-engine tests in this suite. They lock in the contract the provability
feature depends on: a transparent weighting that sums to 100, full evidence
scoring high, every missing / late / ambiguous signal lowering the score and
emitting its specific weakness, the documented band thresholds, points-lost
reconciliation per signal, and full determinism.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.modules.claims_evidence.provability import (
    BAND_MODERATE,
    BAND_STRONG,
    BAND_WEAK,
    MAX_SCORE,
    MIN_SUBSTANTIVE_ENTRIES,
    MODERATE_THRESHOLD,
    STRONG_THRESHOLD,
    WEAKNESS_CHRONOLOGY_GAP,
    WEAKNESS_NO_ACKNOWLEDGEMENT,
    WEAKNESS_NO_DATED_RECORD,
    WEAKNESS_NO_LINKED_INSTRUCTION,
    WEAKNESS_NO_OWNERSHIP_CHAIN,
    WEAKNESS_NOTICE_DUE_UNKNOWN,
    WEAKNESS_NOTICE_LATE,
    WEAKNESS_NOTICE_MISSING,
    WEAKNESS_OWNERSHIP_AMBIGUOUS,
    WEAKNESS_OWNERSHIP_GAP,
    WEAKNESS_THIN_RECORD,
    WEIGHT_ACK,
    WEIGHT_DATES,
    WEIGHT_INSTRUCTION,
    WEIGHT_NOTICE,
    WEIGHT_OWNERSHIP,
    WEIGHTS,
    ProvabilityScore,
    ProvabilitySignals,
    band_for,
    compute_provability,
)

NOW = datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC)


def _ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def _full_signals(**overrides: object) -> ProvabilitySignals:
    """A maximally-provable record; override single fields to weaken it."""
    base: dict[str, object] = dict(
        notice_served_at=_ago(10),
        notice_due_at=_ago(8),  # served 2 days BEFORE due => on time
        has_acknowledgement=True,
        linked_instruction_count=2,
        ownership_chain_present=True,
        ownership_ambiguous=False,
        ownership_chain_inconsistent=False,
        entry_count=6,
        date_from=_ago(12),
        date_to=_ago(1),
        chronology_has_gap=False,
    )
    base.update(overrides)
    return ProvabilitySignals(**base)  # type: ignore[arg-type]


def _tokens(score: ProvabilityScore) -> set[str]:
    return {w.token for w in score.weaknesses}


def _earned_map(score: ProvabilityScore) -> dict[str, int]:
    return {s.signal: s.earned for s in score.sub_scores}


# --- weighting table -------------------------------------------------------- #


def test_weights_sum_to_max_score() -> None:
    assert sum(WEIGHTS.values()) == MAX_SCORE == 100
    # The named constants match the table.
    assert WEIGHTS == {
        "notice_timeliness": WEIGHT_NOTICE,
        "acknowledgement": WEIGHT_ACK,
        "linked_instruction": WEIGHT_INSTRUCTION,
        "ownership_continuity": WEIGHT_OWNERSHIP,
        "date_completeness": WEIGHT_DATES,
    }


def test_subscore_weights_match_table_and_order() -> None:
    score = compute_provability(_full_signals())
    assert [s.signal for s in score.sub_scores] == list(WEIGHTS.keys())
    assert [s.weight for s in score.sub_scores] == list(WEIGHTS.values())


# --- full evidence ---------------------------------------------------------- #


def test_full_evidence_scores_perfect_and_strong() -> None:
    score = compute_provability(_full_signals())
    assert score.score == 100
    assert score.band == BAND_STRONG
    assert score.weaknesses == []
    # Every signal earns its full weight.
    assert _earned_map(score) == {
        "notice_timeliness": WEIGHT_NOTICE,
        "acknowledgement": WEIGHT_ACK,
        "linked_instruction": WEIGHT_INSTRUCTION,
        "ownership_continuity": WEIGHT_OWNERSHIP,
        "date_completeness": WEIGHT_DATES,
    }
    assert all(s.fraction == pytest.approx(1.0) for s in score.sub_scores)


def test_on_time_notice_served_exactly_on_due_date_is_full_credit() -> None:
    # served == due is still "on or before".
    due = _ago(8)
    score = compute_provability(_full_signals(notice_served_at=due, notice_due_at=due))
    assert WEAKNESS_NOTICE_LATE not in _tokens(score)
    assert _earned_map(score)["notice_timeliness"] == WEIGHT_NOTICE
    assert score.score == 100


# --- each missing signal lowers the score + emits its weakness -------------- #


def test_missing_notice_lowers_score_and_flags_it() -> None:
    full = compute_provability(_full_signals())
    score = compute_provability(_full_signals(notice_served_at=None, notice_due_at=None))
    assert score.score == full.score - WEIGHT_NOTICE
    assert WEAKNESS_NOTICE_MISSING in _tokens(score)
    assert _earned_map(score)["notice_timeliness"] == 0
    # Only the notice signal lost points.
    assert _earned_map(score)["acknowledgement"] == WEIGHT_ACK


def test_missing_acknowledgement_lowers_score_and_flags_it() -> None:
    full = compute_provability(_full_signals())
    score = compute_provability(_full_signals(has_acknowledgement=False))
    assert score.score == full.score - WEIGHT_ACK
    assert WEAKNESS_NO_ACKNOWLEDGEMENT in _tokens(score)
    assert _earned_map(score)["acknowledgement"] == 0


def test_missing_linked_instruction_lowers_score_and_flags_it() -> None:
    full = compute_provability(_full_signals())
    score = compute_provability(_full_signals(linked_instruction_count=0))
    assert score.score == full.score - WEIGHT_INSTRUCTION
    assert WEAKNESS_NO_LINKED_INSTRUCTION in _tokens(score)
    assert _earned_map(score)["linked_instruction"] == 0


def test_negative_instruction_count_treated_as_none() -> None:
    score = compute_provability(_full_signals(linked_instruction_count=-3))
    assert WEAKNESS_NO_LINKED_INSTRUCTION in _tokens(score)
    assert _earned_map(score)["linked_instruction"] == 0


# --- late vs on-time notice ------------------------------------------------- #


def test_late_notice_scores_below_on_time_and_flags_late() -> None:
    on_time = compute_provability(_full_signals())
    # Served 4 days AFTER its due date.
    late = compute_provability(_full_signals(notice_served_at=_ago(4), notice_due_at=_ago(8)))
    assert late.score < on_time.score
    assert WEAKNESS_NOTICE_LATE in _tokens(late)
    assert WEAKNESS_NOTICE_MISSING not in _tokens(late)
    # A late notice still earns *some* credit (better than no notice).
    assert _earned_map(late)["notice_timeliness"] > 0
    assert _earned_map(late)["notice_timeliness"] < WEIGHT_NOTICE
    # The message reports the lateness in days.
    late_wk = next(w for w in late.weaknesses if w.token == WEAKNESS_NOTICE_LATE)
    assert "4 day" in late_wk.message


def test_late_notice_singular_day_message() -> None:
    score = compute_provability(_full_signals(notice_served_at=_ago(7), notice_due_at=_ago(8)))
    wk = next(w for w in score.weaknesses if w.token == WEAKNESS_NOTICE_LATE)
    assert "1 day after" in wk.message  # singular, no trailing 's'


def test_notice_served_but_due_date_unknown_scores_partial() -> None:
    missing = compute_provability(_full_signals(notice_served_at=None, notice_due_at=None))
    unknown_due = compute_provability(_full_signals(notice_due_at=None))
    # Served-but-undated beats no notice, but is below an on-time notice.
    assert unknown_due.score > missing.score
    assert unknown_due.score < 100
    assert WEAKNESS_NOTICE_DUE_UNKNOWN in _tokens(unknown_due)
    assert 0 < _earned_map(unknown_due)["notice_timeliness"] < WEIGHT_NOTICE


def test_late_notice_scores_below_unknown_due() -> None:
    unknown_due = compute_provability(_full_signals(notice_due_at=None))
    late = compute_provability(_full_signals(notice_served_at=_ago(4), notice_due_at=_ago(8)))
    # A demonstrably late notice is weaker evidence than one of unknown timing.
    assert late.score < unknown_due.score


# --- ownership continuity --------------------------------------------------- #


def test_no_ownership_chain_zeroes_signal_and_flags_it() -> None:
    full = compute_provability(_full_signals())
    score = compute_provability(_full_signals(ownership_chain_present=False))
    assert score.score == full.score - WEIGHT_OWNERSHIP
    assert WEAKNESS_NO_OWNERSHIP_CHAIN in _tokens(score)
    assert _earned_map(score)["ownership_continuity"] == 0
    # Absent chain does not also raise the ambiguous/gap weaknesses.
    assert WEAKNESS_OWNERSHIP_AMBIGUOUS not in _tokens(score)
    assert WEAKNESS_OWNERSHIP_GAP not in _tokens(score)


def test_ambiguous_ownership_penalty_and_weakness() -> None:
    full = compute_provability(_full_signals())
    score = compute_provability(_full_signals(ownership_ambiguous=True))
    assert score.score < full.score
    assert WEAKNESS_OWNERSHIP_AMBIGUOUS in _tokens(score)
    # Ambiguous (but not inconsistent) earns partial, not zero.
    assert 0 < _earned_map(score)["ownership_continuity"] < WEIGHT_OWNERSHIP


def test_inconsistent_chain_is_worse_than_ambiguous() -> None:
    ambiguous = compute_provability(_full_signals(ownership_ambiguous=True))
    inconsistent = compute_provability(_full_signals(ownership_chain_inconsistent=True))
    assert inconsistent.score < ambiguous.score
    assert WEAKNESS_OWNERSHIP_GAP in _tokens(inconsistent)
    assert _earned_map(inconsistent)["ownership_continuity"] == 0


def test_inconsistent_and_ambiguous_together_points_lost_reconciles() -> None:
    # Both flags set: gap dominates the score; weaknesses' points_lost must not
    # exceed the signal weight.
    score = compute_provability(_full_signals(ownership_ambiguous=True, ownership_chain_inconsistent=True))
    assert WEAKNESS_OWNERSHIP_GAP in _tokens(score)
    assert WEAKNESS_OWNERSHIP_AMBIGUOUS in _tokens(score)
    own_weaknesses = [w for w in score.weaknesses if w.signal == "ownership_continuity"]
    assert sum(w.points_lost for w in own_weaknesses) == WEIGHT_OWNERSHIP
    assert _earned_map(score)["ownership_continuity"] == 0


# --- date completeness ------------------------------------------------------ #


def test_no_dated_record_zeroes_date_signal() -> None:
    score = compute_provability(_full_signals(entry_count=0, date_from=None, date_to=None))
    assert WEAKNESS_NO_DATED_RECORD in _tokens(score)
    assert _earned_map(score)["date_completeness"] == 0


def test_missing_span_zeroes_date_signal_even_with_count() -> None:
    # A count with no from/to span cannot bound a chronology.
    score = compute_provability(_full_signals(date_from=None, date_to=None))
    assert WEAKNESS_NO_DATED_RECORD in _tokens(score)
    assert _earned_map(score)["date_completeness"] == 0


def test_thin_record_scores_partial_and_flags_it() -> None:
    full = compute_provability(_full_signals())
    thin = compute_provability(_full_signals(entry_count=MIN_SUBSTANTIVE_ENTRIES - 1))
    assert thin.score < full.score
    assert WEAKNESS_THIN_RECORD in _tokens(thin)
    assert 0 < _earned_map(thin)["date_completeness"] < WEIGHT_DATES


def test_substantive_record_at_threshold_is_full_date_credit() -> None:
    score = compute_provability(_full_signals(entry_count=MIN_SUBSTANTIVE_ENTRIES))
    assert WEAKNESS_THIN_RECORD not in _tokens(score)
    assert _earned_map(score)["date_completeness"] == WEIGHT_DATES


def test_chronology_gap_lowers_date_signal_and_flags_it() -> None:
    full = compute_provability(_full_signals())
    gapped = compute_provability(_full_signals(chronology_has_gap=True))
    assert gapped.score < full.score
    assert WEAKNESS_CHRONOLOGY_GAP in _tokens(gapped)
    assert _earned_map(gapped)["date_completeness"] < WEIGHT_DATES


def test_thin_and_gapped_record_points_lost_reconciles() -> None:
    score = compute_provability(_full_signals(entry_count=1, chronology_has_gap=True))
    assert WEAKNESS_THIN_RECORD in _tokens(score)
    assert WEAKNESS_CHRONOLOGY_GAP in _tokens(score)
    date_weaknesses = [w for w in score.weaknesses if w.signal == "date_completeness"]
    earned = _earned_map(score)["date_completeness"]
    assert sum(w.points_lost for w in date_weaknesses) == WEIGHT_DATES - earned


# --- points_lost reconciles per signal, every weakness ---------------------- #


def test_points_lost_reconciles_each_signal_for_every_weakness() -> None:
    # A broadly weak record touching every signal.
    score = compute_provability(
        ProvabilitySignals(
            notice_served_at=_ago(2),
            notice_due_at=_ago(8),  # late
            has_acknowledgement=False,
            linked_instruction_count=0,
            ownership_chain_present=True,
            ownership_ambiguous=True,
            ownership_chain_inconsistent=False,
            entry_count=1,
            date_from=_ago(3),
            date_to=_ago(1),
            chronology_has_gap=True,
        )
    )
    earned = _earned_map(score)
    # For every signal, the points_lost summed over its weaknesses equals
    # weight - earned.
    by_signal: dict[str, int] = {}
    for w in score.weaknesses:
        by_signal[w.signal] = by_signal.get(w.signal, 0) + w.points_lost
    for signal, weight in WEIGHTS.items():
        lost = weight - earned[signal]
        assert by_signal.get(signal, 0) == lost, signal


# --- empty / degenerate ----------------------------------------------------- #


def test_empty_signals_score_zero_and_weak() -> None:
    score = compute_provability(ProvabilitySignals())
    assert score.score == 0
    assert score.band == BAND_WEAK
    # Every major absence is reported.
    assert WEAKNESS_NOTICE_MISSING in _tokens(score)
    assert WEAKNESS_NO_ACKNOWLEDGEMENT in _tokens(score)
    assert WEAKNESS_NO_LINKED_INSTRUCTION in _tokens(score)
    assert WEAKNESS_NO_OWNERSHIP_CHAIN in _tokens(score)
    assert WEAKNESS_NO_DATED_RECORD in _tokens(score)
    # All sub-scores earned zero.
    assert all(s.earned == 0 for s in score.sub_scores)


def test_score_never_below_zero_or_above_max() -> None:
    worst = compute_provability(ProvabilitySignals())
    best = compute_provability(_full_signals())
    assert 0 <= worst.score <= MAX_SCORE
    assert 0 <= best.score <= MAX_SCORE


# --- bands ------------------------------------------------------------------ #


def test_band_thresholds_are_inclusive_lower_bounds() -> None:
    assert band_for(MAX_SCORE) == BAND_STRONG
    assert band_for(STRONG_THRESHOLD) == BAND_STRONG
    assert band_for(STRONG_THRESHOLD - 1) == BAND_MODERATE
    assert band_for(MODERATE_THRESHOLD) == BAND_MODERATE
    assert band_for(MODERATE_THRESHOLD - 1) == BAND_WEAK
    assert band_for(0) == BAND_WEAK


def test_band_matches_score_band_field() -> None:
    for signals in (
        _full_signals(),
        _full_signals(has_acknowledgement=False),
        ProvabilitySignals(),
    ):
        score = compute_provability(signals)
        assert score.band == band_for(score.score)


def test_losing_one_major_signal_drops_out_of_strong() -> None:
    # Dropping the linked instruction (20pts) from a perfect 100 -> 80, still
    # strong; dropping notice (30pts) -> 70, no longer strong.
    no_instruction = compute_provability(_full_signals(linked_instruction_count=0))
    assert no_instruction.score == 80
    assert no_instruction.band == BAND_STRONG
    no_notice = compute_provability(_full_signals(notice_served_at=None, notice_due_at=None))
    assert no_notice.score == 70
    assert no_notice.band == BAND_MODERATE


def test_losing_two_major_signals_drops_to_weak() -> None:
    # No notice (30) and no instruction (20) from 100 -> 50 (moderate boundary);
    # also drop ack (15) -> 35 -> weak.
    score = compute_provability(
        _full_signals(
            notice_served_at=None,
            notice_due_at=None,
            linked_instruction_count=0,
            has_acknowledgement=False,
        )
    )
    assert score.score == 35
    assert score.band == BAND_WEAK


# --- timezone handling ------------------------------------------------------ #


def test_naive_notice_datetimes_treated_as_utc() -> None:
    # Naive served/ due compared as UTC: served before due => on time.
    score = compute_provability(
        _full_signals(
            notice_served_at=datetime(2026, 6, 15, 12, 0, 0),
            notice_due_at=datetime(2026, 6, 17, 12, 0, 0),
        )
    )
    assert WEAKNESS_NOTICE_LATE not in _tokens(score)
    assert _earned_map(score)["notice_timeliness"] == WEIGHT_NOTICE


def test_offset_notice_datetimes_normalized_before_comparison() -> None:
    # served 2026-06-17 01:00 +02:00 == 2026-06-16 23:00 UTC, due 2026-06-17 UTC
    # => on time once normalized (would look late if compared naively).
    served = datetime(2026, 6, 17, 1, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    due = datetime(2026, 6, 17, 0, 0, 0, tzinfo=UTC)
    score = compute_provability(_full_signals(notice_served_at=served, notice_due_at=due))
    assert WEAKNESS_NOTICE_LATE not in _tokens(score)
    assert _earned_map(score)["notice_timeliness"] == WEIGHT_NOTICE


# --- determinism ------------------------------------------------------------ #


def test_deterministic_repeated_calls() -> None:
    signals = _full_signals(
        has_acknowledgement=False,
        linked_instruction_count=0,
        ownership_ambiguous=True,
        chronology_has_gap=True,
        entry_count=2,
    )
    a = compute_provability(signals)
    b = compute_provability(signals)
    assert a == b
    assert a.score == b.score
    assert [w.token for w in a.weaknesses] == [w.token for w in b.weaknesses]
    assert a.sub_scores == b.sub_scores


def test_weakness_order_is_stable_signal_order() -> None:
    # Touch every signal so all weaknesses appear; assert they come out in the
    # WEIGHTS signal order (notice, ack, instruction, ownership, dates).
    score = compute_provability(
        ProvabilitySignals(
            notice_served_at=None,
            notice_due_at=None,
            has_acknowledgement=False,
            linked_instruction_count=0,
            ownership_chain_inconsistent=True,
            entry_count=0,
            date_from=None,
            date_to=None,
        )
    )
    signals_in_order = [w.signal for w in score.weaknesses]
    # Each signal's weaknesses are contiguous and follow WEIGHTS order.
    first_index = {sig: signals_in_order.index(sig) for sig in dict.fromkeys(signals_in_order)}
    assert list(first_index.keys()) == [s for s in WEIGHTS if s in first_index]
