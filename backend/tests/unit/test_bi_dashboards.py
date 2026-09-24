# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the BI Dashboards module (Module 20, Wave 4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session

# ── Fixtures ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """PostgreSQL session inside an outer transaction rolled back on teardown.

    The shared ``oe_test_unit`` database already carries the full schema, so
    no per-test table creation is needed; the session's commits become
    savepoints and everything is undone after the test.
    """
    async with transactional_session() as s:
        yield s


@pytest.fixture
def event_spy(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Spy on ``event_bus.publish_detached`` (the production hook is sync —
    it schedules a task — so a plain MagicMock is the right shape)."""
    from app.core.events import event_bus

    spy = MagicMock()
    monkeypatch.setattr(event_bus, "publish_detached", spy)
    return spy


# ── KPI registry ───────────────────────────────────────────────────────


def test_register_kpi_adds_to_registry() -> None:
    from app.modules.bi_dashboards import kpis

    @kpis.register_kpi(
        "test_custom_kpi",
        name="Test Custom",
        unit="count",
        category="operational",
    )
    async def _fake(session, **_):
        return kpis.KPIComputation(value=Decimal("42"), unit="count")

    assert "test_custom_kpi" in kpis.KPI_FORMULAS
    assert kpis.SYSTEM_KPI_META["test_custom_kpi"]["unit"] == "count"


def test_list_system_kpis_returns_metadata() -> None:
    from app.modules.bi_dashboards import kpis

    meta = kpis.list_system_kpis()
    codes = {m["code"] for m in meta}
    # Spot-check that the canonical system KPIs are registered
    for code in (
        "cpi",
        "spi",
        "first_pass_yield",
        "copq",
        "safety_trir",
        "procurement_savings",
        "change_order_ratio",
        "cash_in_30d",
        "cash_out_30d",
        "dso",
        "embodied_carbon_per_m2",
        "equipment_utilization",
        "subcontractor_avg_rating",
        "bid_win_rate",
        "punch_close_rate",
        "rfi_close_avg_days",
        "project_count_active",
    ):
        assert code in codes, f"missing system KPI: {code}"


@pytest.mark.asyncio
async def test_compute_unknown_kpi_returns_zero(session: AsyncSession) -> None:
    from app.modules.bi_dashboards import kpis

    result = await kpis.compute("does_not_exist", session)
    assert result.value == Decimal("0")
    assert result.source_record_count == 0


@pytest.mark.asyncio
async def test_compute_kpi_degrades_when_source_module_missing(
    session: AsyncSession,
) -> None:
    """Every system KPI must gracefully return 0 when upstream modules
    are absent — our test session has no projects/tasks/finance tables."""
    from app.modules.bi_dashboards import kpis

    for code in kpis.KPI_FORMULAS:
        result = await kpis.compute(code, session)
        assert isinstance(result.value, Decimal)
        assert result.source_record_count == 0


# ── Bootstrap & KPI definitions ────────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_seeds_kpi_definitions(session: AsyncSession) -> None:
    from app.modules.bi_dashboards import kpis
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    count = await svc.bootstrap_system_kpis()
    assert count == len(kpis.KPI_FORMULAS)
    rows = await svc.list_kpi_definitions()
    assert len(rows) >= count


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    await svc.bootstrap_system_kpis()
    rows1 = await svc.list_kpi_definitions()
    await svc.bootstrap_system_kpis()  # second run
    rows2 = await svc.list_kpi_definitions()
    assert len(rows1) == len(rows2)


@pytest.mark.asyncio
async def test_list_kpi_definitions_filters_by_category(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    await svc.bootstrap_system_kpis()
    fin = await svc.list_kpi_definitions(category="financial")
    assert len(fin) > 0
    assert all(r.category == "financial" for r in fin)


# ── Dashboard CRUD ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_crud(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.schemas import (
        DashboardCreate,
        DashboardUpdate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    owner = uuid.uuid4()
    dashboard = await svc.create_dashboard(
        DashboardCreate(
            name="My Dashboard",
            description="Test",
            scope="personal",
            refresh_interval_seconds=300,
        ),
        owner_user_id=owner,
    )
    assert dashboard.id is not None
    assert dashboard.owner_user_id == owner

    updated = await svc.update_dashboard(
        dashboard.id,
        DashboardUpdate(name="Renamed"),
    )
    assert updated is not None
    assert updated.name == "Renamed"

    fetched = await svc.get_dashboard(dashboard.id)
    assert fetched is not None
    assert fetched.name == "Renamed"

    ok = await svc.delete_dashboard(dashboard.id)
    assert ok is True
    assert await svc.get_dashboard(dashboard.id) is None


@pytest.mark.asyncio
async def test_list_dashboards_returns_own_plus_role(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.schemas import DashboardCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    alice = uuid.uuid4()
    bob = uuid.uuid4()
    await svc.create_dashboard(
        DashboardCreate(name="alice-personal", scope="personal"),
        owner_user_id=alice,
    )
    await svc.create_dashboard(
        DashboardCreate(name="bob-personal", scope="personal"),
        owner_user_id=bob,
    )
    await svc.create_dashboard(
        DashboardCreate(name="global-board", scope="global"),
        owner_user_id=None,
    )

    alice_visible = await svc.list_dashboards(owner_user_id=alice)
    names = {d.name for d in alice_visible}
    assert "alice-personal" in names
    assert "global-board" in names
    assert "bob-personal" not in names


# ── Widget CRUD + reorder ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_widget_add_and_list_ordered(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.schemas import (
        DashboardCreate,
        WidgetCreate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    dashboard = await svc.create_dashboard(
        DashboardCreate(name="D"),
        owner_user_id=None,
    )
    w1 = await svc.create_widget(
        WidgetCreate(
            dashboard_id=dashboard.id,
            kpi_code="cpi",
            order_seq=2,
        ),
    )
    w2 = await svc.create_widget(
        WidgetCreate(
            dashboard_id=dashboard.id,
            kpi_code="spi",
            order_seq=1,
        ),
    )
    assert w1 is not None
    assert w2 is not None
    widgets = await svc.repo.list_widgets(dashboard.id)
    assert [w.kpi_code for w in widgets] == ["spi", "cpi"]


@pytest.mark.asyncio
async def test_widget_create_rejects_missing_dashboard(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.schemas import WidgetCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    out = await svc.create_widget(
        WidgetCreate(dashboard_id=uuid.uuid4(), kpi_code="cpi"),
    )
    assert out is None


@pytest.mark.asyncio
async def test_widget_update_and_delete(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.schemas import (
        DashboardCreate,
        WidgetCreate,
        WidgetUpdate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    dashboard = await svc.create_dashboard(
        DashboardCreate(name="D"),
        owner_user_id=None,
    )
    widget = await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="cpi"),
    )
    updated = await svc.update_widget(
        widget.id,
        WidgetUpdate(width=6, kpi_code="spi"),
    )
    assert updated.width == 6
    assert updated.kpi_code == "spi"
    assert await svc.delete_widget(widget.id) is True
    assert await svc.delete_widget(widget.id) is False  # already gone


# ── Render & snapshot caching ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_dashboard_returns_widgets(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.schemas import (
        DashboardCreate,
        WidgetCreate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    dashboard = await svc.create_dashboard(
        DashboardCreate(name="D", refresh_interval_seconds=300),
        owner_user_id=None,
    )
    await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="cpi"),
    )
    await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="spi"),
    )
    result = await svc.render_dashboard(dashboard.id)
    assert result is not None
    assert len(result.widgets) == 2
    # First render → not from cache
    assert all(not w.from_cache for w in result.widgets)


@pytest.mark.asyncio
async def test_render_dashboard_uses_snapshot_cache(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.schemas import (
        DashboardCreate,
        WidgetCreate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    dashboard = await svc.create_dashboard(
        DashboardCreate(name="D", refresh_interval_seconds=3600),
        owner_user_id=None,
    )
    await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="cpi"),
    )
    # First render — writes snapshot
    await svc.render_dashboard(dashboard.id)
    # Second render — must hit cache
    result2 = await svc.render_dashboard(dashboard.id)
    assert result2 is not None
    assert any(w.from_cache for w in result2.widgets)


@pytest.mark.asyncio
async def test_snapshot_recomputes_after_expiry(
    session: AsyncSession,
) -> None:
    from sqlalchemy import update

    from app.modules.bi_dashboards.models import DashboardWidgetSnapshot
    from app.modules.bi_dashboards.schemas import (
        DashboardCreate,
        WidgetCreate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    dashboard = await svc.create_dashboard(
        DashboardCreate(name="D", refresh_interval_seconds=3600),
        owner_user_id=None,
    )
    widget = await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="cpi"),
    )
    await svc.render_dashboard(dashboard.id)
    # Expire snapshot
    past = datetime.now(UTC) - timedelta(hours=1)
    await session.execute(
        update(DashboardWidgetSnapshot).where(DashboardWidgetSnapshot.widget_id == widget.id).values(valid_until=past),
    )
    await session.flush()
    result = await svc.render_dashboard(dashboard.id)
    assert result is not None
    # Must have a freshly computed value, not the cached one
    assert all(not w.from_cache for w in result.widgets)


@pytest.mark.asyncio
async def test_update_widget_snapshot_writes_payload(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.schemas import (
        DashboardCreate,
        WidgetCreate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    dashboard = await svc.create_dashboard(
        DashboardCreate(name="D"),
        owner_user_id=None,
    )
    widget = await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="cpi"),
    )
    snap = await svc.update_widget_snapshot(widget.id)
    assert snap is not None
    assert "value" in snap


