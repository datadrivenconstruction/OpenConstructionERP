"""‌⁠‍Safety ORM models.

Tables:
    oe_safety_incident    - safety incident reports (injuries, near misses, etc.)
    oe_safety_observation - proactive safety observations with risk scoring
"""

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SafetyIncident(Base):
    """‌⁠‍A safety incident report tracking injuries, near misses, and property damage."""

    __tablename__ = "oe_safety_incident"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    incident_number: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    incident_date: Mapped[str] = mapped_column(String(40), nullable=False)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    incident_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, default="minor")
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Geo binding (cross-module) ────────────────────────────────────────
    # Companion to the free-form ``location`` text - when the user pins the
    # incident on a map, ``geo_lat``/``geo_lon`` are populated so Geo Hub can
    # render a project-scoped layer of incident pins. Canonical anchor
    # fields are named ``lat``/``lon`` across the platform, but on this
    # table we prefix with ``geo_`` to avoid colliding with any future
    # incident geometry (e.g. zone polygon).
    #
    # Nullable + no server_default - incidents that pre-date this column
    # genuinely have no geo binding, and we don't want a fake (0, 0) point
    # leaking into the map layer. Add via Base.metadata.create_all on
    # fresh installs, and migration v3107_cross_module_geo_binding for
    # existing installs (inspector-guarded so it's a no-op when the
    # column already exists).
    geo_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    geo_lon: Mapped[float | None] = mapped_column(Float, nullable=True)

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

    reported_to_regulator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="reported", index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # ── OSHA Form 300 recordable-incident bookkeeping ────────────────────
    # Added by v3086_hse_osha_corrective_fsm. ``osha_recordable`` is the
    # gate that filters incidents into the OSHA 300 log export.
    #
    # ``server_default="0"`` is load-bearing: fresh installs run
    # ``Base.metadata.create_all`` which honours model-level defaults at
    # CREATE TABLE time. Without it, the committed showcase snapshot
    # (built before this column existed and thus carrying no
    # ``osha_recordable`` value) trips a NOT NULL violation on first boot,
    # leaving the seed transaction open and SQLite write-locked. See #154.
    osha_recordable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        index=True,
    )
    osha_case_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    days_away: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_restricted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 5_whys / fishbone / tap_root / other - kept free-form (validated in
    # the service layer) so we can extend the taxonomy without a migration.
    root_cause_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    root_cause_tags: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
        default=list,
        server_default="[]",
    )

    def __repr__(self) -> str:
        return f"<SafetyIncident {self.incident_number} ({self.incident_type}/{self.status})>"


class HSECorrectiveAction(Base):
    """‌⁠‍Slim incident-scoped corrective action with a strict FSM.

    Distinct from :class:`app.modules.hse_advanced.models.CorrectiveAction`
    (which is the audit/JSA/observation-scoped CAPA carrying 5-Whys and
    effectiveness verification). This table is the lightweight
    construction-suite style "open a CA off an incident" record with a single
    pending → in_progress → verified → closed lifecycle.
    """

    __tablename__ = "oe_hse_corrective_action"

    # Plain UUID - references oe_safety_incident.id, no FK to avoid
    # cross-module coupling (mirrors HSEIncidentInvestigation.incident_ref).
    incident_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    due_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        index=True,
    )
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<HSECorrectiveAction incident={self.incident_id} status={self.status}>"


class SafetyObservation(Base):
    """‌⁠‍A proactive safety observation with risk scoring."""

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
        return f"<SafetyObservation {self.observation_number} ({self.observation_type}/{self.status})>"
