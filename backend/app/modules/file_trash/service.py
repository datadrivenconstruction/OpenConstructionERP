# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Trash business logic.

Stateless service layer. Owns the soft-delete + restore semantics:

* ``soft_delete`` — snapshot the original row's payload into the trash
  table and remove the original.
* ``restore`` — re-insert the payload into its kind table; mark the
  trash row as ``restored_at``.
* ``purge`` — hard-delete a trash row.
* ``purge_expired_trash`` — nightly cron entry point that purges every
  trash row past its ``retention_days`` window.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_trash.models import FileTrash
from app.modules.file_trash.repository import FileTrashRepository

logger = logging.getLogger(__name__)

# Valid file kinds — mirrors file_versions.models.FILE_KINDS so the
# two modules agree on the polymorphic vocabulary.
TRASH_KINDS: tuple[str, ...] = (
    "document",
    "photo",
    "sheet",
    "bim_model",
    "dwg_drawing",
    "takeoff",
    "report",
    "markup",
)


def _validate_kind(kind: str) -> None:
    if kind not in TRASH_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown kind: {kind!r}",
        )


def _serialise_row(row: object) -> dict[str, Any]:
    """JSON-snapshot every column on an ORM row.

    Uses SQLAlchemy's inspection API so this works for every kind
    without hand-rolling a per-kind serialiser. UUID / datetime values
    are coerced to strings so the dict is JSON-safe.
    """
    from sqlalchemy import inspect as sa_inspect

    state = sa_inspect(row)
    if state is None:
        return {}
    out: dict[str, Any] = {}
    for col in state.mapper.column_attrs:
        val = getattr(row, col.key, None)
        if isinstance(val, uuid.UUID):
            out[col.key] = str(val)
        elif isinstance(val, datetime):
            out[col.key] = val.isoformat()
        elif isinstance(val, (dict, list, str, int, float, bool)) or val is None:
            out[col.key] = val
        else:
            out[col.key] = str(val)
    return out


# Polymorphic kind → (ORM model, repository-style id column).
def _kind_model(kind: str) -> type:
    """Resolve the ORM model class for a given file kind.

    Lazy imports keep the trash module loadable without dragging every
    kind module into memory at startup.
    """
    if kind == "document":
        from app.modules.documents.models import Document

        return Document
    if kind == "photo":
        from app.modules.documents.models import ProjectPhoto

        return ProjectPhoto
    if kind == "sheet":
        from app.modules.documents.models import Sheet

        return Sheet
    if kind == "bim_model":
        from app.modules.bim_hub.models import BIMModel

        return BIMModel
    if kind == "dwg_drawing":
        from app.modules.dwg_takeoff.models import DwgDrawing

        return DwgDrawing
    if kind == "takeoff":
        from app.modules.takeoff.models import TakeoffMeasurement

        return TakeoffMeasurement
    if kind == "report":
        # The reporting module names its row class ``GeneratedReport``;
        # the file-manager surface labels the kind simply ``report``.
        from app.modules.reporting.models import GeneratedReport

        return GeneratedReport
    if kind == "markup":
        from app.modules.markups.models import Markup

        return Markup
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unsupported kind: {kind!r}",
    )


