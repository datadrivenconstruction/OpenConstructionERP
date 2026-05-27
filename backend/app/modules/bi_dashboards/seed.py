# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Seed data for the BI Dashboards module.

* All registered system KPIs as :class:`KPIDefinition` rows
* 5 role-based default dashboards (CEO / CFO / PM / Site Manager /
  Safety Officer) with 4-8 widgets each
* 3 ReportDefinitions: Monthly Project Summary, Weekly Safety Report,
  Cash Flow 90d
* 2 ReportSchedules
* 4 AlertRules (CPI<0.9, SPI<0.9, copq>50000, trir>3)
* 8 KPIValue historical rows per KPI (12-week trend)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bi_dashboards.kpis import SYSTEM_KPI_META
from app.modules.bi_dashboards.models import (
    AlertRule,
    Dashboard,
    DashboardWidget,
    KPIValue,
    ReportDefinition,
    ReportSchedule,
)
from app.modules.bi_dashboards.service import (
    BIDashboardsService,
    compute_next_run_at,
)

logger = logging.getLogger(__name__)


# ── Default dashboards ─────────────────────────────────────────────────


_DEFAULT_DASHBOARDS: list[dict] = [
    {
        "name": "CEO Overview",
        "description": "Executive view across financial, schedule, safety, ESG.",
        "scope": "role",
        "role_ref": "admin",
        "widgets": [
            ("kpi_card", "cpi"),
            ("kpi_card", "spi"),
            ("kpi_card", "safety_trir"),
            ("kpi_card", "project_count_active"),
            ("kpi_card", "cash_in_30d"),
            ("kpi_card", "cash_out_30d"),
            ("line_chart", "cpi"),
            ("bar_chart", "embodied_carbon_per_m2"),
        ],
    },
    {
        "name": "CFO Cash & Cost Control",
        "description": "Cash flow, change orders, savings, DSO.",
        "scope": "role",
        "role_ref": "manager",
        "widgets": [
            ("kpi_card", "cpi"),
            ("kpi_card", "cash_in_30d"),
            ("kpi_card", "cash_out_30d"),
            ("kpi_card", "dso"),
            ("kpi_card", "change_order_ratio"),
            ("kpi_card", "procurement_savings"),
            ("line_chart", "cash_in_30d"),
        ],
    },
    {
        "name": "Project Manager Dashboard",
        "description": "CPI/SPI plus RFI/punch close rates.",
        "scope": "role",
        "role_ref": "manager",
        "widgets": [
            ("kpi_card", "cpi"),
            ("kpi_card", "spi"),
            ("kpi_card", "rfi_close_avg_days"),
            ("kpi_card", "punch_close_rate"),
            ("kpi_card", "first_pass_yield"),
            ("kpi_card", "copq"),
            ("bar_chart", "change_order_ratio"),
        ],
    },
    {
        "name": "Site Manager Dashboard",
        "description": "Quality, equipment, subs on the ground.",
        "scope": "role",
        "role_ref": "editor",
        "widgets": [
            ("kpi_card", "first_pass_yield"),
            ("kpi_card", "punch_close_rate"),
            ("kpi_card", "equipment_utilization"),
            ("kpi_card", "subcontractor_avg_rating"),
            ("kpi_card", "safety_trir"),
            ("kpi_card", "rfi_close_avg_days"),
        ],
    },
    {
        "name": "Safety Officer Dashboard",
        "description": "TRIR, COPQ, incident-related compliance.",
        "scope": "role",
        "role_ref": "editor",
        "widgets": [
            ("kpi_card", "safety_trir"),
            ("kpi_card", "first_pass_yield"),
            ("kpi_card", "copq"),
            ("kpi_card", "punch_close_rate"),
            ("line_chart", "safety_trir"),
        ],
    },
]


