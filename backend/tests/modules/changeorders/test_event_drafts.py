"""Drafting a change order from a closed NCR or an answered RFI (pure builders)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.modules.changeorders import events


def _ncr(**over):
    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "ncr_number": "NCR-007",
        "title": "Honeycombing",
        "description": "Voids on soffit",
        "corrective_action": "Repair with grout",
        "root_cause": "Poor vibration",
        "cost_impact": "1500",
        "schedule_impact_days": 3,
        "status": "closed",
    }
    base.update(over)
    return SimpleNamespace(**base)


def _rfi(**over):
    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "rfi_number": "RFI-012",
        "subject": "Beam size",
        "question": "Which size?",
        "official_response": "Use 300x600",
        "cost_impact": True,
        "cost_impact_value": "2500",
        "schedule_impact_days": 2,
        "status": "answered",
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_clip_and_coerce_uuid():
    assert events._clip("short", 10) == "short"
    clipped = events._clip("x" * 50, 10)
    assert len(clipped) == 10 and clipped.endswith("...")
    u = uuid.uuid4()
    assert events._coerce_uuid(u) is u
    assert events._coerce_uuid(str(u)) == u
    assert events._coerce_uuid("") is None
    assert events._coerce_uuid(None) is None
    assert events._coerce_uuid("not-a-uuid") is None


def test_ncr_draft_carries_cost_and_provenance():
    draft = events._ncr_order(_ncr(), project_currency="EUR")
    assert draft is not None
    assert draft.reason_category == "non_conformance"
    assert float(draft.cost_impact) == 1500.0
    assert draft.schedule_impact_days == 3
    assert draft.metadata["source"] == "ncr"
    assert draft.metadata["ncr_cost_impact_raw"] == "1500"
    assert draft.metadata[events.AUTO_DRAFTED_KEY] is True
    assert events.AMOUNT_NEEDS_REVIEW_KEY not in draft.metadata
    assert "Corrective Action:" in draft.description and "Root Cause:" in draft.description


def test_ncr_draft_reads_written_currency_and_convention():
    draft = events._ncr_order(_ncr(cost_impact="BRL 12.000,00"))
    assert draft is not None
    assert float(draft.cost_impact) == 12000.0
    assert draft.currency == "BRL"


def test_ncr_draft_skipped_when_not_closed_or_no_cost():
    assert events._ncr_order(_ncr(status="open")) is None
    assert events._ncr_order(_ncr(cost_impact="")) is None
    assert events._ncr_order(_ncr(cost_impact="no cost")) is None
    assert events._ncr_order(_ncr(cost_impact="0")) is None
    assert events._ncr_order(_ncr(cost_impact="-50")) is None


def test_ncr_draft_unclear_amount_is_zero_and_flagged():
    draft = events._ncr_order(_ncr(cost_impact="12,5,7 or 3.1.2"))
    assert draft is not None
    assert float(draft.cost_impact) == 0.0
    assert draft.metadata[events.AMOUNT_NEEDS_REVIEW_KEY]


def test_ncr_draft_negative_schedule_days_clamped_and_title_clipped():
    draft = events._ncr_order(_ncr(schedule_impact_days=-4, title="T" * 400, description=None))
    assert draft is not None
    assert draft.schedule_impact_days == 0
    assert len(draft.title) <= events._TITLE_MAX


def test_rfi_draft_requires_answer_and_cost():
    assert events._rfi_order(_rfi(status="open")) is None
    assert events._rfi_order(_rfi(cost_impact=False)) is None
    draft = events._rfi_order(_rfi())
    assert draft is not None
    assert draft.reason_category == "client_request"
    assert draft.metadata["source"] == "rfi"
    assert "Response:" in draft.description
    assert events._rfi_order(_rfi(official_response=None, status="closed")) is not None
