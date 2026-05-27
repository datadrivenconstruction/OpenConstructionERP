# OpenConstructionERP — DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""Round-7 tests for the Progress tracking module.

Covers:
    1. percent_complete enforcement: must be in [0, 100]
    2. Per-period delta computation from cumulative series
    3. S-curve: actual vs planned with gap handling
    4. Parent rollup: current_pct is avg of children's latest pct
    5. Geo-tagging: lat ∈ [-90, 90], lon ∈ [-180, 180] at schema level
    6. Geo-tagging: service-layer double-check raises 422 on out-of-range
    7. Upsert plan: idempotent on same (project, period_label)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.progress.schemas import (
    ProgressEntryCreate,
    ProgressPlanCreate,
)
from app.modules.progress.service import ProgressService, _compute_deltas

PROJECT_ID = uuid.uuid4()


# ── Stubs ─────────────────────────────────────────────────────────────────────


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass


class _StubProgressRepo:
    def __init__(self) -> None:
        self.entries: list[Any] = []
        self.plans: dict[str, Any] = {}  # period_label -> plan
        # Customisable outputs for child-position tests
        self._child_ids: list[uuid.UUID] = []
        self._child_pcts: dict[uuid.UUID, float] = {}

    async def create_entry(self, entry: Any) -> Any:
        if getattr(entry, "id", None) is None:
            from types import SimpleNamespace

            entry = SimpleNamespace(
                **{
                    k: getattr(entry, k)
                    for k in (
                        "project_id",
                        "boq_position_id",
                        "period_label",
                        "percent_complete",
                        "notes",
                        "recorded_by",
                        "geo_lat",
                        "geo_lon",
                        "photos",
                        "metadata_",
                    )
                }
            )
            entry.id = uuid.uuid4()
            now = datetime.now(UTC)
            entry.recorded_at = now
            entry.created_at = now
            entry.updated_at = now
        self.entries.append(entry)
        return entry

    async def get_entry(self, entry_id: uuid.UUID) -> Any:
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None

    async def list_entries_for_project(
        self,
        project_id: uuid.UUID,
        *,
        boq_position_id: uuid.UUID | None = None,
        period_label: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Any]:
        rows = [e for e in self.entries if e.project_id == project_id]
        if boq_position_id is not None:
            rows = [e for e in rows if getattr(e, "boq_position_id", None) == boq_position_id]
        if period_label is not None:
            rows = [e for e in rows if e.period_label == period_label]
        return sorted(rows, key=lambda e: e.recorded_at)[offset : offset + limit]

    async def entries_grouped_by_period(
        self,
        project_id: uuid.UUID,
        boq_position_id: uuid.UUID | None = None,
    ) -> list[tuple[str, float]]:
        rows = [e for e in self.entries if e.project_id == project_id]
        if boq_position_id is not None:
            rows = [e for e in rows if getattr(e, "boq_position_id", None) == boq_position_id]
        by_period: dict[str, float] = {}
        for e in rows:
            pct = float(e.percent_complete)
            by_period[e.period_label] = max(by_period.get(e.period_label, 0.0), pct)
        return sorted(by_period.items(), key=lambda x: x[0])

    async def latest_pct_for_positions(
        self,
        project_id: uuid.UUID,
        position_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, float]:
        return {k: v for k, v in self._child_pcts.items() if k in position_ids}

    async def upsert_plan(
        self,
        project_id: uuid.UUID,
        period_label: str,
        planned_pct: float,
        notes: str | None = None,
    ) -> Any:
        from types import SimpleNamespace

        key = f"{project_id}:{period_label}"
        if key in self.plans:
            self.plans[key].planned_pct = planned_pct
        else:
            plan = SimpleNamespace(
                id=uuid.uuid4(),
                project_id=project_id,
                period_label=period_label,
                planned_pct=planned_pct,
                notes=notes,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self.plans[key] = plan
        return self.plans[key]

    async def list_plan(self, project_id: uuid.UUID) -> list[Any]:
        return sorted(
            [p for k, p in self.plans.items() if k.startswith(str(project_id))],
            key=lambda p: p.period_label,
        )


def _make_service() -> ProgressService:
    svc = ProgressService.__new__(ProgressService)
    svc.session = _StubSession()  # type: ignore[assignment]
    svc.repo = _StubProgressRepo()  # type: ignore[assignment]
    return svc


# ── 1. percent_complete range enforcement ─────────────────────────────────────


def test_pct_below_zero_rejected_by_schema() -> None:
    """percent_complete < 0 raises ValidationError."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ProgressEntryCreate(
            project_id=PROJECT_ID,
            period_label="2026-W20",
            percent_complete=-1.0,
        )


def test_pct_above_100_rejected_by_schema() -> None:
    """percent_complete > 100 raises ValidationError."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ProgressEntryCreate(
            project_id=PROJECT_ID,
            period_label="2026-W20",
            percent_complete=100.001,
        )


