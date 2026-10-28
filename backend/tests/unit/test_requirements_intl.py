"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free tests for requirements localized labels and coverage maths."""

import pytest

from app.modules.requirements.intl import (
    BAND_COMPLETE,
    BAND_NONE,
    BAND_PARTIAL,
    PRIORITY_ORDER,
    coverage_band,
    coverage_rate,
    deliverable_status_label,
    explain_coverage,
    priority_label,
    priority_rank,
)


def test_deliverable_status_label_localized_with_fallback():
    assert deliverable_status_label("accepted", "en") == "accepted"
    assert deliverable_status_label("accepted", "de") == "abgenommen"
    assert deliverable_status_label("missing", "ru") == "отсутствует"
    assert deliverable_status_label("submitted", "xx") == "submitted"
    assert deliverable_status_label("nope") == "nope"


def test_priority_label_moscow_localized():
    assert priority_label("must", "en") == "must have"
    assert priority_label("should", "de") == "Soll-Anforderung"
    assert priority_label("could", "ru") == "возможно"
    assert priority_label("wont", "en") == "will not have"
    assert priority_label("nope") == "nope"


def test_labels_resolve_a_regional_code_through_its_base_language():
    # de-AT has no table of its own; it must read the de translation, not
    # silently fall to en the way an exact-string match would.
    assert deliverable_status_label("accepted", "de-AT") == deliverable_status_label("accepted", "de")
    assert deliverable_status_label("accepted", "de-AT") != deliverable_status_label("accepted", "en")
    assert priority_label("must", "ru_RU") == priority_label("must", "ru")


def test_priority_rank_orders_moscow():
    ranks = [priority_rank(p) for p in ("must", "should", "could", "wont")]
    assert ranks == [0, 1, 2, 3]
    assert priority_rank("unknown") == len(PRIORITY_ORDER)


def test_coverage_rate_matches_evaluator_and_guards():
    assert coverage_rate(0, 0) == 0.0
    assert coverage_rate(1, 4) == 25.0
    assert coverage_rate(3, 3) == 100.0
    # Clamp a stray over-count.
    assert coverage_rate(5, 4) == 100.0
    with pytest.raises(ValueError, match="negative"):
        coverage_rate(-1, 4)


def test_coverage_band():
    assert coverage_band(0) == BAND_NONE
    assert coverage_band(50) == BAND_PARTIAL
    assert coverage_band(100) == BAND_COMPLETE


def test_explain_coverage():
    assert "No deliverables defined" in explain_coverage(0, 0, 0)
    text = explain_coverage(2, 1, 1)
    assert "2 of 4 deliverables accepted (50.0%)" in text
    assert "1 in review, 1 outstanding" in text
    with pytest.raises(ValueError, match="negative"):
        explain_coverage(-1, 0, 0)


def test_labels_have_no_em_dashes_or_smart_quotes():
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
            ),
        )
    )
    blobs = []
    for lang in ("en", "de", "ru"):
        blobs += [deliverable_status_label(s, lang) for s in ("accepted", "submitted", "missing")]
        blobs += [priority_label(p, lang) for p in PRIORITY_ORDER]
    blobs += [explain_coverage(2, 1, 1), explain_coverage(0, 0, 0)]
    for blob in blobs:
        assert not any(ch in blob for ch in banned), repr(blob)
