# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests - vision-LLM plan-read cost cap (issue #194).

The plan-read path must never spend over the per-user rolling cap. These tests
pin the pre-flight gate: with the cap at zero a run is refused with a 400 and
the vision call is asserted NOT made (no spend); a rolling-spend fixture near
the cap blocks the next run; an invalid env value falls back to the default;
and after a successful call the run's cost equals ``estimate_cost_usd``.

The vision call is always stubbed; no test makes a real API call.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.takeoff.service import _takeoff_ai_max_cost_usd

# ---------------------------------------------------------------------------
# Cap env reader (mirrors judge.py _max_cost_usd parametrized test)
# ---------------------------------------------------------------------------


class TestCostCapEnvReader:
    def test_default_is_two_dollars(self, monkeypatch) -> None:
        monkeypatch.delenv("TAKEOFF_AI_MAX_COST_USD", raising=False)
        assert _takeoff_ai_max_cost_usd() == 2.00

    def test_valid_env_overrides_default(self, monkeypatch) -> None:
        monkeypatch.setenv("TAKEOFF_AI_MAX_COST_USD", "0.50")
        assert _takeoff_ai_max_cost_usd() == 0.50

    @pytest.mark.parametrize("bad", ["abc", "", "not-a-number"])
    def test_invalid_env_falls_back_to_default(self, monkeypatch, bad: str) -> None:
        monkeypatch.setenv("TAKEOFF_AI_MAX_COST_USD", bad)
        assert _takeoff_ai_max_cost_usd() == 2.00

    def test_zero_env_is_a_real_zero_cap(self, monkeypatch) -> None:
        monkeypatch.setenv("TAKEOFF_AI_MAX_COST_USD", "0.00")
        assert _takeoff_ai_max_cost_usd() == 0.00


# ---------------------------------------------------------------------------
# Pre-flight gate on plan_read_start
# ---------------------------------------------------------------------------


class _FakeRunRepo:
    def __init__(self, spend: float = 0.0) -> None:
        self.runs: dict[uuid.UUID, Any] = {}
        self.spend = spend

    async def create(self, run: Any) -> Any:
        if getattr(run, "id", None) is None:
            run.id = uuid.uuid4()
        self.runs[run.id] = run
        return run

    async def get_by_id(self, run_id: uuid.UUID) -> Any:
        return self.runs.get(run_id)

    async def update_fields(self, run_id: uuid.UUID, **fields: object) -> None:
        run = self.runs.get(run_id)
        for k, v in fields.items():
            setattr(run, k, v)

    async def rolling_spend_usd(self, _user_id: uuid.UUID, *, window_hours: int = 24) -> float:
        return self.spend


class _FakeDocRepo:
    def __init__(self, doc: Any) -> None:
        self._doc = doc

    async def get_by_id(self, _doc_id: uuid.UUID) -> Any:
        return self._doc


def _make_service(*, run_repo, doc: Any):
    from app.modules.takeoff.service import TakeoffService

    svc = object.__new__(TakeoffService)
    svc.session = SimpleNamespace(commit=_noop_commit)
    svc.repo = _FakeDocRepo(doc)
    svc.measurement_repo = SimpleNamespace()
    svc.plan_read_repo = run_repo
    return svc


async def _noop_commit() -> None:
    return None


def _patch_provider(monkeypatch, *, model: str = "claude-sonnet-4-6") -> None:
    async def _resolve(_self, _user_id):  # noqa: ANN001, ANN202
        return "anthropic", "sk-test", None, model

    from app.modules.takeoff.service import TakeoffService

    monkeypatch.setattr(TakeoffService, "_resolve_plan_read_provider", _resolve)


def _patch_no_schedule(monkeypatch) -> dict[str, int]:
    """Stub the background scheduler so plan_read_start does not spawn a task."""
    counter = {"scheduled": 0}

    def _sched(_self, _run_id, *, user_id):  # noqa: ANN001, ANN202, ARG001
        counter["scheduled"] += 1

    from app.modules.takeoff.service import TakeoffService

    monkeypatch.setattr(TakeoffService, "_schedule_plan_read", _sched)
    return counter


def _spy_call_ai(monkeypatch) -> dict[str, int]:
    """Spy on call_ai so a test can assert it was NEVER invoked (no spend)."""
    from app.modules.ai import ai_client as _ac

    counter = {"calls": 0}

    async def _fake(**_kwargs: Any) -> tuple[str, int]:
        counter["calls"] += 1
        return "{}", 0

    monkeypatch.setattr(_ac, "call_ai", _fake)
    return counter


@pytest.mark.asyncio
async def test_zero_cap_refuses_with_400_and_does_not_spend(monkeypatch) -> None:
    """With the cap at zero the run is refused pre-flight; call_ai is never hit."""
    monkeypatch.setenv("TAKEOFF_AI_MAX_COST_USD", "0.00")
    ai_calls = _spy_call_ai(monkeypatch)
    _patch_no_schedule(monkeypatch)
    _patch_provider(monkeypatch)

    run_repo = _FakeRunRepo(spend=0.0)
    doc = SimpleNamespace(pages=3, file_path=None)
    svc = _make_service(run_repo=run_repo, doc=doc)

    with pytest.raises(HTTPException) as exc:
        await svc.plan_read_start(
            project_id=uuid.uuid4(),
            document_id=str(uuid.uuid4()),
            page=1,
            mode="rooms",
            scale_pixels_per_unit=None,
            do_cost_match=False,
            user_id=str(uuid.uuid4()),
        )
    assert exc.value.status_code == 400
    assert "cap" in exc.value.detail.lower()
    # The pre-flight gate ran BEFORE any provider call.
    assert ai_calls["calls"] == 0
    # A failed run row was recorded with the cost_cap reason.
    failed = [r for r in run_repo.runs.values() if r.failure_reason == "cost_cap"]
    assert len(failed) == 1
    assert failed[0].status == "failed"