_DEFAULT_REPORTS: list[dict] = [
    {
        "code": "monthly_project_summary",
        "name": "Monthly Project Summary",
        "description": "CPI, SPI, change-order ratio, TRIR for the period.",
        "source_modules": ["finance", "tasks", "safety", "changeorders"],
        "query_spec_json": {
            "kpis": ["cpi", "spi", "change_order_ratio", "safety_trir"],
        },
        "output_format": "pdf",
        "scope": "global",
    },
    {
        "code": "weekly_safety_report",
        "name": "Weekly Safety Report",
        "description": "Recordable incidents and TRIR over the past week.",
        "source_modules": ["safety"],
        "query_spec_json": {"kpis": ["safety_trir", "copq"]},
        "output_format": "pdf",
        "scope": "global",
    },
    {
        "code": "cash_flow_90d",
        "name": "Cash Flow Forecast (90d)",
        "description": "30/60/90-day projected cash in/out.",
        "source_modules": ["finance"],
        "query_spec_json": {
            "kpis": ["cash_in_30d", "cash_out_30d", "dso"],
        },
        "output_format": "xlsx",
        "scope": "global",
    },
]


_DEFAULT_ALERTS: list[dict] = [
    {
        "name": "CPI dropped below 0.9",
        "kpi_code": "cpi",
        "condition": "below",
        "threshold_value": Decimal("0.9"),
        "severity": "warning",
        "channels_json": ["in_app", "email"],
        "throttle_seconds": 3600,
    },
    {
        "name": "SPI dropped below 0.9",
        "kpi_code": "spi",
        "condition": "below",
        "threshold_value": Decimal("0.9"),
        "severity": "warning",
        "channels_json": ["in_app", "email"],
        "throttle_seconds": 3600,
    },
    {
        "name": "COPQ exceeded $50k",
        "kpi_code": "copq",
        "condition": "above",
        "threshold_value": Decimal("50000"),
        "severity": "critical",
        "channels_json": ["in_app", "email"],
        "throttle_seconds": 7200,
    },
    {
        "name": "Safety TRIR exceeded 3.0",
        "kpi_code": "safety_trir",
        "condition": "above",
        "threshold_value": Decimal("3"),
        "severity": "critical",
        "channels_json": ["in_app", "email", "webhook"],
        "throttle_seconds": 1800,
    },
]


async def _seed_kpi_definitions(
    session: AsyncSession,
    service: BIDashboardsService,
) -> int:
    return await service.bootstrap_system_kpis()


