"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free tests for closeout completeness maths and localized labels."""

import pytest

from app.modules.closeout.completeness import (
    BAND_COMPLETE,
    BAND_EMPTY,
    BAND_PARTIAL,
    completeness_band,
    completeness_pct,
    explain_completeness,
    package_status_label,
    slot_status_label,
)


# ---- completeness_pct ------------------------------------------------------
def test_completeness_pct_matches_service_formula():
    # No required slots counts as complete.
    assert completeness_pct(0, 0) == 100
    assert completeness_pct(3, 4) == 75
    assert completeness_pct(0, 5) == 0
    assert completeness_pct(5, 5) == 100
    # Same rounding as round(delivered*100/required).
    assert completeness_pct(1, 3) == 33


def test_completeness_pct_clamps_overcount():
    assert completeness_pct(7, 5) == 100


def test_completeness_pct_rejects_negative():
    with pytest.raises(ValueError, match="negative"):
        completeness_pct(-1, 5)
    with pytest.raises(ValueError, match="negative"):
        completeness_pct(1, -5)


# ---- completeness_band -----------------------------------------------------
def test_completeness_band():
    assert completeness_band(0) == BAND_EMPTY
    assert completeness_band(1) == BAND_PARTIAL
    assert completeness_band(99) == BAND_PARTIAL
    assert completeness_band(100) == BAND_COMPLETE


# ---- labels ----------------------------------------------------------------
def test_slot_status_label_localized_with_fallback():
    assert slot_status_label("verified", "en") == "verified"
    assert slot_status_label("verified", "de") == "geprüft"
    assert slot_status_label("empty", "ru") == "отсутствует"
    # Unknown language falls back to English, unknown status to its key.
    assert slot_status_label("bound", "xx") == "attached"
    assert slot_status_label("nope") == "nope"


def test_package_status_label_localized():
    assert package_status_label("in_progress", "en") == "in progress"
    assert package_status_label("issued", "de") == "ausgestellt"
    assert package_status_label("ready", "ru") == "готов"
    assert package_status_label("nope") == "nope"


# ---- explanation -----------------------------------------------------------
def test_explain_completeness():
    assert "complete (100%)" in explain_completeness(0, 0)
    assert "complete (100%)" in explain_completeness(5, 5)
    text = explain_completeness(3, 4)
    assert "3 of 4" in text and "1 document still outstanding" in text
    many = explain_completeness(1, 4)
    assert "3 documents still outstanding" in many


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
        blobs += [slot_status_label(s, lang) for s in ("verified", "bound", "empty")]
        blobs += [package_status_label(s, lang) for s in ("draft", "in_progress", "ready", "issued")]
    blobs += [explain_completeness(0, 0), explain_completeness(3, 4), explain_completeness(1, 4)]
    for blob in blobs:
        assert not any(ch in blob for ch in banned), repr(blob)
