# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Source-data register data-access layer."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.source_data.models import SourceChecklistItem, SourceDocument

# The expiry-alert buckets, shared by the "expiring soon" query and the
# dashboard widget. A perpetual document (no valid_until) never enters these.
_ALERT_STATUSES: tuple[str, ...] = ("expiring_soon", "expired")


class SourceDataRepository:
    """Data access for :class:`SourceDocument` and :class:`SourceChecklistItem`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Documents ───────────────────────────────────────────────────────

    async def get_document(self, document_id: uuid.UUID) -> SourceDocument | None:
        return await self.session.get(SourceDocument, document_id)

    async def list_documents(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        doc_type: str | None = None,
    ) -> list[SourceDocument]:
        stmt = select(SourceDocument).where(SourceDocument.project_id == project_id)
        if status is not None:
            stmt = stmt.where(SourceDocument.status == status)
        if doc_type is not None:
            stmt = stmt.where(SourceDocument.doc_type == doc_type)
        # Perpetual documents (NULL valid_until) sort last; the rest ascend by
        # expiry so the most-urgent rows lead, matching the UI default.
        stmt = stmt.order_by(
            SourceDocument.valid_until.is_(None),
            SourceDocument.valid_until.asc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_expiring_soon(
        self,
        project_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[SourceDocument]:
        stmt = (
            select(SourceDocument)
            .where(
                SourceDocument.project_id == project_id,
                SourceDocument.status.in_(_ALERT_STATUSES),
            )
            .order_by(SourceDocument.valid_until.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_blocking(self, project_id: uuid.UUID) -> list[SourceDocument]:
        """Documents that block the schedule: flagged and expired."""
        stmt = (
            select(SourceDocument)
            .where(
                SourceDocument.project_id == project_id,
                SourceDocument.blocks_schedule.is_(True),
                SourceDocument.status == "expired",
            )
            .order_by(SourceDocument.valid_until.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_document(self, document: SourceDocument) -> SourceDocument:
        self.session.add(document)
        await self.session.flush()
        return document

    async def delete_document(self, document_id: uuid.UUID) -> None:
        row = await self.get_document(document_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()

    # ── Checklist items ─────────────────────────────────────────────────

    async def get_checklist_item(self, item_id: uuid.UUID) -> SourceChecklistItem | None:
        return await self.session.get(SourceChecklistItem, item_id)

    async def list_checklist(self, project_id: uuid.UUID) -> list[SourceChecklistItem]:
        stmt = (
            select(SourceChecklistItem)
            .where(SourceChecklistItem.project_id == project_id)
            .order_by(
                SourceChecklistItem.required.desc(),
                SourceChecklistItem.label.asc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_checklist_item(self, item: SourceChecklistItem) -> SourceChecklistItem:
        self.session.add(item)
        await self.session.flush()
        return item

    async def delete_checklist_item(self, item_id: uuid.UUID) -> None:
        row = await self.get_checklist_item(item_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()
