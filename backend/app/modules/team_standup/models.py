# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Team Standup ORM models.

Tables:
    oe_team_standup_entry        - one update per person per calendar day
    oe_team_standup_comment      - replies under an entry
    oe_team_standup_entry_file   - attachments on an entry (photos, dockets)
    oe_team_standup_stage        - the configurable delivery stages
    oe_team_standup_activity     - the configurable "where I am" list
    oe_team_standup_wait_reason  - the configurable waiting-on vocabulary
    oe_team_standup_task         - the delivery-board tasks
    oe_team_standup_task_comment - replies under a task
    oe_team_standup_task_file    - attachments on a task
    oe_team_standup_log          - the board's own activity log

``day``/``due`` are plain ISO ``YYYY-MM-DD`` strings, validated in the
service. A standup day is a calendar label people agree on, not an
instant - a string column sidesteps every timezone round-trip between
Python ``date``, asyncpg and JSON, and sorts correctly by construction.

``user_id``/``assignee_id`` are plain GUID strings rather than FKs to
the users table: GDPR self-erasure anonymises a user row in place, and
an old standup entry should survive that unchanged (``author_name`` /
``assignee_name`` are denormalised at write time for the same reason -
the board renders without a users join and without leaking a later name
change into history).

``project_id`` on a task is likewise a plain string, matching how
comms_intelligence refers to correspondence: the task is part of the
team's record of what happened and must not vanish because a project
row was archived or deleted. Labels resolve from the board's jobs
catalogue at read time.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

#: Where the person is that day. ``office`` is the neutral default.
#: Kept for compatibility with V2 clients; the board now reads the
#: multi-select ``activities`` list instead.
ENTRY_STATUSES = ("office", "site", "wfh", "travel", "leave")

#: Hard caps enforced in the service - a standup line is a paragraph,
#: not a document.
MAX_FIELD_CHARS = 4000
MAX_COMMENT_CHARS = 2000

#: Delivery-board vocabularies, validated in the service.
TASK_PRIORITIES = ("urgent", "high", "medium", "low")
REPEAT_RULES = ("", "weekly", "fortnightly", "monthly", "monthly-last")
#: ``request`` is a department work request (the Work requests module -
#: engineering, drafting, workshop, automation, hazardous area); the board
#: carries the request's id in ``link_target_id`` so the chip opens it.
LINK_KINDS = ("", "rfi", "rfq", "order", "vo", "del", "tbx", "request", "mail")
#: A task is public (the whole team sees it) or private (only its creator,
#: its assignee and an admin do). The rail is enforced server-side in
#: board_service - every read path filters, every write path checks.
TASK_VISIBILITIES = ("public", "private")


