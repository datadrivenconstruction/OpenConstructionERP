"""Safety ORM models.

Tables:
    oe_safety_incident    — safety incident reports (injuries, near misses, etc.)
    oe_safety_observation — proactive safety observations with risk scoring
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SafetyIncident(Base):
    """A safety incident report tracking injuries, near misses, and property damage."""

    __tablename__ = "oe_safety_incident"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    incident_number: Mapped[str] = mapped_column(String(20), nullable=False)
    incident_date: Mapped[str] = mapped_column(String(20), nullable=False)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    incident_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Injured person details: {name, role, company, age, ...}
    injured_person_details: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )

    treatment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    days_lost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Corrective actions: [{description, responsible_id, due_date, status}]
    corrective_actions: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    reported_to_regulator: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="reported", index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<SafetyIncident {self.incident_number} ({self.incident_type}/{self.status})>"


class SafetyObservation(Base):
    """A proactive safety observation with risk scoring."""

    __tablename__ = "oe_safety_observation"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    observation_number: Mapped[str] = mapped_column(String(20), nullable=False)
    observation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    severity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    likelihood: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    immediate_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrective_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open", index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return (
            f"<SafetyObservation {self.observation_number} "
            f"({self.observation_type}/{self.status})>"
        )
