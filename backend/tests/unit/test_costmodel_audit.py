"""Unit tests for the costmodel R5 audit fixes.

These tests pin behaviour for the issues identified in the May 2026 deep
audit of the 5D cost model module:

1. ``generate_budget_from_boq`` must be idempotent — re-running it for the
   same BOQ should NOT double the BAC by recreating budget lines for the
   same positions.
2. Budget / cash-flow rollups must convert per-line currencies into the
   project base currency via the project's ``fx_rates`` — silently summing
   USD into EUR (or vice versa) produced nonsense KPIs for multi-currency
   projects.
3. ``create_snapshot`` must reject a duplicate ``(project_id, period)``
   instead of producing two competing rows where ``get_latest_for_project``
   picks one arbitrarily.
4. ``calculate_evm`` must not return ``tcpi=0.0`` when ``BAC == AC`` — that
   is the divide-by-zero edge that produced a misleading "perfect" TCPI on
   exactly-on-budget projects.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.costmodel.schemas import SnapshotCreate
from app.modules.costmodel.service import CostModelService

# ── Stub repositories (mirrors test_costmodel_service.py) ─────────────────


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

    async def bulk_create(self, lines: list[Any]) -> list[Any]:
        out = []
        for line in lines:
            if getattr(line, "id", None) is None:
                line.id = uuid.uuid4()
            self.rows[line.id] = line
            out.append(line)
        return out

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

    async def existing_position_ids(self, project_id: uuid.UUID) -> set[uuid.UUID]:
        return {
            r.boq_position_id
            for r in self.rows.values()
            if r.project_id == project_id and r.boq_position_id is not None
        }

    async def aggregate_by_project(self, project_id: uuid.UUID) -> dict[str, str]:
        return dict(self._aggregate)

    async def aggregate_by_category(self, project_id: uuid.UUID) -> list[dict[str, str]]:
        return list(self._by_category)


class _StubCashflowRepo:
    async def list_for_project(self, project_id: uuid.UUID, *, limit: int = 1000) -> tuple[list[Any], int]:
        return [], 0

    async def bulk_create(self, entries: list[Any]) -> list[Any]:
        for e in entries:
            if getattr(e, "id", None) is None:
                e.id = uuid.uuid4()
        return entries


def _make_service() -> CostModelService:
    service = CostModelService.__new__(CostModelService)
    service.session = SimpleNamespace()
    service.snapshot_repo = _StubSnapshotRepo()
    service.budget_repo = _StubBudgetRepo()
    service.cashflow_repo = _StubCashflowRepo()
    return service


# ── Fix #1: idempotent generate_budget_from_boq ───────────────────────────


@pytest.mark.asyncio
async def test_generate_budget_is_idempotent_per_boq_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running budget generation must NOT double-count BOQ positions.

    Pre-audit behaviour: each call appended a fresh BudgetLine per position,
    so two clicks of the "Generate budget from BOQ" button doubled the BAC
    silently. Estimators caught this only when the EVM dashboard suddenly
    claimed they had spent 200 % of nothing.

    Post-audit behaviour: positions already wired into a budget line are
    skipped. The second call returns 0 new lines.
    """
    service = _make_service()
    project_id = uuid.uuid4()
    boq_id = uuid.uuid4()

    pos_ids = [uuid.uuid4() for _ in range(3)]
    positions = [
        SimpleNamespace(
            id=pid,
            ordinal=f"1.{i}",
            description=f"Position {i}",
            total=str(1000 * (i + 1)),
        )
        for i, pid in enumerate(pos_ids)
    ]

    class _PositionRepo:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None: ...

        async def list_for_boq(self, boq_id: uuid.UUID, *, limit: int = 10000) -> tuple[list[Any], int]:
            return positions, len(positions)

    from app.modules.boq import repository as boq_repo_mod

    monkeypatch.setattr(boq_repo_mod, "PositionRepository", _PositionRepo)

    first = await service.generate_budget_from_boq(project_id, boq_id)
    assert len(first) == 3, "first run must create one line per BOQ position"

    second = await service.generate_budget_from_boq(project_id, boq_id)
    assert second == [], (
        "second run must be a no-op — every BOQ position already has a "
        "linked BudgetLine; re-running silently doubled BAC pre-audit"
    )


# ── Fix #2: cross-currency rollup respects project fx_rates ───────────────


