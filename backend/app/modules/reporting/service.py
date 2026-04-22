"""Reporting service — business logic for KPI snapshots, templates, and report generation."""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reporting.cron import CronParseError, next_occurrence
from app.modules.reporting.models import GeneratedReport, KPISnapshot, ReportTemplate
from app.modules.reporting.repository import (
    GeneratedReportRepository,
    KPISnapshotRepository,
    ReportTemplateRepository,
)
from app.modules.reporting.schemas import (
    GenerateReportRequest,
    KPISnapshotCreate,
    ReportScheduleRequest,
    ReportTemplateCreate,
)

logger = logging.getLogger(__name__)

# ── System report templates (seeded on first startup) ──────────────────────

SYSTEM_TEMPLATES: list[dict] = [
    {
        "name": "Project Status Report",
        "report_type": "project_status",
        "description": "Comprehensive project status overview with KPIs, schedule, budget, and risk summary.",
        "template_data": {
            "sections": [
                {"id": "header", "title": "Project Overview", "fields": ["name", "status", "dates"]},
                {"id": "kpi", "title": "Key Performance Indicators", "fields": ["cpi", "spi", "budget_consumed_pct"]},
                {"id": "schedule", "title": "Schedule Status", "fields": ["progress_pct", "milestones"]},
                {"id": "risk", "title": "Risk Summary", "fields": ["risk_score_avg", "top_risks"]},
                {"id": "issues", "title": "Open Issues", "fields": ["defects", "observations", "rfis"]},
            ],
        },
    },
    {
        "name": "Cost Report",
        "report_type": "cost_report",
        "description": "Detailed cost breakdown by trade, element, and cost group with budget vs. actual comparison.",
        "template_data": {
            "sections": [
                {"id": "summary", "title": "Cost Summary", "fields": ["budget", "committed", "forecast"]},
                {"id": "breakdown", "title": "Cost Breakdown", "fields": ["by_trade", "by_element"]},
                {"id": "changes", "title": "Change Orders", "fields": ["approved", "pending", "rejected"]},
                {"id": "cashflow", "title": "Cash Flow", "fields": ["monthly_actual", "monthly_forecast"]},
            ],
        },
    },
    {
        "name": "Schedule Status Report",
        "report_type": "schedule_status",
        "description": "Schedule performance with milestone tracking, critical path, and lookahead.",
        "template_data": {
            "sections": [
                {"id": "overview", "title": "Schedule Overview", "fields": ["spi", "progress_pct"]},
                {"id": "milestones", "title": "Milestone Status", "fields": ["upcoming", "overdue"]},
                {"id": "critical", "title": "Critical Path", "fields": ["critical_activities"]},
                {"id": "lookahead", "title": "3-Week Lookahead", "fields": ["planned_activities"]},
            ],
        },
    },
    {
        "name": "Safety Report",
        "report_type": "safety_report",
        "description": "Safety incident summary, near-miss tracking, and safety KPIs.",
        "template_data": {
            "sections": [
                {"id": "kpi", "title": "Safety KPIs", "fields": ["ltifr", "trifr", "days_without_incident"]},
                {"id": "incidents", "title": "Incident Log", "fields": ["recent_incidents"]},
                {"id": "near_miss", "title": "Near-Miss Reports", "fields": ["recent_near_misses"]},
                {"id": "training", "title": "Safety Training", "fields": ["completed", "upcoming"]},
            ],
        },
    },
    {
        "name": "Inspection Report",
        "report_type": "inspection_report",
        "description": "Quality inspection results with pass/fail statistics and punch list status.",
        "template_data": {
            "sections": [
                {"id": "summary", "title": "Inspection Summary", "fields": ["total", "passed", "failed"]},
                {"id": "by_type", "title": "By Inspection Type", "fields": ["type_breakdown"]},
                {"id": "punchlist", "title": "Punch List Status", "fields": ["open", "closed", "overdue"]},
                {"id": "details", "title": "Recent Inspections", "fields": ["recent_list"]},
            ],
        },
    },
    {
        "name": "Portfolio Summary",
        "report_type": "portfolio_summary",
        "description": "Multi-project portfolio dashboard with aggregated KPIs and project comparison.",
        "template_data": {
            "sections": [
                {"id": "overview", "title": "Portfolio Overview", "fields": ["project_count", "total_budget"]},
                {"id": "status", "title": "Project Statuses", "fields": ["by_status", "by_health"]},
                {"id": "kpi_comparison", "title": "KPI Comparison", "fields": ["cpi_table", "spi_table"]},
                {"id": "risks", "title": "Portfolio Risks", "fields": ["top_risks_across"]},
            ],
        },
    },
]