def test_pct_boundary_values_accepted() -> None:
    """0.0 and 100.0 are both valid percent_complete values."""
    e0 = ProgressEntryCreate(
        project_id=PROJECT_ID,
        period_label="2026-W01",
        percent_complete=0.0,
    )
    e100 = ProgressEntryCreate(
        project_id=PROJECT_ID,
        period_label="2026-W52",
        percent_complete=100.0,
    )
    assert e0.percent_complete == 0.0
    assert e100.percent_complete == 100.0


@pytest.mark.asyncio
async def test_service_double_check_rejects_out_of_range() -> None:
    """Service layer raises 422 even if Pydantic is somehow bypassed."""
    from types import SimpleNamespace

    from fastapi import HTTPException

    svc = _make_service()
    # Craft a schema object that bypasses Pydantic (direct construction)
    data = SimpleNamespace(
        project_id=PROJECT_ID,
        boq_position_id=None,
        period_label="2026-W21",
        percent_complete=150.0,  # invalid
        notes=None,
        geo_lat=None,
        geo_lon=None,
        photos=[],
        metadata={},
    )
    with pytest.raises(HTTPException) as exc_info:
        await svc.record_entry(data, user_id="test")  # type: ignore[arg-type]
    assert exc_info.value.status_code == 422


# ── 2. Per-period delta computation ──────────────────────────────────────────


def test_compute_deltas_single_period() -> None:
    """Single period: delta = cumulative_pct, previous = 0."""
    rows = [("2026-W01", 30.0)]
    result = _compute_deltas(rows)
    assert len(result) == 1
    assert result[0].delta_pct == 30.0
    assert result[0].cumulative_pct == 30.0


def test_compute_deltas_sequential_growth() -> None:
    """Deltas are differences between consecutive cumulative readings."""
    rows = [("2026-W01", 20.0), ("2026-W02", 45.0), ("2026-W03", 70.0)]
    result = _compute_deltas(rows)
    assert result[0].delta_pct == 20.0
    assert result[1].delta_pct == 25.0
    assert result[2].delta_pct == 25.0
    assert result[2].cumulative_pct == 70.0


def test_compute_deltas_clamps_negative_delta() -> None:
    """A correction entry that lowers cumulative % produces delta=0 (not negative)."""
    rows = [("2026-W01", 50.0), ("2026-W02", 40.0)]  # correction lowered pct
    result = _compute_deltas(rows)
    assert result[1].delta_pct == 0.0  # clamped
    assert result[1].cumulative_pct == 40.0  # actual value still shown


def test_compute_deltas_empty_returns_empty() -> None:
    assert _compute_deltas([]) == []


# ── 3. S-curve: actual vs planned ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s_curve_merges_actual_and_planned() -> None:
    """S-curve returns actual + planned, aligned by period_label."""
    svc = _make_service()
    repo: _StubProgressRepo = svc.repo  # type: ignore[assignment]

    # Record actual entries for W01 and W02
    for period, pct in [("2026-W01", 25.0), ("2026-W02", 55.0)]:
        await svc.record_entry(
            ProgressEntryCreate(
                project_id=PROJECT_ID,
                period_label=period,
                percent_complete=pct,
            )
        )

    # Add a plan for W01 and W03 (no plan for W02)
    await svc.upsert_plan_point(ProgressPlanCreate(project_id=PROJECT_ID, period_label="2026-W01", planned_pct=30.0))
    await svc.upsert_plan_point(ProgressPlanCreate(project_id=PROJECT_ID, period_label="2026-W03", planned_pct=80.0))

    result = await svc.get_s_curve(PROJECT_ID)
    assert len(result.points) == 3  # W01, W02, W03

    by_period = {p.period_label: p for p in result.points}

    assert by_period["2026-W01"].actual_cumulative_pct == 25.0
    assert by_period["2026-W01"].planned_cumulative_pct == 30.0

    assert by_period["2026-W02"].actual_cumulative_pct == 55.0
    assert by_period["2026-W02"].planned_cumulative_pct is None  # no plan for W02

    assert by_period["2026-W03"].actual_cumulative_pct == 55.0  # carry-forward
    assert by_period["2026-W03"].planned_cumulative_pct == 80.0


