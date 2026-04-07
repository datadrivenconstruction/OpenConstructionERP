"""OpenCDE service — maps internal data to BuildingSMART BCF 3.0 format.

This service bridges our internal project/collaboration models to the
BCF API 3.0 specification. It reads from our existing tables and
translates to/from BCF-standard schemas.

BCF mapping:
    - Our Projects        -> BCF Projects
    - Our Comments (entity_type='bcf_topic') -> BCF Topics
    - Our Comment replies  -> BCF Comments
    - Our Viewpoints       -> BCF Viewpoints
"""

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.collaboration.models import Comment, Viewpoint
from app.modules.opencde_api.schemas import (
    BCFComment,
    BCFCommentCreate,
    BCFProject,
    BCFTopic,
    BCFTopicCreate,
    BCFTopicUpdate,
    BCFViewpoint,
    BCFViewpointCreate,
)
from app.modules.projects.models import Project

logger = logging.getLogger(__name__)

# Entity type used to identify BCF topics in our collaboration system
BCF_TOPIC_ENTITY_TYPE = "bcf_topic"


class OpenCDEService:
    """Maps internal data to/from BuildingSMART BCF 3.0 format."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Projects ─────────────────────────────────────────────────────────

    async def list_projects(self) -> list[BCFProject]:
        """List all projects in BCF format."""
        stmt = select(Project).order_by(Project.created_at.desc())
        result = await self.session.execute(stmt)
        projects = result.scalars().all()
        return [
            BCFProject(project_id=str(p.id), name=p.name)
            for p in projects
        ]

    async def get_project(self, project_id: uuid.UUID) -> BCFProject:
        """Get a single project in BCF format."""
        project = await self.session.get(Project, project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return BCFProject(project_id=str(project.id), name=project.name)

    # ── Topics (mapped from Comments with entity_type='bcf_topic') ───────

    async def list_topics(self, project_id: uuid.UUID) -> list[BCFTopic]:
        """List BCF topics for a project.

        BCF topics are stored as top-level comments with entity_type='bcf_topic'
        and entity_id=project_id.
        """
        stmt = (
            select(Comment)
            .where(
                Comment.entity_type == BCF_TOPIC_ENTITY_TYPE,
                Comment.entity_id == str(project_id),
                Comment.parent_comment_id.is_(None),
                Comment.is_deleted.is_(False),
            )
            .order_by(Comment.created_at.desc())
        )
        result = await self.session.execute(stmt)
        comments = result.scalars().all()
        return [self._comment_to_topic(c) for c in comments]

    async def get_topic(
        self, project_id: uuid.UUID, topic_guid: uuid.UUID
    ) -> BCFTopic:
        """Get a single BCF topic."""
        comment = await self.session.get(Comment, topic_guid)
        if (
            comment is None
            or comment.entity_type != BCF_TOPIC_ENTITY_TYPE
            or comment.entity_id != str(project_id)
            or comment.is_deleted
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Topic not found",
            )
        return self._comment_to_topic(comment)

    async def create_topic(
        self,
        project_id: uuid.UUID,
        data: BCFTopicCreate,
        author_id: uuid.UUID,
    ) -> BCFTopic:
        """Create a new BCF topic (stored as a collaboration comment)."""
        # Verify project exists
        project = await self.session.get(Project, project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        metadata = {
            "bcf_topic_type": data.topic_type,
            "bcf_topic_status": data.topic_status or "Open",
            "bcf_priority": data.priority,
            "bcf_assigned_to": data.assigned_to,
            "bcf_labels": data.labels,
        }

        comment = Comment(
            entity_type=BCF_TOPIC_ENTITY_TYPE,
            entity_id=str(project_id),
            author_id=author_id,
            text=data.title,
            comment_type="comment",
            metadata_=metadata,
        )
        self.session.add(comment)
        await self.session.flush()

        logger.info("BCF topic created: %s in project %s", comment.id, project_id)
        return self._comment_to_topic(comment)

    async def update_topic(
        self,
        project_id: uuid.UUID,
        topic_guid: uuid.UUID,
        data: BCFTopicUpdate,
    ) -> BCFTopic:
        """Update a BCF topic."""
        comment = await self.session.get(Comment, topic_guid)
        if (
            comment is None
            or comment.entity_type != BCF_TOPIC_ENTITY_TYPE
            or comment.entity_id != str(project_id)
            or comment.is_deleted
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Topic not found",
            )

        if data.title is not None:
            comment.text = data.title

        # Update metadata fields
        meta = dict(comment.metadata_) if comment.metadata_ else {}
        if data.topic_type is not None:
            meta["bcf_topic_type"] = data.topic_type
        if data.topic_status is not None:
            meta["bcf_topic_status"] = data.topic_status
        if data.priority is not None:
            meta["bcf_priority"] = data.priority
        if data.assigned_to is not None:
            meta["bcf_assigned_to"] = data.assigned_to
        if data.labels is not None:
            meta["bcf_labels"] = data.labels
        if data.description is not None:
            meta["bcf_description"] = data.description
        comment.metadata_ = meta

        await self.session.flush()
        logger.info("BCF topic updated: %s", topic_guid)
        return self._comment_to_topic(comment)

    # ── Comments (mapped from comment replies) ───────────────────────────

    async def list_comments(
        self, project_id: uuid.UUID, topic_guid: uuid.UUID
    ) -> list[BCFComment]:
        """List BCF comments for a topic (replies to the topic comment)."""
        # Verify topic exists
        topic = await self.session.get(Comment, topic_guid)
        if (
            topic is None
            or topic.entity_type != BCF_TOPIC_ENTITY_TYPE
            or topic.entity_id != str(project_id)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Topic not found",
            )

        stmt = (
            select(Comment)
            .where(
                Comment.parent_comment_id == topic_guid,
                Comment.is_deleted.is_(False),
            )
            .order_by(Comment.created_at.asc())
        )
        result = await self.session.execute(stmt)
        replies = result.scalars().all()
        return [self._comment_to_bcf_comment(r, topic_guid) for r in replies]

    async def create_comment(
        self,
        project_id: uuid.UUID,
        topic_guid: uuid.UUID,
        data: BCFCommentCreate,
        author_id: uuid.UUID,
    ) -> BCFComment:
        """Create a BCF comment (reply to topic)."""
        # Verify topic exists
        topic = await self.session.get(Comment, topic_guid)
        if (
            topic is None
            or topic.entity_type != BCF_TOPIC_ENTITY_TYPE
            or topic.entity_id != str(project_id)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Topic not found",
            )

        metadata: dict = {}
        if data.viewpoint_guid:
            metadata["bcf_viewpoint_guid"] = data.viewpoint_guid

        reply = Comment(
            entity_type=BCF_TOPIC_ENTITY_TYPE,
            entity_id=str(project_id),
            author_id=author_id,
            text=data.comment,
            comment_type="comment",
            parent_comment_id=topic_guid,
            metadata_=metadata,
        )
        self.session.add(reply)
        await self.session.flush()

        logger.info("BCF comment created: %s on topic %s", reply.id, topic_guid)
        return self._comment_to_bcf_comment(reply, topic_guid)

    # ── Viewpoints ───────────────────────────────────────────────────────

    async def list_viewpoints(
        self, project_id: uuid.UUID, topic_guid: uuid.UUID
    ) -> list[BCFViewpoint]:
        """List BCF viewpoints for a topic."""
        # Verify topic exists
        topic = await self.session.get(Comment, topic_guid)
        if (
            topic is None
            or topic.entity_type != BCF_TOPIC_ENTITY_TYPE
            or topic.entity_id != str(project_id)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Topic not found",
            )

        stmt = (
            select(Viewpoint)
            .where(
                Viewpoint.entity_type == BCF_TOPIC_ENTITY_TYPE,
                Viewpoint.entity_id == str(topic_guid),
            )
            .order_by(Viewpoint.created_at.asc())
        )
        result = await self.session.execute(stmt)
        viewpoints = result.scalars().all()
        return [self._viewpoint_to_bcf(vp, idx) for idx, vp in enumerate(viewpoints)]

    async def create_viewpoint(
        self,
        project_id: uuid.UUID,
        topic_guid: uuid.UUID,
        data: BCFViewpointCreate,
        author_id: uuid.UUID,
    ) -> BCFViewpoint:
        """Create a BCF viewpoint linked to a topic."""
        # Verify topic exists
        topic = await self.session.get(Comment, topic_guid)
        if (
            topic is None
            or topic.entity_type != BCF_TOPIC_ENTITY_TYPE
            or topic.entity_id != str(project_id)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Topic not found",
            )

        vp_data: dict = {}
        if data.orthogonal_camera:
            vp_data["orthogonal_camera"] = data.orthogonal_camera.model_dump()
        if data.perspective_camera:
            vp_data["perspective_camera"] = data.perspective_camera.model_dump()

        # Count existing viewpoints for index
        count_stmt = (
            select(func.count())
            .select_from(Viewpoint)
            .where(
                Viewpoint.entity_type == BCF_TOPIC_ENTITY_TYPE,
                Viewpoint.entity_id == str(topic_guid),
            )
        )
        count = (await self.session.execute(count_stmt)).scalar_one()

        viewpoint = Viewpoint(
            entity_type=BCF_TOPIC_ENTITY_TYPE,
            entity_id=str(topic_guid),
            viewpoint_type="bim_section",
            data=vp_data,
            created_by=author_id,
            comment_id=topic_guid,
            metadata_={},
        )
        self.session.add(viewpoint)
        await self.session.flush()

        logger.info("BCF viewpoint created: %s on topic %s", viewpoint.id, topic_guid)
        return self._viewpoint_to_bcf(viewpoint, count)

    # ── Mapping helpers ──────────────────────────────────────────────────

    @staticmethod
    def _comment_to_topic(comment: Comment) -> BCFTopic:
        """Map a Comment (entity_type='bcf_topic') to a BCFTopic."""
        meta = comment.metadata_ or {}
        return BCFTopic(
            guid=str(comment.id),
            topic_type=meta.get("bcf_topic_type", ""),
            topic_status=meta.get("bcf_topic_status", "Open"),
            title=comment.text,
            description=meta.get("bcf_description", ""),
            priority=meta.get("bcf_priority", ""),
            creation_date=comment.created_at,
            creation_author=str(comment.author_id),
            modified_date=comment.updated_at,
            modified_author=str(comment.author_id),
            assigned_to=meta.get("bcf_assigned_to", ""),
            labels=meta.get("bcf_labels", []),
        )

    @staticmethod
    def _comment_to_bcf_comment(
        comment: Comment, topic_guid: uuid.UUID
    ) -> BCFComment:
        """Map a Comment reply to a BCFComment."""
        meta = comment.metadata_ or {}
        return BCFComment(
            guid=str(comment.id),
            date=comment.created_at,
            author=str(comment.author_id),
            comment=comment.text,
            topic_guid=str(topic_guid),
            modified_date=comment.updated_at,
            modified_author=str(comment.author_id),
            viewpoint_guid=meta.get("bcf_viewpoint_guid"),
        )

    @staticmethod
    def _viewpoint_to_bcf(viewpoint: Viewpoint, index: int) -> BCFViewpoint:
        """Map a Viewpoint to a BCFViewpoint."""
        vp_data = viewpoint.data or {}
        return BCFViewpoint(
            guid=str(viewpoint.id),
            index=index,
            orthogonal_camera=vp_data.get("orthogonal_camera"),
            perspective_camera=vp_data.get("perspective_camera"),
        )
