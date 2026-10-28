# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Business logic for the source-data (prerequisite documents) register.

Owns four things a data model alone cannot:

* deriving a document's ``status`` from its validity window (recomputed on every
  write, the lifecycle and terminal states preserved);
* firing a ``source_data.expiry.alert`` event the moment a document
  *transitions* into an alerting bucket, so a notification subscriber can warn
  the team before a prerequisite lapses;
* answering "which prerequisites block the programme" (flagged and expired) and
  "is the required source-data checklist complete"; and
* assembling the structured payload for a "defective or missing source data"
  notice - data only, for another module to turn into correspondence.

All of it is jurisdiction-neutral; the country-specific content is carried as
data on the rows, never as logic here.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import UTC, datetime
from datetime import date as _date
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status

from app.core.events import event_bus
from app.modules.source_data.models import SourceChecklistItem, SourceDocument
from app.modules.source_data.repository import SourceDataRepository
from app.modules.source_data.schemas import (
    ChecklistSummary,
    DefectiveInputsNotice,
    SourceChecklistItemCreate,
    SourceChecklistItemUpdate,
    SourceDocumentCreate,
    SourceDocumentUpdate,
)

logger = logging.getLogger(__name__)

# Buckets whose *entry* fires the expiry alert.
_ALERT_STATUSES: frozenset[str] = frozenset({"expiring_soon", "expired"})

# ``superseded`` is terminal: a replaced document cannot be transitioned out of
# in place - issue a new row and link it via ``superseded_by_id``.
_TERMINAL_STATUSES: frozenset[str] = frozenset({"superseded"})

# Checklist statuses that count as resolved for completeness.
_RESOLVED_CHECKLIST: frozenset[str] = frozenset({"satisfied", "waived"})


def recompute_status(
    today: _date,
    valid_until: _date | None,
    notify_days_before: int,
    *,
    current_status: str | None = None,
) -> str:
    """Derive a source document's ``status`` from its validity window.

    Pure function so unit tests drive it without a session. Mirrors the
    :func:`app.modules.credentials.service.recompute_status` shape.

    Rules:
        - A ``superseded`` document keeps that terminal state - the auto-derive
          path never flips it back.
        - A ``requested`` document has not been received yet, so expiry maths do
          not apply; it stays ``requested``.
        - ``valid_until is None`` → the in-hand base state (``verified`` is
          preserved, otherwise ``received``): a perpetual document that never
          expires.
        - ``today > valid_until`` → ``expired``.
        - ``valid_until - today <= notify_days_before`` → ``expiring_soon``
          (inclusive on the boundary day so a reminder is never skipped).
        - Otherwise → the in-hand base state.
    """
    if current_status in _TERMINAL_STATUSES:
        return current_status  # type: ignore[return-value]
    if current_status == "requested":
        return "requested"
    base = "verified" if current_status == "verified" else "received"
    if valid_until is None:
        return base
    if today > valid_until:
        return "expired"
    delta = (valid_until - today).days
    if delta <= max(0, notify_days_before):
        return "expiring_soon"
    return base


