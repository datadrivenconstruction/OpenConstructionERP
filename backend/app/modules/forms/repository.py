# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Forms & Checklists data access layer."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.orm_write import apply_update
from app.modules.forms.models import FormSubmission, FormTemplate

# How many times a colliding submission number is re-derived before giving up.
_NUMBER_RETRY_LIMIT = 5


def _next_suffix(numbers: list[str]) -> int:
    """MAX(trailing integer) + 1 over a list of ``PREFIX-NNN`` codes.

    Robust to deletions (the highest issued suffix is never reused) and to rows
    whose number doesn't match ``PREFIX-<int>`` (ignored). 1 when nothing parses.
    """
    highest = 0
    for number in numbers:
        if not number:
            continue
        suffix = number.rsplit("-", 1)[-1]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest + 1


class FormsRepository:
    """Data access for form templates and submissions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Templates ────────────────────────────────────────────────────────────

    async def get_template(self, template_id: uuid.UUID) -> FormTemplate | None:
        """Get a template by id."""
        return await self.session.get(FormTemplate, template_id)

    async def list_templates(
        self,
        *,
        project_id: uuid.UUID | None = None,
        include_global: bool = True,
        category: str | None = None,
        status: str | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[FormTemplate], int]:
        """List library templates.

        The library a project sees is its own templates plus the organisation-
        wide (null-project) ones. Pass ``project_id=None`` with
        ``include_global=True`` to browse only the global library.
        """
        base = select(FormTemplate)
        if project_id is not None:
            base = (
                base.where(or_(FormTemplate.project_id == project_id, FormTemplate.project_id.is_(None)))
                if include_global
                else base.where(FormTemplate.project_id == project_id)
            )
        elif include_global:
            base = base.where(FormTemplate.project_id.is_(None))

        if category is not None:
            base = base.where(FormTemplate.category == category)
        if status is not None:
            base = base.where(FormTemplate.status == status)
        if search:
            like = f"%{search.strip().lower()}%"
            base = base.where(
                or_(
                    func.lower(FormTemplate.name).like(like),
                    func.lower(func.coalesce(FormTemplate.description, "")).like(like),
                )
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(FormTemplate.category, FormTemplate.name).offset(offset).limit(limit)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, total

    async def category_counts(self, project_id: uuid.UUID | None) -> dict[str, int]:
        """Count published/draft templates per category in the visible library."""
        stmt = select(FormTemplate.category, func.count()).group_by(FormTemplate.category)
        if project_id is not None:
            stmt = stmt.where(or_(FormTemplate.project_id == project_id, FormTemplate.project_id.is_(None)))
        else:
            stmt = stmt.where(FormTemplate.project_id.is_(None))
        rows = (await self.session.execute(stmt)).all()
        return {str(cat): int(count) for cat, count in rows}

    async def add_template(self, template: FormTemplate) -> FormTemplate:
        """Insert a template."""
        self.session.add(template)
        await self.session.flush()
        return template

    async def update_template_fields(self, template_id: uuid.UUID, **fields: object) -> None:
        """Update specific columns on a template."""
        await apply_update(self.session, FormTemplate, template_id, **fields)

    async def delete_template(self, template_id: uuid.UUID) -> None:
        """Hard delete a template. Submissions keep their snapshot (FK SET NULL)."""
        template = await self.get_template(template_id)
        if template is not None:
            await self.session.delete(template)
            await self.session.flush()

    async def count_seed_templates(self) -> int:
        """How many built-in starter templates exist (0 == never seeded)."""
        stmt = select(func.count()).select_from(FormTemplate).where(FormTemplate.is_seed.is_(True))
        return int((await self.session.execute(stmt)).scalar_one())

    # ── Submissions ──────────────────────────────────────────────────────────

    async def get_submission(self, submission_id: uuid.UUID) -> FormSubmission | None:
        """Get a submission by id."""
        return await self.session.get(FormSubmission, submission_id)

    async def list_submissions(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        category: str | None = None,
        template_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[FormSubmission], int]:
        """List submissions for a project with optional filters."""
        base = select(FormSubmission).where(FormSubmission.project_id == project_id)
        if status is not None:
            base = base.where(FormSubmission.status == status)
        if category is not None:
            base = base.where(FormSubmission.template_category == category)
        if template_id is not None:
            base = base.where(FormSubmission.template_id == template_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(FormSubmission.created_at.desc()).offset(offset).limit(limit)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, total

    async def next_submission_number(self, project_id: uuid.UUID) -> str:
        """Next per-project submission number (FRM-001, FRM-002, ...).

        MAX(suffix)+1 rather than COUNT+1 so a delete never re-issues a used
        number and a failed insert can still advance on retry (mirrors
        inspections).
        """
        stmt = select(FormSubmission.submission_number).where(FormSubmission.project_id == project_id)
        numbers = (await self.session.execute(stmt)).scalars().all()
        return f"FRM-{_next_suffix(numbers):03d}"

    async def add_submission(self, submission: FormSubmission) -> FormSubmission:
        """Insert a submission, deriving its number with a retry on collision.

        MAX(suffix)+1 can race two concurrent creates onto the same value; the
        per-project unique constraint turns that into an IntegrityError, which
        we roll back and retry with a freshly-read maximum.
        """
        project_id = submission.project_id
        for _ in range(_NUMBER_RETRY_LIMIT):
            submission.submission_number = await self.next_submission_number(project_id)
            savepoint = await self.session.begin_nested()
            self.session.add(submission)
            try:
                await self.session.flush()
            except IntegrityError:
                await savepoint.rollback()
                continue
            return submission
        raise RuntimeError(f"Could not allocate a unique submission number for project {project_id}")

    async def update_submission_fields(self, submission_id: uuid.UUID, **fields: object) -> None:
        """Update specific columns on a submission."""
        await apply_update(self.session, FormSubmission, submission_id, **fields)

    async def delete_submission(self, submission_id: uuid.UUID) -> None:
        """Hard delete a submission."""
        submission = await self.get_submission(submission_id)
        if submission is not None:
            await self.session.delete(submission)
            await self.session.flush()
