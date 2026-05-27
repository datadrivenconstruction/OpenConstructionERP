# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Compliance documents service — CRUD + status derivation."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from datetime import date as _date
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.compliance_docs.models import ComplianceDoc
from app.modules.compliance_docs.repository import ComplianceDocRepository
from app.modules.compliance_docs.schemas import (
    ComplianceDocCreate,
    ComplianceDocUpdate,
)

logger = logging.getLogger(__name__)

# Status values that should fire a ``compliance_docs.expiry.alert`` event
# whenever a write transitions a doc INTO them. ``active`` → no alert.
# ``cancelled`` / ``void`` → no alert (manual close, not a deadline).
_ALERT_STATUSES: frozenset[str] = frozenset({"expiring_soon", "expired"})

# ── Status set (kept in sync with schemas.STATUSES) ────────────────────

_TERMINAL_STATUSES: frozenset[str] = frozenset({"cancelled", "void"})


def recompute_status(
    today: _date,
    expires_at: _date,
    notify_days_before: int,
    *,
    current_status: str | None = None,
) -> str:
    """‌⁠‍Derive ``status`` from the date window.

    Pure function so unit tests can drive it without a session.

    Rules:
        - If the caller has explicitly marked the document ``cancelled``
          or ``void``, preserve that — those are terminal manual states
          and must never auto-flip back to ``active``.
        - ``today > expires_at``  → ``expired``.
        - ``today + notify_days_before >= expires_at`` → ``expiring_soon``.
        - Otherwise → ``active``.

    Args:
        today: The reference date (usually :func:`datetime.now().date()`).
        expires_at: When the document loses validity.
        notify_days_before: How many days before expiry counts as
            "expiring soon".
        current_status: Existing stored status; ``cancelled``/``void``
            are preserved.
    """
    if current_status in _TERMINAL_STATUSES:
        return current_status  # type: ignore[return-value]

    if today > expires_at:
        return "expired"

    # Inclusive on both sides — exactly ``notify_days_before`` days out
    # already counts as "expiring soon" so reminders aren't silently
    # skipped on the boundary day.
    delta = (expires_at - today).days
    if delta <= max(0, notify_days_before):
        return "expiring_soon"

    return "active"


