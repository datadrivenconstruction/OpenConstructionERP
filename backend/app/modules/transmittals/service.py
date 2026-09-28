# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Transmittals service - business logic for transmittal management.

Stateless service layer. Handles:
- Transmittal CRUD with auto-numbering
- Locking on issue
- Recipient acknowledgement and response
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.json_merge import merge_metadata
from app.modules.transmittals.logic import (
    RESPONDABLE_STATUSES,
    STATUS_ISSUED,
    STATUS_RESPONDED,
    compute_response_due_date,
    issue_blockers,
    response_due_error,
)
from app.modules.transmittals.models import (
    Transmittal,
    TransmittalItem,
    TransmittalRecipient,
)
from app.modules.transmittals.repository import TransmittalRepository
from app.modules.transmittals.schemas import (
    RecipientCreate,
    TransmittalCreate,
    TransmittalUpdate,
)

logger = logging.getLogger(__name__)
_logger_ev = logging.getLogger(__name__ + ".events")

# Retry budget for ``create_transmittal`` when two concurrent transactions
# race on ``max(transmittal_number)+1``. The ``(project_id,
# transmittal_number)`` unique constraint turns the loser into an
# IntegrityError; we roll back and retry with a freshly-bumped suffix.
# Mirrors the rfi / changeorders code-collision retry loop.
_TRANSMITTAL_CREATE_MAX_RETRIES = 5


def _numbering_config(metadata: dict) -> dict:
    """Read optional per-project numbering settings from a transmittal's metadata.

    Projects can override the default ``TR-001`` scheme by setting
    ``numbering_prefix`` (for example a project code) and ``numbering_pad``
    (counter width) in metadata. Anything missing or the wrong type falls back
    to the sensible defaults in ``next_transmittal_number``.
    """
    config: dict = {}
    prefix = metadata.get("numbering_prefix")
    if isinstance(prefix, str) and prefix.strip():
        config["prefix"] = prefix.strip()
    pad = metadata.get("numbering_pad")
    if isinstance(pad, int) and pad > 0:
        config["pad"] = pad
    return config


def _resolve_response_due_date(
    issued_date: str | None,
    response_due_date: str | None,
    metadata: dict,
) -> str | None:
    """Work out the final response due date and check it is consistent.

    If no explicit due date is given but metadata carries
    ``response_period_days``, the deadline is computed as the issue date plus
    that many calendar days. The result is then checked so a deadline can
    never fall before the issue date. Raises HTTP 422 with a plain-language
    message on any bad value.
    """
    resolved = response_due_date
    if resolved is None:
        period = metadata.get("response_period_days")
        if isinstance(period, int):
            try:
                resolved = compute_response_due_date(issued_date, period)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=str(exc),
                ) from exc

    error = response_due_error(issued_date, resolved)
    if error is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=error,
        )
    return resolved