class FileTrashService:
    """Business logic for the recycle-bin feature."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = FileTrashRepository(session)

    async def get(self, trash_id: uuid.UUID) -> FileTrash:
        row = await self.repo.get_by_id(trash_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Trash item not found",
            )
        return row

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[FileTrash], int]:
        return await self.repo.list_for_project(project_id, offset=offset, limit=limit)

    async def soft_delete(
        self,
        *,
        project_id: uuid.UUID,
        kind: str,
        original_id: str,
        canonical_name: str = "",
        payload: dict[str, Any] | None = None,
        retention_days: int = 30,
        actor_id: uuid.UUID | None = None,
    ) -> FileTrash:
        """Snapshot + remove the original row.

        When ``payload`` is supplied (e.g. the upload handler already
        holds the row in memory), it is stored verbatim. Otherwise the
        service loads the row via :func:`_kind_model` and snapshots it
        via :func:`_serialise_row`. The original row is removed in the
        same transaction so the file disappears from the file manager
        immediately.
        """
        _validate_kind(kind)
        # ``payload=None`` → look up + serialise the live row; any other
        # value (including an explicit empty dict ``{}``) is treated as a
        # caller-provided snapshot, so the live-row deletion path is
        # skipped. This matters for non-database callers (cron jobs,
        # tests) that just want a trash record without touching the
        # source row.
        snapshot: dict[str, Any] = dict(payload) if payload is not None else {}
        caller_supplied_snapshot = payload is not None
        original_row: Any | None = None

        if not caller_supplied_snapshot:
            model = _kind_model(kind)
            try:
                pk_value: Any = uuid.UUID(original_id)
            except (ValueError, TypeError):
                pk_value = original_id
            original_row = await self.session.get(model, pk_value)
            if original_row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Original {kind} row not found: {original_id}",
                )
            snapshot = _serialise_row(original_row)

        now = datetime.now(UTC)
        row = FileTrash(
            project_id=project_id,
            original_kind=kind,
            original_id=original_id,
            canonical_name=canonical_name or snapshot.get("name") or "",
            payload_json=snapshot,
            trashed_at=now,
            trashed_by_id=actor_id,
            retention_days=retention_days,
        )
        await self.repo.add(row)

        # Remove the original after the snapshot is durable. If the
        # caller pre-snapshotted (no in-memory row to delete) the
        # caller is responsible for removing the source.
        if original_row is not None:
            await self.session.delete(original_row)
            await self.session.flush()

        return row

    async def restore(
        self,
        trash_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> FileTrash:
        """Re-create the original row from the JSON snapshot."""
        row = await self.get(trash_id)
        if row.restored_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Trash item already restored",
            )
        if row.purged_at is not None:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Trash item already purged",
            )
        model = _kind_model(row.original_kind)
        payload = dict(row.payload_json or {})

        # Coerce well-known UUID / datetime fields back from their
        # JSON-string form. Anything we can't coerce is passed through
        # as-is and SQLAlchemy / Pydantic will reject it loudly.
        for k, v in list(payload.items()):
            if isinstance(v, str) and k.endswith(("_id", "id")):
                try:
                    payload[k] = uuid.UUID(v)
                    continue
                except (ValueError, TypeError):
                    pass
            if isinstance(v, str) and k.endswith(("_at", "_date", "date_")):
                try:
                    payload[k] = datetime.fromisoformat(v)
                    continue
                except (ValueError, TypeError):
                    pass

        # Build the ORM row using only attributes the model accepts.
        valid = {c.key for c in model.__mapper__.column_attrs}  # type: ignore[attr-defined]
        clean = {k: v for k, v in payload.items() if k in valid}

        # SQLAlchemy assigns a fresh ``created_at`` / ``updated_at``
        # server-default; force the original id back so cross-module
        # links (e.g. activity log, document<->BIM) survive the trip.
        new_row = model(**clean)
        self.session.add(new_row)
        await self.session.flush()

        row.restored_at = datetime.now(UTC)
        row.restored_by_id = actor_id
        await self.session.flush()
        return row

    async def purge(self, trash_id: uuid.UUID, *, confirm_token: str) -> None:
        """Hard-delete a trash row. Requires the matching restore token."""
        row = await self.get(trash_id)
        if confirm_token != row.restore_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid purge confirmation token",
            )
        await self.repo.delete(trash_id)


_STORAGE_PATH_KEYS: tuple[str, ...] = (
    # Documents / photos / sheets / dwg / takeoff all use ``file_path``;
    # markup persists the source under ``image_path``; BIM models use
    # ``model_path``. Cover the union so the purge job is kind-agnostic.
    "file_path",
    "physical_path",
    "image_path",
    "model_path",
    "storage_path",
)


def _candidate_storage_paths(payload: dict[str, Any]) -> list[str]:
    """Best-effort extraction of every on-disk path the snapshot mentions.

    Snapshots are JSON blobs of the original ORM row; the column the
    file lives in depends on the kind. We probe a small whitelist of
    well-known keys and return only non-empty strings — callers are
    responsible for the actual existence / unlink check.
    """
    out: list[str] = []
    for key in _STORAGE_PATH_KEYS:
        val = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(val, str) and val.strip():
            out.append(val.strip())
    return out


def _delete_storage_file(path: str) -> bool:
    """Unlink ``path`` if it exists. Logs + swallows OSErrors.

    Returns True when the file existed and was removed (or never
    existed in the first place, which is also a successful purge),
    False on a hard OSError (permission, in-use, etc.).
    """
    import os

    try:
        if os.path.exists(path):
            os.unlink(path)
            logger.debug("file_trash purge: removed %s", path)
        return True
    except OSError:
        logger.warning("file_trash purge: could not unlink %s", path, exc_info=True)
        return False


async def purge_expired_trash(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Hard-delete every trash row past its retention window.

    Designed as a Celery / cron entry point. Returns the number of rows
    purged so the job can log a meaningful summary. Best-effort deletes
    the snapshotted on-disk file as well: snapshots carry the original
    row's ``file_path`` / ``physical_path`` / ``image_path`` /
    ``model_path`` so the storage entry can be cleaned up alongside the
    trash row. A failed unlink is logged but does not abort the purge —
    the DB row is still removed so the trash table doesn't accumulate
    "stuck" entries.
    """
    if now is None:
        now = datetime.now(UTC)
    repo = FileTrashRepository(session)
    rows = await repo.expired(now)
    count = 0
    for row in rows:
        # Storage-side cleanup first so we never DB-delete a row whose
        # file we still believe lives on disk. ``_delete_storage_file``
        # is graceful — missing files count as success.
        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        for path in _candidate_storage_paths(payload):
            _delete_storage_file(path)
        await session.delete(row)
        count += 1
    if count:
        await session.flush()
        logger.info("purge_expired_trash: removed %d trash row(s)", count)
    return count
