"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the NBR 12721 (ABNT Brazil) validation rules.

The ABNT NBR 12721 cost-group hierarchy uses sections S1..S11 to organise
construction scope. These tests confirm:

* missing `nbr` classification produces a warning result (not an error —
  Brazilian estimators may still tag positions only with SINAPI codes);
* an out-of-range `nbr` code (e.g., S12, S0, or non-S-prefixed) is
  flagged as invalid;
* canonical codes S1..S11 (with optional sub-dotted suffixes) pass.

Companion to ``test_brazil_invoice_pdf.py``.
"""

from __future__ import annotations

import asyncio

from app.core.validation.engine import ValidationContext
from app.core.validation.rules import (
    NBR12721ClassificationRequired,
    NBR12721ValidSection,
)


def _ctx(positions: list[dict]) -> ValidationContext:
    return ValidationContext(
        data={"positions": positions},
        project_id="00000000-0000-0000-0000-000000000000",
        region="BR",
        standard="nbr",
        metadata={"locale": "en"},
    )


# ── NBR12721ClassificationRequired ───────────────────────────────────────


def test_nbr_classification_required_flags_missing_code() -> None:
    rule = NBR12721ClassificationRequired()
    ctx = _ctx(
        [
            {
                "id": "pos-1",
                "ordinal": "01.01",
                "classification": {"sinapi": "87878"},  # has SINAPI, no NBR
            }
        ]
    )
    results = asyncio.run(rule.validate(ctx))
    assert len(results) == 1
    assert results[0].passed is False
    assert "01.01" in results[0].message


def test_nbr_classification_required_passes_when_code_present() -> None:
    rule = NBR12721ClassificationRequired()
    ctx = _ctx(
        [
            {
                "id": "pos-1",
                "ordinal": "01.01",
                "classification": {"nbr": "S3"},
            }
        ]
    )
    results = asyncio.run(rule.validate(ctx))
    assert len(results) == 1
    assert results[0].passed is True


# ── NBR12721ValidSection ────────────────────────────────────────────────


def test_nbr_valid_section_accepts_canonical_codes() -> None:
    rule = NBR12721ValidSection()
    # Every canonical section S1..S11 plus a sub-dotted variant.
    canonical = [f"S{n}" for n in range(1, 12)] + ["S3.1", "S6.2.4"]
    ctx = _ctx(
        [
            {"id": f"pos-{i}", "ordinal": f"01.{i:02d}", "classification": {"nbr": code}}
            for i, code in enumerate(canonical, start=1)
        ]
    )
    results = asyncio.run(rule.validate(ctx))
    assert len(results) == len(canonical)
    for r, code in zip(results, canonical, strict=True):
        assert r.passed is True, f"Expected pass for {code}, got {r.message}"


def test_nbr_valid_section_rejects_out_of_range_codes() -> None:
    rule = NBR12721ValidSection()
    bad = ["S0", "S12", "S99", "X3", "3"]
    ctx = _ctx(
        [
            {"id": f"pos-{i}", "ordinal": f"01.{i:02d}", "classification": {"nbr": code}}
            for i, code in enumerate(bad, start=1)
        ]
    )
    results = asyncio.run(rule.validate(ctx))
    assert len(results) == len(bad)
    for r, code in zip(results, bad, strict=True):
        assert r.passed is False, f"Expected fail for {code}, got {r.message}"


def test_nbr_valid_section_ignores_missing_code() -> None:
    """A position without any `nbr` code is silently skipped — the
    ``classification_required`` rule already raises the warning; this
    rule only checks format when a value is supplied."""
    rule = NBR12721ValidSection()
    ctx = _ctx(
        [
            {"id": "pos-1", "ordinal": "01.01", "classification": {}},
            {"id": "pos-2", "ordinal": "01.02", "classification": None},
        ]
    )
    results = asyncio.run(rule.validate(ctx))
    assert results == []
