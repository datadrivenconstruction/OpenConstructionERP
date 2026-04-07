"""Collaboration data access layer.

All database queries for comments, mentions, and viewpoints live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.collaboration.models import Comment, CommentMention, Viewpoint


class CommentRepository:
    """Data access for Comment model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, comment_id: uuid.UUID) -> Comment | None:
        """Get comment by ID."""
        return await self.session.get(Comment, comment_id)

    async def list_for_entity(
        self,
        entity_type: str,
        entity_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
        include_deleted: bool = False,
    ) -> tuple[list[Comment], int]:
        """List top-level comments for an entity (threaded via relationships).

        Returns (comments, total_count) for top-level comments only.
        Child replies are loaded via the ORM relationship.
        """
        base = select(Comment).where(
            Comment.entity_type == entity_type,
            Comment.entity_id == entity_id,
            Comment.parent_comment_id.is_(None),
        )
        if not include_deleted:
            base = base.where(Comment.is_deleted.is_(False))

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Comment.created_at.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        comments = list(result.scalars().all())

        return comments, total

    async def get_thread(self, comment_id: uuid.UUID) -> list[Comment]:
        """Get a comment and all its descendants (flat list)."""
        # Start with the root comment
        root = await self.get(comment_id)
        if root is None:
            return []

        # Collect all descendants via recursive approach
        result: list[Comment] = [root]
        queue = [root]
        while queue:
            current = queue.pop(0)
            for reply in current.replies:
                result.append(reply)
                queue.append(reply)

        return result

    async def create(self, comment: Comment) -> Comment:
        """Insert a new comment."""
        self.session.add(comment)
        await self.session.flush()
        return comment

    async def update_text(
        self,
        comment_id: uuid.UUID,
        text: str,
        edited_at: object,
    ) -> None:
        """Update the text of a comment."""
        stmt = (
            update(Comment)
            .where(Comment.id == comment_id)
            .values(text=text, edited_at=edited_at)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def soft_delete(self, comment_id: uuid.UUID) -> None:
        """Soft-delete a comment (set is_deleted=True, clear text)."""
        stmt = (
            update(Comment)
            .where(Comment.id == comment_id)
            .values(is_deleted=True, text="[deleted]")
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()


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
