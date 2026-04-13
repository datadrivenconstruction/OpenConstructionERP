"""Unit tests for :class:`CostModelService`.

Scope:
    Baseline smoke coverage for the 5D cost model service — asserts the
    core EVM calculation path, snapshot/budget roundtrips, dashboard
    aggregation, and (critically) verifies the ``schedule_unknown`` status
    regression fix so that unscheduled projects no longer get mislabelled
    as "on track" via the old 50 % time_elapsed_pct fallback.

These tests use in-memory mocks instead of a live DB session — the
service only touches repositories, so swapping them with
``SimpleNamespace`` stubs is enough and keeps the suite fast.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.costmodel.schemas import BudgetLineCreate, SnapshotCreate
from app.modules.costmodel.service import CostModelService

# ── Helpers ───────────────────────────────────────────────────────────────


def _make_service() -> CostModelService:
    """Build a service with a no-op session — repos get monkey-patched."""
    service = CostModelService.__new__(CostModelService)
    service.session = SimpleNamespace()  # not touched by tests
    service.snapshot_repo = _StubSnapshotRepo()
    service.budget_repo = _StubBudgetRepo()
    service.cashflow_repo = _StubCashflowRepo()
    return service


class _StubSnapshotRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, snapshot: Any) -> Any:
        if getattr(snapshot, "id", None) is None:
            snapshot.id = uuid.uuid4()
        self.rows[snapshot.id] = snapshot
        return snapshot

    async def get_by_id(self, snapshot_id: uuid.UUID) -> Any:
        return self.rows.get(snapshot_id)

    async def get_latest_for_project(self, project_id: uuid.UUID) -> Any:
        matches = [s for s in self.rows.values() if s.project_id == project_id]
        return matches[-1] if matches else None

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        period_from: str | None = None,
        period_to: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Any], int]:
        rows = [s for s in self.rows.values() if s.project_id == project_id]
        return rows, len(rows)

    async def delete(self, snapshot_id: uuid.UUID) -> None:
        self.rows.pop(snapshot_id, None)


class _StubBudgetRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._aggregate: dict[str, str] = {
            "total_planned": "0",
            "total_committed": "0",
            "total_actual": "0",
            "total_forecast": "0",
        }

    def set_aggregate(self, **values: str) -> None:
        self._aggregate.update(values)

    async def create(self, line: Any) -> Any:
        if getattr(line, "id", None) is None:
            line.id = uuid.uuid4()
        self.rows[line.id] = line
        return line

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        category: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if category is not None:
            rows = [r for r in rows if r.category == category]
        return rows, len(rows)

    async def aggregate_by_project(self, project_id: uuid.UUID) -> dict[str, str]:
        return dict(self._aggregate)


class _StubCashflowRepo:
    async def list_for_project(
        self, project_id: uuid.UUID, *, limit: int = 1000
    ) -> tuple[list[Any], int]:
        return [], 0


# ── EVM calculation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calculate_evm_zero_bac_returns_unknown() -> None:
    """With no budget at all, EVM can't be meaningfully computed."""
    service = _make_service()
    response = await service.calculate_evm(uuid.uuid4())
    assert response.bac == 0.0
    assert response.status == "unknown"


