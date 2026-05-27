# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Service layer for the BI Dashboards module.

All cross-module reads route through :mod:`.kpis` so the service itself
never imports another module's models directly. This keeps the
read-only contract enforceable.
"""

from __future__ import annotations

import calendar
import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from datetime import date as _date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.bi_dashboards import kpis as _kpis
from app.modules.bi_dashboards.alert_dsl import evaluate_alert_expression
from app.modules.bi_dashboards.models import (
    AlertRule,
    Dashboard,
    DashboardWidget,
    KPIValue,
    ReportDefinition,
    ReportRun,
    ReportSchedule,
    SavedFilter,
)
from app.modules.bi_dashboards.report_builder import (
    build_report,
    export_widget_csv,
    export_widget_svg,
)
from app.modules.bi_dashboards.repository import BIDashboardsRepository
from app.modules.bi_dashboards.schemas import (
    AlertRuleCreate,
    DashboardCreate,
    DashboardEvaluateResponse,
    DashboardRenderResponse,
    DashboardUpdate,
    KPIComputeResponse,
    KPIHistoryPoint,
    ReportDefinitionCreate,
    ReportDefinitionUpdate,
    ReportRunResponse,
    ReportScheduleCreate,
    ReportScheduleUpdate,
    SavedFilterCreate,
    WidgetCreate,
    WidgetEvaluateResult,
    WidgetRead,
    WidgetRenderResult,
    WidgetUpdate,
)

logger = logging.getLogger(__name__)


def _safe_publish(name: str, data: dict[str, Any]) -> None:
    """‌⁠‍Fire-and-forget event publish that never crashes the caller."""
    try:
        event_bus.publish_detached(name, data, source_module="oe_bi_dashboards")
    except Exception:
        logger.debug("bi_dashboards: event publish failed: %s", name)


def _now() -> datetime:
    return datetime.now(UTC)


# ── Scheduling helpers ─────────────────────────────────────────────────


def compute_next_run_at(
    *,
    frequency: str,
    time_of_day: str,
    day_of_week: int | None,
    day_of_month: int | None,
    base: datetime | None = None,
) -> datetime:
    """‌⁠‍Return the next UTC datetime a schedule should fire.

    Pure function — testable without a DB. ``time_of_day`` is ``HH:MM``
    in UTC for simplicity (real impl would honour ``timezone``).
    """
    now = base or _now()
    try:
        hh, mm = (int(p) for p in time_of_day.split(":"))
    except Exception:
        hh, mm = 8, 0
    target_time = time(hour=hh, minute=mm, tzinfo=UTC)

    candidate = datetime.combine(now.date(), target_time)
    if frequency == "daily":
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return candidate

    if frequency == "weekly":
        dow = day_of_week if day_of_week is not None else 0
        delta_days = (dow - now.weekday()) % 7
        candidate = datetime.combine(
            now.date() + timedelta(days=delta_days),
            target_time,
        )
        if candidate <= now:
            candidate = candidate + timedelta(days=7)
        return candidate

    if frequency == "monthly":
        dom = day_of_month if day_of_month is not None else 1
        year, month = now.year, now.month
        last_day = calendar.monthrange(year, month)[1]
        target_day = min(dom, last_day)
        candidate = datetime.combine(
            _date(year, month, target_day),
            target_time,
        )
        if candidate <= now:
            # Roll over to next month
            if month == 12:
                year, month = year + 1, 1
            else:
                month += 1
            last_day = calendar.monthrange(year, month)[1]
            target_day = min(dom, last_day)
            candidate = datetime.combine(
                _date(year, month, target_day),
                target_time,
            )
        return candidate

    if frequency == "quarterly":
        # Next quarter-month boundary: months 1, 4, 7, 10
        quarter_months = (1, 4, 7, 10)
        year, month = now.year, now.month
        # Find next quarter boundary >= today
        next_q = next((m for m in quarter_months if m > month), None)
        if next_q is None:
            year += 1
            next_q = 1
        target_day = min(day_of_month or 1, calendar.monthrange(year, next_q)[1])
        return datetime.combine(
            _date(year, next_q, target_day),
            target_time,
        )

    # Unknown frequency — fall back to 1 day out
    return now + timedelta(days=1)


# ── Service ────────────────────────────────────────────────────────────


class BIDashboardsService:
    """Business logic for the BI Dashboards module."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = BIDashboardsRepository(session)

    # ── KPI Registry ───────────────────────────────────────────────

    async def bootstrap_system_kpis(self) -> int:
        """Upsert one ``KPIDefinition`` row per registered system KPI.

        Idempotent — safe to call on every boot. Returns the number of
        KPI rows touched.
        """
        meta_list = _kpis.list_system_kpis()
        for meta in meta_list:
            await self.repo.upsert_kpi_definition(**meta)
        await self.session.flush()
        return len(meta_list)

    async def list_kpi_definitions(
        self,
        *,
        category: str | None = None,
    ) -> list[Any]:
        return await self.repo.list_kpi_definitions(category=category)

    async def compute_kpi(
        self,
        code: str,
        *,
        project_id: uuid.UUID | None = None,
        period_start: _date | None = None,
        period_end: _date | None = None,
        filters: dict[str, Any] | None = None,
        persist: bool = False,
        include_trend: bool = True,
        include_benchmark: bool = True,
    ) -> KPIComputeResponse:
        """Compute a KPI on-demand.

        Optionally:
            * ``persist``: writes to :class:`KPIValue` for trend history
            * ``include_benchmark``: also returns portfolio median + percentile
        """
        result = await _kpis.compute(
            code,
            self.session,
            project_id=project_id,
            period_start=period_start,
            period_end=period_end,
            filters=filters,
        )
        now = _now()
        if persist and result.source_record_count > 0:
            kv = KPIValue(
                kpi_code=code,
                project_id=project_id,
                period_start=period_start or now.date(),
                period_end=period_end or now.date(),
                value=result.value,
                unit=result.unit,
                computed_at=now,
                source_record_count=result.source_record_count,
            )
            await self.repo.create_kpi_value(kv)
            _safe_publish(
                "bi.kpi.snapshot_written",
                {
                    "kpi_code": code,
                    "value": str(result.value),
                    "unit": result.unit,
                    "project_id": str(project_id) if project_id else None,
                },
            )

        trend: list[dict[str, Any]] = []
        if include_trend:
            history = await self.repo.list_kpi_values(
                code,
                project_id=project_id,
                limit=12,
            )
            trend = [
                {
                    "period_start": h.period_start.isoformat(),
                    "period_end": h.period_end.isoformat(),
                    "value": str(h.value),
                }
                for h in history
            ]

        benchmark_data: dict[str, Any] = {}
        if include_benchmark and project_id is not None:
            try:
                benchmark_data = await _kpis.benchmark(
                    code,
                    self.session,
                    project_id=project_id,
                )
            except Exception:
                logger.debug("compute_kpi: benchmark failed", exc_info=True)
                benchmark_data = {}

        return KPIComputeResponse(
            kpi_code=code,
            value=result.value,
            unit=result.unit,
            source_record_count=result.source_record_count,
            computed_at=now,
            breakdown=result.breakdown,
            trend=trend,
            benchmark=benchmark_data,
        )

    async def kpi_history(
        self,
        code: str,
        *,
        project_id: uuid.UUID | None = None,
        limit: int = 12,
    ) -> list[KPIHistoryPoint]:
        rows = await self.repo.list_kpi_values(
            code,
            project_id=project_id,
            limit=limit,
        )
        return [
            KPIHistoryPoint(
                period_start=r.period_start,
                period_end=r.period_end,
                value=r.value,
                unit=r.unit,
                source_record_count=r.source_record_count,
            )
            for r in rows
        ]

    # ── Dashboards ────────────────────────────────────────────────

    async def create_dashboard(
        self,
        payload: DashboardCreate,
        *,
        owner_user_id: uuid.UUID | None,
    ) -> Dashboard:
        dashboard = Dashboard(
            name=payload.name,
            description=payload.description,
            owner_user_id=owner_user_id,
            scope=payload.scope,
            role_ref=payload.role_ref,
            project_id=payload.project_id,
            layout_json=payload.layout_json,
            is_default=payload.is_default,
            refresh_interval_seconds=payload.refresh_interval_seconds,
            cross_filter_enabled=payload.cross_filter_enabled,
        )
        return await self.repo.create_dashboard(dashboard)

    async def update_dashboard(
        self,
        dashboard_id: uuid.UUID,
        payload: DashboardUpdate,
    ) -> Dashboard | None:
        return await self.repo.update_dashboard(
            dashboard_id,
            **payload.model_dump(exclude_unset=True),
        )

    async def delete_dashboard(self, dashboard_id: uuid.UUID) -> bool:
        return await self.repo.delete_dashboard(dashboard_id)

    async def list_dashboards(
        self,
        *,
        owner_user_id: uuid.UUID | None,
    ) -> list[Dashboard]:
        return await self.repo.list_dashboards_visible_to(owner_user_id)

    async def get_dashboard(
        self,
        dashboard_id: uuid.UUID,
    ) -> Dashboard | None:
        return await self.repo.get_dashboard(dashboard_id)

    # ── Widgets ───────────────────────────────────────────────────

    async def create_widget(
        self,
        payload: WidgetCreate,
    ) -> DashboardWidget | None:
        # Guard: dashboard must exist
        dashboard = await self.repo.get_dashboard(payload.dashboard_id)
        if dashboard is None:
            return None
        widget = DashboardWidget(
            dashboard_id=payload.dashboard_id,
            widget_type=payload.widget_type,
            kpi_code=payload.kpi_code,
            config_json=payload.config_json,
            position_x=payload.position_x,
            position_y=payload.position_y,
            width=payload.width,
            height=payload.height,
            order_seq=payload.order_seq,
            drill_path=payload.drill_path,
        )
        return await self.repo.create_widget(widget)

    async def update_widget(
        self,
        widget_id: uuid.UUID,
        payload: WidgetUpdate,
    ) -> DashboardWidget | None:
        return await self.repo.update_widget(
            widget_id,
            **payload.model_dump(exclude_unset=True),
        )

    async def delete_widget(self, widget_id: uuid.UUID) -> bool:
        return await self.repo.delete_widget(widget_id)

    async def update_widget_snapshot(
        self,
        widget_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        """Recompute the widget's KPI and write a fresh snapshot."""
        widget = await self.repo.get_widget(widget_id)
        if widget is None:
            return None
        if not widget.kpi_code:
            return None
        result = await _kpis.compute(
            widget.kpi_code,
            self.session,
            project_id=widget.config_json.get("project_id") if isinstance(widget.config_json, dict) else None,
        )
        now = _now()
        dashboard = await self.repo.get_dashboard(widget.dashboard_id)
        valid_until = now + timedelta(
            seconds=dashboard.refresh_interval_seconds if dashboard else 300,
        )
        payload = {
            "value": str(result.value),
            "unit": result.unit,
            "breakdown": result.breakdown,
            "source_record_count": result.source_record_count,
        }
        snap = await self.repo.write_snapshot(
            widget_id=widget_id,
            value_json=payload,
            computed_at=now,
            valid_until=valid_until,
        )
        return {
            "snapshot_id": str(snap.id),
            "computed_at": now.isoformat(),
            "valid_until": valid_until.isoformat(),
            **payload,
        }

    async def render_dashboard(
        self,
        dashboard_id: uuid.UUID,
    ) -> DashboardRenderResponse | None:
        dashboard = await self.repo.get_dashboard(dashboard_id)
        if dashboard is None:
            return None
        widgets = await self.repo.list_widgets(dashboard_id)
        results: list[WidgetRenderResult] = []
        now = _now()
        for widget in widgets:
            widget_read = WidgetRead.model_validate(widget)
            value: Decimal | None = None
            unit: str | None = None
            breakdown: dict[str, Any] = {}
            from_cache = False

            # Try cached snapshot first. SQLite returns naive datetimes —
            # assume UTC so the comparison against ``now`` (always tz-aware)
            # doesn't TypeError.
            snap = await self.repo.get_latest_snapshot(widget.id)
            snap_valid_until = (
                snap.valid_until.replace(tzinfo=UTC)
                if snap is not None and snap.valid_until is not None and snap.valid_until.tzinfo is None
                else (snap.valid_until if snap is not None else None)
            )
            if (
                snap is not None
                and snap_valid_until is not None
                and snap_valid_until > now
                and widget.kpi_code is not None
            ):
                payload = snap.value_json or {}
                try:
                    value = Decimal(str(payload.get("value", "0")))
                except Exception:
                    value = Decimal("0")
                unit = payload.get("unit")
                breakdown = payload.get("breakdown", {}) or {}
                from_cache = True
            elif widget.kpi_code is not None:
                # Compute live + write snapshot
                result = await _kpis.compute(
                    widget.kpi_code,
                    self.session,
                )
                value = result.value
                unit = result.unit
                breakdown = result.breakdown
                valid_until = now + timedelta(
                    seconds=dashboard.refresh_interval_seconds,
                )
                await self.repo.write_snapshot(
                    widget_id=widget.id,
                    value_json={
                        "value": str(result.value),
                        "unit": result.unit,
                        "breakdown": result.breakdown,
                        "source_record_count": result.source_record_count,
                    },
                    computed_at=now,
                    valid_until=valid_until,
                )

            results.append(
                WidgetRenderResult(
                    widget=widget_read,
                    value=value,
                    unit=unit,
                    breakdown=breakdown,
                    from_cache=from_cache,
                ),
            )

        _safe_publish(
            "bi.dashboard.viewed",
            {
                "dashboard_id": str(dashboard.id),
                "widget_count": len(results),
            },
        )
        from app.modules.bi_dashboards.schemas import DashboardRead

        return DashboardRenderResponse(
            dashboard=DashboardRead.model_validate(dashboard),
            widgets=results,
            rendered_at=now,
        )

    # ── Cross-filter evaluate (Wave 4 / T11) ──────────────────────

    async def evaluate_dashboard(
        self,
        dashboard_id: uuid.UUID,
        *,
        filters: dict[str, Any] | None = None,
    ) -> DashboardEvaluateResponse | None:
        """Evaluate every widget on a dashboard, optionally cross-filtered.

        When ``cross_filter_enabled`` is False on the dashboard the
        ``filters`` argument is ignored — every widget returns its
        unfiltered headline KPI value, matching :meth:`render_dashboard`'s
        existing static contract.

        When ``cross_filter_enabled`` is True the filter dict is
        propagated to each widget's KPI call. ``project_id`` and
        ``period_start`` / ``period_end`` are first-class — anything else
        is forwarded as ``filters=`` to the KPI formula (each KPI ignores
        keys it doesn't recognise, so unknown keys degrade gracefully).
        """
        dashboard = await self.repo.get_dashboard(dashboard_id)
        if dashboard is None:
            return None
        widgets = await self.repo.list_widgets(dashboard_id)
        cross_filter = bool(getattr(dashboard, "cross_filter_enabled", False))
        # Snapshot the inputs honestly: the response only echoes filters
        # we actually applied so the UI doesn't show a chip the backend
        # silently ignored.
        applied: dict[str, Any] = dict(filters or {}) if cross_filter and filters else {}

        # Pull project_id / period bounds out as first-class kwargs to
        # ``_kpis.compute`` so they hit the KPI's typed signature rather
        # than the catch-all ``filters`` bag.
        project_id_val: uuid.UUID | None = None
        period_start_val: _date | None = None
        period_end_val: _date | None = None
        kpi_filters: dict[str, Any] = {}
        if applied:
            for key, value in applied.items():
                if key == "project_id" and value:
                    try:
                        project_id_val = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
                    except Exception:
                        # Unparseable project_id is treated like any other
                        # unknown key — silently dropped, not 500'd.
                        pass
                elif key == "period_start" and value:
                    try:
                        period_start_val = value if isinstance(value, _date) else _date.fromisoformat(str(value))
                    except Exception:
                        pass
                elif key == "period_end" and value:
                    try:
                        period_end_val = value if isinstance(value, _date) else _date.fromisoformat(str(value))
                    except Exception:
                        pass
                else:
                    kpi_filters[key] = value

        now = _now()
        results: list[WidgetEvaluateResult] = []
        for widget in widgets:
            value: Decimal | None = None
            unit: str | None = None
            breakdown: dict[str, Any] = {}
            if widget.kpi_code is not None:
                # When cross-filter is OFF we deliberately call compute
                # with NO project/period/filter args. That mirrors the
                # static render path byte-for-byte — important for the
                # forward-compat contract: dashboards that haven't opted
                # in must keep returning today's values.
                if cross_filter:
                    # Fall back to widget.config_json["project_id"] when the
                    # caller didn't supply one — preserves the per-widget
                    # default project binding used by render_dashboard.
                    effective_project = project_id_val
                    if effective_project is None and isinstance(
                        widget.config_json,
                        dict,
                    ):
                        cfg_pid = widget.config_json.get("project_id")
                        if cfg_pid:
                            try:
                                effective_project = (
                                    cfg_pid if isinstance(cfg_pid, uuid.UUID) else uuid.UUID(str(cfg_pid))
                                )
                            except Exception:
                                effective_project = None
                    computation = await _kpis.compute(
                        widget.kpi_code,
                        self.session,
                        project_id=effective_project,
                        period_start=period_start_val,
                        period_end=period_end_val,
                        filters=kpi_filters or None,
                    )
                else:
                    computation = await _kpis.compute(
                        widget.kpi_code,
                        self.session,
                    )
                value = computation.value
                unit = computation.unit
                breakdown = computation.breakdown or {}

            # Optional ``series`` for line/bar charts — pulled from the
            # KPI history (cheapest source of a time-axis). For non-
            # chart widgets we omit it to keep the payload light.
            series: list[dict[str, Any]] = []
            if widget.kpi_code is not None and widget.widget_type in ("line_chart", "bar_chart"):
                history = await self.repo.list_kpi_values(
                    widget.kpi_code,
                    project_id=project_id_val,
                    limit=12,
                )
                series = [
                    {
                        "period_start": h.period_start.isoformat(),
                        "period_end": h.period_end.isoformat(),
                        "value": str(h.value),
                    }
                    for h in history
                ]

            results.append(
                WidgetEvaluateResult(
                    id=widget.id,
                    kpi_code=widget.kpi_code,
                    widget_type=widget.widget_type,
                    value=value,
                    unit=unit,
                    series=series,
                    drill_path=widget.drill_path,
                    breakdown=breakdown,
                ),
            )

        _safe_publish(
            "bi.dashboard.evaluated",
            {
                "dashboard_id": str(dashboard.id),
                "cross_filter_enabled": cross_filter,
                "applied_filter_keys": list(applied.keys()),
            },
        )

        return DashboardEvaluateResponse(
            dashboard_id=dashboard.id,
            cross_filter_enabled=cross_filter,
            applied_filters=applied,
            widgets=results,
            evaluated_at=now,
        )

    # ── Reports ───────────────────────────────────────────────────

    async def create_report(
        self,
        payload: ReportDefinitionCreate,
        *,
        owner_user_id: uuid.UUID | None,
    ) -> ReportDefinition:
        # ``ReportDefinition.code`` is globally UNIQUE. A blind insert on a
        # duplicate code raised an unhandled IntegrityError → 500. Detect
        # the collision up front and return a clean 409 (mirrors how the
        # contacts module reports a unique-key conflict, including the
        # existing id so callers can re-run idempotently).
        existing = await self.repo.get_report_by_code(payload.code)
        if existing is not None:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=409,
                detail=(f"A report definition with code '{payload.code}' already exists (id={existing.id})."),
            )
        report = ReportDefinition(
            code=payload.code,
            name=payload.name,
            description=payload.description,
            owner_user_id=owner_user_id,
            source_modules=payload.source_modules,
            query_spec_json=payload.query_spec_json,
            output_format=payload.output_format,
            template_ref=payload.template_ref,
            scope=payload.scope,
        )
        return await self.repo.create_report(report)

    async def update_report(
        self,
        report_id: uuid.UUID,
        payload: ReportDefinitionUpdate,
    ) -> ReportDefinition | None:
        return await self.repo.update_report(
            report_id,
            **payload.model_dump(exclude_unset=True),
        )

    async def delete_report(self, report_id: uuid.UUID) -> bool:
        return await self.repo.delete_report(report_id)

    async def list_reports(
        self,
        *,
        owner_user_id: uuid.UUID | None,
    ) -> list[ReportDefinition]:
        return await self.repo.list_reports(owner_user_id=owner_user_id)

    async def run_report(
        self,
        report_id: uuid.UUID,
        *,
        schedule_id: uuid.UUID | None = None,
        triggered_by_user_id: uuid.UUID | None = None,
        produce_file: bool = True,
    ) -> ReportRunResponse | None:
        """Run a report definition synchronously, render a file, return URL.

        Persists a :class:`ReportRun` audit row with the file path so
        downloads remain available across requests. ``file_url`` is the
        public-facing path under ``/api/v1/bi-dashboards/report-runs/{id}/file``.
        """
        report = await self.repo.get_report(report_id)
        if report is None:
            return None
        spec = report.query_spec_json or {}
        rows: list[dict[str, Any]] = []
        kpis_to_run: list[str] = list(spec.get("kpis") or [])
        project_id_raw = spec.get("project_id")
        try:
            project_id = uuid.UUID(project_id_raw) if project_id_raw else None
        except Exception:
            project_id = None

        started_at = _now()
        run = ReportRun(
            report_definition_id=report.id,
            schedule_id=schedule_id,
            triggered_by_user_id=triggered_by_user_id,
            started_at=started_at,
            output_format=report.output_format,
            status="running",
        )
        self.session.add(run)
        await self.session.flush()

        try:
            for code in kpis_to_run:
                result = await _kpis.compute(
                    code,
                    self.session,
                    project_id=project_id,
                )
                rows.append(
                    {
                        "kpi_code": code,
                        "value": str(result.value),
                        "unit": result.unit,
                        "source_record_count": result.source_record_count,
                        **{f"breakdown__{k}": v for k, v in result.breakdown.items()},
                    },
                )

            # Drill-down rows section: if spec asks for it, append per-KPI
            # detail records below the headline aggregates.
            if spec.get("include_drill_down") and project_id is not None:
                for code in kpis_to_run:
                    detail = await _kpis.drilldown(
                        code,
                        self.session,
                        project_id=project_id,
                        limit=int(spec.get("drill_down_limit") or 25),
                    )
                    for d in detail:
                        rows.append({"_section": f"drill_{code}", **d})

            file_path: str | None = None
            file_size = 0
            if produce_file:
                file_path, file_size = build_report(
                    output_format=report.output_format,
                    report_name=report.code or report.name,
                    rows=rows,
                    description=report.description,
                )

            finished_at = _now()
            run.finished_at = finished_at
            run.status = "success"
            run.row_count = len(rows)
            run.file_path = file_path
            run.file_size_bytes = file_size
            await self.session.flush()

            file_url = f"/api/v1/bi-dashboards/report-runs/{run.id}/file" if file_path else None

            response = ReportRunResponse(
                report_id=report.id,
                file_url=file_url,
                rows=rows,
                row_count=len(rows),
                output_format=report.output_format,
                generated_at=finished_at,
            )
            _safe_publish(
                "bi.report.generated",
                {
                    "report_id": str(report.id),
                    "report_code": report.code,
                    "report_run_id": str(run.id),
                    "row_count": len(rows),
                    "file_url": file_url,
                    "recipients": [],
                },
            )
            return response
        except Exception as exc:
            logger.exception(
                "run_report: failed for %s",
                report_id,
            )
            run.status = "failed"
            run.finished_at = _now()
            run.error_message = str(exc)[:1000]
            await self.session.flush()
            raise

    async def get_report_run(
        self,
        run_id: uuid.UUID,
    ) -> ReportRun | None:
        return await self.session.get(ReportRun, run_id)

    # ── Schedules ─────────────────────────────────────────────────

    async def create_schedule(
        self,
        payload: ReportScheduleCreate,
    ) -> ReportSchedule | None:
        report = await self.repo.get_report(payload.report_definition_id)
        if report is None:
            return None
        next_run = compute_next_run_at(
            frequency=payload.frequency,
            time_of_day=payload.time_of_day,
            day_of_week=payload.day_of_week,
            day_of_month=payload.day_of_month,
        )
        schedule = ReportSchedule(
            report_definition_id=payload.report_definition_id,
            frequency=payload.frequency,
            day_of_week=payload.day_of_week,
            day_of_month=payload.day_of_month,
            time_of_day=payload.time_of_day,
            timezone=payload.timezone,
            recipients_json=payload.recipients_json,
            enabled=payload.enabled,
            next_run_at=next_run,
            filter_overrides_json=payload.filter_overrides_json,
        )
        return await self.repo.create_schedule(schedule)

    async def update_schedule(
        self,
        schedule_id: uuid.UUID,
        payload: ReportScheduleUpdate,
    ) -> ReportSchedule | None:
        existing = await self.repo.get_schedule(schedule_id)
        if existing is None:
            return None
        updates = payload.model_dump(exclude_unset=True)
        # Re-compute next_run_at if scheduling fields changed
        if any(k in updates for k in ("frequency", "time_of_day", "day_of_week", "day_of_month")):
            updates["next_run_at"] = compute_next_run_at(
                frequency=updates.get("frequency", existing.frequency),
                time_of_day=updates.get("time_of_day", existing.time_of_day),
                day_of_week=updates.get("day_of_week", existing.day_of_week),
                day_of_month=updates.get("day_of_month", existing.day_of_month),
            )
        return await self.repo.update_schedule(schedule_id, **updates)

    async def run_scheduled_report(
        self,
        schedule_id: uuid.UUID,
    ) -> ReportRunResponse | None:
        schedule = await self.repo.get_schedule(schedule_id)
        if schedule is None:
            return None
        response = await self.run_report(schedule.report_definition_id)
        now = _now()
        next_run = compute_next_run_at(
            frequency=schedule.frequency,
            time_of_day=schedule.time_of_day,
            day_of_week=schedule.day_of_week,
            day_of_month=schedule.day_of_month,
            base=now,
        )
        await self.repo.update_schedule(
            schedule_id,
            last_run_at=now,
            next_run_at=next_run,
        )
        if response is not None:
            _safe_publish(
                "bi.report.generated",
                {
                    "report_id": str(schedule.report_definition_id),
                    "schedule_id": str(schedule_id),
                    "row_count": response.row_count,
                    "recipients": schedule.recipients_json or [],
                    "file_url": response.file_url,
                },
            )
        return response

    async def enqueue_scheduled_reports(self) -> list[uuid.UUID]:
        """Find all schedules whose ``next_run_at`` is in the past and run
        them, returning the list of schedule IDs that fired.
        """
        now = _now()
        due = await self.repo.list_schedules(due_before=now)
        fired: list[uuid.UUID] = []
        for schedule in due:
            try:
                await self.run_scheduled_report(schedule.id)
                fired.append(schedule.id)
            except Exception:
                logger.exception(
                    "enqueue_scheduled_reports: schedule %s failed",
                    schedule.id,
                )
        return fired

    # ── Alerts ────────────────────────────────────────────────────

    async def create_alert(self, payload: AlertRuleCreate) -> AlertRule:
        alert = AlertRule(
            name=payload.name,
            kpi_code=payload.kpi_code,
            condition=payload.condition,
            threshold_value=payload.threshold_value,
            threshold_unit=payload.threshold_unit,
            severity=payload.severity,
            scope_project_id=payload.scope_project_id,
            recipients_json=payload.recipients_json,
            channels_json=payload.channels_json,
            throttle_seconds=payload.throttle_seconds,
            enabled=payload.enabled,
            expression_json=payload.expression_json,
        )
        return await self.repo.create_alert(alert)

    async def toggle_alert(
        self,
        alert_id: uuid.UUID,
        *,
        enabled: bool,
    ) -> AlertRule | None:
        return await self.repo.update_alert(alert_id, enabled=enabled)

    async def evaluate_alert(
        self,
        alert: AlertRule,
    ) -> bool:
        """Evaluate one alert rule. Return True if it fired this cycle.

        If ``alert.expression_json`` is non-empty, it's evaluated as a
        composite DSL expression (see :mod:`.alert_dsl`). Otherwise the
        legacy single-KPI + threshold path is used.
        """
        now = _now()
        # Throttle check — SQLite can return tz-naive datetimes; normalise
        last_triggered = alert.last_triggered_at
        if last_triggered is not None and last_triggered.tzinfo is None:
            last_triggered = last_triggered.replace(tzinfo=UTC)
        if (
            last_triggered is not None
            and alert.throttle_seconds > 0
            and (now - last_triggered).total_seconds() < alert.throttle_seconds
        ):
            return False

        expression = alert.expression_json or {}
        trace: dict[str, Any] = {}
        triggered = False
        evaluated_value: Decimal | None = None
        evaluated_unit = ""
        cond = alert.condition

        if expression:
            try:
                triggered, trace = await evaluate_alert_expression(
                    expression,
                    self.session,
                    project_id=alert.scope_project_id,
                )
            except Exception:
                logger.exception(
                    "evaluate_alert: DSL evaluation failed for %s",
                    alert.id,
                )
                return False
            # Also compute the headline KPI so the event payload carries a value
            try:
                result = await _kpis.compute(
                    alert.kpi_code,
                    self.session,
                    project_id=alert.scope_project_id,
                )
                evaluated_value = result.value
                evaluated_unit = result.unit
            except Exception:
                pass
        else:
            result = await _kpis.compute(
                alert.kpi_code,
                self.session,
                project_id=alert.scope_project_id,
            )
            evaluated_value = result.value
            evaluated_unit = result.unit
            threshold = alert.threshold_value
            if cond == "above":
                triggered = result.value > threshold
            elif cond == "below":
                triggered = result.value < threshold
            elif cond == "equals":
                triggered = result.value == threshold
            elif cond == "not_equals":
                triggered = result.value != threshold
            elif cond == "changed_by_more_than":
                history = await self.repo.list_kpi_values(
                    alert.kpi_code,
                    project_id=alert.scope_project_id,
                    limit=1,
                )
                if history:
                    delta = abs(result.value - history[0].value)
                    triggered = delta > threshold

        if not triggered:
            return False
        await self.repo.update_alert(alert.id, last_triggered_at=now)
        _safe_publish(
            "bi.alert.triggered",
            {
                "alert_id": str(alert.id),
                "alert_name": alert.name,
                "kpi_code": alert.kpi_code,
                "value": str(evaluated_value) if evaluated_value is not None else "",
                "unit": evaluated_unit,
                "threshold": str(alert.threshold_value),
                "condition": cond if not expression else "composite",
                "severity": alert.severity,
                "scope_project_id": (str(alert.scope_project_id) if alert.scope_project_id else None),
                "recipients": alert.recipients_json or [],
                "channels": alert.channels_json or ["in_app"],
                "trace": trace,
            },
        )
        return True

    async def evaluate_alerts(self) -> int:
        """Iterate all enabled alerts, fire any that breach. Return fired count."""
        alerts = await self.repo.list_alerts(enabled_only=True)
        fired = 0
        for alert in alerts:
            try:
                if await self.evaluate_alert(alert):
                    fired += 1
            except Exception:
                logger.exception(
                    "evaluate_alerts: rule %s raised",
                    alert.id,
                )
        return fired

    # ── Drill-down ────────────────────────────────────────────────

    async def drill_down(
        self,
        code: str,
        *,
        project_id: uuid.UUID | None = None,
        period_start: _date | None = None,
        period_end: _date | None = None,
        filters: dict[str, Any] | None = None,
        depth: int = 1,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return underlying records that fed the aggregate.

        Tries the registered :func:`kpis.drilldown` provider first;
        falls back to the breakdown dict + history if no provider is
        registered for the KPI. The aggregate value is also included so
        the UI can show the tile total alongside the row list.

        ``period_start`` / ``period_end`` / ``filters`` are forwarded to
        the KPI formula so the headline aggregate reflects the same scope
        the caller requested — previously these request fields were
        silently dropped, so a period-filtered drill-down returned the
        all-time aggregate, contradicting its own row list.
        """
        result = await _kpis.compute(
            code,
            self.session,
            project_id=project_id,
            period_start=period_start,
            period_end=period_end,
            filters=filters,
        )
        # Real records from the registered provider
        records: list[dict[str, Any]] = await _kpis.drilldown(
            code,
            self.session,
            project_id=project_id,
            limit=limit,
        )
        if not records:
            # Fallback: synthesise rows from the breakdown + history
            for k, v in (result.breakdown or {}).items():
                records.append({"kind": "breakdown", "key": k, "value": v})
            history = await self.repo.list_kpi_values(
                code,
                project_id=project_id,
                limit=depth * 12,
            )
            for h in history:
                records.append(
                    {
                        "kind": "history",
                        "period_start": h.period_start.isoformat(),
                        "period_end": h.period_end.isoformat(),
                        "value": str(h.value),
                    },
                )
        return {
            "kpi_code": code,
            "records": records,
            "record_count": len(records),
            "aggregate_value": result.value,
            "aggregate_unit": result.unit,
        }

    # ── Saved Filters ─────────────────────────────────────────────

    async def create_filter(
        self,
        payload: SavedFilterCreate,
        *,
        owner_user_id: uuid.UUID | None,
    ) -> SavedFilter:
        sf = SavedFilter(
            name=payload.name,
            owner_user_id=owner_user_id,
            scope=payload.scope,
            module=payload.module,
            filter_json=payload.filter_json,
            is_default=payload.is_default,
            shared_with_user_ids_json=[str(u) for u in (payload.shared_with_user_ids or [])],
        )
        return await self.repo.create_filter(sf)

    async def list_filters(
        self,
        *,
        owner_user_id: uuid.UUID | None,
        module: str | None = None,
    ) -> list[SavedFilter]:
        rows = await self.repo.list_filters(
            owner_user_id=owner_user_id,
            module=module,
        )
        if owner_user_id is None:
            return rows
        # Also include filters shared with this user (sqlalchemy can't JSON-
        # contains check portably across sqlite + postgres). Do it in Python.
        shared_rows = await self.repo.list_filters_shared_with(
            owner_user_id,
            module=module,
        )
        seen_ids = {r.id for r in rows}
        for sr in shared_rows:
            if sr.id not in seen_ids:
                rows.append(sr)
                seen_ids.add(sr.id)
        return rows

    async def share_filter(
        self,
        filter_id: uuid.UUID,
        *,
        owner_user_id: uuid.UUID | None,
        user_ids: list[uuid.UUID],
    ) -> SavedFilter:
        """Add ``user_ids`` to a filter's ``shared_with_user_ids_json``.

        Caller must be the owner (or global admin via the router-level
        ownership check). Idempotent — duplicates are de-duped.
        """
        sf = await self.repo.get_filter(filter_id)
        if sf is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Filter not found")
        if sf.owner_user_id is not None and owner_user_id is not None and sf.owner_user_id != owner_user_id:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Filter not found")
        existing = list(sf.shared_with_user_ids_json or [])
        for uid in user_ids:
            s = str(uid)
            if s not in existing:
                existing.append(s)
        sf.shared_with_user_ids_json = existing
        await self.session.flush()
        _safe_publish(
            "bi.filter.shared",
            {
                "filter_id": str(filter_id),
                "shared_with": [str(u) for u in user_ids],
                "owner_id": str(owner_user_id) if owner_user_id else None,
            },
        )
        return sf

    # ── Widget exports (CSV / SVG) ─────────────────────────────────

    async def export_widget(
        self,
        widget_id: uuid.UUID,
        *,
        format: str,
    ) -> tuple[str, int] | None:
        """Render a widget as CSV or SVG. Returns ``(path, bytes)``."""
        widget = await self.repo.get_widget(widget_id)
        if widget is None:
            return None
        kpi_code = widget.kpi_code or ""
        if kpi_code:
            result = await _kpis.compute(
                kpi_code,
                self.session,
                project_id=(widget.config_json.get("project_id") if isinstance(widget.config_json, dict) else None),
            )
            history_rows = await self.repo.list_kpi_values(kpi_code, limit=24)
            history = [
                {
                    "period_start": h.period_start.isoformat(),
                    "period_end": h.period_end.isoformat(),
                    "value": str(h.value),
                }
                for h in history_rows
            ]
        else:
            result = _kpis.KPIComputation()
            history = []
        widget_label = kpi_code or f"widget_{widget.id}"
        fmt = (format or "csv").lower()
        if fmt == "csv":
            return export_widget_csv(
                widget_label=widget_label,
                breakdown={**(result.breakdown or {}), "value": str(result.value)},
                history=history,
            )
        if fmt == "svg":
            return export_widget_svg(
                widget_label=widget_label,
                history=history,
                unit=result.unit,
            )
        # PNG would need cairosvg or matplotlib — outside the no-mocks bar.
        # Return SVG so caller can convert client-side if desired.
        return export_widget_svg(
            widget_label=widget_label,
            history=history,
            unit=result.unit,
        )


__all__ = [
    "BIDashboardsService",
    "compute_next_run_at",
]
