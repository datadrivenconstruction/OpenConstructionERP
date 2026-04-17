"""Unit tests for the Project Intelligence analytics endpoints (RFC 25).

Scope:
    - Happy path for each of the 5 new services:
      * ``CostModelService.get_variance``
      * ``BOQService.get_line_items``
      * ``BOQService.get_cost_rollup``
      * ``BOQService.get_anomalies``
      * ``TenderingService.get_bid_analysis``
      * ``ScheduleService.get_labor_cost_by_phase``
    - Empty-project edge case for each — the endpoint must return an empty
      container (never None, never a 500).

Repositories / SQLAlchemy sessions are stubbed via fake execute results so
the tests stay hermetic.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.modules.boq.service import BOQService
from app.modules.costmodel.service import CostModelService
from app.modules.schedule.service import ScheduleService
from app.modules.tendering.service import TenderingService

PROJECT_ID = uuid.uuid4()


# ── Fake SQLAlchemy Result helpers ────────────────────────────────────────


class _FakeScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeExecuteResult:
    """Mimics the subset of the SQLAlchemy Result API we rely on."""

    def __init__(self, rows: list[Any] | None = None, all_rows: list[Any] | None = None) -> None:
        self._rows = rows or []
        self._all_rows = all_rows if all_rows is not None else rows or []

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._rows)

    def all(self) -> list[Any]:
        return list(self._all_rows)


def _make_position(
    *,
    total: float,
    unit_rate: float,
    quantity: float = 1.0,
    unit: str = "m3",
    classification: dict[str, str] | None = None,
    boq_id: uuid.UUID | None = None,
    ordinal: str = "01.001",
    description: str = "Sample position",
    sort_order: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        boq_id=boq_id or uuid.uuid4(),
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=str(quantity),
        unit_rate=str(unit_rate),
        total=str(total),
        classification=classification or {},
        sort_order=sort_order,
    )


# ── CostModelService.get_variance ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_variance_happy_path() -> None:
    service = CostModelService.__new__(CostModelService)
    service._get_project_currency = AsyncMock(return_value="EUR")  # type: ignore[method-assign]

    boq = SimpleNamespace(
        project_id=PROJECT_ID,
        positions=[
            _make_position(total=100.0, unit_rate=10.0, quantity=10.0),
            _make_position(total=200.0, unit_rate=10.0, quantity=20.0),
        ],
    )
    service.session = SimpleNamespace(
        execute=AsyncMock(return_value=_FakeExecuteResult(rows=[boq]))
    )

    resp = await service.get_variance(PROJECT_ID)

    assert resp.budget == 300.0
    assert resp.current == 300.0
    assert resp.variance_abs == 0.0
    assert resp.variance_pct == 0.0
    assert resp.red_line == 5.0
    assert resp.currency == "EUR"


@pytest.mark.asyncio
async def test_get_variance_detects_override() -> None:
    """When total diverges from qty * rate we should see non-zero variance."""
    service = CostModelService.__new__(CostModelService)
    service._get_project_currency = AsyncMock(return_value="USD")  # type: ignore[method-assign]

    boq = SimpleNamespace(
        project_id=PROJECT_ID,
        positions=[
            # budget: 1000, current: 1050 -> +5% variance
            _make_position(total=1050.0, unit_rate=100.0, quantity=10.0),
        ],
    )
    service.session = SimpleNamespace(
        execute=AsyncMock(return_value=_FakeExecuteResult(rows=[boq]))
    )

    resp = await service.get_variance(PROJECT_ID)
    assert resp.budget == 1000.0
    assert resp.current == 1050.0
    assert resp.variance_abs == 50.0
    assert resp.variance_pct == 5.0


@pytest.mark.asyncio
async def test_get_variance_empty_project() -> None:
    service = CostModelService.__new__(CostModelService)
    service._get_project_currency = AsyncMock(return_value="EUR")  # type: ignore[method-assign]
    service.session = SimpleNamespace(
        execute=AsyncMock(return_value=_FakeExecuteResult(rows=[]))
    )

    resp = await service.get_variance(PROJECT_ID)
    assert resp.budget == 0.0
    assert resp.current == 0.0
    assert resp.variance_abs == 0.0
    assert resp.variance_pct == 0.0


# ── BOQService.get_line_items ─────────────────────────────────────────────


def _make_boq_service(positions: list[SimpleNamespace]) -> BOQService:
    service = BOQService.__new__(BOQService)
    service.session = SimpleNamespace(
        execute=AsyncMock(return_value=_FakeExecuteResult(rows=positions))
    )
    return service


@pytest.mark.asyncio
async def test_get_line_items_top_n_and_shares() -> None:
    positions = [
        _make_position(total=500.0, unit_rate=50.0, ordinal="01.001"),
        _make_position(total=300.0, unit_rate=30.0, ordinal="01.002"),
        _make_position(total=100.0, unit_rate=10.0, ordinal="01.003"),
        _make_position(total=100.0, unit_rate=10.0, ordinal="01.004"),
    ]
    service = _make_boq_service(positions)

    rows = await service.get_line_items(PROJECT_ID, group="cost", top_n=2)
    assert len(rows) == 2
    assert rows[0]["total_cost"] == 500.0
    assert rows[1]["total_cost"] == 300.0
    # Shares are fractions of the total 1000.0
    assert rows[0]["share_of_total"] == pytest.approx(0.5)
    assert rows[1]["share_of_total"] == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_get_line_items_empty_project() -> None:
    service = _make_boq_service([])
    rows = await service.get_line_items(PROJECT_ID)
    assert rows == []


# ── BOQService.get_cost_rollup ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_cost_rollup_groups_by_din276() -> None:
    positions = [
        _make_position(total=100.0, unit_rate=10.0, classification={"din276": "330"}),
        _make_position(total=200.0, unit_rate=20.0, classification={"din276": "330"}),
        _make_position(total=150.0, unit_rate=15.0, classification={"din276": "340"}),
        _make_position(total=50.0, unit_rate=5.0, classification={}),
    ]
    service = _make_boq_service(positions)

    rows = await service.get_cost_rollup(PROJECT_ID, group_by="din276")
    by_code = {r["code"]: r for r in rows}

    assert by_code["330"]["total"] == 300.0
    assert by_code["330"]["position_count"] == 2
    assert by_code["340"]["total"] == 150.0
    assert by_code["(unclassified)"]["total"] == 50.0


@pytest.mark.asyncio
async def test_get_cost_rollup_empty_project() -> None:
    service = _make_boq_service([])
    rows = await service.get_cost_rollup(PROJECT_ID)
    assert rows == []


# ── BOQService.get_anomalies ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_anomalies_format_missing_fields() -> None:
    positions = [
        _make_position(
            total=0.0,
            unit_rate=0.0,
            quantity=0.0,
            unit="",
            ordinal="01.001",
        ),
    ]
    service = _make_boq_service(positions)

    rows = await service.get_anomalies(PROJECT_ID)
    format_rows = [r for r in rows if r["type"] == "format"]
    assert format_rows, "expected at least one format anomaly"
    assert "unit_rate" in format_rows[0]["detail"]
    assert format_rows[0]["severity"] == "error"


@pytest.mark.asyncio
async def test_get_anomalies_outlier_zscore() -> None:
    boq_id = uuid.uuid4()
    base = [
        _make_position(
            total=100.0,
            unit_rate=100.0,
            classification={"din276": "330"},
            boq_id=boq_id,
            ordinal=f"01.{i:03d}",
            sort_order=i,
        )
        for i in range(10)
    ]
    outlier = _make_position(
        total=100000.0,
        unit_rate=100000.0,
        classification={"din276": "330"},
        boq_id=boq_id,
        ordinal="01.999",
        sort_order=99,
    )
    service = _make_boq_service([*base, outlier])

    rows = await service.get_anomalies(PROJECT_ID)
    outlier_rows = [r for r in rows if r["type"] == "outlier"]
    assert outlier_rows, "expected at least one outlier anomaly"
    assert outlier_rows[0]["position_id"] == str(outlier.id)


@pytest.mark.asyncio
async def test_get_anomalies_empty_project() -> None:
    service = _make_boq_service([])
    rows = await service.get_anomalies(PROJECT_ID)
    assert rows == []


# ── TenderingService.get_bid_analysis ─────────────────────────────────────


def _make_bid(total: float, company: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        company_name=company,
        currency="EUR",
        total_amount=str(total),
    )


@pytest.mark.asyncio
async def test_get_bid_analysis_spread_and_vendors() -> None:
    service = TenderingService.__new__(TenderingService)
    bids = [
        _make_bid(100_000, "Alpha"),
        _make_bid(110_000, "Beta"),
        _make_bid(120_000, "Gamma"),
        _make_bid(130_000, "Delta"),
        _make_bid(500_000, "Sigma"),  # outlier by IQR rule
    ]
    service.session = SimpleNamespace(
        execute=AsyncMock(return_value=_FakeExecuteResult(rows=bids))
    )

    resp = await service.get_bid_analysis(PROJECT_ID)
    assert resp.spread.sample_size == 5
    assert resp.spread.min == 100_000.0
    assert resp.spread.max == 500_000.0
    assert any(o.company_name == "Sigma" for o in resp.outliers)
    names = [v.company_name for v in resp.vendors]
    assert names[0] == "Sigma"  # sorted by total desc
    assert len(resp.vendors) == 5


@pytest.mark.asyncio
async def test_get_bid_analysis_empty_project() -> None:
    service = TenderingService.__new__(TenderingService)
    service.session = SimpleNamespace(
        execute=AsyncMock(return_value=_FakeExecuteResult(rows=[]))
    )
    resp = await service.get_bid_analysis(PROJECT_ID)
    assert resp.vendors == []
    assert resp.outliers == []
    assert resp.spread.sample_size == 0


# ── ScheduleService.get_labor_cost_by_phase ───────────────────────────────


def _make_activity(
    *,
    wbs_code: str = "",
    activity_type: str = "task",
    resources: list[dict] | None = None,
    boq_position_ids: list[str] | None = None,
    start_date: str = "2026-01-01",
    end_date: str = "2026-01-31",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        wbs_code=wbs_code,
        activity_type=activity_type,
        resources=resources or [],
        boq_position_ids=boq_position_ids or [],
        start_date=start_date,
        end_date=end_date,
    )


@pytest.mark.asyncio
async def test_labor_cost_by_phase_groups_by_wbs_prefix() -> None:
    service = ScheduleService.__new__(ScheduleService)
    activities = [
        _make_activity(
            wbs_code="1.1",
            resources=[{"type": "labor", "total_cost": 500.0}],
        ),
        _make_activity(
            wbs_code="1.2",
            resources=[{"type": "labor", "total_cost": 700.0}],
        ),
        _make_activity(
            wbs_code="2.1",
            resources=[{"type": "labor", "total_cost": 400.0}],
        ),
        # Non-labour resources should be ignored for labor_cost
        _make_activity(
            wbs_code="1.3",
            resources=[{"type": "material", "total_cost": 999.0}],
        ),
    ]

    # First execute call returns activities; second (if any) returns position totals
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[_FakeExecuteResult(rows=activities)]
        )
    )
    service.session = session

    resp = await service.get_labor_cost_by_phase(PROJECT_ID)
    phases = {row.phase: row for row in resp.phases}
    assert phases["1"].labor_cost == 1200.0  # 500 + 700 (+ 0 material)
    assert phases["2"].labor_cost == 400.0
    assert phases["1"].activity_count == 3


@pytest.mark.asyncio
async def test_labor_cost_by_phase_empty_project() -> None:
    service = ScheduleService.__new__(ScheduleService)
    service.session = SimpleNamespace(
        execute=AsyncMock(return_value=_FakeExecuteResult(rows=[]))
    )
    resp = await service.get_labor_cost_by_phase(PROJECT_ID)
    assert resp.phases == []
