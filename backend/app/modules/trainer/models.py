# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Trainer ORM models.

Tables (all prefixed ``oe_trainer_``):
    course          -- one row per loaded course file version
    offer           -- store product -> course mapping (a product may bundle courses)
    enrolment       -- one learner on one course, with the refs the seeder wrote
    task_state      -- per enrolment and task: lock state, seed state, progress
    answer          -- the learner's typed panel answers, keyed by answer name
    attempt         -- every check run and its per-item result
    webhook_event   -- store webhook log and idempotency record

Every multi-column constraint and composite index carries an explicit name.
The metadata naming convention only spells ``column_0``, so leaving these to
the convention would give two different constraints the same name. The
Alembic revision ``v53_trainer_tables`` creates the same names.

String vocabularies (statuses, triggers, kinds) are plain ``String`` columns,
as everywhere else in the tree. The allowed values are the ``Literal`` types
in ``schemas.py``.
"""

from __future__ import annotations

import uuid
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


class TrainerCourse(Base):
    """One loaded version of one course file.

    The parsed spec is stored here, so an enrolment pinned to ``sha256`` keeps
    grading against the content it started on after the file is replaced.
    """

    __tablename__ = "oe_trainer_course"
    __table_args__ = (UniqueConstraint("course_key", "version", name="uq_oe_trainer_course_course_key_version"),)

    course_key: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Basename only. An absolute path would publish the server layout.
    source_file: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    spec: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    validation_report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    # active | retired | invalid. An invalid course is never offered or enrolled.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<TrainerCourse {self.course_key} v{self.version} ({self.status})>"


class TrainerOffer(Base):
    """A store product that grants a course."""

    __tablename__ = "oe_trainer_offer"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "product_ref",
            "course_key",
            name="uq_oe_trainer_offer_provider_product_ref_course_key",
        ),
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    product_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    course_key: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<TrainerOffer {self.provider}:{self.product_ref} -> {self.course_key}>"


class TrainerEnrolment(Base):
    """One learner on one course.

    ``course_sha256`` pins the course content at enrolment, so a reload never
    changes the course under a learner who has already started.
    ``seeded_refs`` maps stable keys (``boq.main``, ``contract.main``, ...) to
    the ids the seeder created; every probe reads through it, never by name.
    """

    __tablename__ = "oe_trainer_enrolment"
    # The two ``project_id`` composites, and ``index=True`` on ``user_id`` and
    # ``course_id``, are the indexes ``app.core.pg_optimizations`` would add on
    # ``create_all`` anyway. Declaring them here puts them in the migration too,
    # so a database built by walking the chain matches one built by create_all.
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_oe_trainer_enrolment_user_id_course_id"),
        Index("ix_oe_trainer_enrolment_project_id_status", "project_id", "status"),
        Index("ix_oe_trainer_enrolment_project_id_created_at", "project_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_trainer_course.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    course_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # queued | provisioning | active | completed | revoked | failed.
    # ``queued``: a second paid course waits while another one is active.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="provisioning", index=True)
    seeded_refs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    current_task_n: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # webhook | admin
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    order_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Set by ERP events that may have changed a graded value, cleared by a check.
    stale_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # The enrolment is always read with its tasks, so one extra SELECT is cheaper
    # than a miss. Deleting an enrolment deletes its task states.
    task_states: Mapped[list[TrainerTaskState]] = relationship(
        back_populates="enrolment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="TrainerTaskState.task_n",
    )

    def __repr__(self) -> str:
        return f"<TrainerEnrolment user={self.user_id} course={self.course_id} ({self.status})>"


class TrainerTaskState(Base):
    """Lock, seed and progress state of one task for one enrolment.

    ``unlock_seen_at`` records that the learner has seen the unlock this task's
    pass produced (the lock named by the task's ``opens``). ``hints_revealed``
    counts the hints the learner has been shown; the task view never sends a
    hint past it. ``answers_revision`` is the optimistic-concurrency token of
    the answers PUT: a PUT carrying any other revision is refused with 409.
    """

    __tablename__ = "oe_trainer_task_state"
    __table_args__ = (
        UniqueConstraint("enrolment_id", "task_id", name="uq_oe_trainer_task_state_enrolment_id_task_id"),
        Index("ix_oe_trainer_task_state_enrolment_id_task_n", "enrolment_id", "task_n"),
    )

    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_trainer_enrolment.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(String(16), nullable=False)
    task_n: Mapped[int] = mapped_column(Integer, nullable=False)
    # locked | unlocked | passed
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="locked")
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    passed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unlock_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # none | pending | done | failed
    seed_status: Mapped[str] = mapped_column(String(12), nullable=False, default="none")
    seed_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_passed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hints_revealed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answers_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Plain id, no foreign key: attempts are a log and are read through the
    # repository, not through a relationship.
    last_attempt_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    # Scalar back-reference: the FK is already in the column, so walking up
    # implicitly is refused rather than lazily loaded inside an async session.
    enrolment: Mapped[TrainerEnrolment] = relationship(back_populates="task_states", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<TrainerTaskState {self.task_id} ({self.state})>"


class TrainerAnswer(Base):
    """One typed panel answer.

    Keyed by answer ``name`` rather than ledger key, because one task may grade
    the same ledger key twice under two names. ``value_text`` is exactly what
    the learner typed after trimming and separator normalisation; the checker
    parses it with ``Decimal``. There is deliberately no numeric column, so
    nothing is rounded on the way in. ``revision`` is the task's
    ``answers_revision`` at which this row was last written.
    """

    __tablename__ = "oe_trainer_answer"
    __table_args__ = (
        UniqueConstraint(
            "enrolment_id",
            "task_id",
            "answer_name",
            name="uq_oe_trainer_answer_enrolment_id_task_id_answer_name",
        ),
    )

    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_trainer_enrolment.id", ondelete="CASCADE"),
        nullable=False,
        # Also what pg_optimizations would add for an unindexed foreign key.
        index=True,
    )
    task_id: Mapped[str] = mapped_column(String(16), nullable=False)
    answer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # number | option | text
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    value_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    option_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    def __repr__(self) -> str:
        return f"<TrainerAnswer {self.task_id}/{self.answer_name}>"


class TrainerAttempt(Base):
    """One run of the checker over one task.

    ``client_attempt_id`` makes "Check my work" idempotent: a retried POST with
    the same id returns the stored attempt instead of grading twice. It is null
    for attempts the server starts itself (event rechecks, admin rechecks).
    ``result`` holds the per-item list; ``observed`` values in it are strings,
    never floats, and no expected value is ever stored for the client.
    """

    __tablename__ = "oe_trainer_attempt"
    __table_args__ = (
        Index(
            "ix_oe_trainer_attempt_enrolment_id_task_id_created_at",
            "enrolment_id",
            "task_id",
            "created_at",
        ),
        UniqueConstraint(
            "enrolment_id",
            "client_attempt_id",
            name="uq_oe_trainer_attempt_enrolment_id_client_attempt_id",
        ),
    )

    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_trainer_enrolment.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(String(16), nullable=False)
    client_attempt_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # manual | event | unlock | admin
    trigger: Mapped[str] = mapped_column(String(12), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    graded_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    spec_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<TrainerAttempt {self.task_id} passed={self.passed}>"


class TrainerWebhookEvent(Base):
    """One store webhook delivery.

    The unique ``(provider, event_id)`` pair is the idempotency guarantee: the
    row is inserted first, and an IntegrityError means a duplicate delivery.
    A delivery with a bad signature is logged without its payload. User and
    enrolment ids are plain ids so the log outlives the rows it points at.
    """

    __tablename__ = "oe_trainer_webhook_event"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_oe_trainer_webhook_event_provider_event_id"),)

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # received | processed | duplicate | ignored | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="received")
    # Lowercased.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Address, phone, card and tax-id fields removed before storing.
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    enrolment_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<TrainerWebhookEvent {self.provider}:{self.event_id} ({self.status})>"