# ── Report definitions ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_report_definition_crud(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.schemas import (
        ReportDefinitionCreate,
        ReportDefinitionUpdate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    report = await svc.create_report(
        ReportDefinitionCreate(
            code="r1",
            name="R",
            query_spec_json={"kpis": ["cpi"]},
        ),
        owner_user_id=None,
    )
    updated = await svc.update_report(
        report.id,
        ReportDefinitionUpdate(name="R2"),
    )
    assert updated.name == "R2"
    assert await svc.delete_report(report.id) is True


@pytest.mark.asyncio
async def test_run_report_returns_kpi_rows(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.schemas import ReportDefinitionCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    report = await svc.create_report(
        ReportDefinitionCreate(
            code="r2",
            name="R",
            query_spec_json={"kpis": ["cpi", "spi"]},
        ),
        owner_user_id=None,
    )
    result = await svc.run_report(report.id)
    assert result is not None
    assert result.row_count == 2
    assert {row["kpi_code"] for row in result.rows} == {"cpi", "spi"}


@pytest.mark.asyncio
async def test_run_report_publishes_event(
    session: AsyncSession,
    event_spy: MagicMock,
) -> None:
    from app.modules.bi_dashboards.schemas import ReportDefinitionCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    report = await svc.create_report(
        ReportDefinitionCreate(
            code="r3",
            name="R",
            query_spec_json={"kpis": ["cpi"]},
        ),
        owner_user_id=None,
    )
    await svc.run_report(report.id)
    assert event_spy.called
    events_published = {c.args[0] for c in event_spy.call_args_list}
    assert "bi.report.generated" in events_published


# ── Schedule next_run_at computation ───────────────────────────────────


def test_next_run_at_daily() -> None:
    from app.modules.bi_dashboards.service import compute_next_run_at

    base = datetime(2026, 5, 12, 12, 0, tzinfo=UTC)
    nxt = compute_next_run_at(
        frequency="daily",
        time_of_day="08:00",
        day_of_week=None,
        day_of_month=None,
        base=base,
    )
    # Today's 08:00 already passed at 12:00, so we expect tomorrow 08:00
    assert nxt == datetime(2026, 5, 13, 8, 0, tzinfo=UTC)


def test_next_run_at_weekly_next_monday() -> None:
    from app.modules.bi_dashboards.service import compute_next_run_at

    # Tuesday 2026-05-12, want next Monday (dow=0)
    base = datetime(2026, 5, 12, 12, 0, tzinfo=UTC)
    nxt = compute_next_run_at(
        frequency="weekly",
        time_of_day="07:00",
        day_of_week=0,
        day_of_month=None,
        base=base,
    )
    assert nxt.weekday() == 0
    assert nxt > base


def test_next_run_at_monthly_rolls_to_next_month() -> None:
    from app.modules.bi_dashboards.service import compute_next_run_at

    # Already past day_of_month=1 — expect roll forward
    base = datetime(2026, 5, 12, 8, 0, tzinfo=UTC)
    nxt = compute_next_run_at(
        frequency="monthly",
        time_of_day="07:00",
        day_of_week=None,
        day_of_month=1,
        base=base,
    )
    assert nxt.month == 6
    assert nxt.day == 1


# ── Schedule create + run ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_create_computes_next_run(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.schemas import (
        ReportDefinitionCreate,
        ReportScheduleCreate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    report = await svc.create_report(
        ReportDefinitionCreate(
            code="rsched",
            name="R",
            query_spec_json={"kpis": ["cpi"]},
        ),
        owner_user_id=None,
    )
    schedule = await svc.create_schedule(
        ReportScheduleCreate(
            report_definition_id=report.id,
            frequency="daily",
            time_of_day="06:00",
        ),
    )
    assert schedule is not None
    assert schedule.next_run_at is not None


@pytest.mark.asyncio
async def test_enqueue_scheduled_reports_fires_due(
    session: AsyncSession,
) -> None:
    from sqlalchemy import update

    from app.modules.bi_dashboards.models import ReportSchedule
    from app.modules.bi_dashboards.schemas import (
        ReportDefinitionCreate,
        ReportScheduleCreate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    report = await svc.create_report(
        ReportDefinitionCreate(
            code="due",
            name="R",
            query_spec_json={"kpis": ["cpi"]},
        ),
        owner_user_id=None,
    )
    schedule = await svc.create_schedule(
        ReportScheduleCreate(
            report_definition_id=report.id,
            frequency="daily",
            time_of_day="06:00",
        ),
    )
    # Force next_run_at into the past
    past = datetime.now(UTC) - timedelta(hours=1)
    await session.execute(
        update(ReportSchedule).where(ReportSchedule.id == schedule.id).values(next_run_at=past),
    )
    await session.flush()
    fired = await svc.enqueue_scheduled_reports()
    assert schedule.id in fired


# ── Alert evaluation ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_triggers_when_below_threshold(
    session: AsyncSession,
    event_spy: MagicMock,
) -> None:
    from app.modules.bi_dashboards import kpis
    from app.modules.bi_dashboards.schemas import AlertRuleCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    @kpis.register_kpi(
        "_test_alert_below",
        name="Test",
        unit="ratio",
        category="operational",
    )
    async def _t1(session, **_):
        return kpis.KPIComputation(value=Decimal("0.5"), unit="ratio", source_record_count=1)

    svc = BIDashboardsService(session)
    alert = await svc.create_alert(
        AlertRuleCreate(
            name="below-alert",
            kpi_code="_test_alert_below",
            condition="below",
            threshold_value=Decimal("1.0"),
        ),
    )
    fired = await svc.evaluate_alert(alert)
    assert fired is True
    triggered_events = [c for c in event_spy.call_args_list if c.args[0] == "bi.alert.triggered"]
    assert triggered_events


@pytest.mark.asyncio
async def test_alert_does_not_trigger_when_above_threshold(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards import kpis
    from app.modules.bi_dashboards.schemas import AlertRuleCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    @kpis.register_kpi(
        "_test_alert_above_ok",
        name="Test",
        unit="ratio",
        category="operational",
    )
    async def _t2(session, **_):
        return kpis.KPIComputation(value=Decimal("2.0"), unit="ratio", source_record_count=1)

    svc = BIDashboardsService(session)
    alert = await svc.create_alert(
        AlertRuleCreate(
            name="below-alert",
            kpi_code="_test_alert_above_ok",
            condition="below",
            threshold_value=Decimal("1.0"),
        ),
    )
    assert await svc.evaluate_alert(alert) is False


@pytest.mark.asyncio
async def test_alert_throttle_blocks_double_fire(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards import kpis
    from app.modules.bi_dashboards.schemas import AlertRuleCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    @kpis.register_kpi(
        "_test_alert_throttle",
        name="Test",
        unit="ratio",
        category="operational",
    )
    async def _t3(session, **_):
        return kpis.KPIComputation(value=Decimal("0.1"), unit="ratio", source_record_count=1)

    svc = BIDashboardsService(session)
    alert = await svc.create_alert(
        AlertRuleCreate(
            name="throttle-alert",
            kpi_code="_test_alert_throttle",
            condition="below",
            threshold_value=Decimal("1.0"),
            throttle_seconds=3600,
        ),
    )
    first = await svc.evaluate_alert(alert)
    assert first is True
    refreshed = await svc.repo.get_alert(alert.id)
    second = await svc.evaluate_alert(refreshed)
    assert second is False  # throttled


@pytest.mark.asyncio
async def test_alert_toggle_disables(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.schemas import AlertRuleCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    alert = await svc.create_alert(
        AlertRuleCreate(
            name="x",
            kpi_code="cpi",
            condition="below",
            threshold_value=Decimal("1.0"),
        ),
    )
    updated = await svc.toggle_alert(alert.id, enabled=False)
    assert updated.enabled is False


@pytest.mark.asyncio
async def test_evaluate_alerts_only_enabled(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.schemas import AlertRuleCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    alert = await svc.create_alert(
        AlertRuleCreate(
            name="off",
            kpi_code="cpi",
            condition="below",
            threshold_value=Decimal("1.0"),
            enabled=False,
        ),
    )
    fired = await svc.evaluate_alerts()
    # No enabled alerts fire
    assert fired == 0


# ── Drill-down ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drill_down_returns_records(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    result = await svc.drill_down("cpi")
    assert "records" in result
    assert "record_count" in result
    assert result["kpi_code"] == "cpi"


# ── KPI compute / history ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compute_kpi_response_shape(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    resp = await svc.compute_kpi("cpi")
    assert resp.kpi_code == "cpi"
    assert isinstance(resp.value, Decimal)
    assert resp.unit == "ratio"
    assert isinstance(resp.trend, list)


@pytest.mark.asyncio
async def test_compute_kpi_persist_writes_kpi_value(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards import kpis
    from app.modules.bi_dashboards.service import BIDashboardsService

    @kpis.register_kpi(
        "_test_persist",
        name="Test",
        unit="ratio",
        category="operational",
    )
    async def _t(session, **_):
        return kpis.KPIComputation(
            value=Decimal("0.42"),
            unit="ratio",
            source_record_count=5,
        )

    svc = BIDashboardsService(session)
    await svc.compute_kpi("_test_persist", persist=True)
    history = await svc.kpi_history("_test_persist")
    assert len(history) == 1
    assert history[0].value == Decimal("0.42")


@pytest.mark.asyncio
async def test_compute_kpi_persist_skipped_when_no_records(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    # cpi degrades to 0 with no upstream data → source_record_count=0
    await svc.compute_kpi("cpi", persist=True)
    history = await svc.kpi_history("cpi")
    assert history == []  # nothing persisted


# ── Saved filters ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_saved_filter_create_and_list(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.schemas import SavedFilterCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    user = uuid.uuid4()
    sf = await svc.create_filter(
        SavedFilterCreate(name="my-filter", module="rfi"),
        owner_user_id=user,
    )
    assert sf.module == "rfi"
    listed = await svc.list_filters(owner_user_id=user, module="rfi")
    assert len(listed) == 1
    assert listed[0].id == sf.id


# ── System KPI smoke tests ─────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    [
        "cpi",
        "spi",
        "first_pass_yield",
        "copq",
        "safety_trir",
        "procurement_savings",
        "change_order_ratio",
        "cash_in_30d",
        "cash_out_30d",
        "dso",
        "embodied_carbon_per_m2",
        "equipment_utilization",
        "subcontractor_avg_rating",
        "bid_win_rate",
        "punch_close_rate",
        "rfi_close_avg_days",
        "project_count_active",
    ],
)
async def test_system_kpi_returns_decimal(
    session: AsyncSession,
    code: str,
) -> None:
    """Every system KPI must return a Decimal without raising."""
    from app.modules.bi_dashboards import kpis

    result = await kpis.compute(code, session)
    assert isinstance(result.value, Decimal)
    assert isinstance(result.unit, str)


# ── Seed integration ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_runs_idempotently(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.seed import seed_all

    counts1 = await seed_all(session)
    counts2 = await seed_all(session)
    # Second run should not re-create anything (idempotent)
    assert counts2["dashboards"] == 0
    assert counts2["reports"] == 0
    assert counts2["schedules"] == 0
    assert counts2["alerts"] == 0
    # KPI defs are upsert, so count stays ≥ first run
    assert counts1["kpi_definitions"] > 0


# ── Wave-4 notification subscriber wiring ──────────────────────────────


def test_wave4_subscriber_registration_is_idempotent() -> None:
    from app.modules.notifications._wave4_subscribers import (
        register_bi_dashboards_notification_subscribers,
    )

    register_bi_dashboards_notification_subscribers()
    # Second call must not raise
    register_bi_dashboards_notification_subscribers()


# ── EVM KPIs (PMBOK) ──────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    ["cv", "sv", "eac", "etc", "vac", "tcpi"],
)
async def test_evm_kpis_registered_and_compute_safely(
    session: AsyncSession,
    code: str,
) -> None:
    """Each new EVM KPI is registered and returns a Decimal without raising."""
    from app.modules.bi_dashboards import kpis

    assert code in kpis.KPI_FORMULAS
    result = await kpis.compute(code, session)
    assert isinstance(result.value, Decimal)


def test_evm_kpi_formulas_are_async() -> None:
    """Every registered KPI formula must be an async function.

    Regression guard for the EAC bug where ``@register_kpi("eac")`` sat on the
    pure helper ``_eac_from_primitives`` instead of the async ``eac_kpi``: the
    registry then called ``fn(session, project_id=...)`` on a sync helper that
    only accepts four primitives, raising a TypeError that ``compute`` swallowed
    so EAC silently returned 0. If a decorator ever lands on a sync helper
    again this fails loudly.
    """
    import inspect

    from app.modules.bi_dashboards import kpis

    for code, fn in kpis.KPI_FORMULAS.items():
        assert inspect.iscoroutinefunction(fn), f"KPI '{code}' formula is not async: {fn!r}"


def test_eac_from_primitives_overrun_exceeds_bac() -> None:
    """A project running over both cost and schedule must forecast EAC > BAC."""
    from app.modules.bi_dashboards import kpis

    eac = kpis._eac_from_primitives(bac=Decimal("1000"), pv=Decimal("500"), ev=Decimal("400"), ac=Decimal("500"))
    assert isinstance(eac, Decimal)
    # CPI = SPI = 0.8 -> EAC = 500 + (1000 - 400) / 0.64 = 1437.5
    assert eac > Decimal("1000")
    assert abs(eac - Decimal("1437.5")) < Decimal("1")


def test_eac_from_primitives_no_progress_falls_back_to_bac() -> None:
    """With no actuals / no progress the perf indices are undefined; EAC = BAC."""
    from app.modules.bi_dashboards import kpis

    eac = kpis._eac_from_primitives(bac=Decimal("1000"), pv=Decimal("0"), ev=Decimal("0"), ac=Decimal("0"))
    assert eac == Decimal("1000")


@pytest.mark.asyncio
async def test_evm_drilldown_provider_registered(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards import kpis

    for code in ("cpi", "spi", "cv", "sv", "eac", "etc", "vac", "tcpi"):
        assert code in kpis.KPI_RECORD_PROVIDERS
    # Should not raise even without upstream data
    rows = await kpis.drilldown("cpi", session, project_id=None, limit=10)
    assert isinstance(rows, list)


# ── Drill-down rich payload ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_drill_down_includes_aggregate(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    result = await svc.drill_down("cpi", limit=10)
    assert result["kpi_code"] == "cpi"
    assert "aggregate_value" in result
    assert "aggregate_unit" in result


# ── Benchmark ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_benchmark_returns_empty_when_no_other_projects(
    session: AsyncSession,
) -> None:
    """Benchmark requires Project model + multiple rows; should return {}."""
    from app.modules.bi_dashboards import kpis

    result = await kpis.benchmark("cpi", session, project_id=uuid.uuid4())
    assert result == {}


# ── Composite alert DSL ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_dsl_and_fires(
    session: AsyncSession,
    event_spy: MagicMock,
) -> None:
    from app.modules.bi_dashboards import kpis
    from app.modules.bi_dashboards.schemas import AlertRuleCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    @kpis.register_kpi(
        "_test_dsl_kpi_a",
        name="A",
        unit="ratio",
        category="operational",
    )
    async def _a(session, **_):
        return kpis.KPIComputation(value=Decimal("0.5"), unit="ratio", source_record_count=1)

    @kpis.register_kpi(
        "_test_dsl_kpi_b",
        name="B",
        unit="ratio",
        category="operational",
    )
    async def _b(session, **_):
        return kpis.KPIComputation(value=Decimal("2.0"), unit="ratio", source_record_count=1)

    svc = BIDashboardsService(session)
    alert = await svc.create_alert(
        AlertRuleCreate(
            name="composite-and",
            kpi_code="_test_dsl_kpi_a",  # used for the headline value
            condition="below",  # ignored when expression set
            threshold_value=Decimal("0"),
            expression_json={
                "op": "and",
                "operands": [
                    {
                        "op": "kpi",
                        "code": "_test_dsl_kpi_a",
                        "compare": "lt",
                        "value": "1.0",
                    },
                    {
                        "op": "kpi",
                        "code": "_test_dsl_kpi_b",
                        "compare": "gt",
                        "value": "1.0",
                    },
                ],
            },
        ),
    )
    fired = await svc.evaluate_alert(alert)
    assert fired is True
    triggered_events = [c for c in event_spy.call_args_list if c.args[0] == "bi.alert.triggered"]
    assert triggered_events
    # Trace included
    payload = triggered_events[0].args[1]
    assert "trace" in payload
    assert payload["condition"] == "composite"


@pytest.mark.asyncio
async def test_alert_dsl_or_fires_on_either(session: AsyncSession) -> None:
    from app.modules.bi_dashboards import kpis
    from app.modules.bi_dashboards.schemas import AlertRuleCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    @kpis.register_kpi(
        "_test_dsl_or_a",
        name="A",
        unit="ratio",
        category="operational",
    )
    async def _a(session, **_):
        return kpis.KPIComputation(value=Decimal("0.5"), unit="ratio", source_record_count=1)

    @kpis.register_kpi(
        "_test_dsl_or_b",
        name="B",
        unit="ratio",
        category="operational",
    )
    async def _b(session, **_):
        return kpis.KPIComputation(value=Decimal("0.5"), unit="ratio", source_record_count=1)

    svc = BIDashboardsService(session)
    alert = await svc.create_alert(
        AlertRuleCreate(
            name="composite-or",
            kpi_code="_test_dsl_or_a",
            condition="below",
            threshold_value=Decimal("0"),
            expression_json={
                "op": "or",
                "operands": [
                    {
                        "op": "kpi",
                        "code": "_test_dsl_or_a",
                        "compare": "gt",
                        "value": "1",
                    },  # false
                    {
                        "op": "kpi",
                        "code": "_test_dsl_or_b",
                        "compare": "lt",
                        "value": "1",
                    },  # true
                ],
            },
        ),
    )
    assert await svc.evaluate_alert(alert) is True


@pytest.mark.asyncio
async def test_alert_dsl_malformed_expression_does_not_fire(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.schemas import AlertRuleCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    alert = await svc.create_alert(
        AlertRuleCreate(
            name="bad",
            kpi_code="cpi",
            condition="below",
            threshold_value=Decimal("0"),
            expression_json={"op": "BOGUS"},
        ),
    )
    # Fails closed — does NOT raise to caller, returns False
    assert await svc.evaluate_alert(alert) is False


def test_alert_dsl_eval_directly() -> None:
    from app.modules.bi_dashboards.alert_dsl import _compare

    assert _compare(Decimal("0.5"), "lt", Decimal("1.0")) is True
    assert _compare(Decimal("1.5"), "gt", Decimal("1.0")) is True
    assert _compare("execution", "eq", "execution") is True
    assert _compare("planning", "neq", "execution") is True


# ── Report file generation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_report_produces_pdf_file(session: AsyncSession) -> None:
    import os

    from app.modules.bi_dashboards.schemas import ReportDefinitionCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    report = await svc.create_report(
        ReportDefinitionCreate(
            code="r-pdf",
            name="PDF Test",
            query_spec_json={"kpis": ["cpi", "spi"]},
            output_format="pdf",
        ),
        owner_user_id=None,
    )
    response = await svc.run_report(report.id)
    assert response is not None
    assert response.file_url is not None
    assert response.file_url.startswith("/api/v1/bi-dashboards/report-runs/")
    # And the file actually exists on disk
    runs = (
        (
            await session.execute(
                __import__("sqlalchemy").select(
                    __import__(
                        "app.modules.bi_dashboards.models",
                        fromlist=["ReportRun"],
                    ).ReportRun
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(runs) == 1
    assert os.path.exists(runs[0].file_path)
    assert runs[0].file_size_bytes > 0
    assert runs[0].status == "success"


@pytest.mark.asyncio
async def test_run_report_csv_format(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.schemas import ReportDefinitionCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    report = await svc.create_report(
        ReportDefinitionCreate(
            code="r-csv",
            name="CSV Test",
            query_spec_json={"kpis": ["cpi"]},
            output_format="csv",
        ),
        owner_user_id=None,
    )
    response = await svc.run_report(report.id)
    assert response is not None
    run = await svc.get_report_run(uuid.UUID(response.file_url.split("/")[-2]))
    assert run.file_path.endswith(".csv")
    with open(run.file_path) as fh:
        body = fh.read()
    assert "kpi_code" in body
    assert "cpi" in body


@pytest.mark.asyncio
async def test_run_report_xlsx_format(session: AsyncSession) -> None:
    import os

    from app.modules.bi_dashboards.schemas import ReportDefinitionCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    report = await svc.create_report(
        ReportDefinitionCreate(
            code="r-xlsx",
            name="XLSX Test",
            query_spec_json={"kpis": ["cpi"]},
            output_format="xlsx",
        ),
        owner_user_id=None,
    )
    response = await svc.run_report(report.id)
    assert response is not None
    run = await svc.get_report_run(uuid.UUID(response.file_url.split("/")[-2]))
    assert run.file_size_bytes > 0
    assert os.path.exists(run.file_path)


# ── Saved filter sharing ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_share_saved_filter_with_user(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.schemas import SavedFilterCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    alice = uuid.uuid4()
    bob = uuid.uuid4()
    sf = await svc.create_filter(
        SavedFilterCreate(name="shared", module="rfi"),
        owner_user_id=alice,
    )
    # Alice shares with Bob
    shared = await svc.share_filter(
        sf.id,
        owner_user_id=alice,
        user_ids=[bob],
    )
    assert str(bob) in shared.shared_with_user_ids_json
    # Bob's library now contains the filter
    bobs_filters = await svc.list_filters(owner_user_id=bob, module="rfi")
    assert any(f.id == sf.id for f in bobs_filters)


@pytest.mark.asyncio
async def test_share_filter_non_owner_404(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.schemas import SavedFilterCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    alice = uuid.uuid4()
    eve = uuid.uuid4()
    sf = await svc.create_filter(
        SavedFilterCreate(name="private", module="rfi"),
        owner_user_id=alice,
    )
    with pytest.raises(Exception) as exc:
        # Eve tries to re-share Alice's filter
        await svc.share_filter(
            sf.id,
            owner_user_id=eve,
            user_ids=[uuid.uuid4()],
        )
    # Service raises HTTPException 404
    assert getattr(exc.value, "status_code", 0) == 404


# ── Widget export ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_widget_csv(session: AsyncSession) -> None:
    import os

    from app.modules.bi_dashboards.schemas import (
        DashboardCreate,
        WidgetCreate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    dashboard = await svc.create_dashboard(
        DashboardCreate(name="D"),
        owner_user_id=None,
    )
    widget = await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="cpi"),
    )
    out = await svc.export_widget(widget.id, format="csv")
    assert out is not None
    path, size = out
    assert os.path.exists(path)
    assert path.endswith(".csv")


@pytest.mark.asyncio
async def test_export_widget_svg(session: AsyncSession) -> None:
    import os

    from app.modules.bi_dashboards.schemas import (
        DashboardCreate,
        WidgetCreate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    dashboard = await svc.create_dashboard(
        DashboardCreate(name="D"),
        owner_user_id=None,
    )
    widget = await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="cpi"),
    )
    out = await svc.export_widget(widget.id, format="svg")
    assert out is not None
    path, size = out
    assert os.path.exists(path)
    assert path.endswith(".svg")
    with open(path) as fh:
        body = fh.read()
    assert "<svg" in body


# ── Wave M4: cross-module wiring ───────────────────────────────────────


@pytest.mark.asyncio
async def test_invalidation_handler_publishes_kpi_recompute() -> None:
    """Upstream source-of-truth event → ``bi_dashboards.kpi_recompute``."""
    import asyncio

    from app.core import events as _ev_module
    from app.core.events import Event
    from app.modules.bi_dashboards.events import _on_invalidation_event

    captured: list[tuple[str, dict]] = []

    def _spy(name, data=None, source_module=None):  # noqa: ARG001
        captured.append((name, dict(data or {})))
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        return fut

    pid = str(uuid.uuid4())
    event = Event(
        name="contracts.claim.certified",
        data={
            "project_id": pid,
            "claim_id": str(uuid.uuid4()),
            "kpi_codes": ["cpi", "cash_in_30d"],
        },
        source_module="contracts",
    )
    real = _ev_module.event_bus.publish_detached
    _ev_module.event_bus.publish_detached = _spy  # type: ignore[assignment]
    try:
        await _on_invalidation_event(event)
    finally:
        _ev_module.event_bus.publish_detached = real  # type: ignore[assignment]
    names = [n for n, _ in captured]
    assert "bi_dashboards.kpi_recompute" in names
    payload = next(d for n, d in captured if n == "bi_dashboards.kpi_recompute")
    assert payload["source_event"] == "contracts.claim.certified"
    assert payload["project_id"] == pid
    assert payload["kpi_codes"] == ["cpi", "cash_in_30d"]


@pytest.mark.asyncio
async def test_invalidation_handler_ignores_self_event() -> None:
    """Re-broadcasting ``bi_dashboards.kpi_recompute`` would cause infinite loop —
    handler must short-circuit when fed its own event name."""
    import asyncio

    from app.core import events as _ev_module
    from app.core.events import Event
    from app.modules.bi_dashboards.events import _on_invalidation_event

    captured: list[tuple[str, dict]] = []

    def _spy(name, data=None, source_module=None):  # noqa: ARG001
        captured.append((name, dict(data or {})))
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        return fut

    event = Event(
        name="bi_dashboards.kpi_recompute",
        data={"project_id": str(uuid.uuid4()), "kpi_codes": ["cpi"]},
        source_module="bi_dashboards",
    )
    real = _ev_module.event_bus.publish_detached
    _ev_module.event_bus.publish_detached = _spy  # type: ignore[assignment]
    try:
        await _on_invalidation_event(event)
    finally:
        _ev_module.event_bus.publish_detached = real  # type: ignore[assignment]
    assert captured == []


@pytest.mark.asyncio
async def test_bi_register_subscribers_covers_all_topics() -> None:
    """register_subscribers subscribes to every projection-invalidating event."""
    from app.modules.bi_dashboards.events import (
        _PROJECTION_INVALIDATING_EVENTS,
        register_subscribers,
    )

    register_subscribers()
    # Sanity: the curated list must include at least the five
    # source-of-truth events Wave M4 specifies.
    expected_subset = {
        "safety.incident.created",
        "qms.ncr.raised",
        "daily_diary.closed",
        "supplier_catalogs.material.added",
        "schedule_advanced.actuals_update",
    }
    assert expected_subset.issubset(set(_PROJECTION_INVALIDATING_EVENTS))


# ── KPI history ordering (trend / sparkline correctness) ───────────────


@pytest.mark.asyncio
async def test_kpi_history_returned_oldest_to_newest(
    session: AsyncSession,
) -> None:
    """Trend/sparkline correctness: history must be chronological.

    Returning newest-first flipped every trend chart and inverted the
    period-over-period delta in the UI (frontend treats the LAST element
    as the latest period). This regression-locks oldest → newest order
    and the same-day ``computed_at`` tie-breaker.
    """
    from app.modules.bi_dashboards.models import KPIValue
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    now = datetime.now(UTC)
    base_day = now.date()
    # Insert deliberately out of order, three distinct weeks.
    for week in (2, 0, 1):
        period_end = base_day - timedelta(weeks=week)
        kv = KPIValue(
            kpi_code="_hist_order",
            project_id=None,
            period_start=period_end - timedelta(days=6),
            period_end=period_end,
            value=Decimal(str(week)),  # week 0 newest, value 0
            unit="ratio",
            computed_at=now,
            source_record_count=1,
        )
        session.add(kv)
    await session.flush()

    rows = await svc.kpi_history("_hist_order", limit=12)
    starts = [r.period_start for r in rows]
    assert starts == sorted(starts), "history must be oldest → newest"
    # Newest period (week offset 0, value '2') must be LAST.
    assert rows[-1].value == Decimal("0") or rows[-1].period_start == max(starts)
    assert rows[-1].period_start == max(starts)


@pytest.mark.asyncio
async def test_kpi_history_limit_keeps_most_recent(
    session: AsyncSession,
) -> None:
    """``limit`` must keep the most-recent N, not the oldest N."""
    from app.modules.bi_dashboards.models import KPIValue
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    now = datetime.now(UTC)
    base_day = now.date()
    for week in range(6):
        period_end = base_day - timedelta(weeks=week)
        session.add(
            KPIValue(
                kpi_code="_hist_limit",
                project_id=None,
                period_start=period_end - timedelta(days=6),
                period_end=period_end,
                value=Decimal(str(week)),
                unit="ratio",
                computed_at=now,
                source_record_count=1,
            ),
        )
    await session.flush()
    rows = await svc.kpi_history("_hist_limit", limit=3)
    assert len(rows) == 3
    # Most-recent three weeks are offsets 0,1,2 → period_start strictly
    # newer than the dropped (older) rows; still oldest→newest internally.
    starts = [r.period_start for r in rows]
    assert starts == sorted(starts)
    assert rows[-1].period_start == max(base_day - timedelta(weeks=w) - timedelta(days=6) for w in range(6))


# ── Drill-down forwards period / filters ───────────────────────────────


@pytest.mark.asyncio
async def test_drill_down_forwards_period_and_filters(
    session: AsyncSession,
) -> None:
    """``drill_down`` must thread period_start/end + filters into the KPI.

    Previously these DrillDownRequest fields were silently dropped, so a
    period-filtered drill-down returned the all-time aggregate — a row
    list that contradicted its own headline number.
    """
    from datetime import date

    from app.modules.bi_dashboards import kpis
    from app.modules.bi_dashboards.service import BIDashboardsService

    seen: dict[str, object] = {}

    @kpis.register_kpi(
        "_drill_period_probe",
        name="Probe",
        unit="ratio",
        category="operational",
    )
    async def _probe(session, **kw):  # noqa: ANN001, ANN003
        seen.update(kw)
        return kpis.KPIComputation(
            value=Decimal("1"),
            unit="ratio",
            source_record_count=1,
        )

    svc = BIDashboardsService(session)
    ps, pe = date(2026, 1, 1), date(2026, 3, 31)
    await svc.drill_down(
        "_drill_period_probe",
        period_start=ps,
        period_end=pe,
        filters={"region": "EU"},
        limit=10,
    )
    assert seen.get("period_start") == ps
    assert seen.get("period_end") == pe
    assert seen.get("filters") == {"region": "EU"}


# ── Financial KPI data-integrity + FX (audit findings #1/#3/#8/#9) ─────


@pytest_asyncio.fixture
async def finance_session() -> AsyncSession:
    """PostgreSQL session for the financial KPIs.

    The shared ``oe_test_unit`` database already carries the full schema
    (bi_dashboards + projects + finance + procurement + ncr and every child
    table the ``lazy="selectin"`` relationships eager-load), so the KPIs can
    read real source rows. Runs inside an outer transaction rolled back on
    teardown.
    """
    async with transactional_session() as s:
        yield s


async def _make_project(session: AsyncSession, *, currency: str, fx: list | None = None):
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        email=f"owner-{uuid.uuid4().hex}@example.test",
        hashed_password="x",
        full_name="Owner",
    )
    session.add(owner)
    await session.flush()
    proj = Project(
        name="P",
        description="",
        owner_id=owner.id,
        currency=currency,
        fx_rates=fx or [],
    )
    session.add(proj)
    await session.flush()
    return proj


@pytest.mark.asyncio
async def test_evm_ac_sums_payments_and_pos_with_fx(
    finance_session: AsyncSession,
) -> None:
    """AC is no longer always-zero: it sums settled payments + POs, and
    foreign-currency rows are converted into the project base currency via
    fx_rates before being added (no blind mixed-currency sum)."""
    from app.modules.bi_dashboards import kpis
    from app.modules.finance.models import Invoice, Payment
    from app.modules.procurement.models import PurchaseOrder

    # Base EUR; USD trades at 0.90 EUR per 1 USD.
    proj = await _make_project(
        finance_session,
        currency="EUR",
        fx=[{"code": "USD", "rate": "0.90", "label": "US Dollar"}],
    )
    # A payable invoice with a 100 EUR settled payment.
    inv = Invoice(
        project_id=proj.id,
        invoice_direction="payable",
        invoice_number="INV-1",
        invoice_date="2026-05-01",
        currency_code="EUR",
        amount_total=Decimal("100"),
    )
    finance_session.add(inv)
    await finance_session.flush()
    finance_session.add(
        Payment(
            invoice_id=inv.id,
            payment_date="2026-05-10",
            amount=Decimal("100"),
            currency_code="EUR",
        ),
    )
    # A USD purchase order for 200 USD → 180 EUR after FX.
    finance_session.add(
        PurchaseOrder(
            project_id=proj.id,
            po_number="PO-1",
            currency_code="USD",
            amount_total="200",
        ),
    )
    await finance_session.flush()

    snap = await kpis._evm_snapshot(finance_session, proj.id)
    # AC = 100 EUR payment + (200 USD * 0.90) = 100 + 180 = 280 EUR
    assert snap.ac == Decimal("280")
    assert snap.record_count > 0
    assert snap.breakdown["currency"] == "EUR"

    # cpi reflects real AC (record count > 0, not the old always-zero path)
    result = await kpis.compute("cpi", finance_session, project_id=proj.id)
    assert result.source_record_count > 0
    assert result.breakdown.get("currency") == "EUR"


@pytest.mark.asyncio
async def test_cash_in_30d_reads_real_invoice_fields(
    finance_session: AsyncSession,
) -> None:
    """cash_in_30d reads amount_total minus settled payments on receivable
    invoices (the old code read non-existent amount/paid_amount → always 0)."""
    from app.modules.bi_dashboards import kpis
    from app.modules.finance.models import Invoice, Payment

    proj = await _make_project(finance_session, currency="EUR")
    today = datetime.now(UTC).date()
    inv = Invoice(
        project_id=proj.id,
        invoice_direction="receivable",
        invoice_number="AR-1",
        invoice_date="2026-05-01",
        due_date=(today + timedelta(days=10)).isoformat(),
        currency_code="EUR",
        amount_total=Decimal("1000"),
    )
    finance_session.add(inv)
    await finance_session.flush()
    finance_session.add(
        Payment(
            invoice_id=inv.id,
            payment_date="2026-05-15",
            amount=Decimal("400"),
            currency_code="EUR",
        ),
    )
    await finance_session.flush()

    result = await kpis.compute("cash_in_30d", finance_session, project_id=proj.id)
    # Outstanding = 1000 - 400 = 600 due within the 30-day window
    assert result.value == Decimal("600")
    assert result.source_record_count == 1


@pytest.mark.asyncio
async def test_copq_groups_by_currency_for_portfolio(
    finance_session: AsyncSession,
) -> None:
    """Portfolio copq groups NCR cost impact by each project's base currency
    instead of blending differing currencies into one scalar."""
    from app.modules.bi_dashboards import kpis
    from app.modules.ncr.models import NCR

    eur_proj = await _make_project(finance_session, currency="EUR")
    usd_proj = await _make_project(finance_session, currency="USD")
    finance_session.add(
        NCR(
            project_id=eur_proj.id,
            ncr_number="N-1",
            title="t",
            description="d",
            ncr_type="quality",
            severity="major",
            cost_impact="5000",
        ),
    )
    finance_session.add(
        NCR(
            project_id=usd_proj.id,
            ncr_number="N-2",
            title="t",
            description="d",
            ncr_type="quality",
            severity="major",
            cost_impact="3000",
        ),
    )
    await finance_session.flush()

    result = await kpis.compute("copq", finance_session, project_id=None)
    by_cur = result.breakdown.get("by_currency", {})
    assert by_cur.get("EUR") == "5000"
    assert by_cur.get("USD") == "3000"
    assert result.source_record_count == 2
    # Headline value must be the DOMINANT currency subtotal (5000 EUR > 3000
    # USD), never the blended 8000 scalar, and the breakdown flags the mix.
    assert result.value == Decimal("5000")
    assert result.breakdown.get("currency") == "EUR"
    assert result.breakdown.get("multi_currency") is True


@pytest.mark.asyncio
async def test_cash_in_30d_portfolio_groups_by_currency(
    finance_session: AsyncSession,
) -> None:
    """Portfolio cash_in_30d groups outstanding receivables by each
    invoice's own currency rather than blending into one scalar."""
    from app.modules.bi_dashboards import kpis
    from app.modules.finance.models import Invoice

    eur_proj = await _make_project(finance_session, currency="EUR")
    usd_proj = await _make_project(finance_session, currency="USD")
    today = datetime.now(UTC).date()
    finance_session.add(
        Invoice(
            project_id=eur_proj.id,
            invoice_direction="receivable",
            invoice_number="AR-EUR",
            invoice_date="2026-05-01",
            due_date=(today + timedelta(days=5)).isoformat(),
            currency_code="EUR",
            amount_total=Decimal("1000"),
        ),
    )
    finance_session.add(
        Invoice(
            project_id=usd_proj.id,
            invoice_direction="receivable",
            invoice_number="AR-USD",
            invoice_date="2026-05-01",
            due_date=(today + timedelta(days=5)).isoformat(),
            currency_code="USD",
            amount_total=Decimal("400"),
        ),
    )
    await finance_session.flush()

    result = await kpis.compute("cash_in_30d", finance_session, project_id=None)
    by_cur = result.breakdown.get("by_currency", {})
    # Money strings carry cents (v3 §10 quantize-to-2dp).
    assert by_cur.get("EUR") == "1000.00"
    assert by_cur.get("USD") == "400.00"
    assert result.breakdown.get("multi_currency") is True
    # Dominant = EUR 1000 (> USD 400). Never the blended 1400 sum.
    assert result.value == Decimal("1000")
    assert result.breakdown.get("currency") == "EUR"
    assert result.source_record_count == 2


@pytest.mark.asyncio
async def test_cv_portfolio_groups_by_currency(
    finance_session: AsyncSession,
) -> None:
    """Portfolio Cost Variance (EV - AC) is computed per currency from each
    project's own primitives, not blended across currencies."""
    from app.modules.bi_dashboards import kpis
    from app.modules.finance.models import Invoice, Payment

    eur_proj = await _make_project(finance_session, currency="EUR")
    usd_proj = await _make_project(finance_session, currency="USD")
    # Each project has actual cost (a settled payment) in its own currency.
    for proj, code, amt in (
        (eur_proj, "EUR", "700"),
        (usd_proj, "USD", "300"),
    ):
        inv = Invoice(
            project_id=proj.id,
            invoice_direction="payable",
            invoice_number=f"INV-{code}",
            invoice_date="2026-05-01",
            currency_code=code,
            amount_total=Decimal(amt),
        )
        finance_session.add(inv)
        await finance_session.flush()
        finance_session.add(
            Payment(
                invoice_id=inv.id,
                payment_date="2026-05-10",
                amount=Decimal(amt),
                currency_code=code,
            ),
        )
    await finance_session.flush()

    snap = await kpis._evm_snapshot(finance_session, None)
    assert snap.is_portfolio is True
    assert snap.ac_by_currency.get("EUR") == Decimal("700")
    assert snap.ac_by_currency.get("USD") == Decimal("300")

    result = await kpis.compute("cv", finance_session, project_id=None)
    by_cur = result.breakdown.get("by_currency", {})
    # No tasks → EV = 0 in each currency, so CV = -AC per currency.
    # Money strings carry cents (v3 §10 quantize-to-2dp).
    assert by_cur.get("EUR") == "-700.00"
    assert by_cur.get("USD") == "-300.00"
    assert result.breakdown.get("multi_currency") is True
    # Dominant by magnitude = EUR (-700). Never the blended -1000 scalar.
    assert result.value == Decimal("-700")
    assert result.breakdown.get("currency") == "EUR"


@pytest.mark.asyncio
async def test_dso_uses_invoice_date_and_payment_dates(
    finance_session: AsyncSession,
) -> None:
    """dso reads invoice_date + Payment.payment_date (the old code read
    non-existent issue_date/paid_at → always 0)."""
    from app.modules.bi_dashboards import kpis
    from app.modules.finance.models import Invoice, Payment

    proj = await _make_project(finance_session, currency="EUR")
    inv = Invoice(
        project_id=proj.id,
        invoice_direction="receivable",
        invoice_number="AR-2",
        invoice_date="2026-05-01",
        currency_code="EUR",
        amount_total=Decimal("500"),
    )
    finance_session.add(inv)
    await finance_session.flush()
    finance_session.add(
        Payment(
            invoice_id=inv.id,
            payment_date="2026-05-31",
            amount=Decimal("500"),
            currency_code="EUR",
        ),
    )
    await finance_session.flush()

    result = await kpis.compute("dso", finance_session, project_id=proj.id)
    # 2026-05-01 → 2026-05-31 = 30 days
    assert result.value == Decimal("30")
    assert result.source_record_count == 1


# ── Dashboard render/evaluate portfolio IDOR scope (audit finding #21) ──
#
# The standalone /kpis/* routes already thread accessible_project_ids ->
# allowed_project_ids, but the dashboard CONSUMPTION path (render / evaluate)
# bypassed it: a portfolio widget (project_id=None) fanned out over EVERY
# project in the deployment, so a scoped (non-admin) caller opening a seeded
# global/role dashboard received CPI/SPI/EVM/cost KPI values aggregated across
# every tenant's projects, and that unrestricted value was then cached in the
# widget snapshot and served to everyone after. These tests pin the fix:
# render_dashboard / evaluate_dashboard now accept allowed_project_ids and
# forward it to every portfolio _kpis.compute, and the scope-blind snapshot
# cache is only read/written for unrestricted (admin) callers.


async def _global_dashboard_with_portfolio_widget(svc, *, kpi_code: str = "project_count_active"):
    """Create a global-scope dashboard with one portfolio (un-pinned) widget.

    ``project_count_active`` is a portfolio KPI that simply counts the
    projects in ``allowed_project_ids`` (or every project for an admin /
    ``None``), so its value is a deterministic proxy for "did the scope get
    applied" without depending on FX / currency-dominance logic.
    """
    from app.modules.bi_dashboards.schemas import DashboardCreate, WidgetCreate

    dashboard = await svc.create_dashboard(
        DashboardCreate(name="portfolio-board", scope="global", refresh_interval_seconds=3600),
        owner_user_id=None,
    )
    await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code=kpi_code),
    )
    return dashboard


@pytest.mark.asyncio
async def test_render_dashboard_scopes_portfolio_to_allowed_projects(
    finance_session: AsyncSession,
) -> None:
    """A scoped caller's portfolio widget aggregates ONLY their accessible
    projects, never every tenant's (audit #21)."""
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(finance_session)
    alice_proj = await _make_project(finance_session, currency="EUR")
    await _make_project(finance_session, currency="EUR")  # Bob's project
    dashboard = await _global_dashboard_with_portfolio_widget(svc)

    # Scoped to Alice's single project -> count must be exactly 1, not 2.
    scoped = await svc.render_dashboard(
        dashboard.id,
        allowed_project_ids={alice_proj.id},
    )
    assert scoped is not None
    assert scoped.widgets[0].value == Decimal("1")
    # Scoped caller must NOT serve nor write the shared snapshot.
    assert scoped.widgets[0].from_cache is False


@pytest.mark.asyncio
async def test_render_dashboard_admin_sees_full_portfolio(
    finance_session: AsyncSession,
) -> None:
    """``allowed_project_ids=None`` (admin) keeps the tenant-wide view -
    both projects are counted (audit #21 must not over-restrict admins)."""
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(finance_session)
    await _make_project(finance_session, currency="EUR")
    await _make_project(finance_session, currency="EUR")
    dashboard = await _global_dashboard_with_portfolio_widget(svc)

    admin = await svc.render_dashboard(dashboard.id, allowed_project_ids=None)
    assert admin is not None
    # Both freshly-created projects (and any pre-existing) are visible.
    assert admin.widgets[0].value >= Decimal("2")


@pytest.mark.asyncio
async def test_render_dashboard_scoped_caller_ignores_admin_snapshot(
    finance_session: AsyncSession,
) -> None:
    """The scope-blind snapshot an admin render writes must NEVER be served
    to a later scoped caller (the cache-poisoning half of audit #21)."""
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(finance_session)
    alice_proj = await _make_project(finance_session, currency="EUR")
    await _make_project(finance_session, currency="EUR")  # Bob's project
    dashboard = await _global_dashboard_with_portfolio_widget(svc)

    # 1) Admin renders first -> writes a tenant-wide snapshot (value >= 2).
    admin = await svc.render_dashboard(dashboard.id, allowed_project_ids=None)
    assert admin is not None
    assert admin.widgets[0].value >= Decimal("2")

    # 2) Scoped caller renders -> must recompute live for their own scope
    # (value 1) and NOT pick up the admin's cached >=2 value.
    scoped = await svc.render_dashboard(
        dashboard.id,
        allowed_project_ids={alice_proj.id},
    )
    assert scoped is not None
    assert scoped.widgets[0].from_cache is False
    assert scoped.widgets[0].value == Decimal("1")


@pytest.mark.asyncio
async def test_render_dashboard_empty_scope_yields_zero(
    finance_session: AsyncSession,
) -> None:
    """A non-admin with no accessible projects gets 0, never every project."""
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(finance_session)
    await _make_project(finance_session, currency="EUR")
    await _make_project(finance_session, currency="EUR")
    dashboard = await _global_dashboard_with_portfolio_widget(svc)

    scoped = await svc.render_dashboard(dashboard.id, allowed_project_ids=set())
    assert scoped is not None
    assert scoped.widgets[0].value == Decimal("0")


@pytest.mark.asyncio
async def test_evaluate_dashboard_scopes_portfolio_to_allowed_projects(
    finance_session: AsyncSession,
) -> None:
    """evaluate_dashboard (cross-filter OFF, the UI's static read path) also
    scopes a portfolio widget to the caller's accessible projects (audit #21)."""
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(finance_session)
    alice_proj = await _make_project(finance_session, currency="EUR")
    await _make_project(finance_session, currency="EUR")  # Bob's project
    dashboard = await _global_dashboard_with_portfolio_widget(svc)

    scoped = await svc.evaluate_dashboard(
        dashboard.id,
        allowed_project_ids={alice_proj.id},
    )
    assert scoped is not None
    assert scoped.widgets[0].value == Decimal("1")

    # Admin keeps the tenant-wide aggregate.
    admin = await svc.evaluate_dashboard(dashboard.id, allowed_project_ids=None)
    assert admin is not None
    assert admin.widgets[0].value >= Decimal("2")


# ── EVM spine sourced from the cost model (task #30) ───────────────────
#
# Before this, ``_evm_snapshot_for_project`` read ``planned_value`` /
# ``earned_value`` off ``tasks.models.Task``. ``oe_tasks_task`` defines
# NEITHER column, so both ``getattr`` calls took their default and EV = PV = 0
# for every project on the platform -> cpi = spi = 0 unconditionally. Nothing
# raised, so no test caught it: a ``getattr`` with a default never errors.
# These tests pin the real source and, more importantly, the two ways the fix
# itself could go wrong.


async def _budget_line(session, project, **kw):
    """One ``oe_costmodel_budget_line`` row with EVM amounts."""
    from app.modules.costmodel.models import BudgetLine

    line = BudgetLine(
        project_id=project.id,
        category=kw.pop("category", "general"),
        description=kw.pop("description", ""),
        currency=kw.pop("currency", project.currency),
        **kw,
    )
    session.add(line)
    await session.flush()
    return line


@pytest.mark.asyncio
async def test_evm_sources_pv_ev_ac_from_costmodel_budget_lines(
    finance_session: AsyncSession,
) -> None:
    """EV/AC come from the budget lines, and PV is time-phased by period.

    Line A's period is fully elapsed (contributes all of its planned amount
    to PV); line B's is entirely in the future (contributes none).
    """
    from app.modules.bi_dashboards import kpis

    proj = await _make_project(finance_session, currency="USD")
    await _budget_line(
        finance_session, proj,
        planned_amount="1000", earned_amount=Decimal("400"), actual_amount="500",
        period_start="2020-01-01", period_end="2020-12-31",
    )
    await _budget_line(
        finance_session, proj,
        planned_amount="1000", earned_amount=Decimal("0"), actual_amount="0",
        period_start="2099-01-01", period_end="2099-12-31",
    )

    snap = await kpis._evm_snapshot(finance_session, proj.id)
    assert snap.ev == Decimal("400")
    assert snap.ac == Decimal("500")
    assert snap.pv == Decimal("1000")      # elapsed line only
    assert snap.pv_known is True
    assert snap.breakdown["evm_source"] == "costmodel"
    # No project budget/contract value and no BOQ -> BAC falls back to
    # the sum of planned_amount, which IS budget-at-completion (not the PV).
    assert snap.bac == Decimal("2000")
    assert snap.breakdown["baseline_source"] == "costmodel_planned"

    cpi = await kpis.compute("cpi", finance_session, project_id=proj.id)
    spi = await kpis.compute("spi", finance_session, project_id=proj.id)
    assert cpi.value == Decimal("0.8")     # 400 / 500
    assert spi.value == Decimal("0.4")     # 400 / 1000
    assert cpi.source_record_count > 0
    assert spi.source_record_count > 0


@pytest.mark.asyncio
async def test_evm_pv_is_time_phased_not_budget_at_completion(
    finance_session: AsyncSession,
) -> None:
    """THE TRAP: PV = sum(planned_amount) is BAC, not planned value to date.

    Setting PV to the full planned total would divide EV by a number roughly
    the size of the whole budget and report a schedule catastrophe that is
    really a units error - an SPI that *looks* authoritative. PV must count
    only the portion of each line whose period has elapsed.
    """
    from app.modules.bi_dashboards import kpis

    proj = await _make_project(finance_session, currency="USD")
    await _budget_line(
        finance_session, proj,
        planned_amount="1000", earned_amount=Decimal("500"), actual_amount="500",
        period_start="2020-01-01", period_end="2020-12-31",
    )
    await _budget_line(
        finance_session, proj,
        planned_amount="9000", earned_amount=Decimal("0"), actual_amount="0",
        period_start="2099-01-01", period_end="2099-12-31",
    )

    snap = await kpis._evm_snapshot(finance_session, proj.id)
    assert snap.pv == Decimal("1000"), "PV must be time-phased, not total planned"
    assert snap.pv != snap.bac, "PV must not collapse onto BAC"
    spi = await kpis.compute("spi", finance_session, project_id=proj.id)
    assert spi.value == Decimal("0.5")     # 500 / 1000, NOT 500 / 10000 = 0.05


@pytest.mark.asyncio
async def test_spi_reports_no_data_when_any_budget_line_lacks_a_period(
    finance_session: AsyncSession,
) -> None:
    """A PV summed over fewer lines than EV covers is a units mismatch.

    Most projects on this platform carry budget lines with no period at all.
    Pro-rating PV over only the lines that HAVE periods, while EV counts every
    line, silently inflates SPI - the exact silent-wrong-number this module is
    being cleaned of. So PV is reported unknown and SPI/SV grey out
    (``source_record_count == 0``), matching the existing "no baseline -> no
    data" convention rather than inventing a number.

    CPI is unaffected: it divides EV by AC and never touches PV.
    """
    from app.modules.bi_dashboards import kpis

    proj = await _make_project(finance_session, currency="USD")
    await _budget_line(
        finance_session, proj,
        planned_amount="1000", earned_amount=Decimal("400"), actual_amount="500",
        period_start="2020-01-01", period_end="2020-12-31",
    )
    await _budget_line(   # no period -> PV unmeasurable for this project
        finance_session, proj,
        planned_amount="1000", earned_amount=Decimal("400"), actual_amount="500",
    )

    snap = await kpis._evm_snapshot(finance_session, proj.id)
    assert snap.pv_known is False

    spi = await kpis.compute("spi", finance_session, project_id=proj.id)
    assert spi.source_record_count == 0, "SPI must report no-data, not a number"
    sv = await kpis.compute("sv", finance_session, project_id=proj.id)
    assert sv.source_record_count == 0

    # CPI still reports: EV/AC needs no schedule baseline.
    cpi = await kpis.compute("cpi", finance_session, project_id=proj.id)
    assert cpi.source_record_count > 0
    assert cpi.value == Decimal("0.8")     # 800 / 1000


@pytest.mark.asyncio
async def test_evm_falls_back_to_legacy_path_without_budget_lines(
    finance_session: AsyncSession,
) -> None:
    """A project with no cost model keeps the old task/payment/PO behaviour,
    so existing deployments do not change under them."""
    from app.modules.bi_dashboards import kpis

    proj = await _make_project(finance_session, currency="USD")
    snap = await kpis._evm_snapshot(finance_session, proj.id)
    assert snap.breakdown["evm_source"] == "tasks"
    assert snap.pv_known is True


# ── Render path honours the widget's own project scope (task #30) ──────


@pytest.mark.asyncio
async def test_render_dashboard_scopes_widget_to_config_json_project_id(
    finance_session: AsyncSession,
) -> None:
    """``render_dashboard`` must pass ``config_json["project_id"]`` into the
    KPI. It previously did not, so a pinned widget silently rendered the
    portfolio roll-up - ``update_widget_snapshot`` did the right thing but is
    unreachable, which made the bug easy to miss by reading."""
    from app.modules.bi_dashboards.schemas import DashboardCreate, WidgetCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(finance_session)
    a = await _make_project(finance_session, currency="USD")
    b = await _make_project(finance_session, currency="USD")
    await _budget_line(
        finance_session, a,
        planned_amount="1000", earned_amount=Decimal("400"), actual_amount="500",
        period_start="2020-01-01", period_end="2020-12-31",
    )
    await _budget_line(
        finance_session, b,
        planned_amount="1000", earned_amount=Decimal("900"), actual_amount="900",
        period_start="2020-01-01", period_end="2020-12-31",
    )

    dashboard = await svc.create_dashboard(
        DashboardCreate(name="pinned", scope="global", refresh_interval_seconds=3600),
        owner_user_id=None,
    )
    await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="cpi",
                     config_json={"project_id": str(a.id)}),
    )
    await svc.create_widget(   # same KPI, no scope -> portfolio
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="cpi"),
    )

    rendered = await svc.render_dashboard(dashboard.id, allowed_project_ids=None)
    assert rendered is not None
    pinned = next(w for w in rendered.widgets if w.widget.config_json)
    unpinned = next(w for w in rendered.widgets if not w.widget.config_json)
    assert pinned.value == Decimal("0.8"), "pinned widget must read project A only"
    assert unpinned.value != pinned.value, "unscoped widget must stay a roll-up"


@pytest.mark.asyncio
async def test_render_dashboard_refuses_widget_scoped_to_inaccessible_project(
    finance_session: AsyncSession,
) -> None:
    """Scoping must never widen authorisation.

    ``kpis._scope_portfolio`` no-ops once ``project_id`` is set ("already
    gated"), so feeding it an unvalidated ``config_json`` value would turn any
    stored widget into a cross-tenant read. The render path checks the
    configured project against ``allowed_project_ids`` first, and renders an
    empty tile rather than falling back to the portfolio - a fallback would
    quietly answer a different question than the tile asks.
    """
    from app.modules.bi_dashboards.schemas import DashboardCreate, WidgetCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(finance_session)
    a = await _make_project(finance_session, currency="USD")
    b = await _make_project(finance_session, currency="USD")
    await _budget_line(
        finance_session, a,
        planned_amount="1000", earned_amount=Decimal("400"), actual_amount="500",
        period_start="2020-01-01", period_end="2020-12-31",
    )

    dashboard = await svc.create_dashboard(
        DashboardCreate(name="idor", scope="global", refresh_interval_seconds=3600),
        owner_user_id=None,
    )
    await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="cpi",
                     config_json={"project_id": str(a.id)}),
    )

    # Caller may see only project B; the widget names project A.
    rendered = await svc.render_dashboard(dashboard.id, allowed_project_ids={b.id})
    assert rendered is not None
    assert rendered.widgets[0].value == Decimal("0")
    assert rendered.widgets[0].breakdown.get("error") == "forbidden_project_scope"