# ── 4. Parent rollup from children ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_parent_rollup_averages_child_pcts() -> None:
    """A parent position's current_pct is the avg of children's latest pct."""
    svc = _make_service()
    repo: _StubProgressRepo = svc.repo  # type: ignore[assignment]

    parent_id = uuid.uuid4()
    child_a = uuid.uuid4()
    child_b = uuid.uuid4()

    # Inject child IDs and their latest pcts directly (avoids BOQ DB query)
    repo._child_pcts = {child_a: 60.0, child_b: 40.0}

    # Override the _fetch_child_ids method to return our fake children
    async def _fake_fetch(project_id: uuid.UUID, pid: uuid.UUID) -> list[uuid.UUID]:
        if pid == parent_id:
            return [child_a, child_b]
        return []

    svc._fetch_child_ids = _fake_fetch  # type: ignore[method-assign]

    summary = await svc.get_position_summary(PROJECT_ID, parent_id)
    assert summary.is_rollup is True
    # (60 + 40) / 2 == 50
    assert summary.current_pct == 50.0


@pytest.mark.asyncio
async def test_leaf_position_uses_own_latest_entry() -> None:
    """A leaf position (no children) uses its own most-recent entry."""
    svc = _make_service()

    # No children
    async def _no_children(project_id: uuid.UUID, pid: uuid.UUID) -> list[uuid.UUID]:
        return []

    svc._fetch_child_ids = _no_children  # type: ignore[method-assign]

    position_id = uuid.uuid4()
    for pct in [30.0, 70.0]:
        await svc.record_entry(
            ProgressEntryCreate(
                project_id=PROJECT_ID,
                boq_position_id=position_id,
                period_label="2026-W01",
                percent_complete=pct,
            )
        )

    summary = await svc.get_position_summary(PROJECT_ID, position_id)
    assert summary.is_rollup is False
    # Most-recent entry is 70.0 (last appended)
    assert summary.current_pct == 70.0


# ── 5. Geo-tagging schema validation ─────────────────────────────────────────


def test_geo_lat_above_90_rejected() -> None:
    """geo_lat > 90 is rejected at the Pydantic schema level."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ProgressEntryCreate(
            project_id=PROJECT_ID,
            period_label="2026-W01",
            percent_complete=50.0,
            geo_lat=90.1,
            geo_lon=0.0,
        )


def test_geo_lon_below_minus_180_rejected() -> None:
    """geo_lon < -180 is rejected at the Pydantic schema level."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ProgressEntryCreate(
            project_id=PROJECT_ID,
            period_label="2026-W01",
            percent_complete=50.0,
            geo_lat=0.0,
            geo_lon=-180.1,
        )


@pytest.mark.asyncio
async def test_service_geo_validation_lat_out_of_range() -> None:
    """Service-layer _validate_geo raises 422 for lat out of range."""
    from fastapi import HTTPException

    from app.modules.progress.service import _validate_geo

    with pytest.raises(HTTPException) as exc_info:
        _validate_geo(91.0, 0.0)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_service_geo_validation_lon_out_of_range() -> None:
    """Service-layer _validate_geo raises 422 for lon out of range."""
    from fastapi import HTTPException

    from app.modules.progress.service import _validate_geo

    with pytest.raises(HTTPException) as exc_info:
        _validate_geo(0.0, -181.0)
    assert exc_info.value.status_code == 422


# ── 6. Plan upsert idempotency ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_upsert_updates_existing_point() -> None:
    """Upserting the same (project, period) twice updates rather than creates."""
    svc = _make_service()

    data1 = ProgressPlanCreate(project_id=PROJECT_ID, period_label="2026-W05", planned_pct=40.0)
    data2 = ProgressPlanCreate(project_id=PROJECT_ID, period_label="2026-W05", planned_pct=50.0)

    await svc.upsert_plan_point(data1)
    await svc.upsert_plan_point(data2)

    plans = await svc.list_plan(PROJECT_ID)
    assert len(plans) == 1
    assert float(plans[0].planned_pct) == 50.0


# ── 7. Cumulative breakdown correctness ──────────────────────────────────────


@pytest.mark.asyncio
async def test_cumulative_response_has_correct_running_total() -> None:
    """CumulativeProgressResponse.current_cumulative_pct equals last period's value."""
    svc = _make_service()

    for period, pct in [("W01", 10.0), ("W02", 40.0), ("W03", 80.0)]:
        await svc.record_entry(ProgressEntryCreate(project_id=PROJECT_ID, period_label=period, percent_complete=pct))

    result = await svc.get_cumulative(PROJECT_ID)
    assert result.current_cumulative_pct == 80.0
    assert len(result.periods) == 3
    # Verify deltas
    deltas = {p.period_label: p.delta_pct for p in result.periods}
    assert deltas["W01"] == 10.0
    assert deltas["W02"] == 30.0
    assert deltas["W03"] == 40.0
