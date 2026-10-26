# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Field Time ORM models.

Tables:
    oe_field_time_timesheet       - a foreman's end-of-day, cost-coded, signed
                                    field timesheet for one project-day
    oe_field_time_line            - one labour or plant hours booking on a
                                    timesheet, optionally naming the BOQ
                                    position the hours were spent on

A timesheet moves draft -> submitted -> approved; once approved it is immutable
and the only correction is a reversing timesheet (the original flips to
``reversed`` and a new timesheet with ``reverses_id`` set nets it out).

Each line is labour XOR plant: exactly one of ``resource_id`` (a person / crew
from the resources module) or ``equipment_id`` (a machine from the equipment
module) is set. That invariant is enforced both in the service and by a DB CHECK
constraint so a malformed row can never be persisted.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import AwareDateTime, SafeDate
from app.database import GUID, Base

# Line completeness is enforced in the DB too: exactly one of resource_id /
# equipment_id must be non-null (labour XOR plant). ``num_nonnulls`` is not
# portable to SQLite, so spell the XOR out explicitly.
_LABOUR_XOR_PLANT = (
    "(resource_id IS NOT NULL AND equipment_id IS NULL) OR (resource_id IS NULL AND equipment_id IS NOT NULL)"
)


class FieldTimesheet(Base):
    """A signed field timesheet for one project on one day."""

    __tablename__ = "oe_field_time_timesheet"
    __table_args__ = (
        Index("ix_oe_field_time_timesheet_project_date", "project_id", "date"),
        # One live timesheet number per project (human reference). Reversals get
        # their own row; the number is stored in metadata, not uniquely keyed.
        UniqueConstraint("project_id", "reference", name="uq_oe_field_time_timesheet_project_ref"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Human-facing sequential reference within the project (e.g. "FT-000123").
    reference: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    date: Mapped[date] = mapped_column(SafeDate(), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)

    submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)

    # A reversal points at the timesheet it reverses (self-FK). NULL for an
    # ordinary timesheet. SET NULL so deleting a stray original never blocks.
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_field_time_timesheet.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which statutory working-time regime this day is recorded under, or NULL
    # when nobody chose one. NULL is the state every timesheet starts in and the
    # state every existing row stays in: no regime means no recording deadline,
    # no retention window and nothing on screen about either. The vocabulary is
    # ALL_WORKING_TIME_REGIMES in
    # :mod:`app.modules.field_time.working_time`, stored as a plain string so a
    # further regime never needs a schema change. Deliberately no server
    # default: most of this platform's users work under no such obligation, and
    # a default would be this module answering a legal question for them.
    working_time_regime: Mapped[str | None] = mapped_column(String(30), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    lines: Mapped[list["FieldTimesheetLine"]] = relationship(
        back_populates="timesheet",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<FieldTimesheet {self.reference or self.id} {self.date} ({self.status})>"


class FieldTimesheetLine(Base):
    """One labour or plant hours booking on a field timesheet.

    Labour XOR plant: exactly one of ``resource_id`` / ``equipment_id`` is set.
    Hours are a ``Decimal`` (never float). ``cost_code`` / ``wbs`` code the line
    to the project's own chart of accounts, and ``boq_position_id`` names the
    bill position the hours were spent on when somebody knows which one.

    Those are two different things, and this docstring used to claim they were
    one: it said the cost code coded the line to a BOQ position, and nothing
    implemented that. A cost code is free text on a project chart and a WBS path
    is a tree address; neither resolves to a position id. The consequence was
    that recorded hours could never be compared with the estimate line that
    predicted them, which is the comparison a productivity norm needs in order
    to be worth anything on the next job.

    A line may also carry clock times (``started_at`` / ``ended_at`` and the
    unpaid ``break_minutes``). It never has to: a line without them is the line
    this module has always written. With them, ``hours`` is derived from them
    rather than typed, which is what a statutory working-time record needs and
    what stops a duration from disagreeing with the times that produced it.
    """

    __tablename__ = "oe_field_time_line"
    __table_args__ = (
        CheckConstraint(_LABOUR_XOR_PLANT, name="ck_oe_field_time_line_labour_xor_plant"),
        Index("ix_oe_field_time_line_resource", "resource_id"),
        Index("ix_oe_field_time_line_equipment", "equipment_id"),
        # Named here rather than left to ``index=True`` on the column, because the
        # autogenerated name would carry the ``_id`` suffix and the migration that
        # adds this column on an installation that has already booted creates it
        # without one. Two names for one index means two indexes on one column.
        Index("ix_oe_field_time_line_boq_position", "boq_position_id"),
    )

    timesheet_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_field_time_timesheet.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Labour: a person / crew from the resources module.
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_resources_resource.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Plant: a machine from the equipment module.
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_equipment_equipment.id", ondelete="SET NULL"),
        nullable=True,
    )
    hours: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    cost_code: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    wbs: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # The bill position these hours were spent on. Nullable, no default, and it
    # does not replace the cost-code path: a day that covered six positions
    # honestly names none of them, and a line nobody has attributed has to stay
    # unattributed rather than acquire a position because a column demanded one.
    # Soft link, no foreign key, like ``daywork_sheet_id`` above and like every
    # other cross-module position link in the tree: a signed statutory record of
    # somebody's working day must outlive the estimate it was coded against
    # being deleted or re-imported.
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    is_daywork: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # The variation this daywork was performed under (issued variation order).
    variation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_variations_order.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Soft link to the oe_variations_daywork_sheet row minted on approval for a
    # daywork line. Plain GUID (no DB FK) - the sheet is created dynamically by
    # the variations service and this only records the resulting id for trace.
    daywork_sheet_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Clock times for this booking, and the unpaid break inside them. All three
    # are nullable with no server default, so every line written before they
    # existed - and every line written today by somebody who does not need them -
    # is byte for byte what it was. When both times are present they are the
    # single source of the line's ``hours``: the service derives the duration
    # from them (see ``field_time_math.derive_line_hours``) instead of storing a
    # typed number that could disagree with the times beside it. ``ended_at`` is
    # a full instant, so a night shift simply ends on the following day.
    started_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    break_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Who employs this worker: "own" or "subcontractor" (see ALL_EMPLOYER_KINDS
    # in :mod:`app.modules.field_time.working_time`), NULL when nobody said. A
    # main contractor is answerable for the wages its subcontractors pay, so the
    # employer is part of a statutory working-time record and not a payroll
    # detail. Soft link, no foreign key, exactly like ``daywork_sheet_id``: the
    # subcontractor register is another module's table and a working-time record
    # must outlive an entry being tidied out of it.
    employer_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    employer_subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    timesheet: Mapped[FieldTimesheet] = relationship(back_populates="lines")

    def __repr__(self) -> str:
        kind = "labour" if self.resource_id else "plant"
        return f"<FieldTimesheetLine {kind} {self.hours}h {self.cost_code}>"


# ── Geofenced time clock ─────────────────────────────────────────────────────
#
# A clock event stores the position at the moment of the tap and nothing else:
# no track, no background sampling. The position is personal data under GDPR,
# so it is captured only for a worker with recorded consent, and erased after
# the project's retention window while the event itself (who, when, inside or
# outside) stays as part of the working-time record.


class FieldSiteGeofence(Base):
    """A site boundary on one project: a circle or a polygon in WGS84."""

    __tablename__ = "oe_field_time_geofence"
    __table_args__ = (Index("ix_oe_field_time_geofence_project_active", "project_id", "active"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    shape: Mapped[str] = mapped_column(String(20), nullable=False, default="circle")
    center_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    center_lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    radius_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # ``[[lat, lng], ...]`` for a polygon; empty for a circle.
    polygon: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    # Metres outside the boundary still counted as inside (GPS noise at the gate).
    tolerance_m: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    # Who approves a clock flagged outside this fence (user ids); the project
    # owner is always asked as well.
    supervisor_user_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    # Cost code given to timesheet lines built from shifts clocked at this site.
    default_cost_code: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<FieldSiteGeofence {self.name} ({self.shape})>"


class FieldClockSettings(Base):
    """Per-project switches for the time clock: on/off, retention, break."""

    __tablename__ = "oe_field_time_clock_settings"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_field_time_clock_settings_project"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90, server_default="90")
    default_break_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    consent_text_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1", server_default="1")


class FieldClockConsent(Base):
    """A worker's recorded consent to position capture at clock-in and clock-out."""

    __tablename__ = "oe_field_time_clock_consent"
    __table_args__ = (
        UniqueConstraint("project_id", "resource_id", name="uq_oe_field_time_clock_consent_project_resource"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    granted_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    text_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1", server_default="1")
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class FieldClockEvent(Base):
    """One clock-in or clock-out with the position at that moment only."""

    __tablename__ = "oe_field_time_clock_event"
    __table_args__ = (
        Index("ix_oe_field_time_clock_event_project_time", "project_id", "occurred_at"),
        Index("ix_oe_field_time_clock_event_resource_time", "resource_id", "occurred_at"),
        Index("ix_oe_field_time_clock_event_approval", "project_id", "approval_status"),
        UniqueConstraint("project_id", "client_op_id", name="uq_oe_field_time_clock_event_client_op"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(5), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    # Erased (set NULL) once the retention window passes; ``position_purged_at``
    # then records that it happened.
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    position_purged_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    geofence_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_field_time_geofence.id", ondelete="SET NULL"),
        nullable=True,
    )
    inside: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    distance_m: Mapped[Decimal | None] = mapped_column(Numeric(12, 1), nullable=True)
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_required", server_default="not_required"
    )
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    # The clock-in a clock-out closes (soft link, same table).
    pair_event_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # The timesheet whose line this shift became (soft link).
    timesheet_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    client_op_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<FieldClockEvent {self.kind} {self.occurred_at} ({self.approval_status})>"
