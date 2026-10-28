# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Collaboration data access layer.

All database queries for comments, mentions, and viewpoints live here.
No business logic - pure data access.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key

from app.modules.collaboration.models import Comment, CommentMention, Viewpoint


class CommentRepository:
    """Data access for Comment model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, comment_id: uuid.UUID) -> Comment | None:
        """Get comment by ID."""
        return await self.session.get(Comment, comment_id)

    @staticmethod
    def _pin_reply_tree(comments: list[Comment]) -> dict[uuid.UUID, list[Comment]]:
        """Populate every comment's ``replies`` collection in memory (no lazy IO).

        ``CommentResponse.replies`` is a self-referential schema that Pydantic
        serializes recursively. The model's ``lazy="selectin"`` only pre-loads
        ONE level, so accessing a grandchild's ``replies`` during synchronous
        serialization emits a lazy SELECT - which raises ``MissingGreenlet`` on
        asyncpg (SQLite tolerated it). Assigning the collection with
        ``set_committed_value`` marks it as loaded-from-DB without triggering any
        IO or cascade, so the recursive serialize is fully in-memory on both
        dialects. Returns the ``parent_id -> children`` index for callers that
        still need to walk the tree (e.g. the flat-thread BFS).
        """
        children: dict[uuid.UUID, list[Comment]] = {}
        for c in comments:
            if c.parent_comment_id is not None:
                children.setdefault(c.parent_comment_id, []).append(c)
        for kids in children.values():
            kids.sort(key=lambda c: c.created_at)
        for c in comments:
            set_committed_value(c, "replies", children.get(c.id, []))
        return children

    async def _load_entity_comments(self, entity_type: str, entity_id: str) -> list[Comment]:
        """Load an entity's whole comment set with serialized children eager."""
        stmt = (
            select(Comment)
            .where(
                Comment.entity_type == entity_type,
                Comment.entity_id == entity_id,
            )
            .options(
                selectinload(Comment.mentions),
                selectinload(Comment.viewpoints),
            )
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_entity(
        self,
        entity_type: str,
        entity_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
        include_deleted: bool = False,
    ) -> tuple[list[Comment], int]:
        """List top-level comments for an entity with replies nested.

        Returns ``(top_level_page, total_top_level)``. The whole entity comment
        set is loaded once and the reply tree is pinned in memory (see
        :meth:`_pin_reply_tree`) so the nested ``replies`` serialize without lazy
        IO. Deleted comments are kept in the reply tree (rendered as "[deleted]"
        to preserve threading) but excluded from the top-level page/count unless
        ``include_deleted`` is set - matching the previous behaviour.
        """
        all_comments = await self._load_entity_comments(entity_type, entity_id)
        self._pin_reply_tree(all_comments)

        top_level = [c for c in all_comments if c.parent_comment_id is None]
        if not include_deleted:
            top_level = [c for c in top_level if not c.is_deleted]
        top_level.sort(key=lambda c: c.created_at)
        total = len(top_level)
        return top_level[offset : offset + limit], total

    async def get_with_reply_tree(self, comment_id: uuid.UUID) -> Comment | None:
        """Get one comment with its reply tree pinned for safe serialization."""
        comment = await self.session.get(Comment, comment_id)
        if comment is None:
            return None
        all_comments = await self._load_entity_comments(comment.entity_type, comment.entity_id)
        self._pin_reply_tree(all_comments)
        by_id = {c.id: c for c in all_comments}
        return by_id.get(comment_id, comment)

    async def get_thread(self, comment_id: uuid.UUID) -> list[Comment]:
        """Get a comment and all its descendants as a FLAT list.

        Loads the entity's comment set once (mentions/viewpoints eager), walks
        the subtree rooted at ``comment_id`` via the in-memory child index, and
        pins each returned comment's ``replies`` to ``[]`` so the response stays
        flat (the client threads via ``parent_comment_id``) and no attribute
        access triggers lazy IO during synchronous serialization.
        """
        # Resolve the root to learn which entity it belongs to.
        root = await self.session.get(Comment, comment_id)
        if root is None:
            return []

        all_comments = await self._load_entity_comments(root.entity_type, root.entity_id)
        children = self._pin_reply_tree(all_comments)
        by_id = {c.id: c for c in all_comments}

        # Walk down from the requested comment, collecting it and all descendants.
        start = by_id.get(comment_id, root)
        result: list[Comment] = []
        queue: list[Comment] = [start]
        while queue:
            current = queue.pop(0)
            result.append(current)
            queue.extend(children.get(current.id, []))

        # Flat contract: each item carries no nested replies (descendants are
        # separate list entries), so pin ``replies = []`` to keep it flat and
        # IO-free during serialization.
        for c in result:
            set_committed_value(c, "replies", [])

        return result

    async def create(self, comment: Comment) -> Comment:
        """Insert a new comment."""
        self.session.add(comment)
        await self.session.flush()
        return comment

    def _pin_updated(self, comment_id: uuid.UUID, **values: object) -> None:
        """Write freshly updated values onto the loaded comment, if we hold it.

        Expiring the session instead would be doubly wrong here. It costs the
        ``replies`` collections that ``_pin_reply_tree`` just pinned to keep
        serialization IO-free, and under asyncio the next attribute read on any
        expired object raises ``MissingGreenlet`` rather than re-fetching. Every
        caller passes plain Python values, so nothing has to be read back.
        """
        instance = self.session.identity_map.get(identity_key(Comment, comment_id))
        if instance is None:
            return
        for name, value in values.items():
            set_committed_value(instance, name, value)

    async def update_text(
        self,
        comment_id: uuid.UUID,
        text: str,
        edited_at: datetime,
    ) -> None:
        """Update the text of a comment."""
        stmt = update(Comment).where(Comment.id == comment_id).values(text=text, edited_at=edited_at)
        await self.session.execute(stmt)
        await self.session.flush()
        self._pin_updated(comment_id, text=text, edited_at=edited_at)

    async def soft_delete(self, comment_id: uuid.UUID) -> None:
        """Soft-delete a comment (set is_deleted=True, clear text)."""
        stmt = update(Comment).where(Comment.id == comment_id).values(is_deleted=True, text="[deleted]")
        await self.session.execute(stmt)
        await self.session.flush()
        self._pin_updated(comment_id, is_deleted=True, text="[deleted]")


class MentionRepository:
    """Data access for CommentMention model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_bulk(self, mentions: list[CommentMention]) -> list[CommentMention]:
        """Insert multiple mentions at once."""
        for m in mentions:
            self.session.add(m)
        await self.session.flush()
        return mentions


class ViewpointRepository:
    """Data access for Viewpoint model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, viewpoint_id: uuid.UUID) -> Viewpoint | None:
        """Get viewpoint by ID."""
        return await self.session.get(Viewpoint, viewpoint_id)

    async def list_for_entity(
        self,
        entity_type: str,
        entity_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Viewpoint], int]:
        """List viewpoints for an entity. Returns (viewpoints, total_count)."""
        base = select(Viewpoint).where(
            Viewpoint.entity_type == entity_type,
            Viewpoint.entity_id == entity_id,
        )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Viewpoint.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        viewpoints = list(result.scalars().all())

        return viewpoints, total

    async def create(self, viewpoint: Viewpoint) -> Viewpoint:
        """Insert a new viewpoint."""
        self.session.add(viewpoint)
        await self.session.flush()
        return viewpoint
