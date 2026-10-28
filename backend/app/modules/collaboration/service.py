# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Collaboration service - business logic for comments and viewpoints.

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

from app.core.events import event_bus
from app.modules.collaboration.models import Comment, CommentMention, Viewpoint
from app.modules.collaboration.repository import (
    CommentRepository,
    MentionRepository,
    ViewpointRepository,
)
from app.modules.collaboration.schemas import CommentCreate, CommentUpdate, ViewpointCreate

logger = logging.getLogger(__name__)


async def _safe_publish(name: str, data: dict, source_module: str = "oe_collaboration") -> None:
    """Best-effort detached event publish - never blocks or breaks the caller.

    Uses :meth:`EventBus.publish_detached` so the subscriber (which opens its
    own write session) fires after the request has committed and released the
    SQLite writer lock - matching the pattern the notifications service and
    file_comments use.
    """
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:  # noqa: BLE001 - event publish must never break a create
        logger.debug("collaboration: event publish skipped: %s", name, exc_info=True)


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
        *,
        project_id: uuid.UUID | None = None,
    ) -> Comment:
        """Create a comment with optional mentions and viewpoint.

        ``project_id`` is the owning project of the commented entity, resolved
        by the router's access check. It is forwarded on the detached
        ``collaboration.comment.created`` event so the notifications subscriber
        can fan out to project members without re-resolving the entity.
        """
        # Validate parent exists if threading
        if data.parent_comment_id is not None:
            parent = await self.comment_repo.get(data.parent_comment_id)
            if parent is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Parent comment not found",
                )
            # Ensure parent belongs to the same entity (prevent cross-entity threading)
            if parent.entity_type != data.entity_type or parent.entity_id != data.entity_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Parent comment belongs to a different entity",
                )
            if parent.is_deleted:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot reply to a deleted comment",
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

        # Detached event so the discussion also flows to in-app notifications
        # (and from there to chat connectors). Published fire-and-forget after
        # the request commits; a subscriber failure can never roll back the
        # comment insert.
        await _safe_publish(
            "collaboration.comment.created",
            {
                "comment_id": str(comment.id),
                "entity_type": data.entity_type,
                "entity_id": data.entity_id,
                "project_id": str(project_id) if project_id else None,
                "author_id": str(author_id),
                "parent_comment_id": (str(data.parent_comment_id) if data.parent_comment_id else None),
                "comment_type": data.comment_type,
                "body_excerpt": (data.text or "")[:160],
            },
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

        # Return with the reply tree pinned in memory: the PATCH response is a
        # CommentResponse whose nested ``replies`` serialize recursively, which
        # would otherwise lazy-load and raise MissingGreenlet on asyncpg.
        updated = await self.comment_repo.get_with_reply_tree(comment_id)
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
            return  # Already deleted - idempotent

        await self.comment_repo.soft_delete(comment_id)
        logger.info("Comment soft-deleted: %s by %s", comment_id, user_id)

    # ── Viewpoints ───────────────────────────────────────────────────────

    async def create_viewpoint(
        self,
        data: ViewpointCreate,
        created_by: uuid.UUID,
    ) -> Viewpoint:
        """Create a standalone viewpoint."""
        # Validate the linked comment exists AND belongs to the same entity the
        # caller was access-checked against (the router only gates entity_type /
        # entity_id). Without the entity match a caller could attach a viewpoint
        # carrying arbitrary data/metadata to another tenant's comment by passing
        # their own entity here plus a foreign comment_id; that viewpoint would
        # then surface inside the victim's comment thread. Mirror the
        # parent-entity guard in create_comment.
        if data.comment_id is not None:
            comment = await self.comment_repo.get(data.comment_id)
            if comment is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Linked comment not found",
                )
            if comment.entity_type != data.entity_type or comment.entity_id != data.entity_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Linked comment belongs to a different entity",
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
