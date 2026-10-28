# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠BCF data-access layer.

Thin async wrappers around the ORM so the service layer never builds raw
SQLAlchemy statements. All reads are project-scoped - the service is
responsible for verifying the caller owns the project before calling in.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.bcf.models import BCFComment, BCFTopic, BCFViewpoint


class BCFRepository:
    """Data access for BCF topics, comments and viewpoints."""

    #: Hard upper bound on a single ``list_topics`` page. Mirrors the clamp
    #: other repositories apply (e.g. the OpenCDE topic list caps ``$top`` at
    #: 500) so a caller can never trigger an unbounded full-table scan that
    #: also eager-loads every comment + viewpoint. Also the default page size,
    #: chosen high enough that existing whole-project callers (list endpoint,
    #: export) keep returning their full result set for any realistic project.
    MAX_TOPICS_LIMIT = 1000

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Topics ─────────────────────────────────────────────────────────

    async def list_topics(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = MAX_TOPICS_LIMIT,
    ) -> list[BCFTopic]:
        """Return topics for ``project_id``, newest first.

        Comments + viewpoints are eager-loaded so callers (list endpoint,
        export) can touch the collections after the request session closes.

        Paginated with sane defaults: ``offset`` is floored at 0 and ``limit``
        is clamped to ``[1, MAX_TOPICS_LIMIT]``. The default ``limit`` equals
        the hard cap so existing whole-project callers keep their behaviour
        while a misbehaving / huge project can no longer pull an unbounded
        result set (each topic also drags its full comment + viewpoint
        collections, so the bound matters).
        """
        safe_offset = max(0, offset)
        safe_limit = max(1, min(limit, self.MAX_TOPICS_LIMIT))
        stmt = (
            select(BCFTopic)
            .where(BCFTopic.project_id == project_id)
            .options(
                selectinload(BCFTopic.comments),
                selectinload(BCFTopic.viewpoints),
            )
            .order_by(BCFTopic.created_at.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_topics_by_guids(
        self,
        project_id: uuid.UUID,
        guids: Sequence[str],
        *,
        limit: int = MAX_TOPICS_LIMIT,
    ) -> list[BCFTopic]:
        """Return the topics of ``project_id`` whose ``guid`` is in ``guids``.

        Used by the selective export: a coordination session walks a handful of
        topics and hands the other side exactly those, so the caller names them
        by BCF GUID rather than paging the whole register and filtering client
        side. Unknown GUIDs are simply absent from the result - the caller
        decides whether that is an error.

        Comments + viewpoints are eager-loaded for the same reason as in
        :meth:`list_topics`. The result is capped at ``MAX_TOPICS_LIMIT``; an
        empty ``guids`` returns an empty list without touching the database.
        """
        unique = list(dict.fromkeys(g for g in guids if g))
        if not unique:
            return []
        safe_limit = max(1, min(limit, self.MAX_TOPICS_LIMIT))
        stmt = (
            select(BCFTopic)
            .where(
                BCFTopic.project_id == project_id,
                BCFTopic.guid.in_(unique[: self.MAX_TOPICS_LIMIT]),
            )
            .options(
                selectinload(BCFTopic.comments),
                selectinload(BCFTopic.viewpoints),
            )
            .order_by(BCFTopic.created_at.desc())
            .limit(safe_limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_topic(self, topic_id: uuid.UUID) -> BCFTopic | None:
        """Load a topic by surrogate id with comments + viewpoints eager-loaded.

        A ``select()`` with explicit ``selectinload`` is used instead of
        ``session.get`` so the collections are populated *inside* the async
        context - accessing them later during response serialisation (after
        the request session has committed) would otherwise emit a lazy load
        and raise ``MissingGreenlet``.
        """
        stmt = (
            select(BCFTopic)
            .where(BCFTopic.id == topic_id)
            .options(
                selectinload(BCFTopic.comments),
                selectinload(BCFTopic.viewpoints),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_topic_by_guid(self, project_id: uuid.UUID, guid: str) -> BCFTopic | None:
        """Load a topic by its BCF ``guid`` within a project.

        Comments + viewpoints are eager-loaded for the same reason as in
        :meth:`get_topic`: this is a read path for the API (a client addresses a
        topic by the GUID it was given), and the collections are serialised
        after the request session has committed.
        """
        stmt = (
            select(BCFTopic)
            .where(
                BCFTopic.project_id == project_id,
                BCFTopic.guid == guid,
            )
            .options(
                selectinload(BCFTopic.comments),
                selectinload(BCFTopic.viewpoints),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    def add_topic(self, topic: BCFTopic) -> None:
        """Stage a new topic for insert."""
        self.session.add(topic)

    async def delete_topic(self, topic: BCFTopic) -> None:
        """Delete a topic (comments + viewpoints cascade)."""
        await self.session.delete(topic)

    # ── Comments ───────────────────────────────────────────────────────

    async def get_comment(self, comment_id: uuid.UUID) -> BCFComment | None:
        """Load a comment by surrogate id."""
        return await self.session.get(BCFComment, comment_id)

    async def get_comment_by_guid(self, topic_id: uuid.UUID, guid: str) -> BCFComment | None:
        """Load a comment by its BCF ``guid`` within a topic."""
        stmt = select(BCFComment).where(
            BCFComment.topic_id == topic_id,
            BCFComment.guid == guid,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    def add_comment(self, comment: BCFComment) -> None:
        """Stage a new comment for insert."""
        self.session.add(comment)

    async def delete_comment(self, comment: BCFComment) -> None:
        """Delete a comment."""
        await self.session.delete(comment)

    # ── Viewpoints ─────────────────────────────────────────────────────

    async def get_viewpoint_by_guid(self, topic_id: uuid.UUID, guid: str) -> BCFViewpoint | None:
        """Load a viewpoint by its BCF ``guid`` within a topic."""
        stmt = select(BCFViewpoint).where(
            BCFViewpoint.topic_id == topic_id,
            BCFViewpoint.guid == guid,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    def add_viewpoint(self, viewpoint: BCFViewpoint) -> None:
        """Stage a new viewpoint for insert."""
        self.session.add(viewpoint)

    async def next_viewpoint_index(self, topic_id: uuid.UUID) -> int:
        """Return the next free ``vp_index`` for a topic (0-based)."""
        stmt = select(BCFViewpoint.vp_index).where(BCFViewpoint.topic_id == topic_id)
        result = await self.session.execute(stmt)
        existing = [row for row in result.scalars().all() if row is not None]
        return (max(existing) + 1) if existing else 0

    async def delete_topics_for_project(self, project_id: uuid.UUID) -> int:
        """Bulk-delete every topic of a project. Returns the row count."""
        result = await self.session.execute(delete(BCFTopic).where(BCFTopic.project_id == project_id))
        return int(result.rowcount or 0)
