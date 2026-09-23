# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Backup & Restore API.

Endpoints:
    POST /export    -- Download a ZIP backup of all user data
    POST /restore   -- Upload and restore from a backup ZIP
    POST /validate  -- Validate a backup ZIP without importing

BUG-018: ``POST /export/`` previously returned ``Content-Length: 0`` when
the request had a JSON body. The handler did not declare a body
parameter (so the OpenAPI surface was empty and the bug looked like
"endpoint is a stub"), and it returned ``StreamingResponse`` over an
``io.BytesIO`` - a combination that interacts badly with
``BaseHTTPMiddleware`` when the request also carries a body. The fix
moves the build-the-archive logic into ``service.build_backup`` (which
streams into a ``tempfile.SpooledTemporaryFile``) and exposes a typed
``ExportRequest`` body so the OpenAPI doc actually documents the API.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.dependencies import CurrentUserId, RequirePermission
from app.modules.backup.schemas import ExportRequest, RestoreResponse, ValidateResponse
from app.modules.backup.service import (
    APP_ID,
    BACKUP_FORMAT_VERSION,
    RestoreError,
    build_backup,
    cleanup_temp_file,
    deserialize_row,
    get_backup_tables,
    parse_backup_zip,
    restore_backup_data,
    restore_backup_files,
    serialize_row,
    spool_to_disk,
)

router = APIRouter(tags=["backup"])
logger = logging.getLogger(__name__)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/export/",
    tags=["Backup"],
    dependencies=[Depends(RequirePermission("backup.admin"))],
    summary="Export user data as a ZIP backup",
    response_class=FileResponse,
)
async def export_backup(
    user_id: CurrentUserId,
    body: ExportRequest = Body(default_factory=ExportRequest),
) -> FileResponse:
    """Export the requesting user's data as a downloadable ZIP backup.

    The archive contains:

    * ``manifest.json`` - backup metadata: app id, app version, format
      version, ISO-8601 timestamp, list of modules included, record
      counts per module, file count, SHA-256 checksum, warnings.
    * ``<module>.json`` - one file per module containing the SQLAlchemy
      rows for that module's tables (generic dump via
      :func:`sqlalchemy.inspect`).
    * ``files/<module>/<storage-key>`` - only when
      ``include_files=true``: binary blobs referenced by the module's
      ``file_path`` columns.

    The archive is built into a :class:`tempfile.SpooledTemporaryFile`
    (in-memory below 16 MiB, spilling to disk above) and served via
    :class:`FileResponse`. ``StreamingResponse`` is *not* used because
    the project's JSON-body sanitiser middleware emits an
    ``http.disconnect`` after replaying the request body, which
    Starlette interprets as a client hang-up and uses to cancel
    streaming bodies - the original BUG-018 ``Content-Length: 0``.
    """
    spool, manifest, _size = await build_backup(
        user_id=str(user_id),
        include_modules=body.include_modules,
        include_files=body.include_files,
        compression_level=body.compression_level,
    )
    # A plain file copy, and past the 16 MiB rollover a disk-to-disk one: off
    # the event loop like the build itself.
    path = await asyncio.to_thread(spool_to_disk, spool)

    timestamp = manifest["created_at"].replace("-", "").replace(":", "")[:15]
    filename = f"openconstructionerp_backup_{timestamp}.zip"

    return FileResponse(
        path=path,
        media_type="application/zip",
        filename=filename,
        headers={
            "X-Backup-Format-Version": manifest["format_version"],
            "X-Backup-Checksum": manifest["checksum"],
            "X-Backup-Record-Count": str(manifest["total_records"]),
            "X-Backup-File-Count": str(manifest["file_count"]),
        },
        background=BackgroundTask(cleanup_temp_file, path),
    )


