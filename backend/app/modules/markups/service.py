"""Markups & Annotations service — business logic.

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

from app.modules.markups.models import Markup, ScaleConfig, StampTemplate
from app.modules.markups.repository import (
    MarkupRepository,
    ScaleConfigRepository,
    StampTemplateRepository,
)
from app.modules.markups.schemas import (
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


class MarkupsService:
    """Business logic for markups, scales, and stamp templates."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.markup_repo = MarkupRepository(session)
        self.scale_repo = ScaleConfigRepository(session)
        self.stamp_repo = StampTemplateRepository(session)

    # ── Markup CRUD ──────────────────────────────────────────────────────

    async def create_markup(self, data: MarkupCreate, user_id: str) -> Markup:
        """Create a new markup annotation."""
        item = Markup(
            project_id=data.project_id,
            document_id=data.document_id,
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
            metadata_=data.metadata,
            created_by=user_id,
        )
        item = await self.markup_repo.create(item)
        logger.info("Markup created: %s type=%s project=%s", item.id, data.type, data.project_id)
        return item

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
        )

    async def update_markup(
        self,
        markup_id: uuid.UUID,
        data: MarkupUpdate,
    ) -> Markup:
        """Update markup fields."""
        item = await self.get_markup(markup_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return item

        await self.markup_repo.update_fields(markup_id, **fields)
        await self.session.refresh(item)

        logger.info("Markup updated: %s (fields=%s)", markup_id, list(fields.keys()))
        return item

    async def delete_markup(self, markup_id: uuid.UUID) -> None:
        """Delete a markup."""
        await self.get_markup(markup_id)  # Raises 404 if not found
        await self.markup_repo.delete(markup_id)
        logger.info("Markup deleted: %s", markup_id)

    async def bulk_create_markups(
        self, markups_data: list[MarkupCreate], user_id: str
    ) -> list[Markup]:
        """Create multiple markups at once (for import workflows)."""
        items = [
            Markup(
                project_id=data.project_id,
                document_id=data.document_id,
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
                metadata_=data.metadata,
                created_by=user_id,
            )
            for data in markups_data
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

    async def search_markups(
        self, project_id: uuid.UUID, query: str
    ) -> list[Markup]:
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
        writer.writerow([
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
        ])

        for item in items:
            writer.writerow([
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
            ])

        return output.getvalue()

    async def link_to_boq(self, markup_id: uuid.UUID, position_id: str) -> Markup:
        """Link a measurement markup to a BOQ position."""
        item = await self.get_markup(markup_id)

        await self.markup_repo.update_fields(
            markup_id, linked_boq_position_id=position_id
        )
        await self.session.refresh(item)

        logger.info(
            "Markup %s linked to BOQ position %s", markup_id, position_id
        )
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

    async def list_scales(
        self, document_id: str, *, page: int | None = None
    ) -> list[ScaleConfig]:
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

    async def create_stamp(
        self, data: StampTemplateCreate, user_id: str
    ) -> StampTemplate:
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

    async def list_stamps(
        self, project_id: uuid.UUID | None
    ) -> list[StampTemplate]:
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