# ── change_order_ratio at portfolio scope (task #32) ───────────────────


@pytest.mark.asyncio
async def test_change_order_ratio_computes_denominator_at_portfolio_scope(
    finance_session: AsyncSession,
) -> None:
    """The contract-value probe used to have no ``else`` branch.

    At portfolio scope ``contract_value`` stayed 0, tripped the
    ``contract_value <= 0`` guard and returned value 0 *while still reporting*
    ``source_record_count`` - it summed every change order and divided by a
    denominator it never computed. Every roll-up board read "0 %" over a real
    change-order count, which is a confident wrong number rather than a
    visible gap.
    """
    from app.modules.bi_dashboards import kpis
    from app.modules.changeorders.models import ChangeOrder

    a = await _make_project(finance_session, currency="USD")
    b = await _make_project(finance_session, currency="USD")
    a.contract_value = "1000"
    b.contract_value = "3000"
    finance_session.add_all(
        [
            ChangeOrder(project_id=a.id, code="CO-A", title="a",
                        approved_amount="20", currency="USD"),
            ChangeOrder(project_id=b.id, code="CO-B", title="b",
                        approved_amount="20", currency="USD"),
        ],
    )
    await finance_session.flush()

    # Scoped: 20 / 1000 = 2%.
    scoped = await kpis.compute("change_order_ratio", finance_session, project_id=a.id)
    assert scoped.value == Decimal("2")

    # Portfolio: 40 / 4000 = 1%. Before the fix this was 0 with count 2.
    port = await kpis.compute("change_order_ratio", finance_session, project_id=None)
    assert port.source_record_count == 2
    assert port.value == Decimal("1"), "portfolio denominator must be computed"


