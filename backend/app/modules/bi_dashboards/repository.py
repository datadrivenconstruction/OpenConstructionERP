# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Data-access layer for the BI Dashboards module."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Text, cast, delete, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.bi_dashboards.models import (
    AlertRule,
    BenchmarkSet,
    Dashboard,
    DashboardWidget,
    DashboardWidgetSnapshot,
    KPIDefinition,
    KPIValue,
    ReportDefinition,
    ReportSchedule,
    SavedFilter,
)


def project_scope_clause(column: Any, project_id: uuid.UUID) -> ColumnElement[bool]:
    """Build the "belongs to this project, or to no project" predicate.

    Every BI asset carries a nullable ``project_id`` whose NULL means
    company-wide. A project view therefore shows the project's own rows
    plus the company-wide ones - which is the honest answer and is also
    what keeps rows written before the column existed visible instead of
    orphaned.

    Args:
        column: The model's ``project_id`` column.
        project_id: The project the caller asked for.

    Returns:
        A SQLAlchemy boolean clause to ``AND`` onto an existing query.
        It is never built for a ``None`` project - a project-less call
        keeps the unfiltered, portfolio-wide result set.
    """
    return or_(column == project_id, column.is_(None))


#: Escape character for the ``LIKE`` prefilters below. A KPI code is
#: ``^[a-z][a-z0-9_]*$``, so it routinely contains ``_`` - which is a
#: single-character wildcard in ``LIKE`` and would widen the prefilter to
#: every code of the same length. Escaped, the prefilter stays selective.
_LIKE_ESCAPE = "/"


def _like_contains(needle: str) -> str:
    """Build a ``%needle%`` pattern with the LIKE metacharacters escaped."""
    for ch in (_LIKE_ESCAPE, "%", "_"):
        needle = needle.replace(ch, f"{_LIKE_ESCAPE}{ch}")
    return f"%{needle}%"


def _expression_names_kpi(node: Any, code: str) -> bool:
    """Whether a composite alert-rule tree reads the given KPI code.

    The alert DSL's ``{"op": "kpi", "code": ...}`` leaf may sit at any
    depth under ``and`` / ``or`` / ``not`` operands, so the whole tree is
    walked. The match is structural rather than textual on purpose: a
    ``field`` leaf that happens to *compare against* the string is not a
    reference to the KPI and must not block its deletion.

    Args:
        node: The parsed ``expression_json`` value.
        code: The KPI code being looked for.

    Returns:
        ``True`` when some node is a ``kpi`` leaf naming ``code``.
    """
    # Iterative rather than recursive: the column is user-supplied JSON and
    # the grammar puts no bound on nesting depth.
    stack: list[Any] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if current.get("op") == "kpi" and current.get("code") == code:
                return True
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return False


def _report_spec_names_kpi(spec: Any, code: str) -> bool:
    """Whether a report definition's query spec runs the given KPI code."""
    if not isinstance(spec, dict):
        return False
    return any(entry == code for entry in (spec.get("kpis") or []))


