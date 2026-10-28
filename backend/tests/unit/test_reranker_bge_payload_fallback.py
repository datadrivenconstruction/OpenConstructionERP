"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for reranker_bge's defensive payload-derived fallback.

When the snapshot install populates Qdrant vectors but the SQL/parquet
side is empty (the v3.0.x default), ``MatchCandidate.description`` can
be empty even after ``_hit_to_candidate``'s payload synthesis path. In
that case the BGE cross-encoder's passage half collapses to just the
rate_code — a 6-character opaque token — and the reranker scores it
near zero against any real query. The defensive fallback in
``_build_candidate_text`` folds classification IDs + region into the
passage so the cross-encoder has at least the categorical anchor.
"""

from __future__ import annotations

from app.core.match_service.envelope import MatchCandidate
from app.core.match_service.reranker_bge import _build_candidate_text


def _candidate(**overrides) -> MatchCandidate:
    """Build a MatchCandidate with sensible defaults for these tests."""
    defaults: dict = {
        "id": "rate-1",
        "code": "ABC_DEF",
        "description": "",
        "unit": "",
        "unit_rate": 0.0,
        "currency": "",
        "score": 0.5,
        "vector_score": 0.5,
        "boosts_applied": {},
        "confidence_band": "medium",
        "region_code": "",
        "source": "cwicr",
        "language": "",
        "classification": {},
    }
    defaults.update(overrides)
    return MatchCandidate(**defaults)


def test_build_candidate_text_uses_description_when_present():
    """Happy path — description is the dominant passage signal."""
    cand = _candidate(
        description="Cast-in-place concrete wall C30/37, 240mm",
        unit="m3",
        classification={"din276": "330"},
        region_code="DE",
    )
    text = _build_candidate_text(cand)
    assert "Cast-in-place concrete wall C30/37" in text
    assert "unit m3" in text
    # Fallback fields are NOT folded when description is present.
    assert "din276" not in text
    assert "region" not in text


def test_build_candidate_text_folds_classification_and_region_when_empty():
    """Snapshot-only install: description empty → fold classification + region."""
    cand = _candidate(
        description="",
        classification={
            "din276": "330",
            "nrm": "2.6.1",
            "masterformat": "03 30 00",
        },
        region_code="US",
    )
    text = _build_candidate_text(cand)
    # Code still anchors the passage
    assert "ABC_DEF" in text
    # All three classification IDs are folded in (any order, prefixed)
    assert "din276 330" in text
    assert "nrm 2.6.1" in text
    assert "masterformat 03 30 00" in text
    assert "region US" in text


def test_build_candidate_text_full_candidate_uses_description_skips_fallback():
    """Once description is non-empty, classification/region must NOT be folded."""
    cand = _candidate(
        description="Real description from parquet",
        unit="m2",
        classification={"din276": "330", "masterformat": "03 30 00"},
        region_code="DE",
    )
    text = _build_candidate_text(cand)
    assert "Real description from parquet" in text
    assert "unit m2" in text
    # Negative assertions — fallback fields stay out
    assert "din276" not in text
    assert "masterformat 03 30 00" not in text
    assert "region DE" not in text


def test_build_candidate_text_minimal_candidate_returns_just_code():
    """Truly empty candidate — only the code survives, the rest collapse."""
    cand = _candidate(
        code="X",
        description="",
        unit="",
        classification={},
        region_code="",
    )
    text = _build_candidate_text(cand)
    assert text == "X"


def test_build_candidate_text_partial_fallback_folds_only_available_classification():
    """Only one classification ID + no region → just that one classification fold."""
    cand = _candidate(
        code="MF-09-24-00",
        description="",
        classification={"masterformat": "09 24 00"},
        region_code="",
    )
    text = _build_candidate_text(cand)
    assert "MF-09-24-00" in text
    assert "masterformat 09 24 00" in text
    # din276 / nrm are absent in the dict → must not appear in the passage
    assert "din276" not in text
    assert "nrm" not in text
    # No region was set, so no "region " segment
    assert "region " not in text
