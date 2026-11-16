# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for document templates and their versions."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.doc_templates.models import WORKSPACE_SCOPE, DocTemplate, DocTemplateVersion


class DocTemplateRepository:
    """Template rows are keyed by ``(kind, scope, locale)``; versions by ``(template, number)``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, kind: str, locale: str, scope: str = WORKSPACE_SCOPE) -> DocTemplate | None:
        """The template row for one kind, scope and locale."""
        stmt = select(DocTemplate).where(
            DocTemplate.kind == kind, DocTemplate.scope == scope, DocTemplate.locale == locale
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def for_kind(self, kind: str, scope: str = WORKSPACE_SCOPE) -> list[DocTemplate]:
        """Every locale row of a kind, oldest first."""
        stmt = (
            select(DocTemplate)
            .where(DocTemplate.kind == kind, DocTemplate.scope == scope)
            .order_by(DocTemplate.created_at, DocTemplate.locale)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def all_rows(self, scope: str = WORKSPACE_SCOPE) -> list[DocTemplate]:
        """Every template row in a scope."""
        stmt = select(DocTemplate).where(DocTemplate.scope == scope).order_by(DocTemplate.created_at)
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(self, kind: str, channel: str, locale: str, scope: str = WORKSPACE_SCOPE) -> DocTemplate:
        """A new empty template row."""
        row = DocTemplate(kind=kind, channel=channel, scope=scope, locale=locale)
        self.session.add(row)
        await self.session.flush()
        return row

    async def version(self, version_id: uuid.UUID) -> DocTemplateVersion | None:
        """One version by id."""
        return await self.session.get(DocTemplateVersion, version_id)

    async def versions(self, template_id: uuid.UUID) -> list[DocTemplateVersion]:
        """Versions of a template, newest first."""
        stmt = (
            select(DocTemplateVersion)
            .where(DocTemplateVersion.template_id == template_id)
            .order_by(DocTemplateVersion.number.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def versions_by_ids(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, DocTemplateVersion]:
        """Versions by id, for the list view."""
        if not ids:
            return {}
        stmt = select(DocTemplateVersion).where(DocTemplateVersion.id.in_(ids))
        return {v.id: v for v in (await self.session.execute(stmt)).scalars().all()}

    async def next_number(self, template_id: uuid.UUID) -> int:
        """The number the next version takes."""
        stmt = select(func.max(DocTemplateVersion.number)).where(DocTemplateVersion.template_id == template_id)
        return int((await self.session.execute(stmt)).scalar() or 0) + 1

    async def add_version(self, version: DocTemplateVersion) -> DocTemplateVersion:
        """Persist a new version."""
        self.session.add(version)
        await self.session.flush()
        return version

    async def prune(self, template_id: uuid.UUID, keep: int, protect: set[uuid.UUID]) -> int:
        """Delete the oldest versions beyond *keep*, never one in *protect*."""
        rows = await self.versions(template_id)
        doomed = [v.id for v in rows[keep:] if v.id not in protect]
        if not doomed:
            return 0
        await self.session.execute(delete(DocTemplateVersion).where(DocTemplateVersion.id.in_(doomed)))
        await self.session.flush()
        return len(doomed)
