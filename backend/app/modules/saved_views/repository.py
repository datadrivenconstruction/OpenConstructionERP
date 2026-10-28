# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for the saved-views module.

Pure CRUD on the ``SavedView`` / ``SavedViewRun`` rows ONLY. The repository never
runs a user view (that is the builder's job). Every list method is itself scoped
to an owner / project so the CRUD surface cannot leak other users' saved-view
DEFINITIONS either.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.saved_views.models import SavedView, SavedViewRun


class SavedViewRepository:
    """CRUD + scoped queries for saved-view definition rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, view_id: uuid.UUID) -> SavedView | None:
        """Single view by primary key, ``None`` if absent."""
        return await self.session.get(SavedView, view_id)

    async def list_for_owner(
        self,
        owner_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> list[SavedView]:
        """Every view owned by ``owner_id``, optionally narrowed by entity / project."""
        stmt = select(SavedView).where(SavedView.owner_id == owner_id)
        if entity_type is not None:
            stmt = stmt.where(SavedView.entity_type == entity_type)
        if project_id is not None:
            stmt = stmt.where(SavedView.project_id == project_id)
        stmt = stmt.order_by(SavedView.is_pinned.desc(), SavedView.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_shared_in_project(
        self,
        project_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        member_team_ids: Sequence[uuid.UUID] = (),
        include_all_teams: bool = False,
    ) -> list[SavedView]:
        """Every shared view in ``project_id`` the caller's teams can reach.

        Excludes ``private`` views (those only list for their owner via
        :meth:`list_for_owner`). ``team``-shared views are included only when
        their ``shared_team_id`` is one of ``member_team_ids``, which the
        service resolves from the teams module - the repository never widens a
        share on its own. Passing no team ids therefore lists project and
        workspace shares only, which is the correct fail-closed result when the
        teams module is unavailable.

        Args:
            project_id: The project whose shared views to list.
            entity_type: Optional entity narrowing.
            member_team_ids: Teams the caller actually belongs to.
            include_all_teams: Ignore team membership and list every team
                share. Only the service's admin branch passes this.

        Returns:
            Shared view rows, pinned first, then newest first.
        """
        shared = [
            SavedView.share_scope == "project",
            SavedView.share_scope == "workspace",
        ]
        if include_all_teams:
            shared.append(SavedView.share_scope == "team")
        elif member_team_ids:
            shared.append(
                and_(
                    SavedView.share_scope == "team",
                    SavedView.shared_team_id.in_(list(member_team_ids)),
                )
            )
        stmt = select(SavedView).where(
            and_(SavedView.project_id == project_id, or_(*shared)),
        )
        if entity_type is not None:
            stmt = stmt.where(SavedView.entity_type == entity_type)
        stmt = stmt.order_by(SavedView.is_pinned.desc(), SavedView.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def name_taken(
        self,
        *,
        owner_id: uuid.UUID,
        project_id: uuid.UUID | None,
        entity_type: str,
        name: str,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        """Whether ``uq_saved_views_owner_scope_name`` would reject this name.

        Checked before the insert so the caller gets a 409 naming the clash
        instead of an ``IntegrityError`` that has already aborted the
        transaction. The unique index remains the real guard against a race.

        Args:
            owner_id: Owner of the view.
            project_id: Project pin, or ``None`` for an unpinned view.
            entity_type: Entity the view queries.
            name: The proposed name.
            exclude_id: A view to ignore, so renaming a row to its own name is
                not reported as a clash.

        Returns:
            ``True`` if another row already occupies the name.
        """
        stmt = select(SavedView.id).where(
            SavedView.owner_id == owner_id,
            SavedView.entity_type == entity_type,
            SavedView.name == name,
        )
        # project_id is nullable: ``== None`` must become ``IS NULL``, and the
        # unique constraint treats two NULL project pins as distinct rows on
        # PostgreSQL, so an unpinned view can never clash there.
        if project_id is None:
            return False
        stmt = stmt.where(SavedView.project_id == project_id)
        if exclude_id is not None:
            stmt = stmt.where(SavedView.id != exclude_id)
        return (await self.session.execute(stmt.limit(1))).first() is not None

    async def create(self, view: SavedView) -> SavedView:
        """Persist a new view (caller commits)."""
        self.session.add(view)
        await self.session.flush()
        return view

    async def update_fields(self, view: SavedView, fields: dict[str, Any]) -> SavedView:
        """Apply a field dict to an existing view (caller commits)."""
        for key, value in fields.items():
            setattr(view, key, value)
        await self.session.flush()
        return view

    async def delete(self, view: SavedView) -> None:
        """Hard-delete a view (caller commits)."""
        await self.session.delete(view)
        await self.session.flush()

    async def record_run(self, run: SavedViewRun) -> SavedViewRun:
        """Append an audit row (caller commits)."""
        self.session.add(run)
        await self.session.flush()
        return run

    async def run_outcome_counts(self, view_id: uuid.UUID) -> dict[str, int]:
        """Run counts for one view keyed by outcome.

        Aggregated in the database rather than by walking ``SavedView.runs``:
        that relationship is deliberately ``raise_on_sql`` because run history
        is unbounded.

        Args:
            view_id: The view whose runs to count.

        Returns:
            Outcome to count; outcomes with no runs are absent.
        """
        stmt = (
            select(SavedViewRun.outcome, func.count())
            .where(SavedViewRun.saved_view_id == view_id)
            .group_by(SavedViewRun.outcome)
        )
        rows = (await self.session.execute(stmt)).all()
        return {str(outcome): int(count) for outcome, count in rows}

    async def run_timings(self, view_id: uuid.UUID) -> tuple[int | None, int | None, int]:
        """Average and worst elapsed milliseconds, plus the truncated-run count.

        Args:
            view_id: The view whose runs to measure.

        Returns:
            ``(avg_ms, max_ms, truncated_runs)``; the first two are ``None``
            when the view has never run.
        """
        stmt = select(
            func.avg(SavedViewRun.elapsed_ms),
            func.max(SavedViewRun.elapsed_ms),
            func.count().filter(SavedViewRun.truncated.is_(True)),
        ).where(SavedViewRun.saved_view_id == view_id)
        avg_ms, max_ms, truncated = (await self.session.execute(stmt)).one()
        return (
            int(avg_ms) if avg_ms is not None else None,
            int(max_ms) if max_ms is not None else None,
            int(truncated or 0),
        )

    async def last_run(self, view_id: uuid.UUID) -> SavedViewRun | None:
        """The most recent run row for a view, ``None`` if it has never run."""
        stmt = (
            select(SavedViewRun)
            .where(SavedViewRun.saved_view_id == view_id)
            .order_by(SavedViewRun.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()
