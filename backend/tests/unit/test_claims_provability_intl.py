"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free tests for claims provability localization and cure planning."""

from datetime import UTC, datetime

from app.modules.claims_evidence.provability import (
    BAND_MODERATE,
    BAND_STRONG,
    MAX_SCORE,
    ProvabilitySignals,
    band_label,
    compute_provability,
    cure_plan,
    score_summary,
    signal_label,
)


def _perfect() -> ProvabilitySignals:
    return ProvabilitySignals(
        notice_served_at=datetime(2026, 1, 1, tzinfo=UTC),
        notice_due_at=datetime(2026, 1, 2, tzinfo=UTC),
        has_acknowledgement=True,
        linked_instruction_count=2,
        ownership_chain_present=True,
        ownership_ambiguous=False,
        ownership_chain_inconsistent=False,
        entry_count=5,
        date_from=datetime(2026, 1, 1, tzinfo=UTC),
        date_to=datetime(2026, 2, 1, tzinfo=UTC),
        chronology_has_gap=False,
    )


# ---- localization ----------------------------------------------------------
def test_signal_label_localized_with_english_fallback():
    assert signal_label("notice_timeliness", "en") == "Notice timeliness"
    assert signal_label("notice_timeliness", "de") == "Rechtzeitigkeit der Anzeige"
    assert signal_label("notice_timeliness", "ru") == "Своевременность уведомления"
    # Unknown language falls back to English, unknown signal to its key.
    assert signal_label("acknowledgement", "xx") == "Acknowledgement on record"
    assert signal_label("nope", "de") == "nope"


def test_band_label_localized_with_fallback():
    assert band_label(BAND_STRONG, "en") == "strong"
    assert band_label(BAND_STRONG, "de") == "stark"
    assert band_label(BAND_MODERATE, "ru") == "средняя"
    assert band_label("nope") == "nope"


# ---- cure plan -------------------------------------------------------------
def test_cure_plan_empty_for_perfect_record():
    score = compute_provability(_perfect())
    assert score.score == MAX_SCORE
    assert cure_plan(score) == []
    assert "no gaps to cure" in score_summary(score)


def test_cure_plan_ranks_by_points_recoverable():
    # Missing notice (30) and missing instruction (20) are the two biggest gaps.
    signals = ProvabilitySignals(
        notice_served_at=None,
        has_acknowledgement=True,
        linked_instruction_count=0,
        ownership_chain_present=True,
        entry_count=5,
        date_from=datetime(2026, 1, 1, tzinfo=UTC),
        date_to=datetime(2026, 2, 1, tzinfo=UTC),
    )
    score = compute_provability(signals)
    plan = cure_plan(score)
    assert [step.priority for step in plan] == list(range(1, len(plan) + 1))
    # Descending by points recoverable.
    points = [step.points_recoverable for step in plan]
    assert points == sorted(points, reverse=True)
    assert all(step.points_recoverable > 0 for step in plan)
    # Notice (30) outranks the linked instruction (20).
    assert plan[0].token == "notice_missing"
    assert plan[0].points_recoverable == 30
    assert plan[1].token == "no_linked_instruction"


def test_score_summary_names_the_biggest_gap():
    signals = ProvabilitySignals(
        notice_served_at=None,
        has_acknowledgement=True,
        linked_instruction_count=1,
        ownership_chain_present=True,
        entry_count=5,
        date_from=datetime(2026, 1, 1, tzinfo=UTC),
        date_to=datetime(2026, 2, 1, tzinfo=UTC),
    )
    summary = score_summary(compute_provability(signals))
    assert "Provability is" in summary
    assert "worth 30 points" in summary


def test_presented_strings_have_no_em_dashes_or_smart_quotes():
    banned = "".join(
        map(
            chr,
            (
                0x2014,
                0x2013,
                0x2018,
                0x2019,
                0x201C,
                0x201D,
                0x200C,
                0x200D,
                0x2060,
            ),
        )
    )
    signals = ProvabilitySignals(notice_served_at=None, ownership_chain_present=False)
    score = compute_provability(signals)
    blobs = [score_summary(score)]
    blobs += [step.message for step in cure_plan(score)]
    blobs += [signal_label(s, lang) for s in SIGNALS for lang in ("en", "de", "ru")]
    blobs += [band_label(b, lang) for b in ("weak", "moderate", "strong") for lang in ("en", "de", "ru")]
    for blob in blobs:
        assert not any(ch in blob for ch in banned), repr(blob)


SIGNALS = (
    "notice_timeliness",
    "acknowledgement",
    "linked_instruction",
    "ownership_continuity",
    "date_completeness",
)
