# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What other modules read about a project's legal entity.

Finance numbers and taxes documents by the entity that owns the project, but
legal entities is a module an install can leave out. Callers import this module
inside a ``try`` and treat an ``ImportError`` as "no entity", so the lookups
here return ``None`` rather than raise when nothing is known.

Two answers, deliberately different in how far they fall back:

* :func:`assigned_entity_code` answers only for a project that names its
  entity. A document number is a legal record, and a project that names none
  keeps the numbers it always had, so the default entity never stamps one.
* :func:`entity_country` falls back to the default entity, because it is asked
  only when the project itself records no country and something is better than
  no tax rate at all.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.legal_entities.models import LegalEntity
from app.modules.legal_entities.repository import LegalEntityRepository
from app.modules.projects.models import Project


async def _assigned(session: AsyncSession, project_id: uuid.UUID) -> LegalEntity | None:
    project = await session.get(Project, project_id)
    if project is None or project.legal_entity_id is None:
        return None
    return await LegalEntityRepository(session).get(project.legal_entity_id)


async def assigned_entity_code(session: AsyncSession, project_id: uuid.UUID) -> str | None:
    """The code of the entity the project names, or None when it names none."""
    entity = await _assigned(session, project_id)
    return entity.code if entity is not None else None


async def entity_country(session: AsyncSession, project_id: uuid.UUID) -> str | None:
    """The country of the project's entity, the default entity's when it names none."""
    entity = await _assigned(session, project_id)
    if entity is None:
        entity = await LegalEntityRepository(session).get_default()
    return entity.country_code if entity is not None else None
