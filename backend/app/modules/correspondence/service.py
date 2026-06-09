"""‌⁠‍Correspondence service - business logic for correspondence management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.correspondence.models import Correspondence
from app.modules.correspondence.repository import CorrespondenceRepository
from app.modules.correspondence.schemas import CorrespondenceCreate, CorrespondenceUpdate

logger = logging.getLogger(__name__)

# Max attempts when ``next_reference_number`` collides under concurrent
# creates. Five gives ample slack for high-throughput contention without
# letting a buggy / faulty unique-constraint state pin the request loop.
_MAX_NUMBER_RETRIES = 5


async def _safe_publish(name: str, data: dict, source_module: str = "oe_correspondence") -> None:
    """‌⁠‍Publish an event, swallowing errors so business logic continues.

    Used to drive the ``oe_correspondence_correspondence`` vector indexer
    (item 16) on create / update / delete without ever letting an
    event-bus hiccup break the CRUD path.
    """
    try:
        from app.core.events import event_bus

        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception as exc:
        logger.debug("Event publish failed for %s: %s", name, exc)


class CorrespondenceService:
    """‌⁠‍Business logic for correspondence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CorrespondenceRepository(session)

    async def create_correspondence(
        self,
        data: CorrespondenceCreate,
        user_id: str | None = None,
    ) -> Correspondence:
        """‌⁠‍Create a new correspondence record with auto-generated reference number.

        Concurrent-create race: ``next_reference_number`` computes the next
        ordinal from ``MAX(suffix)+1`` which has TOCTOU semantics. Two parallel
        POSTs can read the same MAX and both attempt to insert ``COR-005``. The
        unique constraint on ``(project_id, reference_number)`` turns the second
        insert into ``IntegrityError`` and we simply re-roll the number. After
        ``_MAX_NUMBER_RETRIES`` collisions we surface 409 rather than spin.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_NUMBER_RETRIES):
            reference_number = await self.repo.next_reference_number(data.project_id)

            correspondence = Correspondence(
                project_id=data.project_id,
                reference_number=reference_number,
                direction=data.direction,
                subject=data.subject,
                from_contact_id=data.from_contact_id,
                to_contact_ids=data.to_contact_ids,
                date_sent=data.date_sent,
                date_received=data.date_received,
                correspondence_type=data.correspondence_type,
                linked_document_ids=data.linked_document_ids,
                linked_transmittal_id=data.linked_transmittal_id,
                linked_rfi_id=data.linked_rfi_id,
                notes=data.notes,
                created_by=user_id,
                metadata_=data.metadata,
            )
            try:
                correspondence = await self.repo.create(correspondence)
            except IntegrityError as exc:
                last_exc = exc
                logger.warning(
                    "Reference-number collision on attempt %d for project %s (number=%s); retrying",
                    attempt + 1,
                    data.project_id,
                    reference_number,
                )
                continue
            # PII discipline: log only structural fields (ref number, direction,
            # type, project id). Subject and notes can contain personal data -
            # legal names, addresses, allegations - and structured-log sinks
            # outside our control (Sentry, Datadog) shouldn't see them.
            logger.info(
                "Correspondence created: %s (%s/%s) for project %s",
                reference_number,
                data.direction,
                data.correspondence_type,
                data.project_id,
            )
            # Publish correspondence.created so the vector indexer embeds the
            # new row for semantic search / the floating-chat assistant
            # (item 16).
            await _safe_publish(
                "correspondence.created",
                {
                    "project_id": str(data.project_id),
                    "correspondence_id": str(correspondence.id),
                    "reference_number": reference_number,
                },
            )
            return correspondence

        # All retries exhausted - translate to 409 so the caller can retry
        # at the HTTP layer with a clear contract.
        logger.error(
            "Reference-number collision still unresolved after %d retries for project %s",
            _MAX_NUMBER_RETRIES,
            data.project_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Could not allocate a unique reference number after {_MAX_NUMBER_RETRIES} attempts; please retry."
            ),
        ) from last_exc

    async def get_correspondence(self, correspondence_id: uuid.UUID) -> Correspondence:
        correspondence = await self.repo.get_by_id(correspondence_id)
        if correspondence is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Correspondence not found",
            )
        return correspondence

    async def list_correspondences(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        direction: str | None = None,
        correspondence_type: str | None = None,
    ) -> tuple[list[Correspondence], int]:
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            direction=direction,
            correspondence_type=correspondence_type,
        )

    async def update_correspondence(
        self,
        correspondence_id: uuid.UUID,
        data: CorrespondenceUpdate,
    ) -> Correspondence:
        correspondence = await self.get_correspondence(correspondence_id)

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return correspondence

        await self.repo.update_fields(correspondence_id, **fields)
        await self.session.refresh(correspondence)
        logger.info(
            "Correspondence updated: %s (fields=%s)",
            correspondence_id,
            list(fields.keys()),
        )
        # Publish correspondence.updated so the vector indexer re-embeds the
        # edited row (subject / notes may have changed) - item 16.
        await _safe_publish(
            "correspondence.updated",
            {
                "project_id": str(correspondence.project_id) if correspondence.project_id is not None else "",
                "correspondence_id": str(correspondence_id),
                "reference_number": getattr(correspondence, "reference_number", None),
            },
        )
        return correspondence

    async def delete_correspondence(self, correspondence_id: uuid.UUID) -> None:
        correspondence = await self.get_correspondence(correspondence_id)
        project_id_s = str(correspondence.project_id) if correspondence.project_id is not None else ""
        await self.repo.delete(correspondence_id)
        logger.info("Correspondence deleted: %s", correspondence_id)
        # Publish correspondence.deleted so the vector indexer drops the
        # embedding for the removed row (item 16).
        await _safe_publish(
            "correspondence.deleted",
            {
                "project_id": project_id_s,
                "correspondence_id": str(correspondence_id),
            },
        )

    async def add_attachment(
        self,
        correspondence_id: uuid.UUID,
        attachment_path: str,
    ) -> Correspondence:
        """‌⁠‍Append a validated attachment path to the correspondence.

        The caller (router) is responsible for magic-byte validation and
        for choosing the server-side filename; this method only mutates
        the JSON column. We avoid logging the path payload itself -
        attachment filenames may carry PII (e.g. ``CV_jane_doe.pdf``).
        """
        correspondence = await self.get_correspondence(correspondence_id)
        attachments = list(correspondence.attachments or [])
        attachments.append(attachment_path)
        await self.repo.update_fields(correspondence_id, attachments=attachments)
        await self.session.refresh(correspondence)
        logger.info(
            "Attachment added to correspondence %s (count=%d)",
            correspondence_id,
            len(attachments),
        )
        return correspondence
