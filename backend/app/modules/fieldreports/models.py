"""Field Reports ORM models.

Tables:
    oe_fieldreports_report — daily/inspection/safety/concrete pour field reports
"""

import uuid

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text
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
    report_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="daily"
    )

    # Weather conditions
    weather_condition: Mapped[str] = mapped_column(
        String(30), nullable=False, default="clear"
    )
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

    # Signature
    signature_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signature_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status & approval
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
