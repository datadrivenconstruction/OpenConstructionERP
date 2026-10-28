# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the revision-compare -> variation handoff (Item 17).

The deterministic diff math itself is locked in by
``tests/unit/test_dwg_compare.py``. This file covers the pieces the
handoff lane added on top of that core:

1. The narrative builders (DWG + PDF) turn the deterministic summary
   tallies into a human-readable, AI-free description.
2. The ``boq_quality.revision_cost_impact_review`` validation rule:
   * flags a non-zero net cost impact that has not yet become a variation,
   * passes once a variation exists,
   * is silent (SKIPPED-friendly, returns []) when there is no priced
     change / no compare payload,
   * degrades safely on a garbage ``net_cost_impact``.

These are pure functions / pure rule logic - no DB, no FastAPI.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from app.core.validation.engine import RuleCategory, Severity, ValidationContext
from app.core.validation.rules import RevisionCostImpactReview
from app.modules.dwg_takeoff.service import _build_revision_narrative
from app.modules.takeoff.service import _build_pdf_revision_narrative

# ── Narrative builders ────────────────────────────────────────────────


def test_dwg_narrative_reports_each_tally() -> None:
    text = _build_revision_narrative(
        entity_tally={"added": 3, "removed": 1, "modified": 2, "unchanged": 9},
        annotation_tally={"added": 4, "removed": 1, "modified": 5, "unchanged": 7},
        changed_linked_count=2,
    )
    assert "3 layers added" in text
    assert "1 removed" in text
    assert "4 annotations added" in text
    assert "2 priced (linked-to-BOQ) annotation values changed" in text
    # No em-dashes leak into the generated copy.
    assert "—" not in text


def test_dwg_narrative_tolerates_missing_or_garbage_tallies() -> None:
    text = _build_revision_narrative(
        entity_tally={"added": "bad"},
        annotation_tally={},
        changed_linked_count=0,
    )
    # "bad" coerces to 0 rather than raising.
    assert "0 layers added" in text
    assert "0 annotations added" in text


def test_pdf_narrative_reports_measurement_tally() -> None:
    text = _build_pdf_revision_narrative(
        measurement_tally={"added": 2, "removed": 0, "modified": 3, "unchanged": 5},
        changed_linked_count=1,
    )
    assert "2 measurements added" in text
    assert "3 changed" in text
    assert "1 priced (linked-to-BOQ) measurement values changed" in text
    assert "—" not in text


# ── Validation rule ───────────────────────────────────────────────────


def _run(rule: RevisionCostImpactReview, ctx: ValidationContext):
    return asyncio.run(rule.validate(ctx))


def test_rule_metadata_is_advisory_consistency() -> None:
    rule = RevisionCostImpactReview()
    assert rule.rule_id == "boq_quality.revision_cost_impact_review"
    assert rule.standard == "boq_quality"
    assert rule.severity == Severity.WARNING
    assert rule.category == RuleCategory.CONSISTENCY


def test_rule_flags_priced_change_without_variation() -> None:
    rule = RevisionCostImpactReview()
    ctx = ValidationContext(data={"summary": {"net_cost_impact": "1500.00"}})
    results = _run(rule, ctx)
    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].severity == Severity.WARNING


def test_rule_passes_once_variation_exists() -> None:
    rule = RevisionCostImpactReview()
    ctx = ValidationContext(
        data={"summary": {"net_cost_impact": "1500.00"}},
        metadata={"variation_request_exists": True},
    )
    results = _run(rule, ctx)
    assert len(results) == 1
    assert results[0].passed is True


def test_rule_silent_when_no_priced_change() -> None:
    rule = RevisionCostImpactReview()
    # None net impact (no linked-BOQ value changed) -> nothing to assert.
    assert _run(rule, ValidationContext(data={"summary": {"net_cost_impact": None}})) == []
    # Zero impact is not a finding either - it passes (rate change netted out).
    zero = _run(rule, ValidationContext(data={"summary": {"net_cost_impact": "0.00"}}))
    assert len(zero) == 1
    assert zero[0].passed is True


def test_rule_silent_without_compare_payload() -> None:
    rule = RevisionCostImpactReview()
    # A plain BOQ positions payload (no summary) is not a compare -> [].
    assert _run(rule, ValidationContext(data={"positions": [{"ordinal": "1"}]})) == []
    assert _run(rule, ValidationContext(data=[])) == []


def test_rule_accepts_summary_passed_directly() -> None:
    rule = RevisionCostImpactReview()
    ctx = ValidationContext(data={"net_cost_impact": "42.00"})
    results = _run(rule, ctx)
    assert len(results) == 1
    assert results[0].passed is False


def test_rule_degrades_on_garbage_net_impact() -> None:
    rule = RevisionCostImpactReview()
    # Unparseable -> treated as "no priced change" -> [].
    assert _run(rule, ValidationContext(data={"summary": {"net_cost_impact": "abc"}})) == []


def test_extract_net_impact_helper() -> None:
    extract = RevisionCostImpactReview._extract_net_impact
    assert extract({"summary": {"net_cost_impact": "10.5"}}) == Decimal("10.5")
    assert extract({"net_cost_impact": "-3"}) == Decimal("-3")
    assert extract({"summary": {"net_cost_impact": None}}) is None
    assert extract({"summary": {}}) is None
    assert extract("nonsense") is None
