# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Trainer data access.

Every query the service runs lives here, so the service reads as the course
rules and not as SQL. Nothing here commits; the caller owns the transaction.

Catalog and enrolment queries only ever look at ``status == "active"``
courses (decision 35): an invalid or retired course is never offered, and an
enrolment is only started on an active one. Grading an enrolment that is
already running reads its pinned course row by id, whatever that row's
status is now, because a learner keeps the content they started on.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.trainer.models import (
    TrainerAnswer,
    TrainerAttempt,
    TrainerCourse,
    TrainerEnrolment,
    TrainerTaskState,
)
from app.modules.users.models import User

#: Enrolment states a learner works in. ``completed`` stays readable so the
#: learner still sees the course map and the badge after the last task.
LEARNER_VISIBLE_STATUSES: tuple[str, ...] = ("active", "completed")


class TrainerRepository:
    """Queries over the ``oe_trainer_*`` tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Courses ──────────────────────────────────────────────────────────────

    async def course(self, course_id: uuid.UUID) -> TrainerCourse | None:
        """One course row by id, whatever its status (an enrolment's pinned row)."""
        return await self.session.get(TrainerCourse, course_id)

    async def active_courses(self) -> list[TrainerCourse]:
        """Every course a learner may be offered (decision 35), newest load first."""
        rows = await self.session.execute(
            select(TrainerCourse)
            .where(TrainerCourse.status == "active")
            .order_by(TrainerCourse.course_key, TrainerCourse.loaded_at.desc())
        )
        return list(rows.scalars().all())

    # ── Enrolments ───────────────────────────────────────────────────────────

    async def enrolment(self, enrolment_id: uuid.UUID, *, for_update: bool = False) -> TrainerEnrolment | None:
        """One enrolment by id, optionally locked for the rest of the transaction."""
        stmt = select(TrainerEnrolment).where(TrainerEnrolment.id == enrolment_id)
        if for_update:
            # A locked read must see the row as it is now, not the identity
            # map's copy from earlier in the session.
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def learner_enrolment(self, user_id: uuid.UUID, *, for_update: bool = False) -> TrainerEnrolment | None:
        """The enrolment the learner works in now (decision 4).

        One course runs at a time: the ``active`` enrolment if there is one,
        else the most recently completed one. A queued, suspended, failed or
        revoked enrolment is never the learner's current course.
        """
        stmt = (
            select(TrainerEnrolment)
            .where(
                TrainerEnrolment.user_id == user_id,
                TrainerEnrolment.status.in_(LEARNER_VISIBLE_STATUSES),
            )
            # "active" sorts before "completed".
            .order_by(TrainerEnrolment.status.asc(), TrainerEnrolment.completed_at.desc().nulls_last())
            .limit(1)
        )
        if for_update:
            # A locked read must see the row as it is now, not the identity
            # map's copy from earlier in the session.
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def next_queued_enrolment(self, user_id: uuid.UUID) -> TrainerEnrolment | None:
        """The learner's oldest queued enrolment on a course that is still active (decision 43)."""
        stmt = (
            select(TrainerEnrolment)
            .join(TrainerCourse, TrainerCourse.id == TrainerEnrolment.course_id)
            .where(
                TrainerEnrolment.user_id == user_id,
                TrainerEnrolment.status == "queued",
                TrainerCourse.status == "active",
            )
            .order_by(TrainerEnrolment.created_at.asc())
            .limit(1)
            .with_for_update(of=TrainerEnrolment)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def running_enrolment_ids_for_project(self, project_id: uuid.UUID) -> list[uuid.UUID]:
        """Active enrolments working in ``project_id`` (event resolution, design §6)."""
        rows = await self.session.execute(
            select(TrainerEnrolment.id).where(
                TrainerEnrolment.project_id == project_id,
                TrainerEnrolment.status == "active",
            )
        )
        return list(rows.scalars().all())

    async def mark_stale(self, enrolment_ids: Iterable[uuid.UUID], when: datetime) -> None:
        """Stamp ``stale_since`` on the enrolments that have none yet."""
        ids = list(enrolment_ids)
        if not ids:
            return
        await self.session.execute(
            update(TrainerEnrolment)
            .where(TrainerEnrolment.id.in_(ids), TrainerEnrolment.stale_since.is_(None))
            .values(stale_since=when)
            .execution_options(synchronize_session=False)
        )

    async def admin_enrolments(
        self,
        *,
        status: str | None = None,
        email: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[TrainerEnrolment, str, str, str]]:
        """Enrolments with the learner's email and the course key and version, newest first."""
        stmt = (
            select(TrainerEnrolment, User.email, TrainerCourse.course_key, TrainerCourse.version)
            .join(User, User.id == TrainerEnrolment.user_id)
            .join(TrainerCourse, TrainerCourse.id == TrainerEnrolment.course_id)
            .order_by(TrainerEnrolment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            stmt = stmt.where(TrainerEnrolment.status == status)
        if email:
            stmt = stmt.where(User.email == email.strip().lower())
        rows = await self.session.execute(stmt)
        return [(row[0], row[1], row[2], row[3]) for row in rows.all()]

    async def admin_enrolment(self, enrolment_id: uuid.UUID) -> tuple[TrainerEnrolment, str, str, str] | None:
        """One enrolment with the learner's email and the course key and version."""
        row = (
            await self.session.execute(
                select(TrainerEnrolment, User.email, TrainerCourse.course_key, TrainerCourse.version)
                .join(User, User.id == TrainerEnrolment.user_id)
                .join(TrainerCourse, TrainerCourse.id == TrainerEnrolment.course_id)
                .where(TrainerEnrolment.id == enrolment_id)
            )
        ).one_or_none()
        return (row[0], row[1], row[2], row[3]) if row is not None else None

    # ── Task states ──────────────────────────────────────────────────────────

    async def task_states(self, enrolment_id: uuid.UUID) -> list[TrainerTaskState]:
        """Every task state of an enrolment, by task number."""
        rows = await self.session.execute(
            select(TrainerTaskState)
            .where(TrainerTaskState.enrolment_id == enrolment_id)
            .order_by(TrainerTaskState.task_n)
            .execution_options(populate_existing=True)
        )
        return list(rows.scalars().all())

    # ── Answers ──────────────────────────────────────────────────────────────

    async def answers(self, enrolment_id: uuid.UUID, task_id: str) -> list[TrainerAnswer]:
        """The stored answers of one task, by name."""
        rows = await self.session.execute(
            select(TrainerAnswer)
            .where(TrainerAnswer.enrolment_id == enrolment_id, TrainerAnswer.task_id == task_id)
            .order_by(TrainerAnswer.answer_name)
        )
        return list(rows.scalars().all())

    async def answered_task_ids(self, enrolment_id: uuid.UUID) -> set[str]:
        """Task ids with at least one stored answer."""
        rows = await self.session.execute(
            select(TrainerAnswer.task_id).where(TrainerAnswer.enrolment_id == enrolment_id).distinct()
        )
        return set(rows.scalars().all())

    async def replace_answers(self, enrolment_id: uuid.UUID, task_id: str, answers: Sequence[TrainerAnswer]) -> None:
        """Replace a task's whole answer set (decision 28)."""
        await self.session.execute(
            delete(TrainerAnswer).where(TrainerAnswer.enrolment_id == enrolment_id, TrainerAnswer.task_id == task_id)
        )
        self.session.add_all(list(answers))
        await self.session.flush()

    # ── Attempts ─────────────────────────────────────────────────────────────

    async def attempt_by_client_id(
        self, enrolment_id: uuid.UUID, client_attempt_id: uuid.UUID
    ) -> TrainerAttempt | None:
        """The attempt a retried "Check" already recorded, if any."""
        return (
            await self.session.execute(
                select(TrainerAttempt).where(
                    TrainerAttempt.enrolment_id == enrolment_id,
                    TrainerAttempt.client_attempt_id == client_attempt_id,
                )
            )
        ).scalar_one_or_none()

    async def attempts(self, enrolment_id: uuid.UUID, *, triggers: Iterable[str] | None = None) -> list[TrainerAttempt]:
        """Every attempt of an enrolment, oldest first, optionally by trigger."""
        stmt = select(TrainerAttempt).where(TrainerAttempt.enrolment_id == enrolment_id)
        if triggers is not None:
            stmt = stmt.where(TrainerAttempt.trigger.in_(list(triggers)))
        rows = await self.session.execute(stmt.order_by(TrainerAttempt.created_at.asc()))
        return list(rows.scalars().all())

    async def add_attempt(self, attempt: TrainerAttempt) -> TrainerAttempt:
        """Insert an attempt and flush it."""
        self.session.add(attempt)
        await self.session.flush()
        return attempt
