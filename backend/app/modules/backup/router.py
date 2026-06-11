"""‌⁠‍Backup & Restore API.

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

import hashlib
import logging
import uuid

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.dependencies import CurrentUserId, RequirePermission
from app.modules.backup.schemas import ExportRequest, RestoreResponse, ValidateResponse
from app.modules.backup.service import (
    APP_ID,
    BACKUP_FORMAT_VERSION,
    build_backup,
    build_scope_clause,
    cleanup_temp_file,
    deserialize_row,
    get_backup_tables,
    parse_backup_zip,
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
    path = spool_to_disk(spool)

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
    mode: str = Form("replace"),
) -> RestoreResponse:
    """Upload and restore from a backup ZIP.

    Args:
        file: ZIP backup file (multipart/form-data).
        mode: ``replace`` (default) deletes the requesting user's own data
            first, then inserts. ``merge`` skips records whose UUID already
            exists, inserts new ones.

    A backup belongs to the user who created it (export is scoped to the
    user's own project graph), so ``replace`` only ever clears that same
    scope. It never touches another user's rows - the earlier behaviour
    deleted every row of every table globally, which let one user wipe the
    whole instance on restore.
    """
    if mode not in ("replace", "merge"):
        raise HTTPException(status_code=400, detail="mode must be 'replace' or 'merge'")

    raw = await file.read()

    try:
        manifest, data = parse_backup_zip(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    tables = get_backup_tables()
    by_key = {key: cls for key, _table_name, cls in tables}

    imported: dict[str, int] = {}
    skipped: dict[str, int] = {}
    warnings: list[str] = []

    from sqlalchemy import delete, select

    from app.database import async_session_factory

    # The whole restore runs inside ONE transaction. Either every table is
    # cleared (replace mode) and re-imported successfully and we commit, or
    # ANY failure aborts the entire operation with a single rollback so the
    # DB is never left half-wiped. We deliberately do NOT swallow a clear or
    # flush error and continue: persisting a partial delete plus a partial
    # import would corrupt the user's data far worse than a clean abort.
    async with async_session_factory() as session:
        try:
            if mode == "replace":
                # FK-safe ordering: delete children before parents (reverse
                # of the import order). A failure to clear any table aborts
                # the whole restore - a half-wiped DB must never be committed.
                # Each delete is scoped to the requesting user's own rows via
                # the SAME ownership graph the export used, so restore can
                # never delete another user's data. Tables with no known
                # ownership path (scope clause None) are left untouched.
                for backup_key, _table_name, model_cls in reversed(tables):
                    scope = build_scope_clause(by_key, backup_key, str(user_id))
                    if scope is None:
                        continue
                    try:
                        await session.execute(delete(model_cls).where(scope))
                    except Exception as exc:
                        await session.rollback()
                        logger.exception("Backup restore failed clearing %s: %s", backup_key, exc)
                        raise HTTPException(
                            status_code=500,
                            detail=("Restore failed while clearing existing data; no changes were applied."),
                        ) from exc

            for backup_key, _table_name, model_cls in tables:
                records = data.get(backup_key, [])
                if not records:
                    imported[backup_key] = 0
                    skipped[backup_key] = 0
                    continue

                count_imported = 0
                count_skipped = 0

                for record in records:
                    if mode == "merge":
                        record_id = record.get("id")
                        if record_id:
                            # Resolve the PK value first. If a string id is not
                            # a valid UUID for a UUID-keyed table we cannot run
                            # the duplicate check, so we must NOT silently fall
                            # through and insert it as a new row - that would
                            # break merge semantics by importing a duplicate.
                            # Treat an un-checkable record as skipped instead.
                            try:
                                lookup_id = uuid.UUID(record_id) if isinstance(record_id, str) else record_id
                            except (ValueError, TypeError):
                                count_skipped += 1
                                logger.debug(
                                    "Skipping un-checkable record id in %s (merge mode): %r",
                                    backup_key,
                                    record_id,
                                )
                                continue

                            existing = (
                                await session.execute(select(model_cls).where(model_cls.id == lookup_id))
                            ).scalar_one_or_none()
                            if existing is not None:
                                count_skipped += 1
                                continue

                    try:
                        obj = deserialize_row(model_cls, record)
                        session.add(obj)
                        count_imported += 1
                    except Exception as exc:
                        count_skipped += 1
                        logger.warning("Skipped record in %s: %s", backup_key, str(exc)[:100])

                imported[backup_key] = count_imported
                skipped[backup_key] = count_skipped

                # Flush per table so we get FK-ordered inserts, but a flush
                # failure is fatal: abort the whole restore rather than
                # rolling back this table and committing the rest, which
                # would leave the DB half-wiped (replace mode already
                # deleted everything above).
                try:
                    await session.flush()
                except Exception as exc:
                    await session.rollback()
                    logger.exception("Backup restore failed flushing %s: %s", backup_key, exc)
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            "Restore failed while importing data; no changes "
                            "were applied. Please check the backup file and try again."
                        ),
                    ) from exc

            await session.commit()
        except HTTPException:
            # Already rolled back at the failure site with a clean 500.
            raise
        except Exception as exc:
            await session.rollback()
            logger.exception("Backup restore failed: %s", exc)
            raise HTTPException(
                status_code=500,
                detail="Restore failed due to an internal error. Please check the backup file and try again.",
            ) from exc

    total_imported = sum(imported.values())
    total_skipped = sum(skipped.values())

    if total_imported == 0 and total_skipped > 0:
        restore_status = "failed"
    elif total_skipped > 0 or warnings:
        restore_status = "partial"
    else:
        restore_status = "success"

    logger.info(
        "Backup restored: mode=%s status=%s imported=%d skipped=%d warnings=%d",
        mode,
        restore_status,
        total_imported,
        total_skipped,
        len(warnings),
    )

    return RestoreResponse(
        status=restore_status,
        mode=mode,
        imported=imported,
        skipped=skipped,
        warnings=warnings,
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
    raw = await file.read()

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
