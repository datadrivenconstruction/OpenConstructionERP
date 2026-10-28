"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the quantity-map match-quality confidence helper.

``BIMHubService._match_quality_confidence`` derives the confidence bucket that
is stamped onto an auto-created BOQ position (``source='cad_import'``) when a
quantity rule is applied. The thresholds intentionally mirror the frontend
``draftConfidence`` so the sandbox preview and the persisted provenance agree.
"""

from __future__ import annotations

from app.modules.bim_hub.service import BIMHubService

_conf = BIMHubService._match_quality_confidence


def test_none_when_nothing_considered() -> None:
    assert _conf(matched=0, skipped=0) is None


def test_high_when_all_matches_yield_quantity() -> None:
    assert _conf(matched=10, skipped=0) == "high"


def test_high_at_ninety_percent_boundary() -> None:
    # 9 of 10 = 0.9 → high (inclusive boundary).
    assert _conf(matched=9, skipped=1) == "high"


def test_medium_in_middle_band() -> None:
    # 7 of 10 = 0.7 → medium.
    assert _conf(matched=7, skipped=3) == "medium"


def test_medium_at_sixty_percent_boundary() -> None:
    assert _conf(matched=6, skipped=4) == "medium"


def test_low_when_most_matches_drop_out() -> None:
    # 3 of 10 = 0.3 → low.
    assert _conf(matched=3, skipped=7) == "low"


def test_low_when_only_skips() -> None:
    assert _conf(matched=0, skipped=5) == "low"
