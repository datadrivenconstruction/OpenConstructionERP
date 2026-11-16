# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which projects a person reaches through the companies they work for.

Membership only ever adds: a person sees the projects they own and the
projects they are on the team of, as before, plus every project of each
entity they are a member of. A project that names no entity belongs to the
default entity, so a member of the default entity reaches it too.

So an install where nobody holds a membership answers every access question
exactly as it did before entities existed, and adding the first member to a
company hides nothing from anyone.

The helpers here are composed into the platform's one access rule in
:mod:`app.modules.teams.access` and :mod:`app.modules.projects.access`; they
decide nothing on their own.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import aliased

from app.modules.legal_entities.models import LegalEntity, LegalEntityMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql import Select
    from sqlalchemy.sql.elements import ColumnElement


def _default_entity_id() -> Any:
    return select(LegalEntity.id).where(LegalEntity.is_default.is_(True)).limit(1).scalar_subquery()


def _owns(project: Any, member: Any) -> ColumnElement[bool]:
    """The project belongs to the member's entity, a project naming none to the default one."""
    return or_(
        project.legal_entity_id == member.legal_entity_id,
        and_(project.legal_entity_id.is_(None), member.legal_entity_id == _default_entity_id()),
    )


def entity_project_ids_select(user_id: uuid.UUID, *, live_only: bool = False) -> Select:
    """A select of the ids of every project of the entities *user_id* is a member of."""
    from app.modules.projects.models import Project

    stmt = (
        select(Project.id)
        .join(LegalEntityMember, _owns(Project, LegalEntityMember))
        .where(LegalEntityMember.user_id == user_id)
    )
    if live_only:
        stmt = stmt.where(Project.status != "archived")
    return stmt


def entity_membership_exists(project_id_column: ColumnElement[Any], user_id: uuid.UUID | None) -> ColumnElement[bool]:
    """A boolean column: does *user_id* reach the project in *project_id_column* through an entity.

    The inner project is an alias, so the test stays correlated to the outer
    statement even when that statement selects from the project table itself.
    """
    if user_id is None:
        return false()
    from app.modules.projects.models import Project

    inner = aliased(Project)
    member = aliased(LegalEntityMember)
    return (
        select(member.id)
        .select_from(inner)
        .join(member, _owns(inner, member))
        .where(inner.id == project_id_column, member.user_id == user_id)
        .correlate_except(inner, member, LegalEntity)
        .exists()
    )


async def reaches_through_entity(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Whether *user_id* reaches *project_id* through an entity membership."""
    from app.modules.projects.models import Project

    row = (
        await session.execute(
            select(LegalEntityMember.id)
            .select_from(Project)
            .join(LegalEntityMember, _owns(Project, LegalEntityMember))
            .where(Project.id == project_id, LegalEntityMember.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def member_entity_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """The entities *user_id* is a member of."""
    rows = await session.execute(select(LegalEntityMember.legal_entity_id).where(LegalEntityMember.user_id == user_id))
    return set(rows.scalars().all())