async def _seed_dashboards(session: AsyncSession) -> list[Dashboard]:
    created: list[Dashboard] = []
    for spec in _DEFAULT_DASHBOARDS:
        # Skip if a dashboard with same name+scope already exists
        existing_q = select(Dashboard).where(
            Dashboard.name == spec["name"],
            Dashboard.scope == spec["scope"],
        )
        if (await session.execute(existing_q)).scalar_one_or_none() is not None:
            continue
        dashboard = Dashboard(
            name=spec["name"],
            description=spec["description"],
            scope=spec["scope"],
            role_ref=spec.get("role_ref"),
            is_default=True,
            refresh_interval_seconds=300,
        )
        session.add(dashboard)
        await session.flush()
        for idx, (wtype, code) in enumerate(spec["widgets"]):
            widget = DashboardWidget(
                dashboard_id=dashboard.id,
                widget_type=wtype,
                kpi_code=code,
                config_json={},
                position_x=(idx % 4) * 3,
                position_y=(idx // 4) * 2,
                width=3,
                height=2,
                order_seq=idx,
            )
            session.add(widget)
        await session.flush()
        created.append(dashboard)
    return created


async def _seed_reports(session: AsyncSession) -> list[ReportDefinition]:
    created: list[ReportDefinition] = []
    for spec in _DEFAULT_REPORTS:
        existing_q = select(ReportDefinition).where(
            ReportDefinition.code == spec["code"],
        )
        if (await session.execute(existing_q)).scalar_one_or_none() is not None:
            continue
        report = ReportDefinition(
            code=spec["code"],
            name=spec["name"],
            description=spec["description"],
            source_modules=spec["source_modules"],
            query_spec_json=spec["query_spec_json"],
            output_format=spec["output_format"],
            scope=spec["scope"],
        )
        session.add(report)
        await session.flush()
        created.append(report)
    return created


async def _seed_schedules(
    session: AsyncSession,
    reports: list[ReportDefinition],
) -> list[ReportSchedule]:
    if not reports:
        return []
    by_code = {r.code: r for r in reports}
    specs = [
        {
            "code": "monthly_project_summary",
            "frequency": "monthly",
            "day_of_month": 1,
            "time_of_day": "07:00",
        },
        {
            "code": "weekly_safety_report",
            "frequency": "weekly",
            "day_of_week": 0,
            "time_of_day": "08:00",
        },
    ]
    created: list[ReportSchedule] = []
    for spec in specs:
        report = by_code.get(spec["code"])
        if report is None:
            continue
        existing_q = select(ReportSchedule).where(
            ReportSchedule.report_definition_id == report.id,
        )
        if (await session.execute(existing_q)).scalar_one_or_none() is not None:
            continue
        next_run = compute_next_run_at(
            frequency=spec["frequency"],
            time_of_day=spec["time_of_day"],
            day_of_week=spec.get("day_of_week"),
            day_of_month=spec.get("day_of_month"),
        )
        schedule = ReportSchedule(
            report_definition_id=report.id,
            frequency=spec["frequency"],
            day_of_week=spec.get("day_of_week"),
            day_of_month=spec.get("day_of_month"),
            time_of_day=spec["time_of_day"],
            recipients_json=[],
            enabled=True,
            next_run_at=next_run,
        )
        session.add(schedule)
        await session.flush()
        created.append(schedule)
    return created


async def _seed_alerts(session: AsyncSession) -> list[AlertRule]:
    created: list[AlertRule] = []
    for spec in _DEFAULT_ALERTS:
        existing_q = select(AlertRule).where(
            AlertRule.name == spec["name"],
            AlertRule.kpi_code == spec["kpi_code"],
        )
        if (await session.execute(existing_q)).scalar_one_or_none() is not None:
            continue
        alert = AlertRule(
            name=spec["name"],
            kpi_code=spec["kpi_code"],
            condition=spec["condition"],
            threshold_value=spec["threshold_value"],
            severity=spec["severity"],
            channels_json=spec.get("channels_json", ["in_app"]),
            throttle_seconds=spec.get("throttle_seconds", 3600),
            enabled=True,
        )
        session.add(alert)
        await session.flush()
        created.append(alert)
    return created


async def _seed_kpi_history(session: AsyncSession) -> int:
    """‌⁠‍Seed 8 historical rows per registered system KPI (12-week trend)."""
    total = 0
    now = datetime.now(UTC)
    today = now.date()
    for code, meta in SYSTEM_KPI_META.items():
        # Skip if any history already exists for this KPI (idempotent)
        q = select(KPIValue).where(KPIValue.kpi_code == code).limit(1)
        if (await session.execute(q)).scalar_one_or_none() is not None:
            continue
        unit = meta.get("unit", "ratio")
        for week_offset in range(8):
            period_end = today - timedelta(weeks=week_offset)
            period_start = period_end - timedelta(days=6)
            # Synthetic but plausible values — never persist if real values
            # will overwrite them via the live computer.
            value = Decimal(str(0.85 + week_offset * 0.02))
            kv = KPIValue(
                kpi_code=code,
                project_id=None,
                period_start=period_start,
                period_end=period_end,
                value=value,
                unit=unit,
                computed_at=now,
                source_record_count=0,
            )
            session.add(kv)
            total += 1
    await session.flush()
    return total


async def seed_all(session: AsyncSession) -> dict[str, int]:
    """‌⁠‍Run every seed step in dependency order and return counts."""
    service = BIDashboardsService(session)
    kpi_count = await _seed_kpi_definitions(session, service)
    dashboards = await _seed_dashboards(session)
    reports = await _seed_reports(session)
    schedules = await _seed_schedules(session, reports)
    alerts = await _seed_alerts(session)
    history_rows = await _seed_kpi_history(session)
    return {
        "kpi_definitions": kpi_count,
        "dashboards": len(dashboards),
        "reports": len(reports),
        "schedules": len(schedules),
        "alerts": len(alerts),
        "kpi_history_rows": history_rows,
    }


__all__ = ["seed_all"]