class ReportingService:
    """Business logic for reporting operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.kpi_repo = KPISnapshotRepository(session)
        self.template_repo = ReportTemplateRepository(session)
        self.report_repo = GeneratedReportRepository(session)

    # ── KPI Snapshots ─────────────────────────────────────────────────────

    async def get_latest_kpi(self, project_id: uuid.UUID) -> KPISnapshot | None:
        """Get the most recent KPI snapshot for a project."""
        return await self.kpi_repo.get_latest(project_id)

    async def list_kpi_history(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[KPISnapshot], int]:
        """List KPI snapshots for a project."""
        return await self.kpi_repo.list_history(project_id, offset=offset, limit=limit)

    async def create_kpi_snapshot(
        self,
        data: KPISnapshotCreate,
        user_id: str | None = None,
    ) -> KPISnapshot:
        """Create a new KPI snapshot."""
        snapshot = KPISnapshot(
            project_id=data.project_id,
            snapshot_date=data.snapshot_date,
            cpi=data.cpi,
            spi=data.spi,
            budget_consumed_pct=data.budget_consumed_pct,
            open_defects=data.open_defects,
            open_observations=data.open_observations,
            schedule_progress_pct=data.schedule_progress_pct,
            open_rfis=data.open_rfis,
            open_submittals=data.open_submittals,
            risk_score_avg=data.risk_score_avg,
            metadata_=data.metadata,
        )
        snapshot = await self.kpi_repo.create(snapshot)
        logger.info(
            "KPI snapshot created for project %s date %s",
            data.project_id,
            data.snapshot_date,
        )
        return snapshot

    # ── Report Templates ──────────────────────────────────────────────────

    async def list_templates(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ReportTemplate], int]:
        """List all report templates."""
        return await self.template_repo.list_all(offset=offset, limit=limit)

    async def create_template(
        self,
        data: ReportTemplateCreate,
        user_id: str | None = None,
    ) -> ReportTemplate:
        """Create a custom report template."""
        template = ReportTemplate(
            name=data.name,
            name_translations=data.name_translations,
            report_type=data.report_type,
            description=data.description,
            template_data=data.template_data,
            is_system=False,
            created_by=uuid.UUID(user_id) if user_id else None,
            metadata_=data.metadata,
        )
        template = await self.template_repo.create(template)
        logger.info("Report template created: %s (%s)", data.name, data.report_type)
        return template

    async def get_template(self, template_id: uuid.UUID) -> ReportTemplate:
        """Fetch a template or raise 404."""
        template = await self.template_repo.get_by_id(template_id)
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report template not found",
            )
        return template

    # ── Scheduling (v2.3.0) ───────────────────────────────────────────────

    async def schedule_template(
        self,
        template_id: uuid.UUID,
        data: ReportScheduleRequest,
    ) -> ReportTemplate:
        """Attach/replace/clear a cron schedule on a template.

        Passing ``schedule_cron=None`` clears scheduling (and also clears
        ``next_run_at``). Otherwise the cron is parsed, the next run is
        computed from ``now`` in UTC, and persisted.
        """
        template = await self.get_template(template_id)

        template.recipients = list(data.recipients)
        template.project_id_scope = data.project_id_scope

        if data.schedule_cron is None:
            template.schedule_cron = None
            template.next_run_at = None
            template.is_scheduled = False
        else:
            try:
                next_run = next_occurrence(
                    data.schedule_cron,
                    datetime.now(UTC),
                )
            except CronParseError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid cron expression: {exc}",
                ) from exc
            template.schedule_cron = data.schedule_cron
            template.next_run_at = next_run.strftime("%Y-%m-%dT%H:%M:%SZ")
            template.is_scheduled = data.is_scheduled

        await self.template_repo.update(template)
        logger.info(
            "Report template %s scheduled: cron=%r is_scheduled=%s next_run=%s",
            template.id,
            template.schedule_cron,
            template.is_scheduled,
            template.next_run_at,
        )
        return template

    async def list_due_templates(self, as_of: datetime | None = None) -> list[ReportTemplate]:
        """List scheduled templates whose next_run_at has arrived.

        Used by the Celery-Beat worker. Accepts an optional ``as_of``
        datetime (UTC) for tests; defaults to now.
        """
        if as_of is None:
            as_of = datetime.now(UTC)
        as_of_iso = as_of.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return await self.template_repo.list_due(as_of_iso)

    async def list_scheduled_templates(self) -> list[ReportTemplate]:
        """List every template that has a cron expression set."""
        return await self.template_repo.list_scheduled()

    async def mark_template_ran(
        self,
        template: ReportTemplate,
        *,
        ran_at: datetime | None = None,
    ) -> ReportTemplate:
        """Advance a template after a successful worker run.

        Records ``last_run_at`` and recomputes ``next_run_at`` using the
        stored cron expression. If the cron expression is no longer valid
        or scheduling was paused, ``next_run_at`` is cleared so the
        worker won't pick it up again.
        """
        if ran_at is None:
            ran_at = datetime.now(UTC)
        ran_at = ran_at.astimezone(UTC)
        template.last_run_at = ran_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        if not template.is_scheduled or not template.schedule_cron:
            template.next_run_at = None
        else:
            try:
                next_run = next_occurrence(template.schedule_cron, ran_at)
                template.next_run_at = next_run.strftime("%Y-%m-%dT%H:%M:%SZ")
            except CronParseError:
                logger.exception(
                    "Template %s has invalid cron %r — pausing",
                    template.id,
                    template.schedule_cron,
                )
                template.next_run_at = None
                template.is_scheduled = False

        await self.template_repo.update(template)
        return template

    # ── Generated Reports ─────────────────────────────────────────────────

    async def list_reports(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[GeneratedReport], int]:
        """List generated reports for a project."""
        return await self.report_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
        )

    async def get_report(self, report_id: uuid.UUID) -> GeneratedReport:
        """Get a generated report by ID. Raises 404 if not found."""
        report = await self.report_repo.get_by_id(report_id)
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report not found",
            )
        return report

    async def generate_report(
        self,
        data: GenerateReportRequest,
        user_id: str | None = None,
    ) -> GeneratedReport:
        """Generate a new report."""
        report = GeneratedReport(
            project_id=data.project_id,
            template_id=data.template_id,
            report_type=data.report_type,
            title=data.title,
            generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            generated_by=uuid.UUID(user_id) if user_id else None,
            format=data.format,
            data_snapshot=data.data_snapshot,
            metadata_=data.metadata,
        )
        report = await self.report_repo.create(report)
        logger.info(
            "Report generated: %s (%s) for project %s",
            data.title,
            data.report_type,
            data.project_id,
        )
        return report

    # ── KPI Auto-Recalculation ───────────────────────────────────────────

    async def auto_recalculate_kpis(self) -> dict:
        """Recalculate KPI snapshots for all active projects.

        Called by the scheduler or manually via the admin API endpoint.
        Queries each module (finance, safety, RFI, schedule, etc.) to
        compute up-to-date KPI values and creates a new KPISnapshot row
        per project.

        Returns a summary dict with counts of processed / failed projects.
        """
        from sqlalchemy import Float, func, select
        from sqlalchemy.sql.expression import cast

        from app.modules.projects.models import Project

        today = datetime.now(UTC).strftime("%Y-%m-%d")

        # Fetch all active projects
        stmt = select(Project).where(Project.status == "active")
        result = await self.session.execute(stmt)
        projects = list(result.scalars().all())

        processed = 0
        failed = 0

        for project in projects:
            try:
                pid = project.id

                # ── Finance: CPI, SPI, budget consumed ──
                cpi: str | None = None
                spi: str | None = None
                budget_consumed_pct: str | None = None
                try:
                    from app.modules.finance.service import FinanceService

                    fin_svc = FinanceService(self.session)
                    dashboard = await fin_svc.get_dashboard(project_id=pid)
                    if dashboard.get("total_budget") and float(dashboard["total_budget"]) > 0:
                        total_budget = float(dashboard["total_budget"])
                        total_actual = float(dashboard.get("total_actual", 0))
                        budget_consumed_pct = str(round((total_actual / total_budget) * 100, 1))
                except Exception:
                    logger.debug("KPI snapshot: finance data unavailable", exc_info=True)

                try:
                    from app.modules.costmodel.service import CostModelService

                    cm_svc = CostModelService(self.session)
                    cm_dash = await cm_svc.get_dashboard(pid)
                    if cm_dash.get("cpi"):
                        cpi = str(cm_dash["cpi"])
                    if cm_dash.get("spi"):
                        spi = str(cm_dash["spi"])
                except Exception:
                    logger.debug("KPI snapshot: cost model data unavailable", exc_info=True)

                # ── Safety: open defects & observations ──
                open_defects = 0
                open_observations = 0
                try:
                    from app.modules.safety.service import SafetyService

                    safety_svc = SafetyService(self.session)
                    safety_stats = await safety_svc.get_stats(pid)
                    open_observations = getattr(safety_stats, "total_observations", 0) - getattr(
                        safety_stats, "closed_observations", 0
                    )
                    if open_observations < 0:
                        open_observations = 0
                    open_defects = getattr(safety_stats, "total_incidents", 0)
                except Exception:
                    logger.debug("KPI snapshot: safety data unavailable", exc_info=True)

                # ── RFIs ──
                open_rfis = 0
                try:
                    from app.modules.rfi.service import RFIService

                    rfi_svc = RFIService(self.session)
                    rfi_stats = await rfi_svc.get_stats(pid)
                    open_rfis = getattr(rfi_stats, "open", 0)
                except Exception:
                    logger.debug("KPI snapshot: RFI data unavailable", exc_info=True)

                # ── Submittals ──
                open_submittals = 0
                try:
                    from sqlalchemy import select as sa_select

                    from app.modules.submittals.models import Submittal

                    sub_count = (
                        await self.session.execute(
                            sa_select(func.count(Submittal.id)).where(
                                Submittal.project_id == pid,
                                Submittal.status.notin_(["approved", "closed"]),
                            )
                        )
                    ).scalar_one()
                    open_submittals = sub_count
                except Exception:
                    logger.debug("KPI snapshot: submittals data unavailable", exc_info=True)

                # ── Schedule progress ──
                schedule_progress_pct: str | None = None
                try:
                    from app.modules.schedule.models import Activity, Schedule

                    sched_ids_stmt = select(Schedule.id).where(Schedule.project_id == pid)
                    sched_result = await self.session.execute(sched_ids_stmt)
                    sched_ids = [r[0] for r in sched_result.all()]

                    if sched_ids:
                        avg_progress = (
                            await self.session.execute(
                                select(func.avg(cast(Activity.progress_pct, Float))).where(
                                    Activity.schedule_id.in_(sched_ids)
                                )
                            )
                        ).scalar_one()
                        if avg_progress is not None:
                            schedule_progress_pct = str(round(avg_progress, 1))
                except Exception:
                    logger.debug("KPI snapshot: schedule data unavailable", exc_info=True)

                # ── Risk score ──
                risk_score_avg: str | None = None
                try:
                    from app.modules.risk.models import RiskItem

                    avg_risk = (
                        await self.session.execute(
                            select(func.avg(cast(RiskItem.risk_score, Float))).where(
                                RiskItem.project_id == pid,
                                RiskItem.status != "closed",
                            )
                        )
                    ).scalar_one()
                    if avg_risk is not None:
                        risk_score_avg = str(round(avg_risk, 2))
                except Exception:
                    logger.debug("KPI snapshot: risk data unavailable", exc_info=True)

                # ── Create snapshot (upsert for today) ──
                existing = None
                existing_stmt = select(KPISnapshot).where(
                    KPISnapshot.project_id == pid,
                    KPISnapshot.snapshot_date == today,
                )
                existing = (await self.session.execute(existing_stmt)).scalar_one_or_none()

                if existing:
                    existing.cpi = cpi
                    existing.spi = spi
                    existing.budget_consumed_pct = budget_consumed_pct
                    existing.open_defects = open_defects
                    existing.open_observations = open_observations
                    existing.schedule_progress_pct = schedule_progress_pct
                    existing.open_rfis = open_rfis
                    existing.open_submittals = open_submittals
                    existing.risk_score_avg = risk_score_avg
                else:
                    snapshot = KPISnapshot(
                        project_id=pid,
                        snapshot_date=today,
                        cpi=cpi,
                        spi=spi,
                        budget_consumed_pct=budget_consumed_pct,
                        open_defects=open_defects,
                        open_observations=open_observations,
                        schedule_progress_pct=schedule_progress_pct,
                        open_rfis=open_rfis,
                        open_submittals=open_submittals,
                        risk_score_avg=risk_score_avg,
                        metadata_={},
                    )
                    self.session.add(snapshot)

                await self.session.flush()
                processed += 1

            except Exception:
                logger.exception("KPI recalculation failed for project %s", project.id)
                failed += 1

        logger.info(
            "KPI auto-recalculation complete: %d processed, %d failed",
            processed,
            failed,
        )
        return {
            "processed": processed,
            "failed": failed,
            "total_projects": len(projects),
            "snapshot_date": today,
        }

    # ── Seed system templates ─────────────────────────────────────────────

    async def seed_system_templates(self) -> int:
        """Seed the 6 system report templates. Truly idempotent.

        Checks each template by name+report_type to avoid duplicates even
        when some templates were manually deleted and re-seeded.
        Returns the number of templates created (0 if all already exist).
        """
        from sqlalchemy import select

        created = 0
        for tmpl_data in SYSTEM_TEMPLATES:
            # Check if this specific template already exists by name + report_type
            stmt = select(ReportTemplate).where(
                ReportTemplate.name == tmpl_data["name"],
                ReportTemplate.report_type == tmpl_data["report_type"],
                ReportTemplate.is_system.is_(True),
            )
            result = await self.session.execute(stmt)
            if result.scalar_one_or_none() is not None:
                continue

            template = ReportTemplate(
                name=tmpl_data["name"],
                report_type=tmpl_data["report_type"],
                description=tmpl_data["description"],
                template_data=tmpl_data["template_data"],
                is_system=True,
                metadata_={},
            )
            self.session.add(template)
            created += 1

        if created:
            await self.session.flush()
            logger.info("Seeded %d system report templates", created)
        return created
