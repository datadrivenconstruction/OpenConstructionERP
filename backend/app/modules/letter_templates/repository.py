# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for letter template overrides."""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.letter_templates.models import LetterTemplateOverride


class LetterTemplateRepository:
    """Reads and writes override rows. NULL ``project_id`` is the company scope."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _scope(project_id: uuid.UUID | None) -> ColumnElement[bool]:
        col = LetterTemplateOverride.project_id
        return col.is_(None) if project_id is None else col == project_id

    async def get(self, key: str, language: str, project_id: uuid.UUID | None) -> LetterTemplateOverride | None:
        """The override for one scope, or ``None``."""
        stmt = (
            select(LetterTemplateOverride)
            .where(
                LetterTemplateOverride.template_key == key,
                LetterTemplateOverride.language == language,
                self._scope(project_id),
            )
            .order_by(LetterTemplateOverride.updated_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def customised(self, project_id: uuid.UUID | None = None) -> list[tuple[str, str]]:
        """``(key, language)`` pairs with an override in the scope."""
        stmt = select(LetterTemplateOverride.template_key, LetterTemplateOverride.language).where(
            self._scope(project_id)
        )
        return [(k, lang) for k, lang in (await self.session.execute(stmt)).all()]

    async def upsert(
        self,
        key: str,
        language: str,
        project_id: uuid.UUID | None,
        fields: dict[str, str],
        user_id: str | None,
    ) -> LetterTemplateOverride:
        """Create or update the override for one scope."""
        row = await self.get(key, language, project_id)
        if row is None:
            row = LetterTemplateOverride(template_key=key, language=language, project_id=project_id)
            self.session.add(row)
        for name, value in fields.items():
            setattr(row, name, value)
        row.updated_by = user_id
        await self.session.flush()
        return row

    async def delete(self, key: str, language: str, project_id: uuid.UUID | None) -> int:
        """Remove the override for one scope (reset to the next level)."""
        stmt = delete(LetterTemplateOverride).where(
            LetterTemplateOverride.template_key == key,
            LetterTemplateOverride.language == language,
            self._scope(project_id),
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)
