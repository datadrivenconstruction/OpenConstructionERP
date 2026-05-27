# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service layer for the file-saved-views module.

All access checks live here (rather than in the router) so the
behaviour is easy to unit-test without spinning up FastAPI. The
router stays a thin wrapper that maps service exceptions to HTTP
status codes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_saved_views.models import FileSavedView
from app.modules.file_saved_views.schemas import (
    FilterSnapshot,
    SavedViewCreate,
    SavedViewUpdate,
)


class SavedViewNotFoundError(Exception):
    """The view does not exist or the caller cannot see it."""


class SavedViewConflictError(Exception):
    """A view with the same (user, project, name) already exists."""


class SavedViewService:
    """CRUD + usage telemetry for :class:`FileSavedView`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── List ──────────────────────────────────────────────────────────────

    async def list_views(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID | None,
    ) -> list[FileSavedView]:
        """Return the views visible to ``user_id`` for ``project_id``.

        Visibility rules:

        * The user's own views (any ``is_shared`` value) — both
          project-scoped and global (``project_id IS NULL``).
        * Other users' views in the same project iff ``is_shared``.

        Ordering: pinned first, then ``sort_order`` ascending, then
        ``last_used_at`` desc (NULLS LAST), then ``created_at`` desc as
        the final tiebreaker so the result is deterministic.
        """
        own_filter = FileSavedView.user_id == user_id
        if project_id is None:
            project_filter = FileSavedView.project_id.is_(None)
            shared_filter = (
                and_(False)  # No shared global views — sharing is project-scoped.
            )
        else:
            project_filter = or_(
                FileSavedView.project_id == project_id,
                FileSavedView.project_id.is_(None),
            )
            shared_filter = and_(
                FileSavedView.project_id == project_id,
                FileSavedView.is_shared.is_(True),
                FileSavedView.user_id != user_id,
            )

        stmt = (
            select(FileSavedView)
            .where(
                or_(
                    and_(own_filter, project_filter),
                    shared_filter,
                ),
            )
            .order_by(
                FileSavedView.is_pinned.desc(),
                FileSavedView.sort_order.asc(),
                FileSavedView.last_used_at.desc().nulls_last(),
                FileSavedView.created_at.desc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── Get ───────────────────────────────────────────────────────────────

    async def _load(
        self,
        view_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> FileSavedView:
        """Load a view if the caller can see it, else raise NotFound."""
        view = await self.session.get(FileSavedView, view_id)
        if view is None:
            raise SavedViewNotFoundError(str(view_id))
        if view.user_id == user_id:
            return view
        # A shared, project-scoped view is readable by project members.
        # We do NOT cross-check team membership here — the router has
        # already verified project access before invoking the service,
        # so a request that reaches us with ``project_id == view.project_id``
        # implies access. We still gate on ``is_shared`` for non-owners.
        if view.is_shared and view.project_id is not None:
            return view
        raise SavedViewNotFoundError(str(view_id))

    async def get(self, view_id: uuid.UUID, user_id: uuid.UUID) -> FileSavedView:
        return await self._load(view_id, user_id)

    # ── Create ────────────────────────────────────────────────────────────

    async def create(
        self,
        payload: SavedViewCreate,
        user_id: uuid.UUID,
    ) -> FileSavedView:
        """Insert a new view. Raises on (user, project, name) collision."""
        view = FileSavedView(
            user_id=user_id,
            project_id=payload.project_id,
            name=payload.name,
            icon=payload.icon,
            filter_json=payload.filter_json.model_dump(mode="json"),
            sort_order=payload.sort_order,
            is_pinned=payload.is_pinned,
            is_shared=payload.is_shared,
        )
        self.session.add(view)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise SavedViewConflictError(payload.name) from exc
        return view

    # ── Update ────────────────────────────────────────────────────────────

    async def update(
        self,
        view_id: uuid.UUID,
        payload: SavedViewUpdate,
        user_id: uuid.UUID,
    ) -> FileSavedView:
        """Patch supplied fields. Only the owner can mutate."""
        view = await self._load(view_id, user_id)
        if view.user_id != user_id:
            # Shared views are read-only for non-owners — same surface
            # as not-found to avoid leaking metadata on writes.
            raise SavedViewNotFoundError(str(view_id))

        data = payload.model_dump(exclude_unset=True)
        # FilterSnapshot is nested — flatten to plain dict for the column.
        if "filter_json" in data and data["filter_json"] is not None:
            if isinstance(payload.filter_json, FilterSnapshot):
                data["filter_json"] = payload.filter_json.model_dump(mode="json")
        for key, value in data.items():
            setattr(view, key, value)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise SavedViewConflictError(view.name) from exc
        return view

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete(self, view_id: uuid.UUID, user_id: uuid.UUID) -> None:
        view = await self._load(view_id, user_id)
        if view.user_id != user_id:
            raise SavedViewNotFoundError(str(view_id))
        await self.session.delete(view)
        await self.session.flush()

    # ── Use (bump telemetry) ──────────────────────────────────────────────

    async def use(self, view_id: uuid.UUID, user_id: uuid.UUID) -> FileSavedView:
        """Mark a view as just-applied: bumps use_count + last_used_at."""
        view = await self._load(view_id, user_id)
        view.use_count = (view.use_count or 0) + 1
        view.last_used_at = datetime.now(UTC)
        await self.session.flush()
        # ``updated_at`` carries an ``onupdate=func.now()`` server-default,
        # so SQLAlchemy marks the column expired after the flush so it can
        # refetch the DB-computed value. Touching the attribute during
        # response serialisation would then trigger a synchronous
        # lazy-load outside the active greenlet and raise MissingGreenlet
        # under asyncio. Refresh explicitly so every column is hydrated
        # before the row leaves the service.
        await self.session.refresh(view)
        return view

    # ── Duplicate ─────────────────────────────────────────────────────────

    async def duplicate(
        self,
        view_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> FileSavedView:
        """Clone a view into the caller's own list as "<name> (copy)".

        If the suffixed name already exists we tack on a numeric counter
        ("name (copy 2)", "name (copy 3)", …) so duplicating twice in a
        row still succeeds.
        """
        original = await self._load(view_id, user_id)
        base_name = f"{original.name} (copy)"
        candidate = base_name
        i = 2
        while await self._name_taken(candidate, user_id, original.project_id):
            candidate = f"{base_name} {i}"
            i += 1
            if i > 999:  # pragma: no cover — defensive ceiling
                raise SavedViewConflictError(base_name)

        clone = FileSavedView(
            user_id=user_id,
            project_id=original.project_id,
            name=candidate,
            icon=original.icon,
            filter_json=dict(original.filter_json or {}),
            sort_order=original.sort_order,
            is_pinned=False,  # never auto-pin a copy
            is_shared=False,  # never auto-share a copy
        )
        self.session.add(clone)
        await self.session.flush()
        return clone

    async def _name_taken(
        self,
        name: str,
        user_id: uuid.UUID,
        project_id: uuid.UUID | None,
    ) -> bool:
        stmt = select(FileSavedView.id).where(
            FileSavedView.user_id == user_id,
            FileSavedView.name == name,
            (FileSavedView.project_id.is_(None) if project_id is None else FileSavedView.project_id == project_id),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
