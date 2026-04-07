"""Collaboration service — business logic for comments and viewpoints.

Stateless service layer. Handles:
- Comment CRUD with threading
- @mention creation alongside comments
- Viewpoint creation (standalone or comment-attached)
- Soft-delete with text replacement
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.collaboration.models import Comment, CommentMention, Viewpoint
from app.modules.collaboration.repository import (
    CommentRepository,
    MentionRepository,
    ViewpointRepository,
)
from app.modules.collaboration.schemas import CommentCreate, CommentUpdate, ViewpointCreate

logger = logging.getLogger(__name__)


class CollaborationService:
    """Business logic for comments and viewpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.comment_repo = CommentRepository(session)
        self.mention_repo = MentionRepository(session)
        self.viewpoint_repo = ViewpointRepository(session)

    # ── Comments ─────────────────────────────────────────────────────────

    async def create_comment(
        self,
        data: CommentCreate,
        author_id: uuid.UUID,
    ) -> Comment:
        """Create a comment with optional mentions and viewpoint."""
        # Validate parent exists if threading
        if data.parent_comment_id is not None:
            parent = await self.comment_repo.get(data.parent_comment_id)
            if parent is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Parent comment not found",
                )

        comment = Comment(
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            author_id=author_id,
            text=data.text,
            comment_type=data.comment_type,
            parent_comment_id=data.parent_comment_id,
            metadata_=data.metadata,
        )
        comment = await self.comment_repo.create(comment)

        # Create mentions
        if data.mentions:
            mention_objs = [
                CommentMention(
                    comment_id=comment.id,
                    mentioned_user_id=m.mentioned_user_id,
                    mention_type=m.mention_type,
                )
                for m in data.mentions
            ]
            await self.mention_repo.create_bulk(mention_objs)

        # Create attached viewpoint
        if data.viewpoint is not None:
            vp = Viewpoint(
                entity_type=data.viewpoint.entity_type,
                entity_id=data.viewpoint.entity_id,
                viewpoint_type=data.viewpoint.viewpoint_type,
                data=data.viewpoint.data,
                created_by=author_id,
                comment_id=comment.id,
                metadata_=data.viewpoint.metadata,
            )
            await self.viewpoint_repo.create(vp)

        # Refresh to load relationships
        await self.session.refresh(comment)

        logger.info(
            "Comment created: %s on %s/%s by %s",
            comment.id,
            data.entity_type,
            data.entity_id,
            author_id,
        )
        return comment

    async def get_comment(self, comment_id: uuid.UUID) -> Comment:
        """Get comment by ID. Raises 404 if not found."""
        comment = await self.comment_repo.get(comment_id)
        if comment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comment not found",
            )
        return comment

    async def list_comments(
        self,
        entity_type: str,
        entity_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Comment], int]:
        """List top-level comments for an entity (threaded)."""
        return await self.comment_repo.list_for_entity(
            entity_type,
            entity_id,
            offset=offset,
            limit=limit,
        )

    async def get_thread(self, comment_id: uuid.UUID) -> list[Comment]:
        """Get the full thread starting from a comment."""
        thread = await self.comment_repo.get_thread(comment_id)
        if not thread:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comment not found",
            )
        return thread

    async def update_comment(
        self,
        comment_id: uuid.UUID,
        data: CommentUpdate,
        user_id: uuid.UUID,
    ) -> Comment:
        """Edit a comment's text. Only the author can edit."""
        comment = await self.get_comment(comment_id)

        if comment.author_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the author can edit this comment",
            )
        if comment.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot edit a deleted comment",
            )

        await self.comment_repo.update_text(
            comment_id,
            data.text,
            edited_at=datetime.now(UTC),
        )

        updated = await self.comment_repo.get(comment_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comment not found",
            )

        logger.info("Comment edited: %s by %s", comment_id, user_id)
        return updated

    async def delete_comment(
        self,
        comment_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Soft-delete a comment. Only the author can delete."""
        comment = await self.get_comment(comment_id)

        if comment.author_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the author can delete this comment",
            )
        if comment.is_deleted:
            return  # Already deleted — idempotent

        await self.comment_repo.soft_delete(comment_id)
        logger.info("Comment soft-deleted: %s by %s", comment_id, user_id)

    # ── Viewpoints ───────────────────────────────────────────────────────

    async def create_viewpoint(
        self,
        data: ViewpointCreate,
        created_by: uuid.UUID,
    ) -> Viewpoint:
        """Create a standalone viewpoint."""
        # Validate linked comment exists
        if data.comment_id is not None:
            comment = await self.comment_repo.get(data.comment_id)
            if comment is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Linked comment not found",
                )

        viewpoint = Viewpoint(
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            viewpoint_type=data.viewpoint_type,
            data=data.data,
            created_by=created_by,
            comment_id=data.comment_id,
            metadata_=data.metadata,
        )
        viewpoint = await self.viewpoint_repo.create(viewpoint)

        logger.info(
            "Viewpoint created: %s (%s) on %s/%s",
            viewpoint.id,
            data.viewpoint_type,
            data.entity_type,
            data.entity_id,
        )
        return viewpoint

    async def list_viewpoints(
        self,
        entity_type: str,
        entity_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Viewpoint], int]:
        """List viewpoints for an entity."""
        return await self.viewpoint_repo.list_for_entity(
            entity_type,
            entity_id,
            offset=offset,
            limit=limit,
        )