@router.post(
    "/restore/",
    response_model=RestoreResponse,
    tags=["Backup"],
    dependencies=[Depends(RequirePermission("backup.admin"))],
)
async def restore_backup(
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    mode: str = Form("merge"),
) -> RestoreResponse:
    """Upload and restore from a backup ZIP.

    Args:
        file: ZIP backup file (multipart/form-data).
        mode: ``merge`` (default) adds records whose id does not already exist
            and deletes nothing, which is the safe way to bring a backup onto
            another machine or into an existing account. ``replace`` clears the
            caller's own data first and is only allowed into an empty account:
            clearing a populated one would cascade-delete project data the backup
            does not carry, so it returns 409 when the account already has data.

    A backup belongs to the user who created it (export is scoped to the user's
    own project graph). Restore is machine-portable: the exporter's ``users`` row
    is never re-created (that account already exists here, with its own id, email
    and password) and every imported row's ownership is forced to the restoring
    user, so a backup taken on one PC lands cleanly under the restoring account on
    another and can never be stamped with another account's id.
    """
    if mode not in ("replace", "merge"):
        raise HTTPException(status_code=400, detail="mode must be 'replace' or 'merge'")

    _MAX_BACKUP_BYTES = 500 * 1024 * 1024  # 500 MB
    raw = await file.read(_MAX_BACKUP_BYTES + 1)
    if len(raw) > _MAX_BACKUP_BYTES:
        raise HTTPException(status_code=413, detail="Backup file exceeds 500 MB limit")

    try:
        manifest, data = parse_backup_zip(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.database import async_session_factory

    # Storage keys of the files backing rows we actually import. File restore
    # runs post-commit and only writes blobs in this set, so an archive cannot
    # push files for keys its rows do not own.
    restored_file_keys: set[str] = set()

    # The whole restore runs inside ONE transaction: commit on full success,
    # or a single rollback on ANY failure so the DB is never left half-wiped.
    async with async_session_factory() as session:
        try:
            imported, skipped, warnings = await restore_backup_data(
                session,
                user_id=str(user_id),
                manifest=manifest,
                data=data,
                mode=mode,
                file_key_sink=restored_file_keys,
            )
            await session.commit()
        except RestoreError as exc:
            await session.rollback()
            if exc.stage == "guard":
                # A deliberate refusal, not a failure: e.g. replace into an
                # account that already holds data. 409 Conflict so the client can
                # show the reason and offer merge instead.
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            logger.exception("Backup restore failed %s %s: %s", exc.stage, exc.table, exc)
            verb = "clearing existing" if exc.stage == "clear" else "importing"
            raise HTTPException(
                status_code=500,
                detail=f"Restore failed while {verb} data; no changes were applied.",
            ) from exc
        except Exception as exc:
            await session.rollback()
            logger.exception("Backup restore failed: %s", exc)
            raise HTTPException(
                status_code=500,
                detail="Restore failed due to an internal error. Please check the backup file and try again.",
            ) from exc

    # Data committed. Now write any embedded files back to storage. This runs
    # outside the DB transaction and is best-effort: a file that fails to write
    # is a warning, not a reason to undo the (already committed) data restore.
    files_restored, file_warnings = await restore_backup_files(raw, allowed_keys=restored_file_keys)
    warnings.extend(file_warnings)

    total_imported = sum(imported.values())
    total_skipped = sum(skipped.values())

    if total_imported == 0 and total_skipped > 0:
        restore_status = "failed"
    elif total_skipped > 0 or warnings:
        restore_status = "partial"
    else:
        restore_status = "success"

    logger.info(
        "Backup restored: mode=%s status=%s imported=%d skipped=%d files=%d warnings=%d",
        mode,
        restore_status,
        total_imported,
        total_skipped,
        files_restored,
        len(warnings),
    )

    return RestoreResponse(
        status=restore_status,
        mode=mode,
        imported=imported,
        skipped=skipped,
        warnings=warnings,
        files_restored=files_restored,
    )


@router.post(
    "/validate/",
    response_model=ValidateResponse,
    tags=["Backup"],
    dependencies=[Depends(RequirePermission("backup.admin"))],
)
async def validate_backup(
    user_id: CurrentUserId,
    file: UploadFile = File(...),
) -> ValidateResponse:
    """Validate a backup ZIP without importing any data."""
    _MAX_BACKUP_BYTES = 500 * 1024 * 1024  # 500 MB
    raw = await file.read(_MAX_BACKUP_BYTES + 1)
    if len(raw) > _MAX_BACKUP_BYTES:
        raise HTTPException(status_code=413, detail="Backup file exceeds 500 MB limit")

    try:
        manifest, data = parse_backup_zip(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    warnings: list[str] = []

    backup_version = manifest.get("format_version", "unknown")
    if backup_version != BACKUP_FORMAT_VERSION:
        warnings.append(f"Format version mismatch: backup={backup_version}, current={BACKUP_FORMAT_VERSION}")

    known_keys = {key for key, _, _ in get_backup_tables()}
    for key in data:
        if key not in known_keys:
            warnings.append(f"Unknown data key in backup: '{key}' (will be ignored on restore)")
    for key in known_keys:
        if key not in data:
            warnings.append(f"Expected data key '{key}' not found in backup")

    record_counts: dict[str, int] = {}
    for key, records in data.items():
        if not isinstance(records, list):
            warnings.append(f"Data key '{key}' is not a list (type={type(records).__name__})")
            record_counts[key] = 0
        else:
            record_counts[key] = len(records)

    checksum = hashlib.sha256(raw).hexdigest()

    return ValidateResponse(
        valid=len(warnings) == 0 or all("not found" not in w.lower() for w in warnings),
        format_version=backup_version,
        created_at=manifest.get("created_at", "unknown"),
        record_counts=record_counts,
        warnings=warnings,
        checksum=checksum,
    )


# ── Re-exports for backward compatibility ─────────────────────────────────────
# Other modules and tests historically imported helpers from this router.
# Keep the public names available so import paths don't break.

__all__ = [
    "APP_ID",
    "BACKUP_FORMAT_VERSION",
    "deserialize_row",
    "parse_backup_zip",
    "router",
    "serialize_row",
]
