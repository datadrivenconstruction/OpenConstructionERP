"""Field Reports ORM models.

Tables:
    oe_fieldreports_report     — daily/inspection/safety/concrete pour field reports
    oe_fieldreports_workforce  — structured workforce log entries per report
    oe_fieldreports_equipment  — structured equipment log entries per report
"""

import uuid

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class FieldReport(Base):
    """A field report documenting on-site conditions, workforce, and activities."""

    __tablename__ = "oe_fieldreports_report"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_date: Mapped[str] = mapped_column(Date, nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(30), nullable=False, default="daily")

    # Weather conditions
    weather_condition: Mapped[str] = mapped_column(String(30), nullable=False, default="clear")
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed: Mapped[str | None] = mapped_column(String(50), nullable=True)
    precipitation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    humidity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Workforce & equipment
    workforce: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    equipment_on_site: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # Work performed
    work_performed: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Delays
    delays: Mapped[str | None] = mapped_column(Text, nullable=True)
    delay_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Site activity
    visitors: Mapped[str | None] = mapped_column(Text, nullable=True)
    deliveries: Mapped[str | None] = mapped_column(Text, nullable=True)
    safety_incidents: Mapped[str | None] = mapped_column(Text, nullable=True)
    materials_used: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    photos: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Structured logs (Phase 15 enhancement)
    workforce_log: Mapped[list | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )
    equipment_log: Mapped[list | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )
    weather_data: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )

    # Signature
    signature_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signature_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status & approval
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Linked documents (cross-module references to oe_documents_document)
    document_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # Standard fields
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<FieldReport {self.report_date} ({self.report_type}/{self.status})>"


class SiteWorkforceLog(Base):
    """Structured workforce log entry linked to a field report.

    Tracks headcount, hours worked, and overtime per trade/company
    for a single day's report.
    """

    __tablename__ = "oe_fieldreports_workforce"

    field_report_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_fieldreports_report.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    worker_type: Mapped[str] = mapped_column(String(100), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    headcount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hours_worked: Mapped[str] = mapped_column(String(10), nullable=False, default="0")
    overtime_hours: Mapped[str] = mapped_column(String(10), nullable=False, default="0")
    wbs_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cost_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<SiteWorkforceLog {self.worker_type} x{self.headcount}>"


class SiteEquipmentLog(Base):
    """Structured equipment log entry linked to a field report.

    Tracks operational, standby, and breakdown hours per piece of
    equipment for a single day's report.
    """

    __tablename__ = "oe_fieldreports_equipment"

    field_report_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_fieldreports_report.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    equipment_description: Mapped[str] = mapped_column(String(500), nullable=False)
    equipment_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hours_operational: Mapped[str] = mapped_column(String(10), nullable=False, default="0")
    hours_standby: Mapped[str] = mapped_column(String(10), nullable=False, default="0")
    hours_breakdown: Mapped[str] = mapped_column(String(10), nullable=False, default="0")
    operator_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<SiteEquipmentLog {self.equipment_description[:40]}>"