class SourceDataService:
    """Business logic for the source-data register."""

    def __init__(self, session: object) -> None:
        self.session = session
        self.repo = SourceDataRepository(session)  # type: ignore[arg-type]

    @staticmethod
    def _today() -> _date:
        return datetime.now(UTC).date()

    @staticmethod
    def _publish_expiry_alert(
        document: SourceDocument,
        *,
        previous_status: str | None,
    ) -> None:
        """Fire ``source_data.expiry.alert`` on a status transition.

        Only the *transition* into ``expiring_soon`` / ``expired`` fires - a
        PATCH that leaves the document in the same alert bucket does not re-spam
        subscribers. ``previous_status=None`` is the create path.
        """
        if document.status not in _ALERT_STATUSES:
            return
        if previous_status == document.status:
            return

        try:
            today = datetime.now(UTC).date()
            days = (document.valid_until - today).days if document.valid_until else 0
        except TypeError:  # pragma: no cover - defensive
            days = 0

        # Detached publish so a notifications subscriber opening its own session
        # can't contend with the request's write transaction.
        event_bus.publish_detached(
            "source_data.expiry.alert",
            {
                "document_id": str(document.id),
                "project_id": str(document.project_id),
                "doc_type": document.doc_type,
                "name": document.name,
                "owner": document.owner,
                "authority": document.authority,
                "status": document.status,
                "blocks_schedule": document.blocks_schedule,
                "valid_until": (document.valid_until.isoformat() if document.valid_until else None),
                "days_until_expiry": days,
                "notify_days_before": document.notify_days_before,
                "previous_status": previous_status,
            },
            source_module="source_data",
        )

    # ── Documents: CRUD ─────────────────────────────────────────────────

    async def create_document(
        self,
        data: SourceDocumentCreate,
        *,
        user_id: str | None = None,
    ) -> SourceDocument:
        initial = data.status or "requested"
        derived_status = recompute_status(
            today=self._today(),
            valid_until=data.valid_until,
            notify_days_before=data.notify_days_before,
            current_status=initial,
        )

        document = SourceDocument(
            project_id=data.project_id,
            name=data.name,
            doc_type=data.doc_type,
            owner=data.owner,
            authority=data.authority,
            identifier=data.identifier,
            issued_at=data.issued_at,
            valid_until=data.valid_until,
            shelf_life_days=data.shelf_life_days,
            notify_days_before=data.notify_days_before,
            blocks_schedule=data.blocks_schedule,
            superseded_by_id=data.superseded_by_id,
            status=derived_status,
            notes=data.notes,
            metadata_=data.metadata,
            created_by=user_id,
        )
        document = await self.repo.create_document(document)
        logger.info(
            "Source document created: %s (%s) for project %s",
            document.id,
            document.doc_type,
            document.project_id,
        )
        self._publish_expiry_alert(document, previous_status=None)
        return document

    async def get_document(self, document_id: uuid.UUID) -> SourceDocument:
        row = await self.repo.get_document(document_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Source document not found.",
            )
        return row

    async def list_documents(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        doc_type: str | None = None,
    ) -> list[SourceDocument]:
        return await self.repo.list_documents(project_id, status=status, doc_type=doc_type)

    async def list_expiring_soon(
        self,
        project_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[SourceDocument]:
        return await self.repo.list_expiring_soon(project_id, limit=limit)

    async def list_blocking_schedule(self, project_id: uuid.UUID) -> list[SourceDocument]:
        """Prerequisite documents that block the programme: flagged and expired."""
        return await self.repo.list_blocking(project_id)

    async def update_document(
        self,
        document_id: uuid.UUID,
        data: SourceDocumentUpdate,
        *,
        user_id: str | None = None,
    ) -> SourceDocument:
        document = await self.get_document(document_id)
        previous_status = document.status

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)

        # Date ordering guard if either side moved.
        new_issued = fields.get("issued_at", document.issued_at)
        new_valid = fields.get("valid_until", document.valid_until)
        if new_issued is not None and new_valid is not None and new_valid < new_issued:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="valid_until must be on or after issued_at.",
            )

        explicit_status = fields.get("status")
        # Terminal-state contract: a superseded document cannot be transitioned
        # out of in place - the auto-derive path already preserves it; block the
        # explicit path too so it can't be revived by a stray PATCH.
        if explicit_status is not None and document.status in _TERMINAL_STATUSES and explicit_status != document.status:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cannot transition out of a terminal status.",
            )
        # When the caller sets a lifecycle status explicitly, feed it through the
        # derive so a received/verified doc with a past window still lands on the
        # honest expired/expiring_soon bucket.
        base_status = explicit_status if explicit_status is not None else document.status
        fields["status"] = recompute_status(
            today=self._today(),
            valid_until=new_valid,
            notify_days_before=fields.get("notify_days_before", document.notify_days_before),
            current_status=base_status,
        )

        # Apply the mutation on the loaded instance so metadata merge and the
        # metadata column alias are handled cleanly.
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            merged = dict(document.metadata_ or {})
            if isinstance(incoming, dict):
                merged.update(incoming)
            fields["metadata_"] = merged

        if user_id is not None:
            merged_meta = dict(fields.get("metadata_") or document.metadata_ or {})
            merged_meta["updated_by"] = user_id
            merged_meta["updated_at"] = datetime.now(UTC).isoformat()
            fields["metadata_"] = merged_meta

        for key, value in fields.items():
            setattr(document, key, value)
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(document)  # type: ignore[attr-defined]

        self._publish_expiry_alert(document, previous_status=previous_status)
        return document

    async def verify_document(
        self,
        document_id: uuid.UUID,
        *,
        user_id: str | None = None,
    ) -> SourceDocument:
        """Mark a document verified, then recompute so the window still governs.

        A verified document with a live window reads ``verified`` (or
        ``expiring_soon`` near its end); a verified but lapsed window still reads
        ``expired`` - verification confirms receipt, it does not extend validity.
        A superseded document cannot be verified.
        """
        document = await self.get_document(document_id)
        if document.status in _TERMINAL_STATUSES:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cannot verify a superseded document.",
            )
        return await self.update_document(
            document_id,
            SourceDocumentUpdate(status="verified"),
            user_id=user_id,
        )

    async def delete_document(self, document_id: uuid.UUID) -> None:
        await self.get_document(document_id)
        await self.repo.delete_document(document_id)

    # ── Checklist: CRUD ─────────────────────────────────────────────────

    async def create_checklist_item(self, data: SourceChecklistItemCreate) -> SourceChecklistItem:
        item = SourceChecklistItem(
            project_id=data.project_id,
            label=data.label,
            required=data.required,
            doc_type=data.doc_type,
            satisfied_by_id=data.satisfied_by_id,
            status=data.status,
        )
        return await self.repo.create_checklist_item(item)

    async def get_checklist_item(self, item_id: uuid.UUID) -> SourceChecklistItem:
        row = await self.repo.get_checklist_item(item_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Checklist item not found.",
            )
        return row

    async def list_checklist(self, project_id: uuid.UUID) -> list[SourceChecklistItem]:
        return await self.repo.list_checklist(project_id)

    async def update_checklist_item(
        self,
        item_id: uuid.UUID,
        data: SourceChecklistItemUpdate,
    ) -> SourceChecklistItem:
        item = await self.get_checklist_item(item_id)
        fields = data.model_dump(exclude_unset=True)
        # A checklist item linked to a satisfying document is, by definition,
        # satisfied unless the caller explicitly waived it.
        if "satisfied_by_id" in fields and fields["satisfied_by_id"] is not None and "status" not in fields:
            fields["status"] = "satisfied"
        for key, value in fields.items():
            setattr(item, key, value)
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(item)  # type: ignore[attr-defined]
        return item

    async def delete_checklist_item(self, item_id: uuid.UUID) -> None:
        await self.get_checklist_item(item_id)
        await self.repo.delete_checklist_item(item_id)

    # ── Aggregates ──────────────────────────────────────────────────────

    @staticmethod
    def summarize_checklist(items: list[SourceChecklistItem]) -> ChecklistSummary:
        """Roll up checklist completeness. Pure so it is unit-testable.

        Completeness is measured over the *required* items only: every required
        item must be satisfied or explicitly waived. A project with no required
        items is complete by vacuity.
        """
        required = [i for i in items if i.required]
        satisfied = sum(1 for i in items if i.status == "satisfied")
        waived = sum(1 for i in items if i.status == "waived")
        pending = sum(1 for i in items if i.status == "pending")
        missing_required = [i.label for i in required if i.status not in _RESOLVED_CHECKLIST]
        return ChecklistSummary(
            total=len(items),
            required=len(required),
            satisfied=satisfied,
            waived=waived,
            pending=pending,
            complete=not missing_required,
            missing_required=missing_required,
        )

    async def checklist_summary(self, project_id: uuid.UUID) -> ChecklistSummary:
        items = await self.repo.list_checklist(project_id)
        return self.summarize_checklist(items)

    async def is_checklist_complete(self, project_id: uuid.UUID) -> bool:
        """True when every required checklist item is satisfied or waived."""
        summary = await self.checklist_summary(project_id)
        return summary.complete

    async def defective_inputs_notice(self, project_id: uuid.UUID) -> DefectiveInputsNotice:
        """Assemble the structured "defective or missing source data" payload.

        Returns *data* another module can turn into a correspondence letter - it
        gathers the unresolved required checklist items and the expired
        documents, picks the owner responsible for the most outstanding items as
        the recipient, and writes a one-line summary. It renders no letter.
        """
        items = await self.repo.list_checklist(project_id)
        documents = await self.repo.list_documents(project_id)

        summary = self.summarize_checklist(items)
        expired = [d for d in documents if d.status == "expired"]

        expired_payload = [
            {
                "document_id": str(d.id),
                "name": d.name,
                "doc_type": d.doc_type,
                "owner": d.owner,
                "authority": d.authority,
                "valid_until": (d.valid_until.isoformat() if d.valid_until else None),
                "blocks_schedule": d.blocks_schedule,
            }
            for d in expired
        ]

        # Recipient heuristic: the owner named on the most expired documents.
        owner_counts = Counter(d.owner for d in expired if d.owner)
        recipient = owner_counts.most_common(1)[0][0] if owner_counts else None

        has_defects = bool(summary.missing_required) or bool(expired_payload)
        if has_defects:
            summary_text = (
                f"{len(summary.missing_required)} missing prerequisite(s) and "
                f"{len(expired_payload)} expired document(s) require attention before the schedule can proceed."
            )
        else:
            summary_text = "All required source data is present and in date."

        return DefectiveInputsNotice(
            project_id=project_id,
            recipient=recipient,
            missing_items=summary.missing_required,
            expired_documents=expired_payload,
            summary=summary_text,
            has_defects=has_defects,
        )
