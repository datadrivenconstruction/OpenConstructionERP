# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ file imports run as background jobs (``POST /import/auto/?background=true``).

A large bill took longer than the editor waits for an answer, and the server
went on writing after the editor had given up, so the user's retry imported
the bill a second time. As a job the upload is answered at once with a job
id the editor polls, and the job is keyed by the bill, the file's hash and
the options. The same file posted again while its job is still pending or
running gets that job back silently: that is an automatic retry. Posted again
after it was imported, and while what it imported is still in the bill, it is
answered 409 ``import_already_done`` with the date, and imports again only
when the person asks for it (``force``).

The bytes wait in the app's upload directory (``<data dir>/uploads/
boq_imports``), and the job deletes them when it ends, whether it succeeded
or not; files a crash left behind are swept at startup. The job runs exactly
the code the synchronous route runs (``router._run_native_import``), so its
result is the response the route would have given.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale, set_locale
from app.core.job_run import JobRun
from app.core.job_runner import register_handler, submit_job, update_progress
from app.core.storage import module_uploads_dir

logger = logging.getLogger(__name__)

JOB_KIND = "boq.import.auto"

# What ``status`` of a job the reader polls says, by phase. The phase is the
# progress message; the editor words it.
_PHASE_PERCENT: dict[str, int] = {"reading": 5, "writing": 40, "validating": 85}

# A job still pending or running this long after it was created is taken for
# lost (the process that ran it in-process restarted) and a retry starts a
# new one. Generous: a regional bill of tens of thousands of rows is minutes.
_STALE_AFTER = timedelta(minutes=30)

_FINISHED_BADLY = frozenset({"failed", "cancelled"})

# The name an upload waits under; anything else in the directory is not ours.
_UPLOAD_NAME = re.compile(r"^[0-9a-f]{32}\.upload$")


class ImportRejectedError(Exception):
    """The file was refused, with the route's 400 ``detail``: a code, its values and an English fallback.

    ``str()`` is that detail as JSON, because the job runner keeps only an
    error's type and text; :func:`_job_view` reads the code back out of it.
    """

    def __init__(self, detail: Any) -> None:
        if not isinstance(detail, dict):
            detail = {"code": None, "params": {}, "message": str(detail)}
        self.detail: dict[str, Any] = detail
        super().__init__(json.dumps(detail, default=str))


def _upload_dir() -> Path:
    # Resolved per call, so the data directory the process runs with is honoured.
    return module_uploads_dir("boq_imports")


def _write_upload(content: bytes) -> str:
    directory = _upload_dir()
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.upload"
    (directory / name).write_bytes(content)
    return name


def _upload_path(name: str) -> Path:
    if not _UPLOAD_NAME.match(name):
        raise ValueError(f"Not an import upload: {name!r}")
    return _upload_dir() / name


def sweep_stale_uploads(*, older_than: timedelta = _STALE_AFTER) -> int:
    """Delete uploads that a crashed job left behind, and say how many.

    A job deletes its upload when it ends, so a file older than the time a
    job is given (``_STALE_AFTER``) belongs to a job that will never end.
    Runs at startup and never raises.
    """
    directory = _upload_dir()
    if not directory.is_dir():
        return 0
    cutoff = time.time() - older_than.total_seconds()
    removed = 0
    for path in directory.iterdir():
        try:
            if _UPLOAD_NAME.match(path.name) and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            logger.warning("Could not delete the stale import upload %s", path, exc_info=True)
    if removed:
        logger.info("Deleted %d import uploads left by jobs that never ended", removed)
    return removed


def _idempotency_base(boq_id: uuid.UUID, content: bytes, *, delete_missing: bool, column_mapping: str | None) -> str:
    """The key of an import's first attempt: the bill, the file, and every option that changes the outcome."""
    digest = hashlib.sha256(content).hexdigest()
    mapping = hashlib.sha256((column_mapping or "").encode("utf-8")).hexdigest()[:16]
    return f"boq_import:{boq_id}:{digest}:{int(delete_missing)}:{mapping}"


async def _still_there(session: AsyncSession, row: JobRun) -> bool:
    """Whether a succeeded import's first created row is still in its bill."""
    from app.modules.boq.models import Position

    first = (row.result_jsonb or {}).get("first_created_id")
    if not first:
        return False
    try:
        first_id = uuid.UUID(str(first))
    except ValueError:
        return False
    return (await session.execute(select(Position.id).where(Position.id == first_id))).first() is not None


