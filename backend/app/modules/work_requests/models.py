# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Work Requests ORM models.

Tables:
    oe_work_requests_department       - one department (engineering, workshop…)
                                        with its stages and request types
    oe_work_requests_request          - one work request (the spine row)
    oe_work_requests_request_hours    - hours logged against a request
    oe_work_requests_comment          - comments, questions, answers, and the
                                        server-written activity lines
    oe_work_requests_planner_alloc    - people per day per request
    oe_work_requests_planner_capacity - people available per day per department
    oe_work_requests_counter          - the per-department reference series

Dates (``due_date``, ``info_required_by``, planner ``day``…) are plain ISO
``YYYY-MM-DD`` strings, validated in the service - the same convention as
team_standup: a due date is a calendar label people agree on, and a string
column sidesteps every timezone round-trip and sorts correctly.

``raised_by_id`` / ``assignee_ids`` / ``lead_user_id`` are plain GUID
strings rather than FKs to the users table: GDPR self-erasure anonymises a
user row in place and a request must survive that unchanged (names are
denormalised at write time into the history for the same reason).
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

#: The status machine. ``draft`` is a request being written; ``submitted``
#: is with the department to accept; ``complete`` is the department saying
#: it is done, and only the requester (or a manager) says ``closed``.
STATUSES = (
    "draft",
    "submitted",
    "accepted",
    "in_progress",
    "on_hold",
    "review",
    "complete",
    "closed",
    "cancelled",
)
#: Work is still outstanding somewhere.
ACTIVE_STATUSES = frozenset({"draft", "submitted", "accepted", "in_progress", "on_hold", "review"})
#: Nothing left to do on the department side.
DONE_STATUSES = frozenset({"complete", "closed", "cancelled"})
#: Never reopened.
TERMINAL_STATUSES = frozenset({"closed", "cancelled"})

PRIORITIES = ("low", "normal", "high", "urgent")
BALL_IN_COURT = ("requester", "department")
COMMENT_KINDS = ("comment", "needs_info", "answer", "system")
FIELD_TYPES = ("text", "area", "date", "number", "bool", "select", "url")

#: Hard caps enforced in the service.
MAX_TITLE_CHARS = 500
MAX_TEXT_CHARS = 20_000
MAX_COMMENT_CHARS = 4000
MAX_LINKS = 50
MAX_ASSIGNEES = 50
#: One request may ask for several types at once (SCADA + PLC + FDS).
MAX_REQUEST_TYPES = 8
#: Checklist items one request type may declare.
MAX_CHECKLIST_ITEMS = 60
#: Requests one bulk update may touch. A bigger edit is several calls -
#: the refusals stay readable and one runaway click cannot walk a board.
MAX_BULK_IDS = 200
#: Estimate lines one request may point at.
MAX_BOQ_POSITIONS = 200
#: Rows one export may carry.
MAX_EXPORT_ROWS = 5000


class WorkDepartment(Base):
    """A business unit that receives work: its stages, request types, people.

    ``stages`` is ``[{key, name, colour, order, closes}]`` - a request moves
    through these on the department's board and a stage with ``closes``
    marks the request complete. ``request_types`` is
    ``[{key, label, disciplines, fields, active, position}]`` where
    ``fields`` are the extra questions that type's raise form asks
    (``{key, label, type, options, required}``). A type is RETIRED with
    ``active: false`` rather than deleted, so the requests already raised
    against it keep reading back with their label.

    ``prefix`` is the three-letter token in every reference the department
    mints (``WR-ENG-000001``). It is stored, not derived on read, so a
    renamed department keeps the references already on its drawings.
    """

    __tablename__ = "oe_work_requests_department"
    __table_args__ = (
        UniqueConstraint("key", name="uq_oe_work_requests_department_key"),
        UniqueConstraint("prefix", name="uq_oe_work_requests_department_prefix"),
    )

    key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    colour: Mapped[str] = mapped_column(String(30), nullable=False, default="slate", server_default="slate")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    lead_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    member_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    #: Money as text, like ``Project.contract_value`` - never a float.
    hourly_rate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stages: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    request_types: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    #: The turnaround the department is judged on, in WORKING days from
    #: the day it accepted the request. ``None`` is "no target" and the
    #: lateness columns read back null rather than pretending to a number.
    target_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<WorkDepartment {self.key} ({self.prefix})>"