async def _safe_publish(name: str, data: dict, source_module: str = "oe_transmittals") -> None:
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


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
        """Create a new transmittal with auto-generated number.

        ``next_number`` reads ``MAX(transmittal_number)+1`` outside a
        SERIALIZABLE transaction, so two concurrent calls can pick the same
        suffix. The ``(project_id, transmittal_number)`` unique constraint
        makes the loser fail with :class:`IntegrityError`; we roll back and
        retry with a freshly-bumped suffix up to
        ``_TRANSMITTAL_CREATE_MAX_RETRIES`` times. If every retry collides
        (high contention) we surface HTTP 409 so the client retries - never
        silently writing a duplicate. Mirrors the rfi create_rfi pattern.
        """
        metadata = data.metadata or {}
        number_config = _numbering_config(metadata)
        response_due_date = _resolve_response_due_date(
            data.issued_date,
            data.response_due_date,
            metadata,
        )

        last_exc: Exception | None = None
        transmittal: Transmittal | None = None
        number = ""
        for _attempt in range(_TRANSMITTAL_CREATE_MAX_RETRIES):
            number = await self.repo.next_number(data.project_id, **number_config)
            candidate = Transmittal(
                project_id=data.project_id,
                transmittal_number=number,
                subject=data.subject,
                sender_org_id=data.sender_org_id,
                purpose_code=data.purpose_code,
                issued_date=data.issued_date,
                response_due_date=response_due_date,
                cover_note=data.cover_note,
                created_by=uuid.UUID(user_id) if user_id else None,
                metadata_=data.metadata,
            )
            try:
                transmittal = await self.repo.create(candidate)
            except IntegrityError as exc:
                # Another transaction picked the same number; roll back
                # and retry with a freshly-bumped suffix.
                last_exc = exc
                await self.session.rollback()
                continue
            break

        if transmittal is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Could not generate a unique transmittal number after "
                    f"{_TRANSMITTAL_CREATE_MAX_RETRIES} attempts (concurrent contention)."
                ),
            ) from last_exc

        # Add recipients
        for r in data.recipients:
            recipient = TransmittalRecipient(
                transmittal_id=transmittal.id,
                recipient_org_id=r.recipient_org_id,
                recipient_user_id=r.recipient_user_id,
                recipient_name=r.recipient_name,
                recipient_email=r.recipient_email,
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
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(transmittal, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )

        # Keep the issue/response dates consistent even when only one of them is
        # changed: compare the incoming value against whatever is already stored.
        effective_issued = fields.get("issued_date", transmittal.issued_date)
        effective_due = fields.get("response_due_date", transmittal.response_due_date)
        date_error = response_due_error(effective_issued, effective_due)
        if date_error is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=date_error,
            )

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

    # ── Recipients (post-hoc edit on a draft) ──────────────────────────────

    async def add_recipient(
        self,
        transmittal_id: uuid.UUID,
        data: "RecipientCreate",
    ) -> TransmittalRecipient:
        """Add a single recipient to a draft transmittal.

        Lets the detail view grow the recipient list one row at a time without
        resending the whole transmittal. Blocked once the transmittal is issued,
        since an issued transmittal is a locked audit record.
        """
        transmittal = await self.get_transmittal(transmittal_id)
        if transmittal.is_locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This transmittal has been issued and its recipients can no longer be changed.",
            )
        recipient = TransmittalRecipient(
            transmittal_id=transmittal_id,
            recipient_org_id=data.recipient_org_id,
            recipient_user_id=data.recipient_user_id,
            recipient_name=data.recipient_name,
            recipient_email=data.recipient_email,
            action_required=data.action_required,
        )
        created = await self.repo.add_recipient(recipient)
        logger.info("Transmittal recipient added: %s", transmittal_id)
        return created

    async def remove_recipient(
        self,
        transmittal_id: uuid.UUID,
        recipient_id: uuid.UUID,
    ) -> None:
        """Remove a recipient from a draft transmittal.

        Blocked once the transmittal is issued. Raises 404 when the recipient
        does not exist or belongs to another transmittal.
        """
        transmittal = await self.get_transmittal(transmittal_id)
        if transmittal.is_locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This transmittal has been issued and its recipients can no longer be changed.",
            )
        deleted = await self.repo.delete_recipient(transmittal_id, recipient_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recipient not found on this transmittal",
            )
        logger.info("Transmittal recipient removed: %s from %s", recipient_id, transmittal_id)

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_transmittal(self, transmittal_id: uuid.UUID) -> None:
        """Delete a transmittal. Only allowed while the transmittal is in
        draft (unlocked); issued transmittals are an audit record and must
        stay for compliance."""
        transmittal = await self.get_transmittal(transmittal_id)
        if transmittal.is_locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Issued transmittals cannot be deleted - they are part of the audit trail",
            )
        await self.repo.delete(transmittal_id)
        logger.info("Transmittal deleted: %s", transmittal.transmittal_number)

    # ── Issue (lock) ──────────────────────────────────────────────────────

    async def issue_transmittal(self, transmittal_id: uuid.UUID) -> Transmittal:
        """Formally send the transmittal: lock it and set status to 'issued'.

        Issuing is the point of no return, so we first check the transmittal is
        actually ready: it must have at least one recipient and at least one
        document, and it must not already be issued.
        """
        transmittal = await self.get_transmittal(transmittal_id)

        if transmittal.is_locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This transmittal has already been issued, so it cannot be issued again.",
            )

        blockers = issue_blockers(
            recipient_count=len(transmittal.recipients or []),
            item_count=len(transmittal.items or []),
        )
        if blockers:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Cannot issue this transmittal yet. " + " ".join(blockers),
            )

        now = datetime.now(UTC).isoformat()
        project_id_s = str(transmittal.project_id)
        transmittal_number_s = transmittal.transmittal_number
        subject_s = transmittal.subject
        recipient_user_ids = [
            str(r.recipient_user_id) for r in (transmittal.recipients or []) if r.recipient_user_id is not None
        ]

        prior_status = transmittal.status
        await self.repo.update_fields(
            transmittal_id,
            status=STATUS_ISSUED,
            is_locked=True,
            issued_date=now,
        )

        updated = await self.repo.get(transmittal_id)

        # Epic H - universal audit trail.
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=str(transmittal.created_by) if transmittal.created_by else None,
            entity_type="transmittal",
            entity_id=str(transmittal_id),
            action="status_changed",
            from_status=prior_status,
            to_status="issued",
            reason="Transmittal issued",
            metadata={
                "transmittal_number": transmittal_number_s,
                "recipient_count": len(recipient_user_ids),
            },
            module="transmittals",
            parent_entity_type="project",
            parent_entity_id=project_id_s,
            before_state={"status": prior_status, "is_locked": False},
            after_state={"status": "issued", "is_locked": True},
        )

        logger.info("Transmittal issued: %s", transmittal.transmittal_number)

        for recipient_user_id in recipient_user_ids:
            await _safe_publish(
                "transmittal.issued",
                {
                    "transmittal_id": str(transmittal_id),
                    "project_id": project_id_s,
                    "recipient_user_id": recipient_user_id,
                    "code": transmittal_number_s,
                    "title": subject_s,
                },
            )

        return updated  # type: ignore[return-value]

    # ── Acknowledge ───────────────────────────────────────────────────────

    async def acknowledge_receipt(
        self,
        transmittal_id: uuid.UUID,
        recipient_id: uuid.UUID,
    ) -> TransmittalRecipient:
        """Record that a recipient has confirmed they received the transmittal."""
        # A recipient can only acknowledge a transmittal that has been issued.
        transmittal = await self.get_transmittal(transmittal_id)
        if transmittal.status not in RESPONDABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This transmittal has not been issued yet, so there is nothing to "
                    "acknowledge. Issue the transmittal first."
                ),
            )

        recipient = await self.repo.get_recipient(recipient_id)
        if recipient is None or recipient.transmittal_id != transmittal_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That recipient is not on this transmittal. Check the recipient id.",
            )

        if recipient.acknowledged_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This recipient has already acknowledged receipt of the transmittal.",
            )

        project_id_s = str(transmittal.project_id)
        sender_user_id_s = str(transmittal.created_by) if transmittal.created_by else None
        ack_user_id_s = str(recipient.recipient_user_id) if recipient.recipient_user_id else None
        transmittal_number_s = transmittal.transmittal_number
        subject_s = transmittal.subject

        now = datetime.now(UTC)
        await self.repo.update_recipient(recipient_id, acknowledged_at=now)

        result = await self.repo.get_recipient(recipient_id)
        logger.info("Transmittal acknowledged: recipient=%s", recipient_id)

        await _safe_publish(
            "transmittal.acknowledged",
            {
                "transmittal_id": str(transmittal_id),
                "project_id": project_id_s,
                "sender_user_id": sender_user_id_s,
                "acknowledged_by_user_id": ack_user_id_s,
                "code": transmittal_number_s,
                "title": subject_s,
            },
        )

        return result  # type: ignore[return-value]

    # ── Respond ───────────────────────────────────────────────────────────

    async def submit_response(
        self,
        transmittal_id: uuid.UUID,
        recipient_id: uuid.UUID,
        response_text: str,
    ) -> TransmittalRecipient:
        """Record a recipient's response to the transmittal."""
        # A recipient can only respond to a transmittal that has been issued.
        transmittal = await self.get_transmittal(transmittal_id)
        if transmittal.status not in RESPONDABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This transmittal has not been issued yet, so there is nothing to "
                    "respond to. Issue the transmittal first."
                ),
            )

        recipient = await self.repo.get_recipient(recipient_id)
        if recipient is None or recipient.transmittal_id != transmittal_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That recipient is not on this transmittal. Check the recipient id.",
            )

        if recipient.responded_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This recipient has already responded to the transmittal.",
            )

        project_id_s = str(transmittal.project_id)
        sender_user_id_s = str(transmittal.created_by) if transmittal.created_by else None
        responder_user_id_s = str(recipient.recipient_user_id) if recipient.recipient_user_id else None
        transmittal_number_s = transmittal.transmittal_number
        subject_s = transmittal.subject
        response_summary = (response_text or "")[:200]

        now = datetime.now(UTC)
        await self.repo.update_recipient(
            recipient_id,
            response=response_text,
            responded_at=now,
        )

        # Once every recipient has responded, mark the whole transmittal as
        # 'responded' so the sender can see the exchange is complete.
        transmittal = await self.repo.get(transmittal_id)
        if transmittal is not None:
            recipients = transmittal.recipients or []
            all_responded = bool(recipients) and all(r.responded_at is not None for r in recipients)
            if all_responded and transmittal.status == STATUS_ISSUED:
                await self.repo.update_fields(transmittal_id, status=STATUS_RESPONDED)

        result = await self.repo.get_recipient(recipient_id)
        logger.info("Transmittal response submitted: recipient=%s", recipient_id)

        await _safe_publish(
            "transmittal.responded",
            {
                "transmittal_id": str(transmittal_id),
                "project_id": project_id_s,
                "sender_user_id": sender_user_id_s,
                "responder_user_id": responder_user_id_s,
                "response_summary": response_summary,
                "code": transmittal_number_s,
                "title": subject_s,
            },
        )

        return result  # type: ignore[return-value]