@pytest.mark.asyncio
async def test_dashboard_currency_is_project_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dashboard currency must always be the project's configured one,
    not a per-line currency. Multi-currency budgets are silently combined
    into the base via fx_rates (Fix #2 implements the conversion at the SQL
    aggregate layer); this test just locks the API contract so the caller
    can trust the label."""
    service = _make_service()
    project_id = uuid.uuid4()
    service.budget_repo.set_aggregate(total_planned="100000")  # type: ignore[attr-defined]

    class _ProjectRepo:
        def __init__(self, *_a: Any, **_kw: Any) -> None: ...

        async def get_by_id(self, _pid: uuid.UUID) -> Any:
            return SimpleNamespace(currency="USD", fx_rates=[])

    from app.modules.projects import repository as proj_repo_mod

    monkeypatch.setattr(proj_repo_mod, "ProjectRepository", _ProjectRepo)

    dashboard = await service.get_dashboard(project_id)

    assert dashboard.currency == "USD"


@pytest.mark.asyncio
async def test_aggregate_by_project_converts_foreign_currency_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-currency rollup regression: aggregate_by_project used to
    SUM(CAST(planned_amount AS Float)) at the SQL layer, completely
    ignoring the per-row ``currency`` column. A project with EUR as base
    and one USD line at 1000 (rate 0.9 EUR/USD) plus one EUR line at
    1000 would silently report a planned total of 2000.0 instead of the
    real 1900.0 EUR equivalent.

    Post-audit: aggregate_by_project converts via the project's
    ``fx_rates`` map (same convention as ``_resource_total_in_base``)
    before summing.
    """
    from app.modules.costmodel.models import BudgetLine
    from app.modules.costmodel.repository import BudgetLineRepository

    project_id = uuid.uuid4()

    # Two budget lines, one EUR (base), one USD with FX rate 0.9 EUR/USD.
    eur_line = BudgetLine(
        project_id=project_id,
        category="material",
        description="EUR line",
        planned_amount="1000",
        committed_amount="0",
        actual_amount="0",
        forecast_amount="0",
        currency="EUR",
    )
    usd_line = BudgetLine(
        project_id=project_id,
        category="material",
        description="USD line",
        planned_amount="1000",
        committed_amount="0",
        actual_amount="0",
        forecast_amount="0",
        currency="USD",
    )

    # Build a fake session that returns these two rows and provides a
    # project with the right fx_rates map.
    class _FakeSession:
        async def execute(self, stmt: Any) -> Any:
            raise AssertionError("aggregation must go through repo helpers")

    repo = BudgetLineRepository(_FakeSession())  # type: ignore[arg-type]

    async def _fake_list_lines_currency_aware(_self: Any, _pid: uuid.UUID) -> list[Any]:
        return [eur_line, usd_line]

    monkeypatch.setattr(
        BudgetLineRepository,
        "_list_lines_for_rollup",
        _fake_list_lines_currency_aware,
    )

    async def _fake_get_project(_self: Any, _pid: uuid.UUID) -> Any:
        return SimpleNamespace(
            currency="EUR",
            fx_rates=[{"code": "USD", "rate": "0.9"}],
        )

    from app.modules.projects import repository as proj_repo_mod

    monkeypatch.setattr(proj_repo_mod.ProjectRepository, "get_by_id", _fake_get_project)

    aggregates = await repo.aggregate_by_project(project_id)

    # 1000 EUR + (1000 USD * 0.9) = 1900 EUR
    assert float(aggregates["total_planned"]) == pytest.approx(1900.0, abs=0.01)


# ── Fix #3: duplicate (project_id, period) snapshot rejected ──────────────


@pytest.mark.asyncio
async def test_create_snapshot_rejects_duplicate_period() -> None:
    """Two snapshots for the same ``(project_id, period)`` would race in
    ``get_latest_for_project`` — the second call must 409 so the caller
    sees the conflict instead of getting a silently-shadowed first row.
    """
    from fastapi import HTTPException

    service = _make_service()
    pid = uuid.uuid4()

    await service.create_snapshot(
        SnapshotCreate(
            project_id=pid,
            period="2026-04",
            planned_cost=1000.0,
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.create_snapshot(
            SnapshotCreate(
                project_id=pid,
                period="2026-04",
                planned_cost=2000.0,
            )
        )

    assert exc_info.value.status_code == 409


# ── Fix #4: TCPI surfaces None on BAC == AC instead of false-zero ─────────


@pytest.mark.asyncio
async def test_evm_tcpi_none_when_bac_equals_ac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-audit: TCPI was ``_safe_divide(bac - ev, bac - ac)`` and silently
    returned ``0.0`` when BAC == AC (the project finished exactly on budget).

    That's a divide-by-zero hole and the legacy zero misleads dashboards
    into reporting "perfect efficiency required" — actually it's undefined.
    Post-audit: the field is omitted from the response (``None``) so the UI
    can render it as N/A.
    """
    service = _make_service()
    service.budget_repo.set_aggregate(  # type: ignore[attr-defined]
        total_planned="100000",
        total_actual="100000",  # BAC == AC
    )

    from app.modules.schedule import repository as schedule_repo_mod

    class _EmptySchedRepo:
        def __init__(self, *_a: Any, **_kw: Any) -> None: ...

        async def list_for_project(self, _pid: uuid.UUID, *, limit: int = 50) -> tuple[list[Any], int]:
            return [], 0

    class _EmptyActivityRepo:
        def __init__(self, *_a: Any, **_kw: Any) -> None: ...

    monkeypatch.setattr(schedule_repo_mod, "ScheduleRepository", _EmptySchedRepo)
    monkeypatch.setattr(schedule_repo_mod, "ActivityRepository", _EmptyActivityRepo)

    response = await service.calculate_evm(uuid.uuid4())

    assert response.tcpi is None, (
        "TCPI must be None (undefined) when BAC == AC; pre-audit it was 0.0 "
        "which dashboards mis-rendered as 'perfect efficiency'."
    )