class BIDashboardsRepository:
    """Single repository per module - entity-typed methods stay grouped."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── KPI Definition ─────────────────────────────────────────────

    async def list_kpi_definitions(
        self,
        *,
        category: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> list[KPIDefinition]:
        """List KPI definitions, optionally narrowed to one project.

        Args:
            category: Restrict to a single KPI category.
            project_id: Restrict to the project's own definitions plus the
                company-wide ones. ``None`` lists every definition.

        Returns:
            KPI definitions ordered by code.
        """
        stmt = select(KPIDefinition).order_by(KPIDefinition.code.asc())
        if category is not None:
            stmt = stmt.where(KPIDefinition.category == category)
        if project_id is not None:
            stmt = stmt.where(project_scope_clause(KPIDefinition.project_id, project_id))
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

    async def create_custom_kpi_definition(self, **values: Any) -> KPIDefinition:
        """Insert one user-defined KPI definition.

        Distinct from :meth:`upsert_kpi_definition` on purpose. That one is
        the starter pack's tool and overwrites by code, which is right for
        rows the platform owns and would be data loss for rows a user
        wrote. This one only ever inserts; a duplicate code is the caller's
        problem to detect and report.
        """
        kd = KPIDefinition(**values)
        self.session.add(kd)
        await self.session.flush()
        return kd

    async def delete_kpi_definition(self, code: str) -> bool:
        """Delete one KPI definition by code. Returns whether a row went."""
        existing = await self.get_kpi_definition_by_code(code)
        if existing is None:
            return False
        await self.session.delete(existing)
        await self.session.flush()
        return True

    async def list_kpi_code_referrers(self, code: str) -> dict[str, list[uuid.UUID]]:
        """Everything that would be left pointing at nothing by a delete.

        ``kpi_code`` is a plain string on both widgets and alert rules -
        this module holds no foreign key to its own KPI table because a
        code may equally be served by a Python formula that has no row.
        So the referential answer has to be assembled here rather than
        delegated to the database.

        The population is every place a code reaches ``kpis.compute``
        having come out of a table, and there are four of them:

        * ``DashboardWidget.kpi_code`` and ``AlertRule.kpi_code``, plain
          columns answered by an equality predicate;
        * ``AlertRule.expression_json``, where the composite-rule grammar
          puts a ``{"op": "kpi", "code": ...}`` leaf at any depth;
        * ``ReportDefinition.query_spec_json["kpis"]``, the list of codes
          a report run computes into its output file.

        The last two are the ones a scalar predicate cannot see, and they
        are the expensive half of the honest answer: a report that keeps
        printing 0.0000 into a client-facing PDF is exactly the silent
        zero this guard exists to prevent.

        ``KPIValue.kpi_code`` is deliberately **not** a referrer. Those
        rows record what the KPI measured while it existed; they stay
        truthful after the definition goes, and counting them would make
        every KPI ever computed with ``persist=True`` undeletable.

        Both JSON columns are the generic ``JSON`` type - JSONB on
        PostgreSQL, TEXT on SQLite - so neither dialect's containment
        operator is portable here. They are narrowed in SQL by a ``LIKE``
        over the column cast to text, which both dialects do understand,
        and each hit is then confirmed in Python against the parsed
        structure. The prefilter may over-select (the quoted code can
        appear somewhere that is not a reference); it cannot under-select,
        because a referring row always contains the code verbatim. That
        keeps the guard a narrowed scan rather than a full table read.

        Args:
            code: The KPI code about to be deleted.

        Returns:
            Referrer ids by kind: ``widgets``, ``alerts``, ``reports``.
        """
        widgets = (
            (await self.session.execute(select(DashboardWidget.id).where(DashboardWidget.kpi_code == code)))
            .scalars()
            .all()
        )
        alerts = list(
            (await self.session.execute(select(AlertRule.id).where(AlertRule.kpi_code == code))).scalars().all(),
        )

        # The code as it is written inside the stored JSON, quotes included,
        # so ``bid_confidence`` cannot prefilter-match ``bid_confidence_v2``.
        pattern = _like_contains(json.dumps(code))

        seen = set(alerts)
        expression_rows = await self.session.execute(
            select(AlertRule.id, AlertRule.expression_json).where(
                cast(AlertRule.expression_json, Text).like(pattern, escape=_LIKE_ESCAPE),
            ),
        )
        for rule_id, expression in expression_rows:
            if rule_id not in seen and _expression_names_kpi(expression, code):
                alerts.append(rule_id)
                seen.add(rule_id)

        report_rows = await self.session.execute(
            select(ReportDefinition.id, ReportDefinition.query_spec_json).where(
                cast(ReportDefinition.query_spec_json, Text).like(pattern, escape=_LIKE_ESCAPE),
            ),
        )
        reports = [report_id for report_id, spec in report_rows if _report_spec_names_kpi(spec, code)]

        return {"widgets": list(widgets), "alerts": alerts, "reports": reports}

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
        *,
        project_id: uuid.UUID | None = None,
    ) -> list[Dashboard]:
        """Return dashboards a user can see: own + role/global ones.

        Args:
            owner_user_id: The caller. ``None`` sees only shared dashboards.
            project_id: When set, narrow the result to that project's own
                dashboards plus the company-wide ones. The visibility rule
                above is unchanged - the project clause is ANDed onto it,
                so a project view never widens who can see what.

        Returns:
            Visible dashboards ordered by scope then name.
        """
        stmt = select(Dashboard).order_by(
            Dashboard.scope.asc(),
            Dashboard.name.asc(),
        )
        if project_id is not None:
            stmt = stmt.where(project_scope_clause(Dashboard.project_id, project_id))

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

    async def get_latest_snapshots_for_widgets(
        self,
        widget_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, DashboardWidgetSnapshot]:
        """Batch-load the latest snapshot per widget in a single query.

        Avoids the N+1 of calling :meth:`get_latest_snapshot` once per
        widget when rendering a dashboard. Uses PostgreSQL ``DISTINCT ON``
        to pick the most-recent (``computed_at`` desc, ``id`` desc as a
        deterministic same-instant tie-breaker) row per ``widget_id``.
        Returns ``{}`` for an empty ``widget_ids`` (no SQL issued).
        """
        if not widget_ids:
            return {}
        stmt = (
            select(DashboardWidgetSnapshot)
            .where(DashboardWidgetSnapshot.widget_id.in_(widget_ids))
            .distinct(DashboardWidgetSnapshot.widget_id)
            .order_by(
                DashboardWidgetSnapshot.widget_id.asc(),
                DashboardWidgetSnapshot.computed_at.desc(),
                DashboardWidgetSnapshot.id.desc(),
            )
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return {row.widget_id: row for row in rows}

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
        project_id: uuid.UUID | None = None,
    ) -> list[ReportDefinition]:
        """List report definitions visible to a caller.

        Args:
            owner_user_id: The caller. ``None`` skips the ownership filter.
            project_id: When set, narrow to that project's own reports plus
                the company-wide ones, ANDed onto the ownership rule.

        Returns:
            Visible report definitions ordered by code.
        """
        stmt = select(ReportDefinition).order_by(ReportDefinition.code.asc())
        if owner_user_id is not None:
            stmt = stmt.where(
                or_(
                    ReportDefinition.owner_user_id == owner_user_id,
                    ReportDefinition.scope.in_(("global", "role")),
                ),
            )
        if project_id is not None:
            stmt = stmt.where(project_scope_clause(ReportDefinition.project_id, project_id))
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

    async def list_schedules_for_reports(
        self,
        report_ids: list[uuid.UUID],
        *,
        project_id: uuid.UUID | None = None,
    ) -> list[ReportSchedule]:
        """Return every schedule (enabled or not) for the given reports.

        Unlike :meth:`list_schedules` - which is the scheduler's
        due-soon picker and is restricted to ``enabled`` rows - this
        returns the full set so the UI can show paused schedules too.
        Returns an empty list for an empty ``report_ids`` (no SQL issued).

        Args:
            report_ids: Parent reports the caller may already see. Callers
                narrow this set by project before calling, so a schedule
                can never outlive its report's own project scope.
            project_id: When set, additionally narrow to the schedules that
                name that project or name none. Both filters apply: a
                schedule pinned to a project the caller did not ask for is
                dropped even when its report is company-wide.

        Returns:
            Schedules ordered by next run, undated ones last.
        """
        if not report_ids:
            return []
        stmt = select(ReportSchedule).where(ReportSchedule.report_definition_id.in_(report_ids))
        if project_id is not None:
            stmt = stmt.where(project_scope_clause(ReportSchedule.project_id, project_id))
        stmt = stmt.order_by(ReportSchedule.next_run_at.asc().nullslast())
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
        project_id: uuid.UUID | None = None,
    ) -> list[SavedFilter]:
        """List saved filters visible to a caller.

        Args:
            owner_user_id: The caller. ``None`` skips the ownership filter.
            module: Restrict to filters saved for one UI module.
            project_id: When set, narrow to that project's own filters plus
                the company-wide ones, ANDed onto the ownership rule.

        Returns:
            Visible saved filters ordered by name.
        """
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
        if project_id is not None:
            stmt = stmt.where(project_scope_clause(SavedFilter.project_id, project_id))
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
        project_id: uuid.UUID | None = None,
    ) -> list[SavedFilter]:
        """Return filters whose ``shared_with_user_ids_json`` contains ``user_id``.

        SQL JSON-contains differs across SQLite + Postgres; we filter in
        Python after a coarse SQL query for portability. The result set
        is small (typically <100 personal filters per tenant) so this is
        cheap.

        Args:
            user_id: The caller the filter was shared with.
            module: Restrict to filters saved for one UI module.
            project_id: When set, narrow to that project's own filters plus
                the company-wide ones. Shared filters obey the project view
                too, otherwise a share would reintroduce the rows the
                project route just excluded.

        Returns:
            Shared saved filters ordered by name.
        """
        stmt = select(SavedFilter).order_by(SavedFilter.name.asc())
        if module is not None:
            stmt = stmt.where(SavedFilter.module == module)
        if project_id is not None:
            stmt = stmt.where(project_scope_clause(SavedFilter.project_id, project_id))
        rows = list((await self.session.execute(stmt)).scalars().all())
        u = str(user_id)
        return [r for r in rows if u in (r.shared_with_user_ids_json or [])]

    # ── KPI Value (history) ────────────────────────────────────────

    async def list_kpi_values(
        self,
        kpi_code: str,
        *,
        project_id: uuid.UUID | None = None,
        boq_id: uuid.UUID | None = None,
        limit: int = 12,
        allowed_project_ids: set[uuid.UUID] | None = None,
    ) -> list[KPIValue]:
        """Return the *most recent* ``limit`` KPI values, oldest → newest.

        The selection picks the newest ``limit`` rows (``period_start``
        descending, ``computed_at`` descending as a deterministic
        tie-breaker for same-day persists), then reverses them so callers
        - trend lists, sparklines, ``changed_by_more_than`` deltas -
        receive points in chronological order. Returning them newest-first
        previously flipped every trend chart and inverted the
        period-over-period delta in the UI.

        ``allowed_project_ids`` is the portfolio IDOR guard for a call that
        did NOT pin a single ``project_id``: ``None`` returns every
        project's persisted snapshots (admin / unrestricted), a set
        restricts to those projects' rows (portfolio-aggregate rows stored
        with ``project_id IS NULL`` are excluded, since they are an
        all-project figure), and an empty set returns nothing - never all.
        Ignored when ``project_id`` is supplied (that row set is already
        access-checked upstream).

        ``boq_id`` picks the estimate dimension, and its default is a
        predicate rather than the absence of one: ``None`` means
        ``boq_id IS NULL``, the project-level reading, which is what every
        row written before that column existed is and what every caller
        here means. Left unfiltered instead, a project's trend line would
        start absorbing per-estimate points the day somebody persisted the
        first estimate-scoped KPI - nine values a period where there was
        one, and the sparkline would keep drawing without complaint.
        """
        stmt = select(KPIValue).where(KPIValue.kpi_code == kpi_code)
        stmt = stmt.where(KPIValue.boq_id == boq_id if boq_id is not None else KPIValue.boq_id.is_(None))
        if project_id is not None:
            stmt = stmt.where(KPIValue.project_id == project_id)
        elif allowed_project_ids is not None:
            stmt = (
                stmt.where(false())
                if not allowed_project_ids
                else stmt.where(KPIValue.project_id.in_(allowed_project_ids))
            )
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

    # ── Benchmark sets ──────────────────────────────────────────────

    async def list_benchmark_sets(self, *, viewer_user_id: uuid.UUID | None) -> list[BenchmarkSet]:
        """The benchmark sets a viewer sees: their own and every shared one, by name."""
        stmt = select(BenchmarkSet).order_by(BenchmarkSet.name.asc(), BenchmarkSet.created_at.asc())
        visible = BenchmarkSet.scope == "shared"
        if viewer_user_id is not None:
            visible = or_(visible, BenchmarkSet.owner_user_id == viewer_user_id)
        return list((await self.session.execute(stmt.where(visible))).scalars().all())

    async def get_benchmark_set(self, set_id: uuid.UUID) -> BenchmarkSet | None:
        return await self.session.get(BenchmarkSet, set_id)

    async def create_benchmark_set(self, row: BenchmarkSet) -> BenchmarkSet:
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete_benchmark_set(self, row: BenchmarkSet) -> None:
        await self.session.delete(row)
        await self.session.flush()


__all__ = ["BIDashboardsRepository", "project_scope_clause"]
