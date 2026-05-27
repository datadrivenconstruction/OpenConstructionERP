# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Unit tests for the BI Dashboards cross-filter pipeline (Wave 4 / T11).

These tests stub the KPI registry so we can observe what arguments
``_kpis.compute`` was called with — proving that:

* When ``cross_filter_enabled=False`` (default) the supplied filter
  dict is dropped and ``compute`` is invoked with zero kwargs, matching
  the v3.x static-render contract.
* When ``cross_filter_enabled=True`` the dict is propagated, with
  ``project_id`` / ``period_start`` / ``period_end`` lifted to typed
  kwargs and the remaining keys forwarded as the ``filters=`` bag.
* Unknown filter keys (no KPI knows what to do with them) ride along in
  ``filters=`` without raising — each KPI ignores keys it doesn't
  recognise, so the wire is graceful.
"""

from __future__ import annotations

import uuid
from datetime import date as _date
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """In-memory SQLite session with the bi_dashboards tables only."""
    from app.modules.bi_dashboards import models as _m

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    tables = [
        _m.KPIDefinition.__table__,
        _m.Dashboard.__table__,
        _m.DashboardWidget.__table__,
        _m.DashboardWidgetSnapshot.__table__,
        _m.KPIValue.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


class _ComputeSpy:
    """Drop-in for ``_kpis.compute`` that records every call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        code: str,
        session: AsyncSession,
        *,
        project_id: uuid.UUID | None = None,
        period_start: _date | None = None,
        period_end: _date | None = None,
        filters: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(
            {
                "code": code,
                "project_id": project_id,
                "period_start": period_start,
                "period_end": period_end,
                "filters": filters,
            },
        )
        # Mirror the real KPIComputation shape just enough.
        from app.modules.bi_dashboards.kpis import KPIComputation

        return KPIComputation(
            value=Decimal("42"),
            unit="ratio",
            source_record_count=1,
            breakdown={"echo_filters": filters or {}},
        )


async def _make_dashboard_with_widget(
    session: AsyncSession,
    *,
    cross_filter: bool,
    kpi_code: str = "cpi",
    drill_path: dict[str, Any] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert one dashboard + one widget; return (dashboard_id, widget_id)."""
    from app.modules.bi_dashboards.models import Dashboard, DashboardWidget

    dashboard = Dashboard(
        name="t",
        scope="personal",
        owner_user_id=uuid.uuid4(),
        refresh_interval_seconds=300,
        cross_filter_enabled=cross_filter,
    )
    session.add(dashboard)
    await session.flush()
    widget = DashboardWidget(
        dashboard_id=dashboard.id,
        widget_type="kpi_card",
        kpi_code=kpi_code,
        drill_path=drill_path,
    )
    session.add(widget)
    await session.flush()
    return dashboard.id, widget.id


@pytest.mark.asyncio
async def test_evaluate_off_path_ignores_filters(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cross_filter_enabled=False -> compute called with no kwargs even when
    caller supplies a filter dict. Forward-compat contract."""
    from app.modules.bi_dashboards import kpis as _kpis
    from app.modules.bi_dashboards.service import BIDashboardsService

    spy = _ComputeSpy()
    monkeypatch.setattr(_kpis, "compute", spy)

    dashboard_id, _ = await _make_dashboard_with_widget(
        session,
        cross_filter=False,
    )
    svc = BIDashboardsService(session)
    response = await svc.evaluate_dashboard(
        dashboard_id,
        filters={"project_id": str(uuid.uuid4())},
    )

    assert response is not None
    assert response.cross_filter_enabled is False
    # applied_filters MUST be empty on the off path — we don't echo back
    # filters the backend silently dropped.
    assert response.applied_filters == {}
    assert len(spy.calls) == 1
    call = spy.calls[0]
    # OFF path: bare call, no project/period/filters routing.
    assert call["project_id"] is None
    assert call["period_start"] is None
    assert call["period_end"] is None
    assert call["filters"] is None


@pytest.mark.asyncio
async def test_evaluate_on_path_propagates_filters(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cross_filter_enabled=True -> filters propagate. project_id and
    period bounds are lifted to typed kwargs; the rest go into filters="""
    from app.modules.bi_dashboards import kpis as _kpis
    from app.modules.bi_dashboards.service import BIDashboardsService

    spy = _ComputeSpy()
    monkeypatch.setattr(_kpis, "compute", spy)

    project_uuid = uuid.uuid4()
    dashboard_id, _ = await _make_dashboard_with_widget(
        session,
        cross_filter=True,
    )
    svc = BIDashboardsService(session)
    response = await svc.evaluate_dashboard(
        dashboard_id,
        filters={
            "project_id": str(project_uuid),
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "trade": "concrete",
        },
    )

    assert response is not None
    assert response.cross_filter_enabled is True
    assert response.applied_filters["project_id"] == str(project_uuid)
    assert response.applied_filters["trade"] == "concrete"
    assert len(spy.calls) == 1
    call = spy.calls[0]
    assert call["project_id"] == project_uuid
    assert call["period_start"] == _date(2026, 1, 1)
    assert call["period_end"] == _date(2026, 3, 31)
    # ``trade`` is unknown to compute() — gets routed through filters=
    assert call["filters"] == {"trade": "concrete"}


@pytest.mark.asyncio
async def test_evaluate_unknown_filter_keys_are_passed_through(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown filter keys (no first-class kwarg + no KPI handler) must
    not 500 — they ride along in ``filters=`` and each KPI ignores
    what it doesn't recognise."""
    from app.modules.bi_dashboards import kpis as _kpis
    from app.modules.bi_dashboards.service import BIDashboardsService

    spy = _ComputeSpy()
    monkeypatch.setattr(_kpis, "compute", spy)

    dashboard_id, _ = await _make_dashboard_with_widget(
        session,
        cross_filter=True,
    )
    svc = BIDashboardsService(session)
    response = await svc.evaluate_dashboard(
        dashboard_id,
        filters={"some_made_up_field": "xyz", "another_unknown": 7},
    )

    assert response is not None
    assert response.cross_filter_enabled is True
    # Both keys forwarded, neither raised
    call = spy.calls[0]
    assert call["filters"] == {
        "some_made_up_field": "xyz",
        "another_unknown": 7,
    }
    # Aggregate still has a value (spy returned 42)
    assert response.widgets[0].value == Decimal("42")


@pytest.mark.asyncio
async def test_evaluate_missing_dashboard_returns_none(
    session: AsyncSession,
) -> None:
    """Unknown dashboard id returns None (router maps to 404)."""
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    out = await svc.evaluate_dashboard(uuid.uuid4(), filters={"foo": 1})
    assert out is None


@pytest.mark.asyncio
async def test_widget_drill_path_round_trips(session: AsyncSession) -> None:
    """``drill_path`` survives create -> evaluate (so the UI can read it
    off each widget result and use it to compute the next filter on
    click)."""
    from app.modules.bi_dashboards.service import BIDashboardsService

    drill_path = {
        "filter_field": "project_id",
        "filter_value_from": "row.project_id",
    }
    dashboard_id, widget_id = await _make_dashboard_with_widget(
        session,
        cross_filter=True,
        drill_path=drill_path,
    )
    svc = BIDashboardsService(session)
    response = await svc.evaluate_dashboard(dashboard_id, filters=None)
    assert response is not None
    matched = next(w for w in response.widgets if w.id == widget_id)
    assert matched.drill_path == drill_path
