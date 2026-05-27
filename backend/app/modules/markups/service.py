"""‌⁠‍Markups & Annotations service — business logic.

Stateless service layer. Handles:
- Markup CRUD, bulk creation, and text search
- Scale calibration management
- Stamp template CRUD with predefined seed data
- CSV export of markups
- BOQ position linking for measurement markups
"""

import csv
import io
import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.markups.models import Markup, MarkupComment, ScaleConfig, StampTemplate
from app.modules.markups.repository import (
    MarkupCommentRepository,
    MarkupRepository,
    ScaleConfigRepository,
    StampTemplateRepository,
)
from app.modules.markups.schemas import (
    MarkupCommentCreate,
    MarkupCreate,
    MarkupUpdate,
    ScaleConfigCreate,
    StampTemplateCreate,
    StampTemplateUpdate,
)

logger = logging.getLogger(__name__)

# Default stamp templates seeded on first startup
DEFAULT_STAMPS: list[dict[str, Any]] = [
    {
        "name": "Approved",
        "text": "APPROVED",
        "color": "#22c55e",
        "background_color": "#dcfce7",
        "icon": "check-circle",
        "category": "predefined",
    },
    {
        "name": "Rejected",
        "text": "REJECTED",
        "color": "#ef4444",
        "background_color": "#fee2e2",
        "icon": "x-circle",
        "category": "predefined",
    },
    {
        "name": "For Review",
        "text": "FOR REVIEW",
        "color": "#eab308",
        "background_color": "#fef9c3",
        "icon": "eye",
        "category": "predefined",
    },
    {
        "name": "Revised",
        "text": "REVISED",
        "color": "#3b82f6",
        "background_color": "#dbeafe",
        "icon": "refresh-cw",
        "category": "predefined",
    },
    {
        "name": "Final",
        "text": "FINAL",
        "color": "#a855f7",
        "background_color": "#f3e8ff",
        "icon": "award",
        "category": "predefined",
    },
]


def _validate_geometry(geometry: dict[str, Any], markup_type: str) -> None:
    """‌⁠‍Validate that geometry coordinates are reasonable for the given markup type.

    Checks that coordinate values are finite numbers. Does not enforce strict
    ranges because coordinate systems vary per viewer/document.

    Raises HTTPException on invalid data.
    """
    if not geometry:
        return

    # Check that any coordinate-like values are finite numbers
    for key, value in geometry.items():
        if isinstance(value, (int, float)):
            if not (-1e9 < value < 1e9):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Geometry value '{key}' is out of range: {value}",
                )
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    for coord_key, coord_val in item.items():
                        if isinstance(coord_val, (int, float)) and not (-1e9 < coord_val < 1e9):
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Geometry point[{i}].{coord_key} is out of range: {coord_val}",
                            )