@pytest.mark.asyncio
async def test_change_order_ratio_portfolio_denominator_honours_idor_gate(
    finance_session: AsyncSession,
) -> None:
    """The denominator must span exactly the projects the numerator spans.

    ``allowed_project_ids`` scopes the change-order query, so summing contract
    value over *every* project would divide an accessible numerator by an
    inaccessible denominator and silently under-report the ratio.
    """
    from app.modules.bi_dashboards import kpis
    from app.modules.changeorders.models import ChangeOrder

    a = await _make_project(finance_session, currency="USD")
    b = await _make_project(finance_session, currency="USD")
    a.contract_value = "1000"
    b.contract_value = "9000"
    finance_session.add_all(
        [
            ChangeOrder(project_id=a.id, code="CO-A", title="a",
                        approved_amount="20", currency="USD"),
            ChangeOrder(project_id=b.id, code="CO-B", title="b",
                        approved_amount="900", currency="USD"),
        ],
    )
    await finance_session.flush()

    # Caller may see only project A: 20 / 1000 = 2%, NOT 20 / 10000.
    res = await kpis.compute(
        "change_order_ratio", finance_session,
        project_id=None, allowed_project_ids={a.id},
    )
    assert res.source_record_count == 1
    assert res.value == Decimal("2")


# ── Chart widgets carry their history (render path) ────────────────────
#
# ``render_dashboard`` calls ``_kpis.compute`` directly, and that returns a
# single current value. The trend list is assembled by ``compute_kpi``, which
# the render path never calls - so ``line_chart``/``bar_chart`` tiles arrived
# at the frontend with no ``breakdown["trend"]`` and the Sparkline fell back
# to a one-element ``[value]``, drawing a single dot no matter how much
# history had been persisted. These two pin the fix and its gating.


