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
from datetime import date
from decimal import Decimal
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

    async def get_for_project_period(self, project_id: uuid.UUID, period: str) -> Any:
        for snap in self.rows.values():
            if snap.project_id == project_id and snap.period == period:
                return snap
        return None

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
        self._by_category: list[dict[str, str]] = []

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

    async def distinct_currencies(self, project_id: uuid.UUID) -> set[str]:
        return {
            (getattr(r, "currency", "") or "").strip().upper()
            for r in self.rows.values()
            if r.project_id == project_id and (getattr(r, "currency", "") or "").strip()
        }

    async def aggregate_by_category(self, project_id: uuid.UUID, **_kwargs: Any) -> list[dict[str, str]]:
        return list(self._by_category)

    def set_by_category(self, rows: list[dict[str, str]]) -> None:
        self._by_category = rows


class _StubCashflowRepo:
    async def list_for_project(self, project_id: uuid.UUID, *, limit: int = 1000) -> tuple[list[Any], int]:
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

        async def list_for_project(self, project_id: uuid.UUID, *, limit: int = 50) -> tuple[list[Any], int]:
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

        async def list_for_project(self, project_id: uuid.UUID, *, limit: int = 50) -> tuple[list[Any], int]:
            return [], 0

    class _EmptyActivityRepo:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None: ...

    pytest.MonkeyPatch().setattr(schedule_repo_mod, "ScheduleRepository", _EmptySchedRepo)
    pytest.MonkeyPatch().setattr(schedule_repo_mod, "ActivityRepository", _EmptyActivityRepo)

    response = await service.calculate_evm(uuid.uuid4())

    for field in ("bac", "pv", "ev", "ac", "sv", "cv", "spi", "cpi", "eac"):
        assert hasattr(response, field), f"EVMResponse missing {field}"


# ── Time-phased Planned Value ───────────────────────────────────────────────


def _line(amount: str, *, activity_id: Any = None, period: tuple[str, str] | None = None) -> SimpleNamespace:
    """Build a BudgetLine-shaped stub for the time-phased PV helper."""
    return SimpleNamespace(
        planned_amount=amount,
        activity_id=activity_id,
        period_start=period[0] if period else None,
        period_end=period[1] if period else None,
    )


def test_time_phased_pv_two_activity_windows_at_mid_date() -> None:
    """Two lines on different activity windows are time-phased independently.

    Line A: 100,000 over 2026-01-01 .. 2026-01-11 (10-day window).
    Line B:  60,000 over 2026-01-06 .. 2026-01-16 (10-day window).
    As-of  : 2026-01-11.

        A fraction = (Jan11 - Jan01) / 10 = 10/10 = 1.0   → 100,000
        B fraction = (Jan11 - Jan06) / 10 =  5/10 = 0.5   →  30,000
        PV         = 130,000
    """
    act_a = uuid.uuid4()
    act_b = uuid.uuid4()
    lines = [
        _line("100000", activity_id=act_a),
        _line("60000", activity_id=act_b),
    ]
    activity_window = {
        str(act_a): (date(2026, 1, 1), date(2026, 1, 11)),
        str(act_b): (date(2026, 1, 6), date(2026, 1, 16)),
    }

    pv = CostModelService._time_phased_pv(
        lines,
        activity_window=activity_window,
        project_period=None,
        as_of=date(2026, 1, 11),
        time_elapsed_pct=0.0,
    )
    assert pv == Decimal("130000")


def test_time_phased_pv_falls_back_to_line_period() -> None:
    """A line with no activity link uses its own period_start/period_end.

    Line: 80,000 over 2026-03-01 .. 2026-03-05 (4-day window), as-of mid =
    2026-03-03 → fraction = 2/4 = 0.5 → PV = 40,000.
    """
    lines = [_line("80000", period=("2026-03-01", "2026-03-05"))]
    pv = CostModelService._time_phased_pv(
        lines,
        activity_window={},
        project_period=None,
        as_of=date(2026, 3, 3),
        time_elapsed_pct=0.0,
    )
    assert pv == Decimal("40000")


