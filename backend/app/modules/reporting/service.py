"""Reporting service — business logic for KPI snapshots, templates, and report generation."""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reporting.models import GeneratedReport, KPISnapshot, ReportTemplate
from app.modules.reporting.repository import (
    GeneratedReportRepository,
    KPISnapshotRepository,
    ReportTemplateRepository,
)
from app.modules.reporting.schemas import (
    GenerateReportRequest,
    KPISnapshotCreate,
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
            project_id, offset=offset, limit=limit,
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

    # ── Seed system templates ─────────────────────────────────────────────

    async def seed_system_templates(self) -> int:
        """Seed the 6 system report templates. Idempotent.

        Returns the number of templates created (0 if already seeded).
        """
        existing = await self.template_repo.count_system()
        if existing >= len(SYSTEM_TEMPLATES):
            return 0

        created = 0
        for tmpl_data in SYSTEM_TEMPLATES:
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

        await self.session.flush()
        logger.info("Seeded %d system report templates", created)
        return created
