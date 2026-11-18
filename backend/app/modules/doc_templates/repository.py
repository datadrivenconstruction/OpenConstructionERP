# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for document templates and their versions."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.doc_templates.models import (
    WORKSPACE_SCOPE,
    DocClause,
    DocLayout,
    DocLayoutVersion,
    DocTemplate,
    DocTemplateVersion,
)


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


class DocLayoutRepository:
    """Layout rows are keyed by ``(kind, scope, variant)``; versions by ``(layout, number)``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, kind: str, scope: str, variant: str) -> DocLayout | None:
        """One layout row."""
        stmt = select(DocLayout).where(DocLayout.kind == kind, DocLayout.scope == scope, DocLayout.variant == variant)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def in_scopes(self, kind: str, scopes: list[str]) -> list[DocLayout]:
        """Every variant of a kind in the given scopes, oldest first."""
        stmt = (
            select(DocLayout)
            .where(DocLayout.kind == kind, DocLayout.scope.in_(scopes))
            .order_by(DocLayout.created_at, DocLayout.variant)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def all_rows(self) -> list[DocLayout]:
        """Every layout row, for the documents list."""
        return list((await self.session.execute(select(DocLayout))).scalars().all())

    async def create(self, kind: str, scope: str, variant: str, name: str = "") -> DocLayout:
        """A new layout row without a draft or a version."""
        row = DocLayout(kind=kind, scope=scope, variant=variant, name=name, is_default=False)
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, row: DocLayout) -> None:
        """Delete a layout and its versions."""
        await self.session.execute(delete(DocLayoutVersion).where(DocLayoutVersion.layout_id == row.id))
        await self.session.delete(row)
        await self.session.flush()

    async def version(self, version_id: uuid.UUID) -> DocLayoutVersion | None:
        """One version by id."""
        return await self.session.get(DocLayoutVersion, version_id)

    async def versions(self, layout_id: uuid.UUID) -> list[DocLayoutVersion]:
        """Versions of a layout, newest first."""
        stmt = (
            select(DocLayoutVersion)
            .where(DocLayoutVersion.layout_id == layout_id)
            .order_by(DocLayoutVersion.number.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def next_number(self, layout_id: uuid.UUID) -> int:
        """The number the next version takes."""
        stmt = select(func.max(DocLayoutVersion.number)).where(DocLayoutVersion.layout_id == layout_id)
        return int((await self.session.execute(stmt)).scalar() or 0) + 1

    async def add_version(self, version: DocLayoutVersion) -> DocLayoutVersion:
        """Persist a new version."""
        self.session.add(version)
        await self.session.flush()
        return version

    async def prune(self, layout_id: uuid.UUID, keep: int, protect: set[uuid.UUID]) -> int:
        """Delete the oldest versions beyond *keep*, never one in *protect*."""
        rows = await self.versions(layout_id)
        doomed = [v.id for v in rows[keep:] if v.id not in protect]
        if not doomed:
            return 0
        await self.session.execute(delete(DocLayoutVersion).where(DocLayoutVersion.id.in_(doomed)))
        await self.session.flush()
        return len(doomed)

    async def clauses(self) -> list[DocClause]:
        """The clause library, by key."""
        return list((await self.session.execute(select(DocClause).order_by(DocClause.key))).scalars().all())

    async def clause(self, key: str) -> DocClause | None:
        """One clause by key."""
        stmt = select(DocClause).where(DocClause.key == key)
        return (await self.session.execute(stmt)).scalar_one_or_none()