class StandupEntry(Base):
    """One person's update for one day. Upserted in place on re-save."""

    __tablename__ = "oe_team_standup_entry"
    __table_args__ = (
        UniqueConstraint("user_id", "day", name="uq_oe_team_standup_entry_user_day"),
        # Board hot path: everything for one day.
        Index("ix_team_standup_entry_day", "day"),
    )

    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    day: Mapped[str] = mapped_column(String(10), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="office", server_default="office")
    #: The multi-select "where I am" - StandupActivity ids as strings.
    #: Supersedes ``status`` (kept in step for old readers). NOT NULL with
    #: a server_default so the boot column-heal can add it to a live DB.
    activities: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    yesterday: Mapped[str] = mapped_column(Text, nullable=False, default="")
    today: Mapped[str] = mapped_column(Text, nullable=False, default="")
    blockers: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: When the blocker is needed by (ISO day), or '' for no date.
    blocker_by: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    #: Jobs (project GUID strings) this person is on that day. Validated
    #: against ACTIVE projects at write time; labels resolve at read time
    #: from the board's jobs catalogue, so a renamed job renders its
    #: current name everywhere.
    job_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )

    comments: Mapped[list["StandupComment"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="StandupComment.created_at",
        lazy="selectin",
    )
    files: Mapped[list["StandupEntryFile"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="StandupEntryFile.created_at",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<StandupEntry {self.author_name or self.user_id} {self.day} {self.status}>"


class StandupComment(Base):
    """A reply under a standup entry."""

    __tablename__ = "oe_team_standup_comment"

    entry_id: Mapped[str] = mapped_column(
        GUID(),
        ForeignKey("oe_team_standup_entry.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")

    entry: Mapped[StandupEntry] = relationship(back_populates="comments")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<StandupComment by {self.author_name or self.user_id} on {self.entry_id}>"


class StandupEntryFile(Base):
    """An attachment on a standup entry (photo, docket, drawing).

    Column set follows field_diary's DiaryAttachment: ``filename`` is the
    client's name and informational only; ``storage_key`` is the
    server-derived relative path under the module uploads dir and is the
    only thing trusted to touch the disk.
    """

    __tablename__ = "oe_team_standup_entry_file"

    entry_id: Mapped[str] = mapped_column(
        GUID(),
        ForeignKey("oe_team_standup_entry.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    mime_type: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="application/octet-stream",
        server_default="application/octet-stream",
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    uploaded_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")

    entry: Mapped[StandupEntry] = relationship(back_populates="files")


class StandupStage(Base):
    """One column of the delivery board. Fully configurable.

    ``spawn`` is the stage template: task titles that are auto-created
    whenever a task ENTERS this stage (the rail lives in the service's
    move_task, the single path every stage change goes through).
    ``is_done`` marks the stages that close a task.

    ``project_id`` scopes a row: '' is the standard set every job uses;
    a project GUID makes the row part of THAT job's own stage run (a
    per-job override). A job with any override rows uses only those; a
    job with none uses the standard set. Same plain-string convention as
    ``StandupTask.project_id`` - no FK, so an archived project's stages
    stay readable.
    """

    __tablename__ = "oe_team_standup_stage"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, default="", server_default="", index=True)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="slate")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", index=True)
    wip_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    spawn: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )


class StandupActivity(Base):
    """One "where I am" option (office, site, on leave...). Configurable.

    ``exclusive`` means picking it clears every other selection - "on
    leave" is not a mixed day.
    """

    __tablename__ = "oe_team_standup_activity"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="slate")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", index=True)
    exclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class StandupWaitReason(Base):
    """One entry in the team's waiting-on vocabulary."""

    __tablename__ = "oe_team_standup_wait_reason"

    label: Mapped[str] = mapped_column(String(160), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", index=True)


class StandupTask(Base):
    """A delivery-board task.

    Richer than the native oe_tasks row on purpose: stage, waiting flag,
    recurrence, record link and priority are delivery-board concepts that
    do not exist upstream, and adding them to the native table would make
    every upstream merge a fight. The board owns its tasks.

    ``origin``/``origin_task_id`` record HOW a task came to exist
    ('spawn' from a stage template, 'repeat' from a recurrence rule) so
    the move-undo endpoint can verify it is deleting exactly what the
    move created and nothing else.
    """

    __tablename__ = "oe_team_standup_task"
    __table_args__ = (
        Index("ix_team_standup_task_stage", "stage_id"),
        Index("ix_team_standup_task_project", "project_id"),
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    stage_id: Mapped[str] = mapped_column(
        GUID(),
        ForeignKey("oe_team_standup_stage.id", ondelete="RESTRICT"),
        nullable=False,
    )
    assignee_id: Mapped[str] = mapped_column(String(36), nullable=False, default="", index=True)
    assignee_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    due: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="medium", server_default="medium")
    waiting_on: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    repeat_rule: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    link_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    link_ref: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    link_target_id: Mapped[str] = mapped_column(String(36), nullable=False, default="", server_default="")
    #: A follow-up created by a stage template (renders with the sub glyph).
    is_sub: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    #: 'public' (default) or 'private'. NOT NULL with a server_default so
    #: the boot column-heal (ADD COLUMN IF NOT EXISTS) can add it to a
    #: live database - every existing task stays public.
    visibility: Mapped[str] = mapped_column(String(10), nullable=False, default="public", server_default="public")
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    origin_task_id: Mapped[str] = mapped_column(String(36), nullable=False, default="", server_default="")
    #: Soft delete - "Delete" on the board is undoable, and a deleted task
    #: keeps its comments and files for the undo instead of cascading them
    #: away. The board never serves deleted rows.
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")

    comments: Mapped[list["StandupTaskComment"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="StandupTaskComment.created_at",
        lazy="selectin",
    )
    files: Mapped[list["StandupTaskFile"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="StandupTaskFile.created_at",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<StandupTask {self.title!r} stage={self.stage_id}>"


class StandupTaskComment(Base):
    """A reply under a delivery-board task."""

    __tablename__ = "oe_team_standup_task_comment"

    task_id: Mapped[str] = mapped_column(
        GUID(),
        ForeignKey("oe_team_standup_task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")

    task: Mapped[StandupTask] = relationship(back_populates="comments")


class StandupTaskFile(Base):
    """An attachment on a delivery-board task. Same shape as entry files."""

    __tablename__ = "oe_team_standup_task_file"

    task_id: Mapped[str] = mapped_column(
        GUID(),
        ForeignKey("oe_team_standup_task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    mime_type: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="application/octet-stream",
        server_default="application/octet-stream",
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    uploaded_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")

    task: Mapped[StandupTask] = relationship(back_populates="files")


class StandupLog(Base):
    """One line of the board's own activity log.

    Written server-side by every mutation path - who did what, when,
    where - so the log survives a refresh and cannot be edited from the
    client. ``where_label`` is a job code, 'Standup' or 'Settings';
    ``kind`` buckets the log filter (task/standup/config); ``color`` is
    the palette key the UI paints the dot with.
    """

    __tablename__ = "oe_team_standup_log"
    __table_args__ = (Index("ix_team_standup_log_created", "created_at"),)

    user_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    author_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    what: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    where_label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="task")
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="slate")
    #: The task a line is about ('' for config/standup lines). A line
    #: names the task's title, so the log follows the task's visibility:
    #: lines about a private task are served only to those who may see it.
    task_id: Mapped[str] = mapped_column(String(36), nullable=False, default="", server_default="")
