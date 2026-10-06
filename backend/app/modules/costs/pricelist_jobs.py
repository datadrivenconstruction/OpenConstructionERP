# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regional price lists read and imported as background jobs, with progress.

A regional list runs to 44 000 voci and 125 MB. Read inside the request, the
preview alone outlasts the 120 s the proxy in front of the API waits, and the
browser is told the import failed while the server goes on writing it. So the
upload is stored once and answered at once with a job id, and the preview and
the import each run as a job the import screen polls:

    POST   /import/pricelist/uploads/                      -> {upload_id, job_id}  (the preview)
    POST   /import/pricelist/uploads/{upload_id}/preview/  -> {job_id}  (again, with corrections)
    POST   /import/pricelist/uploads/{upload_id}/import/   -> {job_id}
    GET    /import/pricelist/jobs/{job_id}                 -> state, progress, result or refusal
    DELETE /import/pricelist/uploads/{upload_id}/

The bytes go to the platform's storage backend under the uploader's id, so a
worker process can read them and nobody else can name them. A refusal the user
can act on (a taken catalogue name, an unknown region) ends the job with a
code the screen translates, the same codes the synchronous endpoints answer.
An upload is deleted once its import succeeds, when the user cancels, or a day
after it was made.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC
from pathlib import Path
from typing import IO, Any

from sqlalchemy import select

from app.core.job_run import JobRun
from app.core.job_runner import register_handler, submit_job
from app.core.storage import get_storage_backend
from app.modules.costs.pricelist_import import PriceListRefused, import_list, preview, with_free_suggestion
from app.modules.costs.pricelists.containers import MAX_UPLOAD_BYTES, ContainerRefused
from app.modules.costs.pricelists.service import plan_upload

logger = logging.getLogger(__name__)

PREVIEW_KIND = "costs.pricelist_preview"
IMPORT_KIND = "costs.pricelist_import"
KINDS = frozenset({PREVIEW_KIND, IMPORT_KIND})

UPLOAD_PREFIX = "pricelist-uploads/"
UPLOAD_ID_RE = re.compile(r"^\d{10}-[0-9a-f]{16}$")
# An upload nobody imported is removed this long after it was made.
UPLOAD_TTL_SECONDS = 24 * 3600
# How often a running job writes its progress.
PROGRESS_EVERY_SECONDS = 1.0
# A job still pending or running this long after it was created is taken for
# lost (the process that ran it restarted), and asking again starts a new one.
STALE_AFTER_SECONDS = 30 * 60

_COPY_CHUNK = 1024 * 1024


# ── Uploads ──────────────────────────────────────────────────────────────