class MarkupsService:
    """‌⁠‍Business logic for markups, scales, and stamp templates."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.markup_repo = MarkupRepository(session)
        self.scale_repo = ScaleConfigRepository(session)
        self.stamp_repo = StampTemplateRepository(session)
        self.comment_repo = MarkupCommentRepository(session)

    # ── Markup CRUD ──────────────────────────────────────────────────────

    async def create_markup(self, data: MarkupCreate, user_id: str) -> Markup:
        """Create a new markup annotation.

        Epic C — ``file_version_id`` defaults to the current chain head
        for ``data.document_id`` so the viewer can later detect when
        the markup is on a stale revision (and fade it).
        """
        _validate_geometry(data.geometry, data.type)
        file_version_id = await self._resolve_file_version_id(
            project_id=data.project_id,
            document_id=data.document_id,
            explicit=data.file_version_id,
        )
        item = Markup(
            project_id=data.project_id,
            document_id=data.document_id,
            file_version_id=file_version_id,
            page=data.page,
            type=data.type,
            geometry=data.geometry,
            text=data.text,
            color=data.color,
            line_width=data.line_width,
            opacity=data.opacity,
            author_id=data.author_id or user_id,
            status=data.status,
            label=data.label,
            measurement_value=data.measurement_value,
            measurement_unit=data.measurement_unit,
            stamp_template_id=data.stamp_template_id,
            linked_boq_position_id=data.linked_boq_position_id,
            layer=data.layer,
            metadata_=data.metadata,
            created_by=user_id,
        )
        item = await self.markup_repo.create(item)
        logger.info("Markup created: %s type=%s project=%s", item.id, data.type, data.project_id)
        return item

    async def _resolve_file_version_id(
        self,
        *,
        project_id: uuid.UUID,
        document_id: str | None,
        explicit: uuid.UUID | None,
    ) -> uuid.UUID | None:
        """Default the markup's ``file_version_id`` to the chain head.

        Returns ``explicit`` unchanged when the caller provides it. When
        omitted, looks up the current row in the chain keyed on
        ``(project_id, document, file_id=document_id)``. Best-effort:
        any failure leaves the field NULL (the viewer treats NULL as
        "current", preserving legacy behaviour).
        """
        if explicit is not None:
            return explicit
        if not document_id:
            return None
        try:
            from app.modules.file_versions.repository import FileVersionRepository

            repo = FileVersionRepository(self.session)
            seeds = await repo.list_for_file_id(str(document_id), "document")
            if not seeds:
                return None
            chain = await repo.list_chain(
                project_id=seeds[0].project_id,
                file_kind=seeds[0].file_kind,
                canonical_name=seeds[0].canonical_name,
            )
            current = next((r for r in chain if r.is_current), None)
            return current.id if current else None
        except Exception:
            logger.debug(
                "Failed to default file_version_id for markup; leaving NULL",
                exc_info=True,
            )
            return None

    async def get_markup(self, markup_id: uuid.UUID) -> Markup:
        """Get markup by ID. Raises 404 if not found."""
        item = await self.markup_repo.get_by_id(markup_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Markup not found",
            )
        return item

    async def list_markups(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        type_filter: str | None = None,
        status_filter: str | None = None,
        document_id: str | None = None,
        page: int | None = None,
        layer: str | None = None,
    ) -> tuple[list[Markup], int]:
        """List markups for a project with pagination and filters."""
        return await self.markup_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            type_filter=type_filter,
            status_filter=status_filter,
            document_id=document_id,
            page=page,
            layer=layer,
        )

    async def update_markup(
        self,
        markup_id: uuid.UUID,
        data: MarkupUpdate,
    ) -> Markup:
        """Update markup fields."""
        item = await self.get_markup(markup_id)

        if data.geometry is not None:
            _validate_geometry(data.geometry, data.type or item.type)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return item

        prior_status = item.status

        await self.markup_repo.update_fields(markup_id, **fields)
        await self.session.refresh(item)

        # Epic H — universal audit trail. Only emit a status-changed row
        # when status actually moved; ordinary geometry / colour edits
        # land in the audit table under ``action="updated"``.
        from app.core.audit_log import log_activity as _log_activity

        new_status = fields.get("status")
        action = "status_changed" if new_status is not None and new_status != prior_status else "updated"
        await _log_activity(
            self.session,
            actor_id=None,  # router caller knows the actor; service stays neutral
            entity_type="markup",
            entity_id=str(markup_id),
            action=action,
            from_status=prior_status if action == "status_changed" else None,
            to_status=new_status if action == "status_changed" else None,
            metadata={"fields": list(fields.keys())},
            module="markups",
            parent_entity_type="project",
            parent_entity_id=str(item.project_id),
        )

        logger.info("Markup updated: %s (fields=%s)", markup_id, list(fields.keys()))
        return item

    async def delete_markup(self, markup_id: uuid.UUID) -> None:
        """Delete a markup."""
        item = await self.get_markup(markup_id)  # Raises 404 if not found

        # Epic H — record deletion before the row vanishes.
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=None,
            entity_type="markup",
            entity_id=str(markup_id),
            action="deleted",
            from_status=item.status,
            module="markups",
            parent_entity_type="project",
            parent_entity_id=str(item.project_id),
            before_state={"status": item.status, "type": item.type},
        )

        await self.markup_repo.delete(markup_id)
        logger.info("Markup deleted: %s", markup_id)

    async def bulk_create_markups(self, markups_data: list[MarkupCreate], user_id: str) -> list[Markup]:
        """Create multiple markups at once (for import workflows).

        Epic C — defaults ``file_version_id`` per item to the current
        chain head if the caller omitted it (same rule as single create).
        """
        resolved_versions: list[uuid.UUID | None] = []
        for data in markups_data:
            resolved_versions.append(
                await self._resolve_file_version_id(
                    project_id=data.project_id,
                    document_id=data.document_id,
                    explicit=data.file_version_id,
                )
            )
        items = [
            Markup(
                project_id=data.project_id,
                document_id=data.document_id,
                file_version_id=resolved_versions[idx],
                page=data.page,
                type=data.type,
                geometry=data.geometry,
                text=data.text,
                color=data.color,
                line_width=data.line_width,
                opacity=data.opacity,
                author_id=data.author_id or user_id,
                status=data.status,
                label=data.label,
                measurement_value=data.measurement_value,
                measurement_unit=data.measurement_unit,
                stamp_template_id=data.stamp_template_id,
                linked_boq_position_id=data.linked_boq_position_id,
                layer=data.layer,
                metadata_=data.metadata,
                created_by=user_id,
            )
            for idx, data in enumerate(markups_data)
        ]
        items = await self.markup_repo.create_bulk(items)
        logger.info("Bulk created %d markups", len(items))
        return items

    async def get_summary(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Get aggregated stats for a project's markups."""
        summary = await self.markup_repo.summary_for_project(project_id)
        return {
            "total_markups": summary["total"],
            "by_type": summary["by_type"],
            "by_status": summary["by_status"],
        }

    async def search_markups(self, project_id: uuid.UUID, query: str) -> list[Markup]:
        """Search markups by label/text content."""
        return await self.markup_repo.search(project_id, query)

    async def export_to_csv(
        self,
        project_id: uuid.UUID,
        *,
        type_filter: str | None = None,
        status_filter: str | None = None,
    ) -> str:
        """Export markups to CSV string."""
        items, _ = await self.markup_repo.list_for_project(
            project_id,
            offset=0,
            limit=10000,
            type_filter=type_filter,
            status_filter=status_filter,
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "document_id",
                "page",
                "type",
                "text",
                "label",
                "color",
                "status",
                "measurement_value",
                "measurement_unit",
                "author_id",
                "linked_boq_position_id",
                "created_at",
            ]
        )

        for item in items:
            writer.writerow(
                [
                    str(item.id),
                    item.document_id or "",
                    item.page,
                    item.type,
                    item.text or "",
                    item.label or "",
                    item.color,
                    item.status,
                    item.measurement_value if item.measurement_value is not None else "",
                    item.measurement_unit or "",
                    item.author_id,
                    item.linked_boq_position_id or "",
                    item.created_at.isoformat() if item.created_at else "",
                ]
            )

        return output.getvalue()

    async def link_to_boq(self, markup_id: uuid.UUID, position_id: str) -> Markup:
        """Link a measurement markup to a BOQ position."""
        item = await self.get_markup(markup_id)

        await self.markup_repo.update_fields(markup_id, linked_boq_position_id=position_id)
        await self.session.refresh(item)

        logger.info("Markup %s linked to BOQ position %s", markup_id, position_id)
        return item

    # ── Scale Config CRUD ────────────────────────────────────────────────

    async def create_scale(self, data: ScaleConfigCreate, user_id: str) -> ScaleConfig:
        """Create or save a scale calibration config."""
        item = ScaleConfig(
            document_id=data.document_id,
            page=data.page,
            pixels_per_unit=data.pixels_per_unit,
            unit_label=data.unit_label,
            calibration_points=data.calibration_points,
            real_distance=data.real_distance,
            created_by=user_id,
        )
        item = await self.scale_repo.create(item)
        logger.info(
            "Scale config created: doc=%s page=%d %.2f px/%s",
            data.document_id,
            data.page,
            data.pixels_per_unit,
            data.unit_label,
        )
        return item

    async def list_scales(self, document_id: str, *, page: int | None = None) -> list[ScaleConfig]:
        """List scale configs for a document."""
        return await self.scale_repo.list_for_document(document_id, page=page)

    async def delete_scale(self, config_id: uuid.UUID) -> None:
        """Delete a scale config."""
        item = await self.scale_repo.get_by_id(config_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scale config not found",
            )
        await self.scale_repo.delete(config_id)
        logger.info("Scale config deleted: %s", config_id)

    # ── Stamp Template CRUD ──────────────────────────────────────────────

    async def seed_default_stamps(self) -> int:
        """Seed predefined stamp templates if they don't exist yet.

        Returns the number of stamps created.
        """
        existing = await self.stamp_repo.list_predefined()
        existing_names = {s.name for s in existing}

        created = 0
        for stamp_data in DEFAULT_STAMPS:
            if stamp_data["name"] in existing_names:
                continue
            item = StampTemplate(
                project_id=None,
                owner_id="system",
                name=stamp_data["name"],
                category=stamp_data["category"],
                text=stamp_data["text"],
                color=stamp_data["color"],
                background_color=stamp_data.get("background_color"),
                icon=stamp_data.get("icon"),
                include_date=True,
                include_name=True,
                is_active=True,
                metadata_={},
            )
            await self.stamp_repo.create(item)
            created += 1

        if created:
            logger.info("Seeded %d default stamp templates", created)
        return created

    async def create_stamp(self, data: StampTemplateCreate, user_id: str) -> StampTemplate:
        """Create a new stamp template."""
        item = StampTemplate(
            project_id=data.project_id,
            owner_id=user_id,
            name=data.name,
            category=data.category,
            text=data.text,
            color=data.color,
            background_color=data.background_color,
            icon=data.icon,
            include_date=data.include_date,
            include_name=data.include_name,
            is_active=True,
            metadata_=data.metadata,
        )
        item = await self.stamp_repo.create(item)
        logger.info("Stamp template created: %s (%s)", data.name, item.id)
        return item

    async def list_stamps(self, project_id: uuid.UUID | None) -> list[StampTemplate]:
        """List stamp templates: predefined + project-specific."""
        return await self.stamp_repo.list_for_project(project_id)

    async def update_stamp(
        self,
        template_id: uuid.UUID,
        data: StampTemplateUpdate,
    ) -> StampTemplate:
        """Update stamp template fields."""
        item = await self.stamp_repo.get_by_id(template_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Stamp template not found",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return item

        await self.stamp_repo.update_fields(template_id, **fields)
        await self.session.refresh(item)

        logger.info("Stamp template updated: %s (fields=%s)", template_id, list(fields.keys()))
        return item

    async def delete_stamp(self, template_id: uuid.UUID) -> None:
        """Delete a stamp template."""
        item = await self.stamp_repo.get_by_id(template_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Stamp template not found",
            )
        await self.stamp_repo.delete(template_id)
        logger.info("Stamp template deleted: %s", template_id)

    # ── Markup Comments ─────────────────────────────────────────────────

    async def list_comments(self, markup_id: uuid.UUID) -> list[MarkupComment]:
        """List threaded comments on a markup, oldest first."""
        # Ensure parent exists so callers get a 404 instead of an empty list
        # for a non-existent markup id.
        await self.get_markup(markup_id)
        return await self.comment_repo.list_for_markup(markup_id)

    async def create_comment(
        self,
        markup_id: uuid.UUID,
        data: MarkupCommentCreate,
        user_id: str,
    ) -> MarkupComment:
        """Append a comment to a markup thread."""
        await self.get_markup(markup_id)  # 404 if missing
        item = MarkupComment(
            markup_id=markup_id,
            user_id=user_id,
            body=data.body,
        )
        item = await self.comment_repo.create(item)
        logger.info("Markup comment created: markup=%s user=%s", markup_id, user_id)
        return item

    async def get_comment(self, comment_id: uuid.UUID) -> MarkupComment:
        """Get a comment by id, raise 404 if missing."""
        item = await self.comment_repo.get_by_id(comment_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comment not found",
            )
        return item

    async def delete_comment(self, comment_id: uuid.UUID) -> None:
        """Delete a comment."""
        await self.get_comment(comment_id)
        await self.comment_repo.delete(comment_id)
        logger.info("Markup comment deleted: %s", comment_id)
