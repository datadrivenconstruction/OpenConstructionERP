# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Data-access layer for the BI Dashboards module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bi_dashboards.models import (
    AlertRule,
    Dashboard,
    DashboardWidget,
    DashboardWidgetSnapshot,
    KPIDefinition,
    KPIValue,
    ReportDefinition,
    ReportSchedule,
    SavedFilter,
)


class BIDashboardsRepository:
    """‌⁠‍Single repository per module — entity-typed methods stay grouped."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── KPI Definition ─────────────────────────────────────────────

    async def list_kpi_definitions(
        self,
        *,
        category: str | None = None,
    ) -> list[KPIDefinition]:
        stmt = select(KPIDefinition).order_by(KPIDefinition.code.asc())
        if category is not None:
            stmt = stmt.where(KPIDefinition.category == category)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_kpi_definition_by_code(
        self,
        code: str,
    ) -> KPIDefinition | None:
        stmt = select(KPIDefinition).where(KPIDefinition.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def upsert_kpi_definition(
        self,
        *,
        code: str,
        name: str,
        description: str,
        formula_ref: str,
        source_modules: list[str],
        unit: str,
        target_default: Any,
        aggregation: str,
        category: str,
        is_system: bool,
    ) -> KPIDefinition:
        existing = await self.get_kpi_definition_by_code(code)
        if existing is None:
            kd = KPIDefinition(
                code=code,
                name=name,
                description=description,
                formula_ref=formula_ref,
                source_modules=source_modules,
                unit=unit,
                target_default=target_default,
                aggregation=aggregation,
                category=category,
                is_system=is_system,
            )
            self.session.add(kd)
            await self.session.flush()
            return kd
        existing.name = name
        existing.description = description
        existing.formula_ref = formula_ref
        existing.source_modules = source_modules
        existing.unit = unit
        existing.target_default = target_default
        existing.aggregation = aggregation
        existing.category = category
        existing.is_system = is_system
        await self.session.flush()
        return existing

    # ── Dashboard ──────────────────────────────────────────────────

    async def get_dashboard(self, dashboard_id: uuid.UUID) -> Dashboard | None:
        return await self.session.get(Dashboard, dashboard_id)

    async def list_dashboards(
        self,
        *,
        owner_user_id: uuid.UUID | None = None,
        scope: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> list[Dashboard]:
        stmt = select(Dashboard).order_by(Dashboard.name.asc())
        if owner_user_id is not None:
            stmt = stmt.where(Dashboard.owner_user_id == owner_user_id)
        if scope is not None:
            stmt = stmt.where(Dashboard.scope == scope)
        if project_id is not None:
            stmt = stmt.where(Dashboard.project_id == project_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_dashboards_visible_to(
        self,
        owner_user_id: uuid.UUID | None,
    ) -> list[Dashboard]:
        """‌⁠‍Return dashboards a user can see: own + role/global ones."""
        stmt = select(Dashboard).order_by(
            Dashboard.scope.asc(),
            Dashboard.name.asc(),
        )
        from sqlalchemy import or_

        if owner_user_id is None:
            stmt = stmt.where(Dashboard.scope.in_(("global", "role")))
        else:
            stmt = stmt.where(
                or_(
                    Dashboard.owner_user_id == owner_user_id,
                    Dashboard.scope.in_(("global", "role")),
                ),
            )
        return list((await self.session.execute(stmt)).scalars().all())

    async def create_dashboard(self, dashboard: Dashboard) -> Dashboard:
        self.session.add(dashboard)
        await self.session.flush()
        return dashboard

    async def update_dashboard(
        self,
        dashboard_id: uuid.UUID,
        **fields: Any,
    ) -> Dashboard | None:
        dashboard = await self.get_dashboard(dashboard_id)
        if dashboard is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(dashboard, key, value)
        await self.session.flush()
        return dashboard

    async def delete_dashboard(self, dashboard_id: uuid.UUID) -> bool:
        dashboard = await self.get_dashboard(dashboard_id)
        if dashboard is None:
            return False
        await self.session.delete(dashboard)
        await self.session.flush()
        return True

    # ── Widget ─────────────────────────────────────────────────────

    async def list_widgets(
        self,
        dashboard_id: uuid.UUID,
    ) -> list[DashboardWidget]:
        stmt = (
            select(DashboardWidget)
            .where(DashboardWidget.dashboard_id == dashboard_id)
            .order_by(DashboardWidget.order_seq.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_widget(self, widget_id: uuid.UUID) -> DashboardWidget | None:
        return await self.session.get(DashboardWidget, widget_id)

    async def create_widget(self, widget: DashboardWidget) -> DashboardWidget:
        self.session.add(widget)
        await self.session.flush()
        return widget

    async def update_widget(
        self,
        widget_id: uuid.UUID,
        **fields: Any,
    ) -> DashboardWidget | None:
        widget = await self.get_widget(widget_id)
        if widget is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(widget, key, value)
        await self.session.flush()
        return widget

    async def delete_widget(self, widget_id: uuid.UUID) -> bool:
        widget = await self.get_widget(widget_id)
        if widget is None:
            return False
        await self.session.delete(widget)
        await self.session.flush()
        return True

    # ── Snapshot ───────────────────────────────────────────────────

    async def get_latest_snapshot(
        self,
        widget_id: uuid.UUID,
    ) -> DashboardWidgetSnapshot | None:
        stmt = (
            select(DashboardWidgetSnapshot)
            .where(DashboardWidgetSnapshot.widget_id == widget_id)
            .order_by(DashboardWidgetSnapshot.computed_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def write_snapshot(
        self,
        *,
        widget_id: uuid.UUID,
        value_json: dict,
        computed_at: datetime,
        valid_until: datetime,
    ) -> DashboardWidgetSnapshot:
        snap = DashboardWidgetSnapshot(
            widget_id=widget_id,
            computed_at=computed_at,
            value_json=value_json,
            valid_until=valid_until,
        )
        self.session.add(snap)
        await self.session.flush()
        return snap

    async def purge_snapshots(self, widget_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(DashboardWidgetSnapshot).where(
                DashboardWidgetSnapshot.widget_id == widget_id,
            ),
        )

    # ── Report Definition ─────────────────────────────────────────

    async def list_reports(
        self,
        *,
        owner_user_id: uuid.UUID | None = None,
    ) -> list[ReportDefinition]:
        from sqlalchemy import or_

        stmt = select(ReportDefinition).order_by(ReportDefinition.code.asc())
        if owner_user_id is not None:
            stmt = stmt.where(
                or_(
                    ReportDefinition.owner_user_id == owner_user_id,
                    ReportDefinition.scope.in_(("global", "role")),
                ),
            )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_report(
        self,
        report_id: uuid.UUID,
    ) -> ReportDefinition | None:
        return await self.session.get(ReportDefinition, report_id)

    async def get_report_by_code(self, code: str) -> ReportDefinition | None:
        stmt = select(ReportDefinition).where(ReportDefinition.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create_report(self, report: ReportDefinition) -> ReportDefinition:
        self.session.add(report)
        await self.session.flush()
        return report

    async def update_report(
        self,
        report_id: uuid.UUID,
        **fields: Any,
    ) -> ReportDefinition | None:
        report = await self.get_report(report_id)
        if report is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(report, key, value)
        await self.session.flush()
        return report

    async def delete_report(self, report_id: uuid.UUID) -> bool:
        report = await self.get_report(report_id)
        if report is None:
            return False
        await self.session.delete(report)
        await self.session.flush()
        return True

    # ── Report Schedule ────────────────────────────────────────────

    async def list_schedules(
        self,
        *,
        due_before: datetime | None = None,
    ) -> list[ReportSchedule]:
        stmt = select(ReportSchedule).where(ReportSchedule.enabled.is_(True))
        if due_before is not None:
            stmt = stmt.where(
                (ReportSchedule.next_run_at.is_(None)) | (ReportSchedule.next_run_at <= due_before),
            )
        stmt = stmt.order_by(ReportSchedule.next_run_at.asc().nullsfirst())
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_schedule(
        self,
        schedule_id: uuid.UUID,
    ) -> ReportSchedule | None:
        return await self.session.get(ReportSchedule, schedule_id)

    async def create_schedule(
        self,
        schedule: ReportSchedule,
    ) -> ReportSchedule:
        self.session.add(schedule)
        await self.session.flush()
        return schedule

    async def update_schedule(
        self,
        schedule_id: uuid.UUID,
        **fields: Any,
    ) -> ReportSchedule | None:
        schedule = await self.get_schedule(schedule_id)
        if schedule is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(schedule, key, value)
        await self.session.flush()
        return schedule

    # ── Alert Rule ─────────────────────────────────────────────────

    async def list_alerts(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[AlertRule]:
        stmt = select(AlertRule).order_by(AlertRule.name.asc())
        if enabled_only:
            stmt = stmt.where(AlertRule.enabled.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_alert(self, alert_id: uuid.UUID) -> AlertRule | None:
        return await self.session.get(AlertRule, alert_id)

    async def create_alert(self, alert: AlertRule) -> AlertRule:
        self.session.add(alert)
        await self.session.flush()
        return alert

    async def update_alert(
        self,
        alert_id: uuid.UUID,
        **fields: Any,
    ) -> AlertRule | None:
        alert = await self.get_alert(alert_id)
        if alert is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(alert, key, value)
        await self.session.flush()
        return alert

    async def delete_alert(self, alert_id: uuid.UUID) -> bool:
        alert = await self.get_alert(alert_id)
        if alert is None:
            return False
        await self.session.delete(alert)
        await self.session.flush()
        return True

    # ── Saved Filter ───────────────────────────────────────────────

    async def list_filters(
        self,
        *,
        owner_user_id: uuid.UUID | None = None,
        module: str | None = None,
    ) -> list[SavedFilter]:
        from sqlalchemy import or_

        stmt = select(SavedFilter).order_by(SavedFilter.name.asc())
        if owner_user_id is not None:
            stmt = stmt.where(
                or_(
                    SavedFilter.owner_user_id == owner_user_id,
                    SavedFilter.scope.in_(("global", "role")),
                ),
            )
        if module is not None:
            stmt = stmt.where(SavedFilter.module == module)
        return list((await self.session.execute(stmt)).scalars().all())

    async def create_filter(self, sf: SavedFilter) -> SavedFilter:
        self.session.add(sf)
        await self.session.flush()
        return sf

    async def get_filter(
        self,
        filter_id: uuid.UUID,
    ) -> SavedFilter | None:
        return await self.session.get(SavedFilter, filter_id)

    async def list_filters_shared_with(
        self,
        user_id: uuid.UUID,
        *,
        module: str | None = None,
    ) -> list[SavedFilter]:
        """Return filters whose ``shared_with_user_ids_json`` contains ``user_id``.

        SQL JSON-contains differs across SQLite + Postgres; we filter in
        Python after a coarse SQL query for portability. The result set
        is small (typically <100 personal filters per tenant) so this is
        cheap.
        """
        stmt = select(SavedFilter).order_by(SavedFilter.name.asc())
        if module is not None:
            stmt = stmt.where(SavedFilter.module == module)
        rows = list((await self.session.execute(stmt)).scalars().all())
        u = str(user_id)
        return [r for r in rows if u in (r.shared_with_user_ids_json or [])]

    # ── KPI Value (history) ────────────────────────────────────────

    async def list_kpi_values(
        self,
        kpi_code: str,
        *,
        project_id: uuid.UUID | None = None,
        limit: int = 12,
    ) -> list[KPIValue]:
        """Return the *most recent* ``limit`` KPI values, oldest → newest.

        The selection picks the newest ``limit`` rows (``period_start``
        descending, ``computed_at`` descending as a deterministic
        tie-breaker for same-day persists), then reverses them so callers
        — trend lists, sparklines, ``changed_by_more_than`` deltas —
        receive points in chronological order. Returning them newest-first
        previously flipped every trend chart and inverted the
        period-over-period delta in the UI.
        """
        stmt = select(KPIValue).where(KPIValue.kpi_code == kpi_code)
        if project_id is not None:
            stmt = stmt.where(KPIValue.project_id == project_id)
        stmt = stmt.order_by(
            KPIValue.period_start.desc(),
            KPIValue.computed_at.desc(),
        ).limit(limit)
        rows = list((await self.session.execute(stmt)).scalars().all())
        rows.reverse()
        return rows

    async def create_kpi_value(self, kv: KPIValue) -> KPIValue:
        self.session.add(kv)
        await self.session.flush()
        return kv


__all__ = ["BIDashboardsRepository"]