@pytest.mark.asyncio
async def test_render_attaches_trend_history_to_chart_widgets(
    session: AsyncSession,
) -> None:
    from datetime import timedelta

    from app.modules.bi_dashboards.models import KPIValue
    from app.modules.bi_dashboards.schemas import DashboardCreate, WidgetCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    dashboard = await svc.create_dashboard(
        DashboardCreate(name="charts", refresh_interval_seconds=300),
        owner_user_id=None,
    )
    await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="cpi", widget_type="line_chart"),
    )

    now = datetime.now(UTC)
    base_day = now.date()
    # Insert newest-first so the assertion below also proves the render path
    # hands back chronological points rather than raw query order - drawing
    # them reversed would invert the curve and raise nothing.
    for week in (0, 1, 2):
        period_end = base_day - timedelta(weeks=week)
        session.add(
            KPIValue(
                kpi_code="cpi",
                project_id=None,
                period_start=period_end - timedelta(days=6),
                period_end=period_end,
                value=Decimal(str(week)),
                unit="ratio",
                computed_at=now,
                source_record_count=1,
            ),
        )
    await session.flush()

    result = await svc.render_dashboard(dashboard.id)
    assert result is not None
    chart = result.widgets[0]
    trend = chart.breakdown["trend"]
    assert len(trend) == 3
    # week 2 is the oldest and carries value 2; chronological order means it
    # comes FIRST and the newest (value 0) comes last.
    assert [p["value"] for p in trend] == ["2.000000", "1.000000", "0.000000"]