class ComplianceDocService:
    """‌⁠‍Business logic for the compliance docs tracker."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ComplianceDocRepository(session)

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _today() -> _date:
        return datetime.now(UTC).date()

    @staticmethod
    def _publish_expiry_alert(
        doc: ComplianceDoc,
        *,
        previous_status: str | None,
    ) -> None:
        """Fire ``compliance_docs.expiry.alert`` on a status transition.

        Only the *transition* into ``expiring_soon`` / ``expired`` fires
        the event — repeated PATCHes that leave a doc inside the same
        alert bucket don't re-spam subscribers. ``previous_status=None``
        is treated as "no prior state" (create path).
        """
        if doc.status not in _ALERT_STATUSES:
            return
        if previous_status == doc.status:
            return  # No transition — already in this bucket.

        try:
            today = datetime.now(UTC).date()
            days = (doc.expires_at - today).days if doc.expires_at else 0
        except TypeError:  # pragma: no cover — defensive
            days = 0

        # Detached publish so SQLite's single-writer constraint isn't
        # hit by a notifications subscriber opening a second session
        # while we still hold the request's write lock.
        event_bus.publish_detached(
            "compliance_docs.expiry.alert",
            {
                "doc_id": str(doc.id),
                "project_id": str(doc.project_id),
                "doc_type": doc.doc_type,
                "name": doc.name,
                "status": doc.status,
                "expires_at": (doc.expires_at.isoformat() if doc.expires_at else None),
                "days_until_expiry": days,
                "notify_days_before": doc.notify_days_before,
                "previous_status": previous_status,
            },
            source_module="compliance_docs",
        )

    async def _check_attachment(
        self,
        project_id: uuid.UUID,
        attachment_document_id: uuid.UUID | None,
    ) -> None:
        """Reject an attachment from a different project.

        FK is enough to prevent dangling references, but cross-project
        smuggling needs an extra service-level guard.
        """
        if attachment_document_id is None:
            return
        # Lazy import — keeps the module loadable when the documents
        # module is disabled.
        try:
            from app.modules.documents.models import Document
        except ImportError:  # pragma: no cover — documents always present
            return

        stmt = select(Document.project_id).where(Document.id == attachment_document_id)
        row = (await self.session.execute(stmt)).first()
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Attachment document not found.",
            )
        if str(row[0]) != str(project_id):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=("Attachment document belongs to a different project."),
            )

    # ── CRUD ────────────────────────────────────────────────────────

    async def create_doc(
        self,
        data: ComplianceDocCreate,
        *,
        user_id: str | None = None,
    ) -> ComplianceDoc:
        if data.expires_at < data.effective_date:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=("expires_at must be on or after effective_date."),
            )

        await self._check_attachment(
            data.project_id,
            data.attachment_document_id,
        )

        derived_status = data.status or recompute_status(
            today=self._today(),
            expires_at=data.expires_at,
            notify_days_before=data.notify_days_before,
        )

        doc = ComplianceDoc(
            project_id=data.project_id,
            doc_type=data.doc_type,
            name=data.name,
            issuer=data.issuer,
            policy_number=data.policy_number,
            coverage_amount=data.coverage_amount,
            currency=data.currency,
            effective_date=data.effective_date,
            expires_at=data.expires_at,
            notify_days_before=data.notify_days_before,
            status=derived_status,
            attachment_document_id=data.attachment_document_id,
            notes=data.notes,
            metadata_=data.metadata,
            created_by=user_id,
        )
        doc = await self.repo.create(doc)
        logger.info(
            "Compliance doc created: %s (%s) for project %s",
            doc.id,
            doc.doc_type,
            doc.project_id,
        )
        # Fire expiry alert if the doc was created already-expiring.
        # ``previous_status=None`` → unconditional fire when current
        # status is in the alert set.
        self._publish_expiry_alert(doc, previous_status=None)
        return doc

    async def get_doc(self, doc_id: uuid.UUID) -> ComplianceDoc:
        doc = await self.repo.get_by_id(doc_id)
        if doc is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Compliance document not found.",
            )
        return doc

    async def list_docs(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        doc_type: str | None = None,
    ) -> list[ComplianceDoc]:
        return await self.repo.list_for_project(
            project_id,
            status=status,
            doc_type=doc_type,
        )

    async def list_expiring_soon(
        self,
        project_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[ComplianceDoc]:
        return await self.repo.list_expiring_soon(project_id, limit=limit)

    async def update_doc(
        self,
        doc_id: uuid.UUID,
        data: ComplianceDocUpdate,
        *,
        user_id: str | None = None,
    ) -> ComplianceDoc:
        doc = await self.get_doc(doc_id)
        previous_status = doc.status

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Same-project guard if attachment is being changed.
        if "attachment_document_id" in fields:
            await self._check_attachment(
                doc.project_id,
                fields["attachment_document_id"],
            )

        # Validate date ordering if either side moved.
        new_effective = fields.get("effective_date", doc.effective_date)
        new_expires = fields.get("expires_at", doc.expires_at)
        if new_expires < new_effective:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=("expires_at must be on or after effective_date."),
            )

        # If status not explicitly set in the patch, recompute it from
        # the (possibly updated) date window.
        explicit_status = fields.get("status")
        if explicit_status is None:
            fields["status"] = recompute_status(
                today=self._today(),
                expires_at=new_expires,
                notify_days_before=fields.get(
                    "notify_days_before",
                    doc.notify_days_before,
                ),
                current_status=doc.status,
            )

        # Audit: track who applied the patch inside ``metadata_`` so we
        # don't need an alembic migration for a new column. Caller may
        # have also patched ``metadata`` itself — merge instead of
        # clobber.
        if user_id is not None:
            merged_meta = dict(fields.get("metadata_") or doc.metadata_ or {})
            merged_meta["updated_by"] = user_id
            merged_meta["updated_at"] = datetime.now(UTC).isoformat()
            fields["metadata_"] = merged_meta

        if not fields:
            return doc

        await self.repo.update_fields(doc_id, **fields)
        fresh = await self.repo.get_by_id(doc_id)
        result = fresh or doc
        # Emit alert only if the patch *moved* the doc into an alerting
        # bucket — same bucket → no event (avoids subscriber re-spam).
        self._publish_expiry_alert(result, previous_status=previous_status)
        return result

    async def delete_doc(self, doc_id: uuid.UUID) -> None:
        await self.get_doc(doc_id)
        await self.repo.delete(doc_id)
        logger.info("Compliance doc deleted: %s", doc_id)

    async def attach_file(
        self,
        doc_id: uuid.UUID,
        *,
        relative_path: str,
        detected_mime: str,
        size_bytes: int,
        user_id: str | None = None,
    ) -> ComplianceDoc:
        """Record a magic-byte-validated upload against a compliance doc.

        Caller (the router) is responsible for the magic-byte gate and
        for actually writing the bytes to disk — this method just
        persists the metadata. Stored under ``metadata_["attachment"]``
        to avoid an alembic migration; readers should treat the dict
        as opaque.
        """
        doc = await self.get_doc(doc_id)

        merged_meta = dict(doc.metadata_ or {})
        merged_meta["attachment"] = {
            "path": relative_path,
            "mime": detected_mime,
            "size": int(size_bytes),
            "uploaded_at": datetime.now(UTC).isoformat(),
            "uploaded_by": user_id,
        }
        if user_id is not None:
            merged_meta["updated_by"] = user_id
            merged_meta["updated_at"] = datetime.now(UTC).isoformat()

        await self.repo.update_fields(doc_id, metadata_=merged_meta)
        fresh = await self.repo.get_by_id(doc_id)
        logger.info(
            "Compliance doc %s attachment recorded (%s, %d bytes)",
            doc_id,
            detected_mime,
            size_bytes,
        )
        return fresh or doc


__all__ = ["ComplianceDocService", "recompute_status"]