class WorkRequest(Base):
    """One piece of work asked of a department, on a job."""

    __tablename__ = "oe_work_requests_request"
    __table_args__ = (
        # The series is per department and global across jobs, so the
        # reference alone is unique. The counter is read under a row lock;
        # this constraint is the backstop that turns a lost race into an
        # IntegrityError the service retries instead of a duplicate.
        UniqueConstraint("reference", name="uq_oe_work_requests_request_reference"),
        Index("ix_work_requests_request_project_dept", "project_id", "department"),
        Index("ix_work_requests_request_dept_status", "department", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    department: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    #: The FIRST of ``request_types``, kept as its own column so every
    #: already-seeded row and every reader that still asks for the
    #: singular keeps working unchanged.
    request_type: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    #: Every type this one request asks for, in the order chosen - a panel
    #: may need FDS *and* PLC programming *and* SCADA. A ``server_default``
    #: so the boot column-heal can add it to a live database; a row written
    #: before it existed reads back as ``[request_type]``.
    request_types: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="submitted", server_default="submitted", index=True
    )
    stage: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    #: ``[{stage, at, by_id, by_name, note}]`` - append only.
    stage_history: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    raised_by_id: Mapped[str] = mapped_column(String(36), nullable=False, default="", index=True)
    raised_by_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    assignee_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    responsible_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    #: ``{discipline: cost centre}`` and ``{discipline: hours}``.
    cost_centres: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    estimated_hours: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    quoted_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The department's own estimate of what is left - the "cost to
    #: complete" column of the switchboard tracker.
    hours_to_complete: Mapped[float | None] = mapped_column(Float, nullable=True)
    info_required_by: Mapped[str | None] = mapped_column(String(10), nullable=True)
    due_date: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    scheduled_start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    scheduled_end: Mapped[str | None] = mapped_column(String(10), nullable=True)
    delivered_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tested_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal", server_default="normal")
    #: ``[{label, url}]``.
    links: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    #: The request type's own questions, ``{field key: value}``.
    fields: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    planner_uploaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    #: requester | department - who the next move belongs to.
    ball_in_court: Mapped[str] = mapped_column(
        String(12), nullable=False, default="department", server_default="department"
    )
    #: The open question when the ball is with the requester.
    needs_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    depends_on_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_work_requests_request.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Server-owned: ``[{filename, size, uploaded_at, by_id, by_name, mime}]``.
    attachments: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    #: Server-owned: ``{reason: date}`` - the deadline sweep's once-a-day memory.
    notified: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    #: ``{item key: {done, by, at}}`` - the TICKS only. The checklist
    #: DEFINITION lives on the request type, so a department editing its
    #: list never rewrites what somebody already ticked.
    checklist_state: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    #: THIS request's departures from the type's checklist - never a copy
    #: of the list, only the difference, so a later edit to the TYPE still
    #: shows through on every item nobody has overridden here::
    #:
    #:     {"added":  [{key, label, required, after_key}],
    #:      "hidden": [key, ...],
    #:      "edits":  {key: {label?, required?}},
    #:      "order":  [key, ...]}
    #:
    #: ``server_default`` so the boot column-heal can add it to a live
    #: database; a row written before it existed reads back as ``{}``,
    #: which is exactly "no overrides - use the type's list".
    checklist_overrides: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    #: A template is a request kept to copy from, never a live one: it is
    #: left out of every list, board, planner, summary and sweep.
    is_template: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    #: The programme activity this work feeds and the estimate lines it
    #: draws on. PLAIN ids, deliberately not foreign keys: this module
    #: READS those tables, it does not depend on them existing.
    schedule_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    boq_position_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    #: The day the department took it on - the clock a turnaround target
    #: runs from. Server-owned, written once by the status machine.
    accepted_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<WorkRequest {self.reference} ({self.department}/{self.status})>"


class WorkRequestHours(Base):
    """Hours one person logged on one request on one day."""

    __tablename__ = "oe_work_requests_request_hours"
    __table_args__ = (Index("ix_work_requests_hours_request_day", "request_id", "day"),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_work_requests_request.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, default="", index=True)
    user_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class WorkRequestComment(Base):
    """A comment, a question to the requester, its answer - or a system line.

    ``kind == "system"`` rows are written by the service on every mutation
    (raised, status, stage, assignment, handoff, hours, attachment) and
    are what the activity feed reads; ``detail`` carries the specifics.
    """

    __tablename__ = "oe_work_requests_comment"
    __table_args__ = (Index("ix_work_requests_comment_request_created", "request_id", "created_at"),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_work_requests_request.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    author_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mention_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="comment", server_default="comment")


class WorkPlannerAlloc(Base):
    """People on one request on one day - the headcount grid cell."""

    __tablename__ = "oe_work_requests_planner_alloc"
    __table_args__ = (UniqueConstraint("request_id", "day", name="uq_oe_work_requests_planner_alloc_request_day"),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_work_requests_request.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    people: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class WorkPlannerCapacity(Base):
    """An override of how many people a department has on one day."""

    __tablename__ = "oe_work_requests_planner_capacity"
    __table_args__ = (
        UniqueConstraint("department", "day", name="uq_oe_work_requests_planner_capacity_department_day"),
    )

    department: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    available: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class WorkRequestCounter(Base):
    """One row per reference prefix. The number is the record.

    Read with a row lock and never goes backwards, so a number is burned
    exactly once even when two people raise in the same second. The
    series is global per department (``WR-WKS-000042`` names one board in
    the whole business), which is what a workshop reads off a job card.
    """

    __tablename__ = "oe_work_requests_counter"
    __table_args__ = (UniqueConstraint("prefix", name="uq_oe_work_requests_counter_prefix"),)

    prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    #: The last number ISSUED. The next mint is value + 1.
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<WorkRequestCounter {self.prefix}={self.value}>"