def test_time_phased_pv_falls_back_to_project_period() -> None:
    """No activity link and no line period → distribute over the project period."""
    lines = [_line("50000")]
    pv = CostModelService._time_phased_pv(
        lines,
        activity_window={},
        project_period=(date(2026, 1, 1), date(2026, 1, 11)),
        as_of=date(2026, 1, 6),  # halfway through the 10-day project window
        time_elapsed_pct=0.0,
    )
    assert pv == Decimal("25000")


def test_time_phased_pv_last_resort_approximation() -> None:
    """With no window of any kind, fall back to amount × time_elapsed%."""
    lines = [_line("200000")]
    pv = CostModelService._time_phased_pv(
        lines,
        activity_window={},
        project_period=None,
        as_of=date(2026, 1, 1),
        time_elapsed_pct=30.0,
    )
    assert pv == Decimal("60000.0")


@pytest.mark.asyncio
async def test_calculate_evm_uses_time_phased_pv_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: calculate_evm wires time-phased PV from activities.

    Two budget lines linked to two activities with different windows that
    both fully span before today (a 2020 schedule), so each line is 100 %
    time-phased and PV == BAC. This proves the wiring distributes per line
    rather than using the old BAC × time_elapsed% proxy.
    """
    service = _make_service()
    pid = uuid.uuid4()
    act_a = uuid.uuid4()
    act_b = uuid.uuid4()

    service.budget_repo.set_aggregate(  # type: ignore[attr-defined]
        total_planned="160000",
        total_actual="0",
    )
    # Seed two activity-linked budget lines into the stub repo.
    await service.budget_repo.create(  # type: ignore[attr-defined]
        SimpleNamespace(project_id=pid, activity_id=act_a, planned_amount="100000", category="material")
    )
    await service.budget_repo.create(  # type: ignore[attr-defined]
        SimpleNamespace(project_id=pid, activity_id=act_b, planned_amount="60000", category="labor")
    )

    from app.modules.schedule import repository as schedule_repo_mod

    sched = SimpleNamespace(id=uuid.uuid4(), start_date="2020-01-01", end_date="2020-12-31")

    class _SchedRepo:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def list_for_project(self, project_id: uuid.UUID, *, limit: int = 50) -> tuple[list[Any], int]:
            return [sched], 1

    class _ActivityRepo:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def list_for_schedule(self, schedule_id: uuid.UUID, *, limit: int = 10000) -> tuple[list[Any], int]:
            return (
                [
                    SimpleNamespace(id=act_a, start_date="2020-01-01", end_date="2020-03-01", progress_pct="100"),
                    SimpleNamespace(id=act_b, start_date="2020-04-01", end_date="2020-06-01", progress_pct="100"),
                ],
                2,
            )

    monkeypatch.setattr(schedule_repo_mod, "ScheduleRepository", _SchedRepo)
    monkeypatch.setattr(schedule_repo_mod, "ActivityRepository", _ActivityRepo)

    response = await service.calculate_evm(pid)

    # Both activity windows are entirely in the past → each line is 100 %
    # planned-value-earned → PV == BAC == 160,000.
    assert response.bac == 160_000.0
    assert response.pv == 160_000.0


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
    snap = await service.create_snapshot(SnapshotCreate(project_id=pid, period="2026-04"))
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

    paths = {(route.path, method) for route in router.routes for method in getattr(route, "methods", set())}
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

    monkeypatch.setattr(CostModelService, "_get_project_currency", _fake_currency)

    dashboard = await service.get_dashboard(pid)

    assert dashboard.total_budget == 100_000.0
    assert dashboard.total_committed == 40_000.0
    assert dashboard.total_actual == 30_000.0
    assert dashboard.total_forecast == 95_000.0
    # Variance = planned - forecast = 5000 → on_budget
    assert dashboard.status == "on_budget"
    assert dashboard.currency == "EUR"


@pytest.mark.asyncio
async def test_get_dashboard_no_currency_does_not_fabricate_eur(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression (currency must be data-driven): when the project lookup
    yields no currency the dashboard must return an empty string, never a
    hardcoded ``EUR`` — that silently mislabels USD/GBP/JPY budgets.
    """
    service = _make_service()
    pid = uuid.uuid4()
    service.budget_repo.set_aggregate(total_planned="100000")  # type: ignore[attr-defined]

    class _NoCurrencyRepo:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def get_by_id(self, _pid: uuid.UUID) -> Any:
            return SimpleNamespace(currency="")

    from app.modules.projects import repository as proj_repo_mod

    monkeypatch.setattr(proj_repo_mod, "ProjectRepository", _NoCurrencyRepo)

    dashboard = await service.get_dashboard(pid)

    assert dashboard.currency == ""


