"""Transmittals service — business logic for transmittal management.

Stateless service layer. Handles:
- Transmittal CRUD with auto-numbering
- Locking on issue
- Recipient acknowledgement and response
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.transmittals.models import (
    Transmittal,
    TransmittalItem,
    TransmittalRecipient,
)
from app.modules.transmittals.repository import TransmittalRepository
from app.modules.transmittals.schemas import (
    TransmittalCreate,
    TransmittalUpdate,
)

logger = logging.getLogger(__name__)


class TransmittalService:
    """Business logic for transmittal operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TransmittalRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_transmittal(
        self,
        data: TransmittalCreate,
        user_id: str | None = None,
    ) -> Transmittal:
        """Create a new transmittal with auto-generated number."""
        number = await self.repo.next_number(data.project_id)

        transmittal = Transmittal(
            project_id=data.project_id,
            transmittal_number=number,
            subject=data.subject,
            sender_org_id=data.sender_org_id,
            purpose_code=data.purpose_code,
            issued_date=data.issued_date,
            response_due_date=data.response_due_date,
            cover_note=data.cover_note,
            created_by=uuid.UUID(user_id) if user_id else None,
            metadata_=data.metadata,
        )
        transmittal = await self.repo.create(transmittal)

        # Add recipients
        for r in data.recipients:
            recipient = TransmittalRecipient(
                transmittal_id=transmittal.id,
                recipient_org_id=r.recipient_org_id,
                recipient_user_id=r.recipient_user_id,
                action_required=r.action_required,
            )
            await self.repo.add_recipient(recipient)

        # Add items
        for item_data in data.items:
            item = TransmittalItem(
                transmittal_id=transmittal.id,
                document_id=item_data.document_id,
                revision_id=item_data.revision_id,
                item_number=item_data.item_number,
                description=item_data.description,
                notes=item_data.notes,
            )
            await self.repo.add_item(item)

        # Re-fetch to get relationships loaded
        result = await self.repo.get(transmittal.id)
        logger.info("Transmittal created: %s (%s)", number, data.subject)
        return result  # type: ignore[return-value]

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_transmittal(self, transmittal_id: uuid.UUID) -> Transmittal:
        """Get transmittal by ID. Raises 404 if not found."""
        transmittal = await self.repo.get(transmittal_id)
        if transmittal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transmittal not found",
            )
        return transmittal

    async def list_transmittals(
        self,
        project_id: uuid.UUID,
        *,
        transmittal_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Transmittal], int]:
        """List transmittals for a project."""
        return await self.repo.list_by_project(
            project_id,
            status=transmittal_status,
            limit=limit,
            offset=offset,
        )

    # ── Update ────────────────────────────────────────────────────────────

    async def update_transmittal(
        self,
        transmittal_id: uuid.UUID,
        data: TransmittalUpdate,
    ) -> Transmittal:
        """Update transmittal fields. Fails if transmittal is locked."""
        transmittal = await self.get_transmittal(transmittal_id)

        if transmittal.is_locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Transmittal is locked after issue and cannot be modified",
            )

        fields = data.model_dump(exclude_unset=True, exclude={"recipients", "items"})
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            await self.repo.update_fields(transmittal_id, **fields)

        # Replace recipients if provided
        if data.recipients is not None:
            await self.repo.delete_recipients(transmittal_id)
            for r in data.recipients:
                recipient = TransmittalRecipient(
                    transmittal_id=transmittal_id,
                    recipient_org_id=r.recipient_org_id,
                    recipient_user_id=r.recipient_user_id,
                    action_required=r.action_required,
                )
                await self.repo.add_recipient(recipient)

        # Replace items if provided
        if data.items is not None:
            await self.repo.delete_items(transmittal_id)
            for item_data in data.items:
                item = TransmittalItem(
                    transmittal_id=transmittal_id,
                    document_id=item_data.document_id,
                    revision_id=item_data.revision_id,
                    item_number=item_data.item_number,
                    description=item_data.description,
                    notes=item_data.notes,
                )
                await self.repo.add_item(item)

        updated = await self.repo.get(transmittal_id)
        logger.info("Transmittal updated: %s", transmittal_id)
        return updated  # type: ignore[return-value]

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_transmittal(self, transmittal_id: uuid.UUID) -> None:
        """Delete a transmittal. Only allowed while the transmittal is in
        draft (unlocked); issued transmittals are an audit record and must
        stay for compliance."""
        transmittal = await self.get_transmittal(transmittal_id)
        if transmittal.is_locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Issued transmittals cannot be deleted — they are part of the audit trail",
            )
        await self.repo.delete(transmittal_id)
        logger.info("Transmittal deleted: %s", transmittal.transmittal_number)

    # ── Issue (lock) ──────────────────────────────────────────────────────

    async def issue_transmittal(self, transmittal_id: uuid.UUID) -> Transmittal:
        """Lock the transmittal and set status to 'issued'."""
        transmittal = await self.get_transmittal(transmittal_id)

        if transmittal.is_locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Transmittal has already been issued",
            )

        now = datetime.now(UTC).isoformat()
        await self.repo.update_fields(
            transmittal_id,
            status="issued",
            is_locked=True,
            issued_date=now,
        )

        updated = await self.repo.get(transmittal_id)
        logger.info("Transmittal issued: %s", transmittal.transmittal_number)
        return updated  # type: ignore[return-value]

    # ── Acknowledge ───────────────────────────────────────────────────────

    async def acknowledge_receipt(
        self,
        transmittal_id: uuid.UUID,
        recipient_id: uuid.UUID,
    ) -> TransmittalRecipient:
        """Mark a recipient as having acknowledged the transmittal."""
        # Verify transmittal exists and is in a valid state for acknowledgement
        transmittal = await self.get_transmittal(transmittal_id)
        if transmittal.status not in ("issued", "responded"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot acknowledge transmittal in status '{transmittal.status}'",
            )

        recipient = await self.repo.get_recipient(recipient_id)
        if recipient is None or recipient.transmittal_id != transmittal_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recipient not found for this transmittal",
            )

        if recipient.acknowledged_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Recipient has already acknowledged this transmittal",
            )

        now = datetime.now(UTC)
        await self.repo.update_recipient(recipient_id, acknowledged_at=now)

        result = await self.repo.get_recipient(recipient_id)
        logger.info("Transmittal acknowledged: recipient=%s", recipient_id)
        return result  # type: ignore[return-value]

    # ── Respond ───────────────────────────────────────────────────────────

    async def submit_response(
        self,
        transmittal_id: uuid.UUID,
        recipient_id: uuid.UUID,
        response_text: str,
    ) -> TransmittalRecipient:
        """Submit a response from a recipient."""
        # Verify transmittal exists and is in a valid state for responses
        transmittal = await self.get_transmittal(transmittal_id)
        if transmittal.status not in ("issued", "responded"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot respond to transmittal in status '{transmittal.status}'",
            )

        recipient = await self.repo.get_recipient(recipient_id)
        if recipient is None or recipient.transmittal_id != transmittal_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recipient not found for this transmittal",
            )

        now = datetime.now(UTC)
        await self.repo.update_recipient(
            recipient_id,
            response=response_text,
            responded_at=now,
        )

        # Check if all recipients responded — auto-close if so
        transmittal = await self.repo.get(transmittal_id)
        if transmittal is not None:
            all_responded = all(r.responded_at is not None for r in transmittal.recipients)
            if all_responded and transmittal.status == "issued":
                await self.repo.update_fields(transmittal_id, status="responded")

        result = await self.repo.get_recipient(recipient_id)
        logger.info("Transmittal response submitted: recipient=%s", recipient_id)
        return result  # type: ignore[return-value]