@pytest.mark.asyncio
async def test_rolling_spend_near_cap_blocks_next_run(monkeypatch) -> None:
    """A user whose rolling spend is already near the cap is blocked."""
    monkeypatch.setenv("TAKEOFF_AI_MAX_COST_USD", "2.00")
    ai_calls = _spy_call_ai(monkeypatch)
    _patch_no_schedule(monkeypatch)
    _patch_provider(monkeypatch)

    # 1.999 already spent; the next call's pre-flight estimate pushes over 2.00.
    run_repo = _FakeRunRepo(spend=1.999)
    doc = SimpleNamespace(pages=1, file_path=None)
    svc = _make_service(run_repo=run_repo, doc=doc)

    with pytest.raises(HTTPException) as exc:
        await svc.plan_read_start(
            project_id=uuid.uuid4(),
            document_id=str(uuid.uuid4()),
            page=1,
            mode="rooms",
            scale_pixels_per_unit=None,
            do_cost_match=False,
            user_id=str(uuid.uuid4()),
        )
    assert exc.value.status_code == 400
    assert ai_calls["calls"] == 0


@pytest.mark.asyncio
async def test_under_cap_creates_queued_run_and_schedules(monkeypatch) -> None:
    """Under the cap the run is created queued and the coroutine is scheduled."""
    monkeypatch.setenv("TAKEOFF_AI_MAX_COST_USD", "2.00")
    _spy_call_ai(monkeypatch)
    scheduled = _patch_no_schedule(monkeypatch)
    _patch_provider(monkeypatch)

    run_repo = _FakeRunRepo(spend=0.0)
    doc = SimpleNamespace(pages=2, file_path=None)
    svc = _make_service(run_repo=run_repo, doc=doc)

    run = await svc.plan_read_start(
        project_id=uuid.uuid4(),
        document_id=str(uuid.uuid4()),
        page=1,
        mode="rooms",
        scale_pixels_per_unit=None,
        do_cost_match=False,
        user_id=str(uuid.uuid4()),
    )
    assert run.status == "queued"
    assert run.failure_reason is None
    assert scheduled["scheduled"] == 1


@pytest.mark.asyncio
async def test_cost_recorded_equals_estimate_cost_usd(monkeypatch, tmp_path) -> None:
    """After a successful call the run cost equals estimate_cost_usd(model, tokens)."""
    import json

    from app.core.ai.pricing import estimate_cost_usd
    from app.modules.ai import ai_client as _ac
    from app.modules.takeoff import plan_read as pr

    monkeypatch.setenv("TAKEOFF_AI_MAX_COST_USD", "100.00")

    tokens = 1700
    model = "claude-sonnet-4-6"

    async def _fake(**_kwargs: Any) -> tuple[str, int]:
        return json.dumps({"scale": None, "rooms": [], "symbols": []}), tokens

    monkeypatch.setattr(_ac, "call_ai", _fake)

    def _raster(_content, _page, *, target_long_edge_px=2000):  # noqa: ANN001, ANN202, ARG001
        return (b"png", "image/png", 150, 1684.0, 2384.0)

    monkeypatch.setattr(pr, "rasterize_page", _raster)

    async def _resolve(_self, _user_id):  # noqa: ANN001, ANN202
        return "anthropic", "sk-test", None, model

    from app.modules.takeoff.service import TakeoffService

    monkeypatch.setattr(TakeoffService, "_resolve_plan_read_provider", _resolve)

    run_repo = _FakeRunRepo(spend=0.0)
    doc = SimpleNamespace(pages=1, file_path=str(tmp_path / "x.pdf"))
    (tmp_path / "x.pdf").write_bytes(b"%PDF stub")
    svc = object.__new__(TakeoffService)
    svc.session = SimpleNamespace()
    svc.repo = _FakeDocRepo(doc)

    class _MeasRepo:
        async def create_bulk(self, ms):  # noqa: ANN001, ANN202
            return ms

    svc.measurement_repo = _MeasRepo()
    svc.plan_read_repo = run_repo

    run = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        document_id=str(uuid.uuid4()),
        page=1,
        mode="rooms",
        user_id=uuid.uuid4(),
        status="queued",
        scale_pixels_per_unit=None,
        provider=None,
        model_used=None,
        total_tokens=0,
        cost_usd_estimate=0.0,
        duration_ms=0,
        proposal_count=0,
        accepted_count=0,
        validation_report=None,
        failure_reason=None,
        do_cost_match=False,
    )
    run_repo.runs[run.id] = run
    await svc._run_plan_read(run.id, user_id=str(run.user_id))

    assert run.status == "review"
    assert run.total_tokens == tokens
    assert run.cost_usd_estimate == pytest.approx(float(estimate_cost_usd(model, tokens)))
