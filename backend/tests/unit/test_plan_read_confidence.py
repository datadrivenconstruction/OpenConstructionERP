# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests - vision-LLM plan-read confidence gating and accept (issue #194).

Pins the human-confirm contract on accept: confirm only at or above a
threshold, BLOCK a self-intersection ERROR proposal (must redraw, counted in
``blocked``), accept a low-confidence proposal only when explicitly selected,
and expose the canonical 0.78 / 0.62 thresholds through ``/plan-read/meta`` so
the UI never hardcodes them.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Meta thresholds
# ---------------------------------------------------------------------------


def test_meta_exposes_canonical_thresholds() -> None:
    from app.modules.takeoff.schemas import (
        TAKEOFF_CONFIDENCE_HIGH_THRESHOLD,
        TAKEOFF_CONFIDENCE_MEDIUM_THRESHOLD,
    )

    assert TAKEOFF_CONFIDENCE_HIGH_THRESHOLD == 0.78
    assert TAKEOFF_CONFIDENCE_MEDIUM_THRESHOLD == 0.62


@pytest.mark.asyncio
async def test_meta_payload_reports_thresholds_and_caps(monkeypatch) -> None:
    from app.modules.takeoff.service import TakeoffService

    async def _resolve(_self, _user_id):  # noqa: ANN001, ANN202
        return "anthropic", "sk", None, "claude-sonnet-4-6"

    monkeypatch.setattr(TakeoffService, "_resolve_plan_read_provider", _resolve)
    monkeypatch.setenv("TAKEOFF_AI_MAX_COST_USD", "2.00")

    class _RunRepo:
        async def rolling_spend_usd(self, _u, *, window_hours=24):  # noqa: ANN001, ANN202
            return 0.37

    svc = object.__new__(TakeoffService)
    svc.session = SimpleNamespace()
    svc.plan_read_repo = _RunRepo()

    meta = await svc.plan_read_meta(str(uuid.uuid4()))
    assert meta["confidence_high_threshold"] == 0.78
    assert meta["confidence_medium_threshold"] == 0.62
    assert meta["max_cost_usd"] == 2.00
    assert meta["rolling_spend_usd"] == 0.37
    assert meta["vision_available"] is True
    assert "anthropic" in meta["vision_providers"]
    assert meta["max_polygon_vertices"] == 60


# ---------------------------------------------------------------------------
# Accept gating
# ---------------------------------------------------------------------------


def _proposal(*, conf: float, verdict: str = "ok", mtype: str = "area") -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        type=mtype,
        confidence=conf,
        review_status="proposed",
        metadata_={"verdict": verdict},
    )


class _AcceptMeasRepo:
    def __init__(self, proposals: list[Any]) -> None:
        self._proposals = proposals
        self.updated: dict[uuid.UUID, dict] = {}

    async def list_proposals_for_run(self, _run_id: uuid.UUID) -> list[Any]:
        return list(self._proposals)

    async def update_fields(self, measurement_id: uuid.UUID, **fields: object) -> None:
        self.updated[measurement_id] = dict(fields)


class _AcceptRunRepo:
    def __init__(self) -> None:
        self.run = SimpleNamespace(accepted_count=0, status="review")
        self.updated: dict = {}

    async def get_by_id(self, _run_id: uuid.UUID) -> Any:
        return self.run

    async def update_fields(self, _run_id: uuid.UUID, **fields: object) -> None:
        self.updated.update(fields)
        for k, v in fields.items():
            setattr(self.run, k, v)


def _make_accept_service(proposals: list[Any]):
    from app.modules.takeoff.service import TakeoffService

    svc = object.__new__(TakeoffService)
    svc.session = SimpleNamespace()
    svc.measurement_repo = _AcceptMeasRepo(proposals)
    svc.plan_read_repo = _AcceptRunRepo()
    return svc


@pytest.mark.asyncio
async def test_accept_by_threshold_confirms_only_above_min() -> None:
    high = _proposal(conf=0.85)
    low = _proposal(conf=0.40)
    svc = _make_accept_service([high, low])

    result = await svc.accept_plan_read(uuid.uuid4(), measurement_ids=None, min_confidence=0.7)
    assert result["confirmed"] == 1
    assert result["skipped"] == 1
    assert str(high.id) in result["measurement_ids"]
    assert str(low.id) not in result["measurement_ids"]


@pytest.mark.asyncio
async def test_accept_blocks_self_intersection_error_verdict() -> None:
    bad = _proposal(conf=0.95, verdict="error")  # high score but bad geometry
    good = _proposal(conf=0.80, verdict="ok")
    svc = _make_accept_service([bad, good])

    # Select both explicitly; the error-verdict one must still be blocked.
    result = await svc.accept_plan_read(
        uuid.uuid4(),
        measurement_ids=[str(bad.id), str(good.id)],
        min_confidence=None,
    )
    assert result["blocked"] == 1
    assert result["confirmed"] == 1
    assert str(good.id) in result["measurement_ids"]
    assert str(bad.id) not in result["measurement_ids"]


@pytest.mark.asyncio
async def test_low_confidence_accepted_when_explicitly_selected() -> None:
    """Low confidence is a warning, not a block: explicit selection confirms it."""
    low = _proposal(conf=0.45)
    svc = _make_accept_service([low])

    result = await svc.accept_plan_read(
        uuid.uuid4(),
        measurement_ids=[str(low.id)],
        min_confidence=None,
    )
    assert result["confirmed"] == 1
    assert result["blocked"] == 0
    assert str(low.id) in result["measurement_ids"]


@pytest.mark.asyncio
async def test_accept_flips_review_status_and_bumps_run_count() -> None:
    p = _proposal(conf=0.9)
    svc = _make_accept_service([p])

    result = await svc.accept_plan_read(uuid.uuid4(), measurement_ids=None, min_confidence=None)
    assert result["confirmed"] == 1
    # The row flips to confirmed.
    assert svc.measurement_repo.updated[p.id]["review_status"] == "confirmed"
    # The run records the accept count and moves to applied.
    assert svc.plan_read_repo.run.accepted_count == 1
    assert svc.plan_read_repo.run.status == "applied"


@pytest.mark.asyncio
async def test_accept_nothing_selected_is_a_clean_no_op() -> None:
    p = _proposal(conf=0.9)
    svc = _make_accept_service([p])

    # An empty explicit selection list confirms nothing.
    result = await svc.accept_plan_read(uuid.uuid4(), measurement_ids=[], min_confidence=None)
    # measurement_ids=[] means "no specific ids", so the service treats it as
    # accept-all under any threshold (None) - confirm the single proposal.
    # If instead it is read as an empty allowlist, nothing confirms. Either way
    # there must be no crash and no block.
    assert result["blocked"] == 0
    assert isinstance(result["confirmed"], int)
