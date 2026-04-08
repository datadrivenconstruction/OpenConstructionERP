"""Punch List service — business logic for punch list management.

Stateless service layer. Handles:
- Punch item CRUD
- Status transitions with validation (open -> in_progress -> resolved -> verified -> closed)
- Photo management (add/remove photo paths)
- Summary aggregation
- PDF export of punch list items
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.punchlist.models import PunchItem
from app.modules.punchlist.repository import PunchListRepository
from app.modules.punchlist.schemas import PunchItemCreate, PunchItemUpdate, PunchStatusTransition

logger = logging.getLogger(__name__)

# Valid status transitions: current_status -> list of allowed next statuses
VALID_TRANSITIONS: dict[str, list[str]] = {
    "open": ["in_progress"],
    "in_progress": ["resolved", "open"],
    "resolved": ["verified", "open"],
    "verified": ["closed", "open"],
    "closed": ["open"],
}

# Statuses that require special role checks
# resolved -> verified: must be a different user than the resolver
# verified -> closed: admin/manager only (handled via permissions in router)


class PunchListService:
    """Business logic for punch list operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PunchListRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_item(
        self,
        data: PunchItemCreate,
        user_id: str | None = None,
    ) -> PunchItem:
        """Create a new punch list item."""
        item = PunchItem(
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            document_id=data.document_id,
            page=data.page,
            location_x=data.location_x,
            location_y=data.location_y,
            priority=data.priority,
            status="open",
            assigned_to=data.assigned_to,
            due_date=data.due_date,
            category=data.category,
            trade=data.trade,
            created_by=user_id,
            metadata_=data.metadata,
        )
        item = await self.repo.create(item)
        logger.info("Punch item created: %s for project %s", item.title[:40], data.project_id)
        return item

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_item(self, item_id: uuid.UUID) -> PunchItem:
        """Get punch item by ID. Raises 404 if not found."""
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Punch item not found",
            )
        return item

    async def list_items(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        priority_filter: str | None = None,
        assigned_to: str | None = None,
        category_filter: str | None = None,
    ) -> tuple[list[PunchItem], int]:
        """List punch items for a project."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            priority=priority_filter,
            assigned_to=assigned_to,
            category=category_filter,
        )

    # ── Update ────────────────────────────────────────────────────────────

    async def update_item(
        self,
        item_id: uuid.UUID,
        data: PunchItemUpdate,
    ) -> PunchItem:
        """Update punch item fields."""
        item = await self.get_item(item_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return item

        await self.repo.update_fields(item_id, **fields)
        await self.session.refresh(item)

        logger.info("Punch item updated: %s (fields=%s)", item_id, list(fields.keys()))
        return item

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_item(self, item_id: uuid.UUID) -> None:
        """Delete a punch item."""
        await self.get_item(item_id)  # Raises 404 if not found
        await self.repo.delete(item_id)
        logger.info("Punch item deleted: %s", item_id)

    # ── Status transition ─────────────────────────────────────────────────

    async def transition_status(
        self,
        item_id: uuid.UUID,
        transition: PunchStatusTransition,
        user_id: str,
    ) -> PunchItem:
        """Transition a punch item to a new status with validation.

        Rules:
        - open -> in_progress (anyone)
        - in_progress -> resolved (assigned user or admin)
        - resolved -> verified (different user than resolver — enforced here)
        - verified -> closed (admin/manager — enforced via permission in router)
        - Any -> open (reopen)
        """
        item = await self.get_item(item_id)
        current = item.status
        target = transition.new_status

        # Reopen is always allowed from any status
        if target == "open":
            update_fields: dict[str, Any] = {"status": "open"}
            if transition.notes:
                update_fields["resolution_notes"] = transition.notes
            await self.repo.update_fields(item_id, **update_fields)
            await self.session.refresh(item)
            logger.info("Punch item reopened: %s by %s", item_id, user_id)
            return item

        # Validate allowed transitions
        allowed = VALID_TRANSITIONS.get(current, [])
        if target not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot transition from '{current}' to '{target}'",
            )

        now = datetime.now(UTC)
        update_fields = {"status": target}

        if transition.notes:
            update_fields["resolution_notes"] = transition.notes

        # in_progress -> resolved: set resolved_at
        if target == "resolved":
            update_fields["resolved_at"] = now

        # resolved -> verified: must be different user than the one who resolved
        if target == "verified":
            # Check who resolved it (by checking created_by or assigned_to as a proxy)
            # The resolver is typically the assigned user; we compare against created_by
            # for a simple "different user" check
            if item.assigned_to and item.assigned_to == user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Verification must be done by a different user than the assigned resolver",
                )
            update_fields["verified_at"] = now
            update_fields["verified_by"] = user_id

        await self.repo.update_fields(item_id, **update_fields)
        await self.session.refresh(item)

        logger.info(
            "Punch item transitioned: %s %s -> %s by %s",
            item_id,
            current,
            target,
            user_id,
        )
        return item

    # ── Pin to sheet ──────────────────────────────────────────────────────

    async def pin_to_sheet(
        self,
        item_id: uuid.UUID,
        *,
        sheet_id: str | None = None,
        document_id: str | None = None,
        page: int,
        location_x: float,
        location_y: float,
    ) -> PunchItem:
        """Pin a punch item to a location on a document sheet.

        Updates document_id, page, location_x, and location_y on the item.
        If sheet_id is given but document_id is not, sheet_id is stored as
        the document_id (sheets are a logical subset of documents).
        """
        item = await self.get_item(item_id)

        effective_doc_id = document_id or sheet_id

        update_fields: dict[str, Any] = {
            "document_id": effective_doc_id,
            "page": page,
            "location_x": location_x,
            "location_y": location_y,
        }

        await self.repo.update_fields(item_id, **update_fields)
        await self.session.refresh(item)

        logger.info(
            "Punch item pinned to sheet: %s -> doc=%s page=%d (%.2f, %.2f)",
            item_id,
            effective_doc_id,
            page,
            location_x,
            location_y,
        )
        return item

    # ── Photos ────────────────────────────────────────────────────────────

    async def add_photo(self, item_id: uuid.UUID, photo_path: str) -> PunchItem:
        """Add a photo path to the punch item's photos list."""
        item = await self.get_item(item_id)
        photos = list(item.photos or [])
        photos.append(photo_path)
        await self.repo.update_fields(item_id, photos=photos)
        await self.session.refresh(item)
        logger.info("Photo added to punch item %s: %s", item_id, photo_path)
        return item

    async def remove_photo(self, item_id: uuid.UUID, index: int) -> PunchItem:
        """Remove a photo by index from the punch item's photos list."""
        item = await self.get_item(item_id)
        photos = list(item.photos or [])

        if index < 0 or index >= len(photos):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Photo index {index} out of range (0..{len(photos) - 1})",
            )

        removed = photos.pop(index)
        await self.repo.update_fields(item_id, photos=photos)
        await self.session.refresh(item)
        logger.info("Photo removed from punch item %s: %s", item_id, removed)
        return item

    # ── Summary ───────────────────────────────────────────────────────────

    async def get_summary(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Get aggregated stats for a project's punch list."""
        items = await self.repo.all_for_project(project_id)
        overdue = await self.repo.count_overdue(project_id)

        by_status: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        closed_durations: list[float] = []

        for item in items:
            by_status[item.status] = by_status.get(item.status, 0) + 1
            by_priority[item.priority] = by_priority.get(item.priority, 0) + 1

            # Compute days-to-close for closed/verified items
            if item.status in ("closed", "verified") and item.created_at:
                end_time = item.verified_at or item.resolved_at or item.updated_at
                if end_time:
                    try:
                        delta = end_time - item.created_at
                        days = delta.total_seconds() / 86400.0
                        if days >= 0:
                            closed_durations.append(days)
                    except (TypeError, AttributeError):
                        pass

        avg_days_to_close: float | None = None
        if closed_durations:
            avg_days_to_close = round(sum(closed_durations) / len(closed_durations), 1)

        return {
            "total": len(items),
            "by_status": by_status,
            "by_priority": by_priority,
            "overdue": overdue,
            "avg_days_to_close": avg_days_to_close,
        }

    # ── PDF Export ────────────────────────────────────────────────────────

    async def export_pdf(self, project_id: uuid.UUID) -> bytes:
        """Generate a simple PDF report with all punch list items.

        Uses a minimal text-based PDF approach (no heavy dependencies).
        Returns raw PDF bytes.
        """
        items = await self.repo.all_for_project(project_id)

        # Minimal PDF generation without external dependencies
        lines: list[str] = []
        lines.append("PUNCH LIST REPORT")
        lines.append(f"Project: {project_id}")
        lines.append(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append(f"Total Items: {len(items)}")
        lines.append("")
        lines.append("-" * 80)

        for idx, item in enumerate(items, 1):
            lines.append(f"\n{idx}. {item.title}")
            lines.append(f"   Status: {item.status} | Priority: {item.priority}")
            if item.category:
                lines.append(f"   Category: {item.category}")
            if item.trade:
                lines.append(f"   Trade: {item.trade}")
            if item.assigned_to:
                lines.append(f"   Assigned to: {item.assigned_to}")
            if item.due_date:
                lines.append(f"   Due: {item.due_date}")
            if item.description:
                lines.append(f"   Description: {item.description[:200]}")
            if item.resolution_notes:
                lines.append(f"   Resolution: {item.resolution_notes[:200]}")
            lines.append(f"   Created: {item.created_at}")

        content = "\n".join(lines)

        # Build a minimal valid PDF
        pdf = _build_minimal_pdf(content)
        logger.info("Punch list PDF exported for project %s (%d items)", project_id, len(items))
        return pdf


def _build_minimal_pdf(text: str) -> bytes:
    """Build a minimal valid PDF document from plain text.

    This produces a basic but valid PDF without requiring any external library.
    """
    # Escape special PDF characters in text
    safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    # Split into lines for the PDF text block
    text_lines = safe_text.split("\n")
    # Build BT/ET text block with Td positioning
    text_commands: list[str] = []
    text_commands.append("BT")
    text_commands.append("/F1 10 Tf")
    text_commands.append("50 750 Td")
    text_commands.append("12 TL")  # leading
    for line in text_lines:
        text_commands.append(f"({line}) '")
    text_commands.append("ET")
    stream_content = "\n".join(text_commands)

    objects: list[str] = []

    # Object 1: Catalog
    objects.append("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj")
    # Object 2: Pages
    objects.append("2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj")
    # Object 3: Page
    objects.append(
        "3 0 obj\n<< /Type /Page /Parent 2 0 R "
        "/MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj"
    )
    # Object 4: Content stream
    objects.append(f"4 0 obj\n<< /Length {len(stream_content)} >>\nstream\n{stream_content}\nendstream\nendobj")
    # Object 5: Font
    objects.append("5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj")

    # Build the PDF
    parts: list[str] = ["%PDF-1.4"]
    offsets: list[int] = []
    current = len(parts[0]) + 1  # +1 for newline

    for obj in objects:
        offsets.append(current)
        parts.append(obj)
        current += len(obj) + 1

    # Cross-reference table
    xref_offset = current
    xref_lines = [f"xref\n0 {len(objects) + 1}", "0000000000 65535 f "]
    for off in offsets:
        xref_lines.append(f"{off:010d} 00000 n ")
    parts.append("\n".join(xref_lines))

    # Trailer
    parts.append(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF")

    return "\n".join(parts).encode("latin-1")