def _is_stale(row: JobRun) -> bool:
    created = row.created_at
    if created is None:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return datetime.now(UTC) - created > _STALE_AFTER


async def _attempt(session: AsyncSession, base_key: str) -> tuple[str, JobRun | None, JobRun | None]:
    """The key for this upload, the job still running it, and the last import of it still in the bill.

    Same chaining as the onboarding provisioner: every attempt that no longer
    holds the file (failed, cancelled, lost or succeeded) passes the key on to
    the next one (``<key>:after:<id>``), so the chain stays deterministic and
    a double post starts one job, not two. A succeeded attempt whose rows are
    still in the bill is remembered on the way, so the caller can say the
    file was already imported.
    """
    key = base_key
    imported: JobRun | None = None
    for _ in range(100):
        row = (await session.execute(select(JobRun).where(JobRun.idempotency_key == key))).scalar_one_or_none()
        if row is None:
            return key, None, imported
        if row.status in ("pending", "started") and not _is_stale(row):
            return key, row, imported
        if row.status == "success" and await _still_there(session, row):
            imported = row
        key = f"{base_key}:after:{row.id}"
    return key, None, imported


def _already_imported(row: JobRun) -> HTTPException:
    when = row.completed_at or row.created_at
    if when is not None and when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    stamp = when.isoformat() if when is not None else None
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "import_already_done",
            "params": {"imported_at": stamp, "job_id": str(row.id)},
            "message": f"This file was already imported into this bill on {stamp}. Send it with force=true to import it again.",
        },
    )


def _job_view(row: JobRun, *, reused: bool | None = None) -> dict[str, Any]:
    """What the client reads about a job: state, progress, and the result or the reason it failed."""
    result = dict(row.result_jsonb or {})
    view: dict[str, Any] = {
        "job_id": str(row.id),
        "status": row.status,
        "progress_percent": 100 if row.status == "success" else int(row.progress_percent or 0),
        "phase": result.pop("progress_message", None),
    }
    if reused is not None:
        view["reused"] = reused
    if row.status == "success":
        result.pop("first_created_id", None)
        view["result"] = result
    elif row.status in _FINISHED_BADLY:
        error = row.error_jsonb or {}
        # Only a refusal is passed on, as the route's coded detail; anything
        # else is an internal failure the editor words itself.
        view["error"] = None
        if error.get("type") == ImportRejectedError.__name__:
            detail = _rejection_detail(str(error.get("message") or ""))
            view["error"] = detail.get("message")
            view["error_code"] = detail.get("code")
            view["error_params"] = detail.get("params") or {}
    return view


def _rejection_detail(text: str) -> dict[str, Any]:
    """The detail an :class:`ImportRejectedError` stored, or the bare text of an older one."""
    try:
        detail = json.loads(text)
    except ValueError:
        return {"message": text}
    return detail if isinstance(detail, dict) else {"message": text}


async def enqueue_boq_import(
    session: AsyncSession,
    *,
    boq_id: uuid.UUID,
    actor_id: uuid.UUID | str | None,
    content: bytes,
    file_name: str,
    format_id: str,
    delete_missing: bool,
    column_mapping: str | None,
    force: bool = False,
) -> dict[str, Any]:
    """Start the import of ``content`` into the bill, or hand back the job already importing it.

    The caller has checked access to the bill and that it is writable.

    Raises:
        HTTPException 409 ``import_already_done``: the file was imported into
            this bill before and what it imported is still there; ``force``
            imports it again.
    """
    base_key = _idempotency_base(boq_id, content, delete_missing=delete_missing, column_mapping=column_mapping)
    key, holder, imported = await _attempt(session, base_key)
    if holder is not None:
        return _job_view(holder, reused=True)
    if imported is not None and not force:
        raise _already_imported(imported)

    upload = await asyncio.to_thread(_write_upload, content)
    payload = {
        "boq_id": str(boq_id),
        "owner_user_id": str(actor_id) if actor_id is not None else None,
        "locale": get_locale(),
        "file_name": file_name,
        "format_id": format_id,
        "upload": upload,
        "delete_missing": delete_missing,
        "column_mapping": column_mapping,
    }
    try:
        row = await submit_job(JOB_KIND, payload, idempotency_key=key)
    except Exception:
        await _discard(upload)
        raise
    if (row.payload_jsonb or {}).get("upload") != upload:
        # A concurrent post of the same file won the key; its job has its own copy.
        await _discard(upload)
        return _job_view(row, reused=True)
    return _job_view(row, reused=False)


