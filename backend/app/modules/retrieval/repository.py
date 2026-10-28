# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for saved searches.

Every read takes the owner's id as a required argument rather than inferring
it, so a caller cannot reach another user's pins by forgetting a filter. A pin
belonging to somebody else reads as absent, which lets the router answer 404
for both "no such row" and "not yours" and keeps the API from being usable to
probe for ids.

Reads use ``select()`` with an explicit owner predicate rather than
``session.get()``: ``session.get()`` answers from the identity map, so it can
hand back a row another statement in the same session already deleted, and it
cannot express the owner filter at all.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.retrieval.models import SavedSearch

#: How many pins one user may hold on one project. The browser kept 30; the
#: server keeps the same ceiling so behaviour does not change under people who
#: already have a full list, and so a scripted caller cannot grow the list
#: without bound.
SAVED_SEARCH_LIMIT = 30


class SavedSearchRepository:
    """CRUD for one user's pinned searches on one project."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_owner(
        self,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> Sequence[SavedSearch]:
        """Every pin the user holds on a project, most useful first.

        Ordered by last use, then by creation: a search the user actually
        replays climbs to the top of the list, and a brand new pin sits above
        older ones that have never been run.
        """
        stmt = (
            select(SavedSearch)
            .where(SavedSearch.user_id == user_id)
            .where(SavedSearch.project_id == project_id)
            .order_by(
                SavedSearch.last_used_at.desc().nullslast(),
                SavedSearch.created_at.desc(),
            )
            .limit(SAVED_SEARCH_LIMIT)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def count_for_owner(self, user_id: uuid.UUID, project_id: uuid.UUID) -> int:
        """How many pins the user already holds on a project."""
        stmt = select(SavedSearch.id).where(SavedSearch.user_id == user_id).where(SavedSearch.project_id == project_id)
        return len((await self.session.execute(stmt)).scalars().all())

    async def get_owned(
        self,
        saved_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> SavedSearch | None:
        """One pin by id, or None when it is missing or belongs to somebody else."""
        stmt = select(SavedSearch).where(SavedSearch.id == saved_id).where(SavedSearch.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_signature(
        self,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        signature: str,
    ) -> SavedSearch | None:
        """The pin already holding these facets, or None.

        This is the read behind "saving the same search twice updates the pin":
        the unique constraint guarantees at most one match.
        """
        stmt = (
            select(SavedSearch)
            .where(SavedSearch.user_id == user_id)
            .where(SavedSearch.project_id == project_id)
            .where(SavedSearch.signature == signature)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def oldest_unused(
        self,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> SavedSearch | None:
        """The pin that would be evicted to make room for a new one.

        The least recently used, falling back to the oldest created - the
        inverse of the list ordering, so the row that drops off the bottom of
        the list is the row that gets evicted.
        """
        stmt = (
            select(SavedSearch)
            .where(SavedSearch.user_id == user_id)
            .where(SavedSearch.project_id == project_id)
            .order_by(
                SavedSearch.last_used_at.asc().nullsfirst(),
                SavedSearch.created_at.asc(),
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, saved: SavedSearch) -> SavedSearch:
        """Insert a new pin and flush so its id and timestamps are populated."""
        self.session.add(saved)
        await self.session.flush()
        return saved

    async def touch(self, saved: SavedSearch) -> SavedSearch:
        """Record a replay: bump the use count and stamp the time."""
        saved.use_count = (saved.use_count or 0) + 1
        saved.last_used_at = datetime.now(UTC)
        await self.session.flush()
        return saved

    async def remove(self, saved: SavedSearch) -> None:
        """Delete one pin."""
        await self.session.execute(delete(SavedSearch).where(SavedSearch.id == saved.id))
        await self.session.flush()


__all__ = ["SAVED_SEARCH_LIMIT", "SavedSearchRepository"]
