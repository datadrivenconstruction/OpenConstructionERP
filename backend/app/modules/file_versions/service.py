# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Versioning business logic.

Stateless service layer. Owns the version-chain rules:

* ``register_new_version`` — supersede the current row + insert a new
  one as current; auto-increment ``version_number`` per chain.
* ``restore_version`` — flip a historical row back to current; the
  previously-current row is moved to superseded with a chain pointer.

The service is wired through the router but the public functions are
also importable from upload pipelines so other modules can register a
new version without going through the HTTP boundary (e.g. the document
upload handler).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_versions.models import FILE_KINDS, FileVersion
from app.modules.file_versions.repository import FileVersionRepository
from app.modules.file_versions.schemas import FileVersionCreate

logger = logging.getLogger(__name__)


def _validate_kind(kind: str) -> None:
    if kind not in FILE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown file_kind: {kind!r}",
        )


def _canonicalize(name: str) -> str:
    """Strip trailing whitespace; case-preserving — chain key is exact."""
    return name.strip()


class FileVersionService:
    """Business logic for the version-chain feature."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = FileVersionRepository(session)

    async def get(self, version_id: uuid.UUID) -> FileVersion:
        row = await self.repo.get_by_id(version_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Version not found",
            )
        return row

    async def list_chain(
        self,
        *,
        project_id: uuid.UUID,
        file_kind: str,
        canonical_name: str,
    ) -> list[FileVersion]:
        _validate_kind(file_kind)
        return await self.repo.list_chain(
            project_id=project_id,
            file_kind=file_kind,
            canonical_name=_canonicalize(canonical_name),
        )

    async def list_for_file(
        self,
        *,
        file_id: str,
        file_kind: str,
    ) -> list[FileVersion]:
        _validate_kind(file_kind)
        return await self.repo.list_for_file_id(file_id, file_kind)

    async def register_new_version(
        self,
        payload: FileVersionCreate,
        *,
        uploaded_by_id: uuid.UUID | None,
    ) -> FileVersion:
        """Insert a new version row + supersede the prior current row.

        Behaviour:
            1. Find the existing ``is_current`` row in the chain (if any).
            2. Compute the next ``version_number`` (chain max + 1; v1
               when chain is empty).
            3. Insert the new row with ``is_current=True``.
            4. Flip the previous current row to ``is_current=False`` and
               link it backwards via ``superseded_by_id`` /
               ``superseded_at``. Wire the new row's
               ``previous_version_id`` to the prior current.
        """
        _validate_kind(payload.file_kind)
        canonical = _canonicalize(payload.canonical_name)
        now = datetime.now(UTC)

        previous_current = await self.repo.get_current(
            project_id=payload.project_id,
            file_kind=payload.file_kind,
            canonical_name=canonical,
        )

        # Caller may pass an explicit previous_version_id (e.g. when
        # rolling a side-branch back into the main chain). When omitted
        # we auto-link to the currently-active row.
        previous_id: uuid.UUID | None = payload.previous_version_id
        if previous_id is None and previous_current is not None:
            previous_id = previous_current.id

        version_number = await self.repo.next_version_number(
            project_id=payload.project_id,
            file_kind=payload.file_kind,
            canonical_name=canonical,
        )

        row = FileVersion(
            project_id=payload.project_id,
            file_kind=payload.file_kind,
            file_id=payload.file_id,
            version_number=version_number,
            canonical_name=canonical,
            previous_version_id=previous_id,
            is_current=True,
            superseded_at=None,
            superseded_by_id=None,
            notes=payload.notes,
            uploaded_by_id=uploaded_by_id,
            uploaded_at=now,
            file_size=payload.file_size,
            checksum=payload.checksum,
        )
        await self.repo.add(row)

        # Supersede the prior current — done AFTER adding the new row
        # so the supersede pointer is set in one transaction.
        if previous_current is not None and previous_current.id != row.id:
            previous_current.is_current = False
            previous_current.superseded_at = now
            previous_current.superseded_by_id = row.id
            await self.session.flush()

        # ── Fan-out subscription notifications (W10) ─────────────────
        # Only when this revision actually supersedes a prior current
        # row do we count it as a "new revision posted" event — the
        # very first version of a brand-new file is a "created" event
        # and is owned by the kind module's own upload handler.
        # Lazy-import so the file_versions module stays runnable when
        # the file_distribution module is disabled / not installed.
        if previous_current is not None and previous_current.id != row.id:
            try:
                from app.modules.file_distribution.service import (
                    on_file_new_revision,
                )

                await on_file_new_revision(
                    self.session,
                    project_id=row.project_id,
                    file_kind=row.file_kind,
                    file_id=str(row.file_id),
                    canonical_name=row.canonical_name,
                    version_number=row.version_number,
                    actor_id=uploaded_by_id,
                )
            except Exception:  # noqa: BLE001
                # A subscription / notification failure must never
                # roll back a successful version write.
                logger.debug(
                    "on_file_new_revision hook failed; version row was still committed",
                    exc_info=True,
                )

        return row

    async def restore_version(
        self,
        version_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None,
    ) -> FileVersion:
        """Promote ``version_id`` back to current; demote the prior current."""
        target = await self.get(version_id)
        if target.is_current:
            # Already the current row — nothing to do, just echo back.
            return target

        now = datetime.now(UTC)
        previous_current = await self.repo.get_current(
            project_id=target.project_id,
            file_kind=target.file_kind,
            canonical_name=target.canonical_name,
        )

        if previous_current is not None and previous_current.id != target.id:
            previous_current.is_current = False
            previous_current.superseded_at = now
            previous_current.superseded_by_id = target.id

        target.is_current = True
        target.superseded_at = None
        target.superseded_by_id = None
        # Record actor on the restored row's audit trail by reusing the
        # ``uploaded_by_id`` slot when caller provided one — historical
        # uploader is preserved on the prior current row.
        if actor_id is not None and target.uploaded_by_id is None:
            target.uploaded_by_id = actor_id

        await self.session.flush()
        # ``updated_at`` carries an ``onupdate=func.now()`` server-default,
        # so SQLAlchemy marks the column expired after the flush so it can
        # refetch the DB-computed value. Touching the attribute during
        # response serialisation would then trigger a synchronous
        # lazy-load outside the active greenlet and raise MissingGreenlet
        # under asyncio. Refresh explicitly so every column is hydrated
        # before the row leaves the service.
        await self.session.refresh(target)
        return target