@pytest.mark.asyncio
async def test_calculate_evm_no_schedule_sets_schedule_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: projects with budget but no schedule must surface
    ``schedule_unknown`` rather than the legacy 50 % fallback that used
    to mislabel them as "on_track"/"at_risk" at random.
    """
    service = _make_service()
    service.budget_repo.set_aggregate(  # type: ignore[attr-defined]
        total_planned="1000000",
        total_actual="400000",
    )

    # Patch ScheduleRepository to return an empty list so the code hits
    # the "no schedule" branch.
    from app.modules.schedule import repository as schedule_repo_mod

    class _EmptySchedRepo:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None: ...

        async def list_for_project(
            self, project_id: uuid.UUID, *, limit: int = 50
        ) -> tuple[list[Any], int]:
            return [], 0

    class _EmptyActivityRepo:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None: ...

    monkeypatch.setattr(schedule_repo_mod, "ScheduleRepository", _EmptySchedRepo)
    monkeypatch.setattr(schedule_repo_mod, "ActivityRepository", _EmptyActivityRepo)

    response = await service.calculate_evm(uuid.uuid4())

    assert response.bac == 1_000_000.0
    assert response.ac == 400_000.0
    # This is the key regression assertion — the OLD code would have
    # produced "on_track"/"at_risk" here thanks to the silent 50 %.
    assert response.status == "schedule_unknown"
    assert response.time_elapsed_pct == 0.0


@pytest.mark.asyncio
async def test_calculate_evm_returns_bcws_bcwp_acwp_fields() -> None:
    """Stubbed-project sanity: the response exposes all BCWS/BCWP/ACWP
    columns callers rely on, even when they come back at 0."""
    service = _make_service()
    service.budget_repo.set_aggregate(  # type: ignore[attr-defined]
        total_planned="500000",
        total_actual="100000",
    )

    # We monkey-patch to keep schedule path empty — point of this test
    # is the response shape, not the numbers.
    from app.modules.schedule import repository as schedule_repo_mod

    class _EmptySchedRepo:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None: ...

        async def list_for_project(
            self, project_id: uuid.UUID, *, limit: int = 50
        ) -> tuple[list[Any], int]:
            return [], 0

    class _EmptyActivityRepo:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None: ...

    pytest.MonkeyPatch().setattr(
        schedule_repo_mod, "ScheduleRepository", _EmptySchedRepo
    )
    pytest.MonkeyPatch().setattr(
        schedule_repo_mod, "ActivityRepository", _EmptyActivityRepo
    )

    response = await service.calculate_evm(uuid.uuid4())

    for field in ("bac", "pv", "ev", "ac", "sv", "cv", "spi", "cpi", "eac"):
        assert hasattr(response, field), f"EVMResponse missing {field}"


# ── Snapshots ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_snapshot_persists_row() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    data = SnapshotCreate(
        project_id=pid,
        period="2026-04",
        planned_cost=100_000.0,
        earned_value=80_000.0,
        actual_cost=90_000.0,
    )
    snap = await service.create_snapshot(data)

    assert snap.id is not None
    # SPI auto-computed from EV / PV
    assert float(snap.spi) == pytest.approx(0.8, rel=1e-3)
    # CPI auto-computed from EV / AC
    assert float(snap.cpi) == pytest.approx(80_000 / 90_000, rel=1e-3)
    assert snap.id in service.snapshot_repo.rows  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_delete_snapshot_removes_row() -> None:
    """Exercises the new ``delete_snapshot`` method added alongside the
    router endpoint."""
    service = _make_service()
    pid = uuid.uuid4()
    snap = await service.create_snapshot(
        SnapshotCreate(project_id=pid, period="2026-04")
    )
    assert snap.id in service.snapshot_repo.rows  # type: ignore[attr-defined]

    await service.delete_snapshot(snap.id)

    assert snap.id not in service.snapshot_repo.rows  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_delete_snapshot_missing_raises_404() -> None:
    from fastapi import HTTPException

    service = _make_service()
    with pytest.raises(HTTPException) as exc_info:
        await service.delete_snapshot(uuid.uuid4())
    assert exc_info.value.status_code == 404


# ── Budget lines ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_line_create_and_list_roundtrip() -> None:
    service = _make_service()
    pid = uuid.uuid4()

    line = await service.create_budget_line(
        BudgetLineCreate(
            project_id=pid,
            category="material",
            description="Concrete C30/37",
            planned_amount=12_500.0,
        )
    )

    assert line.id is not None
    rows, total = await service.list_budget_lines(pid)
    assert total == 1
    assert rows[0].id == line.id
    assert rows[0].category == "material"


# ── Dashboard ─────────────────────────────────────────────────────────────


def test_delete_snapshot_route_is_registered() -> None:
    """Smoke: the DELETE /projects/{pid}/5d/snapshots/{sid} route the
    service depends on must be wired into the costmodel router, so the
    frontend "delete snapshot" button has something to call."""
    from app.modules.costmodel.router import router

    paths = {
        (route.path, method)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }
    assert (
        "/projects/{project_id}/5d/snapshots/{snapshot_id}",
        "DELETE",
    ) in paths


@pytest.mark.asyncio
async def test_get_dashboard_returns_aggregated_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service()
    pid = uuid.uuid4()
    service.budget_repo.set_aggregate(  # type: ignore[attr-defined]
        total_planned="100000",
        total_committed="40000",
        total_actual="30000",
        total_forecast="95000",
    )

    # Stub out _get_project_currency to avoid the projects import path.
    async def _fake_currency(_self: Any, _pid: uuid.UUID) -> str:
        return "EUR"

    monkeypatch.setattr(
        CostModelService, "_get_project_currency", _fake_currency
    )

    dashboard = await service.get_dashboard(pid)

    assert dashboard.total_budget == 100_000.0
    assert dashboard.total_committed == 40_000.0
    assert dashboard.total_actual == 30_000.0
    assert dashboard.total_forecast == 95_000.0
    # Variance = planned - forecast = 5000 → on_budget
    assert dashboard.status == "on_budget"
    assert dashboard.currency == "EUR"