@pytest.mark.asyncio
async def test_render_does_not_attach_trend_to_kpi_cards(
    session: AsyncSession,
) -> None:
    """The history query is gated on widget_type, for two reasons.

    It keeps the added cost at one query per CHART rather than per widget on
    a board that may carry a dozen tiles, and it leaves ``kpi_card`` output
    byte-identical - the card reads the same key to decide whether to draw a
    delta chip, so attaching a trend here would silently add chips to tiles
    that have never had one.
    """
    from app.modules.bi_dashboards.schemas import DashboardCreate, WidgetCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    dashboard = await svc.create_dashboard(
        DashboardCreate(name="cards", refresh_interval_seconds=300),
        owner_user_id=None,
    )
    await svc.create_widget(
        WidgetCreate(dashboard_id=dashboard.id, kpi_code="cpi", widget_type="kpi_card"),
    )
    result = await svc.render_dashboard(dashboard.id)
    assert result is not None
    assert "trend" not in (result.widgets[0].breakdown or {})


# ── Per-currency buckets must hold RAW amounts, not base conversions ───
#
# ``_add_currency_bucket`` files an amount under an ISO code. Two of its seven
# call sites passed the BASE-CONVERTED amount while labelling the bucket with
# the row's OWN currency, so the tile rendered a USD number badged "EUR". The
# other five pass the raw amount, which is the intended contract.


