"""Reporting & Dashboards ORM models.

Tables:
    oe_reporting_kpi_snapshot — periodic KPI snapshots per project
    oe_reporting_template     — reusable report templates (system + custom)
    oe_reporting_generated    — generated report instances
"""

import uuid

from sqlalchemy import JSON, Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class KPISnapshot(Base):
    """Periodic KPI snapshot for a project.

    Stores cost, schedule, quality, and risk indicators at a point in time.
    String types are used for numeric fields to avoid float precision issues
    across databases; parsing happens at the application layer.
    """

    __tablename__ = "oe_reporting_kpi_snapshot"
    __table_args__ = (
        UniqueConstraint("project_id", "snapshot_date", name="uq_kpi_project_date"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    snapshot_date: Mapped[str] = mapped_column(String(20), nullable=False)  # ISO date

    # Earned Value indicators
    cpi: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    spi: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    budget_consumed_pct: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None,
    )

    # Quality / defects
    open_defects: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Schedule
    schedule_progress_pct: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None,
    )

    # Submittals & RFIs
    open_rfis: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_submittals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Risk
    risk_score_avg: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None,
    )

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<KPISnapshot project={self.project_id} date={self.snapshot_date}>"


class ReportTemplate(Base):
    """Reusable report template (system or custom).

    System templates (is_system=True) are seeded on first startup and
    cannot be deleted by users.
    """

    __tablename__ = "oe_reporting_template"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_translations: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True, default=None,
    )
    report_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
    )  # project_status / cost_report / schedule_status / safety_report / inspection_report / portfolio_summary
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    template_data: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}",
    )  # sections, fields, layout config
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True, default=None,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ReportTemplate {self.name} ({self.report_type})>"


class GeneratedReport(Base):
    """A report generated from a template (or ad-hoc) for a project."""

    __tablename__ = "oe_reporting_generated"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True, default=None,
    )
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    generated_at: Mapped[str] = mapped_column(String(20), nullable=False)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True, default=None,
    )
    format: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pdf",
    )  # pdf / excel / html
    storage_key: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None,
    )
    data_snapshot: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True, default=None,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<GeneratedReport {self.title} ({self.report_type})>"