async def read_boq_import_job(session: AsyncSession, *, boq_id: uuid.UUID, job_id: uuid.UUID) -> dict[str, Any]:
    """The job's view, when ``job_id`` is an import job of this bill; 404 otherwise.

    The caller has checked access to the bill. A job of another bill, or of
    another kind, is not found through this bill.
    """
    row = await session.get(JobRun, job_id)
    if row is None or row.kind != JOB_KIND or (row.payload_jsonb or {}).get("boq_id") != str(boq_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import job not found")
    return _job_view(row)


async def _discard(upload: str) -> None:
    try:
        await asyncio.to_thread(_upload_path(upload).unlink, missing_ok=True)
    except Exception:  # noqa: BLE001 - a leftover upload is swept at the next start
        logger.warning("Could not delete the uploaded import %s", upload, exc_info=True)


async def _report_phase(job_run_id: uuid.UUID, phase: str) -> None:
    """Record the phase; progress is a courtesy and never fails the import."""
    try:
        await update_progress(job_run_id, percent=_PHASE_PERCENT.get(phase, 0), message=phase)
    except Exception:  # noqa: BLE001 - see docstring
        logger.debug("Could not record import phase %s for job %s", phase, job_run_id, exc_info=True)


async def run_boq_import_job(job_run: JobRun, payload: dict[str, Any]) -> dict[str, Any]:
    """The job handler: read the stored upload and run the same import the route runs."""
    from app.database import async_session_factory
    from app.modules.boq import router as boq_router
    from app.modules.boq.importers import REGISTERED_IMPORTERS
    from app.modules.boq.service import BOQService

    set_locale(str(payload.get("locale") or "en"))
    upload = str(payload["upload"])
    try:
        await _report_phase(job_run.id, "reading")
        content = await asyncio.to_thread(_upload_path(upload).read_bytes)
        chosen = next((imp for imp in REGISTERED_IMPORTERS if imp.format_id == payload.get("format_id")), None)
        if chosen is None:
            raise ImportRejectedError(
                {
                    "code": "import_parse_unexpected",
                    "params": {"format": payload.get("format_id")},
                    "message": f"No reader for format {payload.get('format_id')!r}",
                }
            )
        actor_raw = payload.get("owner_user_id")
        async with async_session_factory() as session:
            service = BOQService(session)
            try:
                result = await boq_router._run_native_import(
                    uuid.UUID(str(payload["boq_id"])),
                    chosen,
                    content,
                    file_name=str(payload.get("file_name") or "upload"),
                    overrides=boq_router._read_column_mapping(payload.get("column_mapping")),
                    delete_missing=bool(payload.get("delete_missing")),
                    actor_id=uuid.UUID(str(actor_raw)) if actor_raw else None,
                    service=service,
                    on_phase=lambda phase: _report_phase(job_run.id, phase),
                )
            except HTTPException as exc:
                await session.rollback()
                raise ImportRejectedError(exc.detail) from exc
            await session.commit()
            result["first_created_id"] = await _first_created_id(session, payload, result)
        return result
    finally:
        await _discard(upload)


async def _first_created_id(session: AsyncSession, payload: dict[str, Any], result: dict[str, Any]) -> str | None:
    """A row this import created, by which a retry tells the import is still in the bill."""
    from app.modules.boq.models import Position

    if not int(result.get("created") or 0):
        return None
    stmt = (
        select(Position.id)
        .where(
            Position.boq_id == uuid.UUID(str(payload["boq_id"])),
            Position.metadata_["import_source"].as_string() == str(payload.get("file_name") or "upload"),
        )
        .order_by(Position.sort_order.desc())
        .limit(1)
    )
    first = (await session.execute(stmt)).scalar()
    return str(first) if first is not None else None


def register_boq_import_job_handler() -> None:
    """Wire the import handler into the job runner."""
    register_handler(JOB_KIND, run_boq_import_job)


# Registered on import as well as from the module's startup hook, the way the
# validators are: a worker that imports this module to run a job has the handler.
register_boq_import_job_handler()