@pytest.mark.asyncio
async def test_pending_variation_value_buckets_raw_amount_under_source_currency(
    finance_session: AsyncSession,
) -> None:
    """A EUR variation on a USD project buckets 22,459 EUR - not its USD value.

    This is the on-screen defect: the hero project is USD, its pending
    variations are EUR, and the tile showed the USD conversion 24,031.13
    under the label EUR. Neither number was correct for its label.
    """
    from app.modules.bi_dashboards import kpis
    from app.modules.variations.models import VariationRequest

    proj = await _make_project(
        finance_session,
        currency="USD",
        fx=[{"code": "EUR", "rate": "1.07", "label": "Euro"}],
    )
    finance_session.add(
        VariationRequest(
            project_id=proj.id,
            code="VR-1",
            title="t",
            estimated_cost_impact="22459",
            currency="EUR",
            status="submitted",
        ),
    )
    await finance_session.flush()

    result = await kpis.compute("pending_variation_value", finance_session, project_id=None)
    by_cur = result.breakdown.get("by_currency", {})
    # 22459 EUR stays 22459 EUR. The pre-fix value here was 24031.13 - the
    # USD conversion, filed under "EUR".
    assert Decimal(by_cur["EUR"]) == Decimal("22459")
    assert result.breakdown.get("currency") == "EUR"


@pytest.mark.asyncio
async def test_risk_open_exposure_buckets_raw_amount_under_source_currency(
    finance_session: AsyncSession,
) -> None:
    """Same defect, same fix, on the tile sitting beside it.

    This one was latent: the hero's risks are already USD, so the conversion
    was the identity and the label was right BY ACCIDENT. It would misprice
    the moment a non-USD risk was seeded, which is what this pins.
    """
    from app.modules.bi_dashboards import kpis
    from app.modules.risk.models import RiskItem

    proj = await _make_project(
        finance_session,
        currency="USD",
        fx=[{"code": "EUR", "rate": "1.07", "label": "Euro"}],
    )
    finance_session.add(
        RiskItem(
            project_id=proj.id,
            code="R-1",
            title="t",
            impact_cost="10000",
            currency="EUR",
            status="identified",
            probability="0.5",
        ),
    )
    await finance_session.flush()

    result = await kpis.compute("risk_open_exposure", finance_session, project_id=None)
    by_cur = result.breakdown.get("by_currency", {})
    assert Decimal(by_cur["EUR"]) == Decimal("10000")