@pytest.mark.asyncio
async def test_get_dashboard_uses_project_currency_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A project configured in USD must surface USD, not EUR."""
    service = _make_service()
    pid = uuid.uuid4()
    service.budget_repo.set_aggregate(total_planned="50000")  # type: ignore[attr-defined]

    class _UsdRepo:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def get_by_id(self, _pid: uuid.UUID) -> Any:
            return SimpleNamespace(currency="USD")

    from app.modules.projects import repository as proj_repo_mod

    monkeypatch.setattr(proj_repo_mod, "ProjectRepository", _UsdRepo)

    dashboard = await service.get_dashboard(pid)

    assert dashboard.currency == "USD"


# ── Budget summary ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_summary_returns_absolute_variance() -> None:
    """Regression (BUG-1): ``BudgetCategoryRow`` must carry an absolute
    ``variance`` (planned - forecast) so the frontend table stops having to
    recompute it locally — the field used to be missing from the payload.
    """
    service = _make_service()
    pid = uuid.uuid4()
    service.budget_repo.set_by_category(  # type: ignore[attr-defined]
        [
            {
                "category": "material",
                "planned": "100000",
                "committed": "20000",
                "actual": "30000",
                "forecast": "90000",
            },
            {
                "category": "labor",
                "planned": "50000",
                "committed": "0",
                "actual": "10000",
                "forecast": "60000",
            },
        ]
    )

    summary = await service.get_budget_summary(pid)

    by_cat = {c.category: c for c in summary.categories}
    # material: under forecast → positive variance
    assert by_cat["material"].variance == 10_000.0
    assert by_cat["material"].variance_pct == 10.0
    # labor: over forecast → negative variance
    assert by_cat["labor"].variance == -10_000.0
    assert by_cat["labor"].variance_pct == -20.0


# ── S-curve ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s_curve_plots_snapshot_values_without_double_cumulation() -> None:
    """Regression (BUG-6): EVM snapshots store cumulative-to-date BCWS/BCWP/
    ACWP. The S-curve must plot them verbatim — the previous implementation
    re-summed them across periods and produced curves that climbed far past
    BAC (a what-if snapshot storing BAC alone would already exceed it).
    """
    service = _make_service()
    pid = uuid.uuid4()

    await service.create_snapshot(
        SnapshotCreate(
            project_id=pid,
            period="2026-01",
            planned_cost=100_000.0,
            earned_value=90_000.0,
            actual_cost=95_000.0,
        )
    )
    await service.create_snapshot(
        SnapshotCreate(
            project_id=pid,
            period="2026-02",
            planned_cost=200_000.0,
            earned_value=180_000.0,
            actual_cost=190_000.0,
        )
    )

    s_curve = await service.get_s_curve(pid)
    points = {p.period: p for p in s_curve.periods}

    # Values are plotted as-is, NOT 100k + 200k = 300k for Feb.
    assert points["2026-01"].planned == 100_000.0
    assert points["2026-02"].planned == 200_000.0
    assert points["2026-02"].earned == 180_000.0
    assert points["2026-02"].actual == 190_000.0
