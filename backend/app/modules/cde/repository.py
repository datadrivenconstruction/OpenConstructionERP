# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CDE data access layer.

All database queries for document containers and revisions live here.
No business logic - pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cde.models import DocumentContainer, DocumentRevision, StateTransition


class ContainerRepository:
    """Data access for DocumentContainer models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, container_id: uuid.UUID) -> DocumentContainer | None:
        """Get container by ID."""
        return await self.session.get(DocumentContainer, container_id)

    async def get_by_code_and_project(
        self,
        project_id: uuid.UUID,
        container_code: str,
    ) -> DocumentContainer | None:
        """Get container by code within a project (uniqueness check)."""
        stmt = select(DocumentContainer).where(
            DocumentContainer.project_id == project_id,
            DocumentContainer.container_code == container_code,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        cde_state: str | None = None,
        discipline_code: str | None = None,
    ) -> tuple[list[DocumentContainer], int]:
        """List containers for a project with pagination and filters."""
        base = select(DocumentContainer).where(DocumentContainer.project_id == project_id)
        if cde_state is not None:
            base = base.where(DocumentContainer.cde_state == cde_state)
        if discipline_code is not None:
            base = base.where(DocumentContainer.discipline_code == discipline_code)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(DocumentContainer.container_code.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, container: DocumentContainer) -> DocumentContainer:
        """Insert a new container."""
        self.session.add(container)
        await self.session.flush()
        return container

    async def update_fields(self, container_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a container."""
        stmt = update(DocumentContainer).where(DocumentContainer.id == container_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def stats_for_project(self, project_id: uuid.UUID) -> dict:
        """Compute aggregate statistics for a project's CDE containers.

        Returns dict with keys: total, by_state, by_discipline, latest_revisions.
        """
        # Total count
        total_stmt = (
            select(func.count()).select_from(DocumentContainer).where(DocumentContainer.project_id == project_id)
        )
        total = (await self.session.execute(total_stmt)).scalar_one()

        # Count by state
        state_stmt = (
            select(DocumentContainer.cde_state, func.count())
            .where(DocumentContainer.project_id == project_id)
            .group_by(DocumentContainer.cde_state)
        )
        state_rows = (await self.session.execute(state_stmt)).all()
        by_state = {row[0]: row[1] for row in state_rows}

        # Count by discipline
        # Group by the bare column, not coalesce(): PostgreSQL emits the literal
        # default as a bound parameter, so coalesce(col, $1) in SELECT and
        # coalesce(col, $2) in GROUP BY are seen as *different* expressions and PG
        # raises "column discipline_code must appear in the GROUP BY clause".
        # Grouping by the column itself is valid on both dialects (the SELECT
        # coalesce stays single-valued per group) and keeps the None->"other" map.
        disc_stmt = (
            select(
                func.coalesce(DocumentContainer.discipline_code, "other"),
                func.count(),
            )
            .where(DocumentContainer.project_id == project_id)
            .group_by(DocumentContainer.discipline_code)
        )
        disc_rows = (await self.session.execute(disc_stmt)).all()
        by_discipline = {row[0]: row[1] for row in disc_rows}

        # Count containers that have at least one revision (latest_revisions)
        rev_stmt = (
            select(func.count(func.distinct(DocumentRevision.container_id)))
            .select_from(DocumentRevision)
            .join(
                DocumentContainer,
                DocumentRevision.container_id == DocumentContainer.id,
            )
            .where(DocumentContainer.project_id == project_id)
        )
        latest_revisions = (await self.session.execute(rev_stmt)).scalar_one()

        return {
            "total": total,
            "by_state": by_state,
            "by_discipline": by_discipline,
            "latest_revisions": latest_revisions,
        }

    async def readiness_facts_for_project(self, project_id: uuid.UUID) -> dict:
        """Raw facts a CDE go-live readiness score is derived from.

        Returns primitives only (the readiness *semantics* live in the pure
        :mod:`app.modules.cde.readiness` engine, called by the service):

        * ``total`` - number of containers in the project
        * ``has_naming`` / ``has_suitability`` / ``has_classification`` -
          whether any container carries a structured originator code, a
          suitability code, or a classification code
        * ``states`` - the set of distinct CDE states present
        * ``has_signed_transition`` - any gate crossing recorded with a signature
        * ``has_multi_revision`` - any container with more than one revision
        """
        # One pass for the count-based facts. COUNT(col) counts non-nulls, so a
        # positive count means at least one container carries that field.
        agg_stmt = select(
            func.count(),
            func.count(DocumentContainer.originator_code),
            func.count(DocumentContainer.suitability_code),
            func.count(DocumentContainer.classification_code),
        ).where(DocumentContainer.project_id == project_id)
        total, naming_n, suit_n, class_n = (await self.session.execute(agg_stmt)).one()

        # Distinct states present (drives shared/published/archived milestones).
        states_stmt = (
            select(DocumentContainer.cde_state)
            .where(DocumentContainer.project_id == project_id)
            .distinct()
        )
        states = {row[0] for row in (await self.session.execute(states_stmt)).all()}

        # Any gate crossing signed off (join transition -> its container's project).
        signed_stmt = (
            select(StateTransition.id)
            .join(DocumentContainer, StateTransition.container_id == DocumentContainer.id)
            .where(
                DocumentContainer.project_id == project_id,
                StateTransition.signature.isnot(None),
            )
            .limit(1)
        )
        has_signed = (await self.session.execute(signed_stmt)).first() is not None

        # Any container with more than one revision (versioning actually in use).
        multi_rev_stmt = (
            select(DocumentRevision.container_id)
            .join(DocumentContainer, DocumentRevision.container_id == DocumentContainer.id)
            .where(DocumentContainer.project_id == project_id)
            .group_by(DocumentRevision.container_id)
            .having(func.count() > 1)
            .limit(1)
        )
        has_multi_rev = (await self.session.execute(multi_rev_stmt)).first() is not None

        return {
            "total": total,
            "has_naming": naming_n > 0,
            "has_suitability": suit_n > 0,
            "has_classification": class_n > 0,
            "states": states,
            "has_signed_transition": has_signed,
            "has_multi_revision": has_multi_rev,
        }


class RevisionRepository:
    """Data access for DocumentRevision models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, revision_id: uuid.UUID) -> DocumentRevision | None:
        """Get revision by ID."""
        return await self.session.get(DocumentRevision, revision_id)

    async def list_for_container(
        self,
        container_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[DocumentRevision], int]:
        """List revisions for a container with pagination."""
        base = select(DocumentRevision).where(DocumentRevision.container_id == container_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(DocumentRevision.revision_number.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def next_revision_number(self, container_id: uuid.UUID) -> int:
        """Get the next revision number for a container.

        Two concurrent ``create_revision`` calls on the same container would
        otherwise both read the same ``MAX(revision_number)`` and mint
        duplicate revision numbers (and identical revision codes). To serialise
        them, take an exclusive row lock on the parent container first: the
        lock is held until the surrounding transaction commits, so a second
        concurrent transaction blocks here until the first has flushed its new
        revision row and then sees the updated max. Mirrors the
        ``with_for_update`` pattern used in approval_routes/service.py.

        ``FOR UPDATE`` is honoured on PostgreSQL (the only supported backend);
        the recompute of ``MAX(revision_number)`` after the lock is acquired is
        the actual integrity guarantee.
        """
        lock_stmt = select(DocumentContainer.id).where(DocumentContainer.id == container_id).with_for_update()
        await self.session.execute(lock_stmt)

        stmt = select(func.coalesce(func.max(DocumentRevision.revision_number), 0)).where(
            DocumentRevision.container_id == container_id
        )
        current_max = (await self.session.execute(stmt)).scalar_one()
        return current_max + 1

    async def create(self, revision: DocumentRevision) -> DocumentRevision:
        """Insert a new revision."""
        self.session.add(revision)
        await self.session.flush()
        return revision

    async def update_fields(self, revision_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a revision."""
        stmt = update(DocumentRevision).where(DocumentRevision.id == revision_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()
