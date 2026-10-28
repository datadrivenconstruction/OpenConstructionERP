# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data-access layer for the authority-submission factory."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authority_submission.models import Submission, SubmissionProfile


class ProfileRepository:
    """Data access for global :class:`SubmissionProfile` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, profile_id: uuid.UUID) -> SubmissionProfile | None:
        return await self.session.get(SubmissionProfile, profile_id)

    async def find_builtin(self, name: str, format_key: str) -> SubmissionProfile | None:
        result = await self.session.execute(
            select(SubmissionProfile).where(
                SubmissionProfile.name == name,
                SubmissionProfile.format_key == format_key,
                SubmissionProfile.is_builtin.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self, *, format_key: str | None = None) -> list[SubmissionProfile]:
        stmt = select(SubmissionProfile)
        if format_key is not None:
            stmt = stmt.where(SubmissionProfile.format_key == format_key)
        stmt = stmt.order_by(
            SubmissionProfile.is_builtin.desc(),
            SubmissionProfile.name.asc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    def add(self, profile: SubmissionProfile) -> None:
        self.session.add(profile)


class SubmissionRepository:
    """Data access for project-scoped :class:`Submission` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, submission_id: uuid.UUID) -> Submission | None:
        return await self.session.get(Submission, submission_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        profile_id: uuid.UUID | None = None,
    ) -> list[Submission]:
        stmt = select(Submission).where(Submission.project_id == project_id)
        if status is not None:
            stmt = stmt.where(Submission.status == status)
        if profile_id is not None:
            stmt = stmt.where(Submission.profile_id == profile_id)
        stmt = stmt.order_by(Submission.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    def add(self, submission: Submission) -> None:
        self.session.add(submission)

    async def delete(self, submission: Submission) -> None:
        await self.session.delete(submission)
        await self.session.flush()