def _safe_name(filename: str) -> str:
    """The upload's file name, kept for its extension, reduced to characters every backend accepts."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename or "upload").name).strip("._") or "upload"
    return name[-100:]


def _owner_prefix(owner_id: str) -> str:
    return f"{UPLOAD_PREFIX}{uuid.UUID(owner_id).hex}/"


def _spool_to_disk(stream: IO[bytes]) -> Path:
    """Copy the request's spooled upload into a named temporary file, refusing what is too large."""
    stream.seek(0)
    handle = tempfile.NamedTemporaryFile(prefix="oe-pricelist-", suffix=".upload", delete=False)  # noqa: SIM115
    size = 0
    try:
        with handle:
            while chunk := stream.read(_COPY_CHUNK):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise PriceListRefused("file_too_large", limit_mb=MAX_UPLOAD_BYTES // (1024 * 1024))
                handle.write(chunk)
        if size == 0:
            raise PriceListRefused("empty_file")
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return Path(handle.name)


async def store_upload(stream: IO[bytes], filename: str, owner_id: str) -> tuple[str, str]:
    """Store an upload under its owner; return its id and the file name the readers see."""
    path = await asyncio.to_thread(_spool_to_disk, stream)
    upload_id = f"{int(time.time()):010d}-{uuid.uuid4().hex[:16]}"
    name = _safe_name(filename)
    try:
        # The local backend moves the file into place; a remote one copies it.
        await get_storage_backend().put_stream(f"{_owner_prefix(owner_id)}{upload_id}/{name}", path)
    finally:
        path.unlink(missing_ok=True)
    await sweep_stale_uploads()
    return upload_id, name


async def find_upload(upload_id: str, owner_id: str) -> str:
    """The storage key of the owner's upload, or a refusal when there is none."""
    if not UPLOAD_ID_RE.fullmatch(upload_id or ""):
        raise PriceListRefused("upload_not_found", 404)
    listed = await get_storage_backend().list_prefix(f"{_owner_prefix(owner_id)}{upload_id}/")
    if not listed:
        raise PriceListRefused("upload_not_found", 404)
    return listed[0][0]


async def delete_upload(upload_id: str, owner_id: str) -> int:
    """Remove the owner's upload; return how many files went."""
    if not UPLOAD_ID_RE.fullmatch(upload_id or ""):
        return 0
    return await get_storage_backend().delete_prefix(f"{_owner_prefix(owner_id)}{upload_id}/")


async def sweep_stale_uploads(now: float | None = None) -> int:
    """Remove uploads older than a day, whoever made them. Best effort."""
    cutoff = (now if now is not None else time.time()) - UPLOAD_TTL_SECONDS
    storage = get_storage_backend()
    removed = 0
    try:
        listed = await storage.list_prefix(UPLOAD_PREFIX)
    except Exception:  # noqa: BLE001 - housekeeping never fails an upload
        logger.debug("Could not list price-list uploads", exc_info=True)
        return 0
    for key, _size in listed:
        parts = key[len(UPLOAD_PREFIX) :].split("/")
        if len(parts) < 3 or not UPLOAD_ID_RE.fullmatch(parts[1]):
            continue
        if int(parts[1].split("-", 1)[0]) >= cutoff:
            continue
        try:
            await storage.delete(key)
            removed += 1
        except Exception:  # noqa: BLE001 - see docstring
            logger.debug("Could not delete stale price-list upload %s", key, exc_info=True)
    return removed


@contextlib.asynccontextmanager
async def _opened(storage_key: str) -> AsyncIterator[IO[bytes]]:
    """The stored upload as a seekable binary file, read from disk and never whole into memory."""
    storage = get_storage_backend()
    local = storage.local_path(storage_key)
    if local is not None:
        if not local.exists():
            raise PriceListRefused("upload_not_found", 404)
        with local.open("rb") as handle:
            yield handle
        return
    # A remote backend: stream it into a temporary file first.
    with tempfile.TemporaryFile(prefix="oe-pricelist-") as handle:
        try:
            async for chunk in storage.open_stream(storage_key):
                await asyncio.to_thread(handle.write, chunk)
        except FileNotFoundError as exc:
            raise PriceListRefused("upload_not_found", 404) from exc
        handle.seek(0)
        yield handle


# ── Progress ─────────────────────────────────────────────────────────────


class _Progress:
    """What a running job reports: its stage, rows read, voci written, and a percent when one is known."""

    def __init__(self, job_id: uuid.UUID, stage: str, expected_rows: int | None = None) -> None:
        self.job_id = job_id
        self.stage = stage
        self.expected_rows = expected_rows if expected_rows and expected_rows > 0 else None
        self.rows_read = 0
        self.imported = 0

    def tick(self) -> None:
        """One row read (called from the reading thread; an int add is atomic enough for a counter)."""
        self.rows_read += 1

    def percent(self) -> int:
        if self.expected_rows is None:
            return 0
        # Never 100 before the job has finished: the commit is still ahead.
        return min(99, int(self.rows_read * 100 / self.expected_rows))

    async def report(self) -> None:
        """Write the progress to the job row; a courtesy that never fails the job."""
        from app.database import async_session_factory

        try:
            async with async_session_factory() as session:
                row = await session.get(JobRun, self.job_id)
                if row is None:
                    return
                percent = self.percent()
                if percent > (row.progress_percent or 0):
                    row.progress_percent = percent
                state = dict(row.result_jsonb or {})
                state.update({"progress_message": self.stage, "rows_read": self.rows_read, "imported": self.imported})
                row.result_jsonb = state
                await session.commit()
        except Exception:  # noqa: BLE001 - see docstring
            logger.debug("Could not record price-list job progress for %s", self.job_id, exc_info=True)


# ── Handlers ─────────────────────────────────────────────────────────────


def _refusal(exc: PriceListRefused) -> dict[str, Any]:
    return {"refused": exc.as_dict()}


async def run_preview_job(job_run: JobRun, payload: dict[str, Any]) -> dict[str, Any]:
    """Read the stored upload and report it, writing how many rows it has read as it goes."""
    progress = _Progress(job_run.id, "reading")
    try:
        async with _opened(str(payload["storage_key"])) as stream:
            plan = await asyncio.to_thread(plan_upload, stream, str(payload.get("file_name") or "upload"))
            work = asyncio.ensure_future(
                asyncio.to_thread(preview, plan, payload.get("region_code"), payload.get("edition"), progress.tick)
            )
            while not work.done():
                await asyncio.wait({work}, timeout=PROGRESS_EVERY_SECONDS)
                await progress.report()
            report = work.result()
    except ContainerRefused as exc:
        return _refusal(PriceListRefused(exc.code, **exc.params))
    except PriceListRefused as exc:
        return _refusal(exc)
    from app.database import async_session_factory

    async with async_session_factory() as session:
        report = await with_free_suggestion(session, report)
    return {"preview": report, "rows_read": progress.rows_read}


async def run_import_job(job_run: JobRun, payload: dict[str, Any]) -> dict[str, Any]:
    """Create the catalogue and write the voci, reporting rows read and voci written after each slice."""
    from app.database import async_session_factory

    progress = _Progress(job_run.id, "writing", payload.get("expected_rows"))
    owner = payload.get("owner_user_id")

    async def on_progress(rows_read: int, imported: int) -> None:
        progress.rows_read = rows_read
        progress.imported = imported
        await progress.report()

    storage_key = str(payload["storage_key"])
    try:
        async with _opened(storage_key) as stream:
            plan = await asyncio.to_thread(plan_upload, stream, str(payload.get("file_name") or "upload"))
            async with async_session_factory() as session:
                result = await import_list(
                    session,
                    plan,
                    catalog_name=str(payload.get("catalog_name") or ""),
                    region_code=payload.get("region_code"),
                    edition=payload.get("edition"),
                    owner_id=uuid.UUID(owner) if owner else None,
                    on_progress=on_progress,
                )
    except ContainerRefused as exc:
        return _refusal(PriceListRefused(exc.code, **exc.params))
    except PriceListRefused as exc:
        # The upload stays: the user can correct the name or region and import again.
        return _refusal(exc)
    with contextlib.suppress(Exception):
        await get_storage_backend().delete(storage_key)
    return {"result": result, "rows_read": result.get("rows", 0), "imported": result.get("imported", 0)}


def register_pricelist_job_handlers() -> None:
    """Wire both handlers into the job runner."""
    register_handler(PREVIEW_KIND, run_preview_job)
    register_handler(IMPORT_KIND, run_import_job)


# Registered on import: ``costs/router.py`` imports the price-list router, which
# imports this module, so the API process and any worker that loads the app have it.
register_pricelist_job_handlers()


# ── Submitting and reading ───────────────────────────────────────────────


def _is_stale(row: JobRun) -> bool:
    created = row.created_at
    if created is None:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return time.time() - created.timestamp() > STALE_AFTER_SECONDS


async def _free_key(base_key: str, *, success_answers: bool) -> tuple[str, JobRun | None]:
    """The key for this request and the job already answering it, if one still does.

    A running job answers a repeat of the same request (a double click), and
    so does an import that succeeded (``success_answers``). A finished preview
    does not: what it suggested, such as a free catalogue name, may have
    changed since. A failed, refused or lost job passes the key on
    (``<key>:after:<id>``), so asking again after a refusal starts a new job.
    """
    from app.database import async_session_factory

    key = base_key
    async with async_session_factory() as session:
        for _ in range(100):
            row = (await session.execute(select(JobRun).where(JobRun.idempotency_key == key))).scalar_one_or_none()
            if row is None:
                return key, None
            refused = bool((row.result_jsonb or {}).get("refused"))
            if row.status in ("pending", "started") and not _is_stale(row):
                return key, row
            if success_answers and row.status == "success" and not refused:
                return key, row
            key = f"{base_key}:after:{row.id}"
    return key, None


async def submit_preview(
    *, upload_id: str, storage_key: str, file_name: str, owner_id: str, region_code: str | None, edition: str | None
) -> JobRun:
    """Start a preview of the stored upload with the user's corrections."""
    key, holder = await _free_key(
        f"pricelist_preview:{upload_id}:{region_code or ''}:{edition or ''}", success_answers=False
    )
    if holder is not None:
        return holder
    return await submit_job(
        PREVIEW_KIND,
        {
            "upload_id": upload_id,
            "storage_key": storage_key,
            "file_name": file_name,
            "owner_user_id": owner_id,
            "region_code": region_code,
            "edition": edition,
        },
        idempotency_key=key,
    )


async def submit_import(
    *,
    upload_id: str,
    storage_key: str,
    owner_id: str,
    catalog_name: str,
    region_code: str | None,
    edition: str | None,
    expected_rows: int | None,
) -> JobRun:
    """Start the import of the stored upload into a new catalogue."""
    key, holder = await _free_key(
        f"pricelist_import:{upload_id}:{catalog_name.strip().casefold()}", success_answers=True
    )
    if holder is not None:
        return holder
    return await submit_job(
        IMPORT_KIND,
        {
            "upload_id": upload_id,
            "storage_key": storage_key,
            "file_name": storage_key.rsplit("/", 1)[-1],
            "owner_user_id": owner_id,
            "catalog_name": catalog_name,
            "region_code": region_code,
            "edition": edition,
            "expected_rows": expected_rows,
        },
        idempotency_key=key,
    )


async def read_job(job_id: uuid.UUID, owner_id: str) -> dict[str, Any] | None:
    """What the import screen reads about one of the owner's jobs; None for anyone else's."""
    from app.database import async_session_factory

    async with async_session_factory() as session:
        row = await session.get(JobRun, job_id)
        if row is None or row.kind not in KINDS or (row.payload_jsonb or {}).get("owner_user_id") != owner_id:
            return None
        return job_view(row)


def job_view(row: JobRun) -> dict[str, Any]:
    """State, progress, and the preview, the import result, or the reason it stopped."""
    state = dict(row.result_jsonb or {})
    refused = state.get("refused")
    status = row.status
    if status == "success" and refused:
        status = "failed"
    view: dict[str, Any] = {
        "job_id": str(row.id),
        "kind": "preview" if row.kind == PREVIEW_KIND else "import",
        "upload_id": (row.payload_jsonb or {}).get("upload_id"),
        "status": status,
        "progress_percent": 100 if status == "success" else int(row.progress_percent or 0),
        "stage": state.get("progress_message"),
        "rows_read": int(state.get("rows_read") or 0),
        "imported": int(state.get("imported") or 0),
    }
    if status == "success":
        view["result"] = state.get("preview") if row.kind == PREVIEW_KIND else state.get("result")
    elif status in ("failed", "cancelled"):
        # A refusal is passed on with its code; anything else is an internal
        # failure the screen words itself, without the traceback.
        view["error"] = refused or {"code": "import_failed", "message": "", "params": {}}
    return view


__all__ = [
    "IMPORT_KIND",
    "KINDS",
    "PREVIEW_KIND",
    "UPLOAD_PREFIX",
    "delete_upload",
    "find_upload",
    "job_view",
    "read_job",
    "register_pricelist_job_handlers",
    "run_import_job",
    "run_preview_job",
    "store_upload",
    "submit_import",
    "submit_preview",
    "sweep_stale_uploads",
]
