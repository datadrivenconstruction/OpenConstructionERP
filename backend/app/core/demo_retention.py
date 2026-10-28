# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Retention policy for visitor uploads on the public hosted demo.

Off by default, and off by construction rather than by configuration
discipline. Nothing in this module deletes anything unless BOTH of these are
true at the moment the sweep runs:

1. ``OE_DEMO_READ_ONLY`` is on (``demo_read_only`` on
   :class:`app.config.Settings`) - the same flag that already declares "this
   deployment is the public demo" for :mod:`app.core.demo_read_only`. There is
   one idea here, not two: a self-hosted install never sets it, so a
   self-hosted install can never take any branch below.
2. ``OE_DEMO_UPLOADS_RETENTION_DAYS`` is a positive integer. Zero, the
   default, means "keep everything forever", which is what every install that
   is not the hosted demo does today and keeps doing.

A fat-fingered retention window on a self-hosted box therefore deletes
nothing, because that box is not a read-only demo. That is the whole point of
the conjunction: the destructive half of the switch is inert without the half
that says which deployment this is.

Why a demo needs this at all
----------------------------
The hosted demo is a public sandbox. Its data directory grows with every
visitor who drops a model, a drawing or a takeoff PDF into it, and until now
nothing ever removed any of it. The seeded example projects are the product;
a stranger's 223 MB IFC from three weeks ago is not, and it has no claim on
the disk that the nightly database dump needs.

What is protected, structurally
-------------------------------
*Seeded rows.* Every seeder in the platform stamps its rows with a truthy
``seed`` (and usually ``demo``) key in the row's own JSON metadata column -
see ``app/modules/*/seed.py``, e.g. ``metadata_={"seed": True, "demo": True}``
in ``app.modules.bim_hub.seed``. :func:`is_seeded_row` reads that marker off
the row itself, so the rule is a property of the record and not of its
filename, its directory, its age or the project it hangs off. A visitor who
uploads into a demo project is still a visitor; a seeded file that a visitor
renamed is still seeded.

*Rows that cannot answer the question.* A row whose metadata column is
missing or is not a JSON object cannot prove it is a visitor upload, and
"unknown" is resolved as keep, never as delete. A source whose model has no
metadata column of its own is not in :data:`UPLOAD_SOURCES` at all.

*Blobs somebody else still points at.* Blobs are shared across tables here:
opening a Project-Files PDF in takeoff references the same bytes rather than
copying them (see ``preserve_blobs_for_deleted_source`` in
``app.modules.takeoff.service``), and a soft-deleted file keeps its blob alive
through ``oe_file_trash.payload_json`` while its own row is already gone. So a
blob is only unlinked once no live row anywhere in the registry - and no trash
snapshot - still names that exact path.

The order, and what a half-finished run leaves behind
-----------------------------------------------------
Per candidate: delete the row, commit, then delete the blob. Never the other
way round. The two possible residues after a kill -9 are not symmetric:

* row first - the process dies owning a blob nothing references. Invisible,
  costs disk, and is recoverable by hand (or, for BIM, by the existing
  ``POST /api/v1/bim_hub/cleanup-orphans/``).
* blob first - the process dies owning a row that points at bytes which are
  gone. The demo shows a file that 404s on download, and no sweep can put the
  bytes back.

Only the first one is recoverable, which is why the platform's own deletes
already choose it - ``app.modules.bim_hub.service`` line 1259 puts blob
cleanup "after DB delete so we never strand files belonging to a still-live
DB row", and ``app.modules.documents.service.delete_document`` says the same.
Committing per candidate rather than per batch bounds that residue to a
single blob no matter when the process dies.

Safe to run twice: the second run finds no candidate rows, because the rows
it would have selected are gone. Safe to interrupt: see above. Safe to run as
a dry run: :func:`sweep_demo_uploads` with ``dry_run=True`` performs every
query and every size probe and issues no DELETE and no unlink.

It says what it did
-------------------
Every run - dry runs, and runs that deleted nothing - writes
``demo_retention_last_run.json`` into the data directory, atomically, and logs
one machine-readable INFO line. A stale timestamp in that file is itself the
signal that the job stopped running, which is the failure this whole module
exists downstream of: the component that first noticed the disk filling up
wrote a line into a log nobody read.

Three flags in that artifact carry the states a watchdog has to tell apart.
``armed`` false with a ``skipped_reason`` means nothing was asked of this
deployment, which is the healthy answer on a self-hosted install. ``failed``
true with a ``failure`` means the run was wanted and did not happen, and needs
a person - the CLI exits 1 for that and 2 for the first. ``capped`` true means
the run stopped at :data:`MAX_ROWS_PER_SOURCE` with backlog still behind it,
so a large ``rows_deleted`` is not the same as a finished source.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "MAX_ROWS_PER_SOURCE",
    "REPORT_FILENAME",
    "SEED_MARKER_KEYS",
    "UPLOAD_SOURCES",
    "BlobRef",
    "RetentionReport",
    "SourceOutcome",
    "UploadSource",
    "demo_retention_enabled",
    "is_seeded_row",
    "register_jobs",
    "report_path",
    "retention_window_days",
    "run_sweep_once",
    "sweep_demo_uploads",
]


#: Recommended window, and the one the CLI defaults to. Defended rather than
#: rounded: the demo takes on roughly 33 MB of visitor uploads a day, so an
#: N-day window bounds the visitor half of the data directory at about 33·N MB.
#: Fourteen days keeps every file a visitor could plausibly come back for -
#: a weekend, a week off, a colleague they sent the link to - and holds the
#: visitor backlog under 500 MB, about one percent of the 48 GB volume. Seven
#: would be tighter than a holiday; thirty is 1 GB of strangers' files with
#: nobody left who remembers uploading them.
DEFAULT_RETENTION_DAYS = 14

#: Ceiling on candidates per source per run. A nightly job that has to clear a
#: 2.2 GB backlog converges over a few runs instead of doing one enormous
#: irreversible pass, and the report stays readable. Not a correctness bound.
MAX_ROWS_PER_SOURCE = 1000

#: Written into the data directory after every run, dry or not.
REPORT_FILENAME = "demo_retention_last_run.json"

#: Metadata keys the seeders stamp. A truthy value under any of them means the
#: row was authored by a seeder and is part of the demo, not part of a visit.
#: ``seed`` is sometimes ``True`` and sometimes a marker string (``_SEED_MARK``
#: in ``app.modules.cvr.seed``, ``_SHOWCASE_MARKER`` in
#: ``app.modules.daily_diary.seed``); truthiness covers both.
SEED_MARKER_KEYS: tuple[str, ...] = ("seed", "demo")


# ── What the policy considers a blob ────────────────────────────────────────


@dataclass(frozen=True)
class BlobRef:
    """One blob a candidate row owns.

    ``path`` is an absolute filesystem path written by an upload handler.
    ``prefix`` is a storage-backend key prefix (``bim/{project}/{model}/``),
    deleted through the configured backend so an S3 deployment behaves the
    same as a local one. A prefix carries the row's own id, so unlike a path
    it cannot be shared with another row and needs no reference check.
    """

    kind: Literal["path", "prefix"]
    locator: str


# ── The registry ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UploadSource:
    """One table that holds visitor uploads.

    Membership has a hard requirement: the model must carry its own JSON
    metadata column, because that is the only structural way a row can prove
    it is seeded. A model that inherits the answer from a parent, or has no
    metadata at all, is left out rather than guessed at - see
    :data:`EXCLUDED_SOURCES`.
    """

    #: Label from the platform's file-kind vocabulary
    #: (``app.modules.file_versions.models.FILE_KINDS``).
    kind: str
    #: Lazy import, so this module stays loadable when a module is not
    #: installed and so importing it costs nothing at startup.
    load_model: Callable[[], type[Any]]
    #: Attributes holding absolute filesystem paths. Also the columns the
    #: cross-table reference check searches.
    path_attrs: tuple[str, ...] = ()
    #: Storage-backend prefix owned exclusively by this row, if any.
    prefix_for: Callable[[Any], str] | None = None


def _document_model() -> type[Any]:
    from app.modules.documents.models import Document

    return Document


def _photo_model() -> type[Any]:
    from app.modules.documents.models import ProjectPhoto

    return ProjectPhoto


def _takeoff_document_model() -> type[Any]:
    from app.modules.takeoff.models import TakeoffDocument

    return TakeoffDocument


def _bim_model() -> type[Any]:
    from app.modules.bim_hub.models import BIMModel

    return BIMModel


def _bim_prefix(row: Any) -> str:
    from app.modules.bim_hub.file_storage import bim_model_prefix

    return bim_model_prefix(row.project_id, row.id)


#: The sources the policy sweeps, biggest first. Together they are the
#: dominant mass of the data directory: BIM/CAD uploads are 2.2 GB of 3.1 GB,
#: and takeoff PDFs are where the largest single arrivals land.
UPLOAD_SOURCES: tuple[UploadSource, ...] = (
    UploadSource(kind="bim_model", load_model=_bim_model, prefix_for=_bim_prefix),
    UploadSource(kind="takeoff", load_model=_takeoff_document_model, path_attrs=("file_path",)),
    UploadSource(kind="document", load_model=_document_model, path_attrs=("file_path",)),
    UploadSource(kind="photo", load_model=_photo_model, path_attrs=("file_path", "thumbnail_path")),
)

#: Deliberately absent, with the reason. Documented here so the boundary is a
#: decision somebody can revisit rather than an oversight.
EXCLUDED_SOURCES: dict[str, str] = {
    "dwg_drawing": (
        "Its blobs span three directories - the upload, a sidecar spreadsheet, "
        "per-version entities files and a thumbnail - resolved by private helpers "
        "in app.modules.dwg_takeoff.service. Covering it correctly means that "
        "module exporting its own blob set, which is a change to that module "
        "rather than to this policy."
    ),
    "field_diary_attachment": (
        "oe_field_diary_attachment has no metadata column, so a row cannot say "
        "whether it was seeded. Unknown resolves to keep."
    ),
    "report": (
        "Generated reports are derived artifacts rather than visitor uploads, and "
        "they are cheap to regenerate. Not a growth vector worth the risk."
    ),
}


# ── Arming ──────────────────────────────────────────────────────────────────


def demo_retention_enabled() -> bool:
    """Whether this deployment may delete visitor uploads.

    Read per call and never cached here, matching
    :func:`app.core.demo_read_only.demo_read_only_enabled`. The settings object
    is itself an ``lru_cache`` singleton, so a test that flips the environment
    clears that cache; caching the answer in this module as well would make it
    impossible to exercise both states in one process, which is exactly how a
    guard quietly becomes on-by-default without the suite noticing.
    """
    from app.config import get_settings

    settings = get_settings()
    return bool(settings.demo_read_only) and retention_window_days() > 0


def retention_window_days() -> int:
    """Configured window in days. ``0`` (the default) means retention is off."""
    from app.config import get_settings

    try:
        return max(0, int(getattr(get_settings(), "demo_uploads_retention_days", 0) or 0))
    except (TypeError, ValueError):
        return 0


def is_seeded_row(row: Any) -> bool | None:
    """Whether ``row`` was written by a seeder.

    ``True`` seeded, ``False`` a visitor upload, ``None`` when the row cannot
    answer - no metadata column, or a metadata value that is not a JSON
    object. The caller must treat ``None`` as keep: a record that cannot prove
    it is disposable is not disposable.
    """
    meta = getattr(row, "metadata_", None)
    if not isinstance(meta, dict):
        return None
    return any(bool(meta.get(key)) for key in SEED_MARKER_KEYS)


# ── The report ──────────────────────────────────────────────────────────────


@dataclass
class SourceOutcome:
    """What the sweep did to one source."""

    kind: str
    #: True when this source hit ``max_rows_per_source`` and there is more
    #: backlog waiting for the next run. Without it an operator reading
    #: ``rows_deleted: 1000`` cannot tell a finished source from a capped one.
    capped: bool = False
    rows_examined: int = 0
    rows_kept_seeded: int = 0
    rows_kept_unmarked: int = 0
    rows_deleted: int = 0
    blobs_deleted: int = 0
    blobs_missing: int = 0
    blobs_kept_referenced: int = 0
    blobs_kept_outside_data_dir: int = 0
    bytes_freed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "capped": self.capped,
            "rows_examined": self.rows_examined,
            "rows_kept_seeded": self.rows_kept_seeded,
            "rows_kept_unmarked": self.rows_kept_unmarked,
            "rows_deleted": self.rows_deleted,
            "blobs_deleted": self.blobs_deleted,
            "blobs_missing": self.blobs_missing,
            "blobs_kept_referenced": self.blobs_kept_referenced,
            "blobs_kept_outside_data_dir": self.blobs_kept_outside_data_dir,
            "bytes_freed": self.bytes_freed,
            "errors": list(self.errors),
        }


@dataclass
class RetentionReport:
    """What one run of the policy did, in a form a watchdog can act on."""

    started_at: datetime
    dry_run: bool
    window_days: int
    armed: bool
    finished_at: datetime | None = None
    cutoff: datetime | None = None
    #: Set when the sweep declined to run: not a demo, or no window configured.
    #: A skipped run is a success - there was nothing this deployment wanted done.
    skipped_reason: str | None = None
    #: Set when the sweep started and then blew up. This is deliberately a
    #: different field from ``skipped_reason``: a watchdog that cannot tell
    #: "this is not a demo" from "the sweep crashed" is the failure the report
    #: exists to prevent, and both would otherwise surface as ``armed: false``.
    failure: str | None = None
    sources: list[SourceOutcome] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.failure is not None

    @property
    def capped(self) -> bool:
        """True when any source left backlog behind for the next run."""
        return any(s.capped for s in self.sources)

    @property
    def rows_deleted(self) -> int:
        return sum(s.rows_deleted for s in self.sources)

    @property
    def blobs_deleted(self) -> int:
        return sum(s.blobs_deleted for s in self.sources)

    @property
    def bytes_freed(self) -> int:
        return sum(s.bytes_freed for s in self.sources)

    @property
    def errors(self) -> list[str]:
        return [err for s in self.sources for err in s.errors]

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "dry_run": self.dry_run,
            "armed": self.armed,
            "failed": self.failed,
            "failure": self.failure,
            "skipped_reason": self.skipped_reason,
            "capped": self.capped,
            "window_days": self.window_days,
            "cutoff": self.cutoff.isoformat() if self.cutoff else None,
            "rows_deleted": self.rows_deleted,
            "blobs_deleted": self.blobs_deleted,
            "bytes_freed": self.bytes_freed,
            "errors": self.errors,
            "sources": [s.to_dict() for s in self.sources],
        }


def report_path() -> Path:
    """Where :data:`REPORT_FILENAME` is written."""
    from app.core.storage import resolve_data_dir

    return resolve_data_dir() / REPORT_FILENAME


def _persist_report(report: RetentionReport) -> None:
    """Write the report atomically. Never raises - a run that deleted files
    must not be reported as a failure because the summary could not be saved.
    """
    try:
        target = report_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        logger.warning("demo_retention: could not write %s", REPORT_FILENAME, exc_info=True)


def _log_report(report: RetentionReport) -> None:
    """One INFO line per run, greppable by a person and parsable by a watchdog."""
    logger.info(
        "demo_retention: armed=%s failed=%s capped=%s dry_run=%s window_days=%d rows_deleted=%d "
        "blobs_deleted=%d bytes_freed=%d errors=%d report=%s",
        report.armed,
        report.failed,
        report.capped,
        report.dry_run,
        report.window_days,
        report.rows_deleted,
        report.blobs_deleted,
        report.bytes_freed,
        len(report.errors),
        report_path(),
    )


# ── Filesystem helpers ──────────────────────────────────────────────────────


def _data_root() -> Path:
    """The active data directory, resolved.

    Only the active root, never the back-compat read roots in
    :func:`app.core.storage.safe_data_roots`: this code deletes, and a blob
    found under a fallback root may still belong to a live model. That is the
    same rule ``cleanup_orphan_bim_files`` states for its own scan.
    """
    from app.core.storage import resolve_data_dir

    return resolve_data_dir().resolve()


def _is_inside_data_root(path: Path) -> bool:
    """Containment check with ``relative_to``, not ``startswith``.

    A sibling directory whose name merely shares a prefix cannot pass, and a
    symlink escape is defeated because the path is resolved first. A row whose
    stored path points anywhere else - a packaged asset, a temp file, an
    operator's home directory - is never unlinked.
    """
    try:
        path.relative_to(_data_root())
    except (OSError, ValueError):
        return False
    return True


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


# ── Cross-table reference check ─────────────────────────────────────────────


async def _trash_referenced_paths(session: AsyncSession) -> set[str]:
    """Paths held alive by the recycle bin.

    ``app.modules.file_trash`` snapshots a row into ``oe_file_trash`` and
    deletes the original, so a trashed file has no row in its own table while
    its blob is still on disk and still restorable. Sweeping "a blob with no
    row" would delete exactly those. The snapshot is read once per run, which
    is safe precisely because of the arming condition: on a read-only demo no
    request can soft-delete anything while the sweep runs, since both layers
    of :mod:`app.core.demo_read_only` refuse the write.
    """
    try:
        from app.modules.file_trash.models import FileTrash
        from app.modules.file_trash.service import _STORAGE_PATH_KEYS
    except ImportError:
        logger.debug("demo_retention: file_trash not installed, no trash paths to honour")
        return set()

    paths: set[str] = set()
    rows = (await session.execute(select(FileTrash.payload_json).where(FileTrash.restored_at.is_(None)))).all()
    for (payload,) in rows:
        if not isinstance(payload, dict):
            continue
        for key in _STORAGE_PATH_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                paths.add(value.strip())
    return paths


async def _path_still_referenced(
    session: AsyncSession,
    path: str,
    *,
    excluded: dict[str, set[uuid.UUID]],
) -> bool:
    """Whether any live row in the registry still names ``path``.

    ``excluded`` maps table name to the ids this run has selected for deletion,
    so a dry run reaches the same verdict a real run does: in a real run those
    rows are already gone by the time this is asked, and in a dry run they are
    still present but must not count as a reason to keep the blob.

    Matching is exact string equality, which is how the platform's own
    zero-copy bookkeeping matches blobs (``preserve_blobs_for_deleted_source``:
    "Matching on the blob alone is what the correctness argument actually
    needs"). Both sides are written by the same upload handlers on the same
    host, so the strings agree or the rows are genuinely about different files.
    """
    for source in UPLOAD_SOURCES:
        if not source.path_attrs:
            continue
        try:
            model = source.load_model()
        except ImportError:
            continue
        skip = excluded.get(getattr(model, "__tablename__", ""), set())
        for attr in source.path_attrs:
            column = getattr(model, attr, None)
            if column is None:
                continue
            stmt = select(model.id).where(column == path)
            if skip:
                stmt = stmt.where(model.id.notin_(skip))
            if (await session.execute(stmt.limit(1))).first() is not None:
                return True
    return False


# ── Blob resolution ─────────────────────────────────────────────────────────


def _blob_refs(source: UploadSource, row: Any) -> list[BlobRef]:
    """Every blob ``row`` owns, in the shape the deleter needs."""
    refs: list[BlobRef] = []
    for attr in source.path_attrs:
        value = getattr(row, attr, None)
        if isinstance(value, str) and value.strip():
            refs.append(BlobRef(kind="path", locator=value.strip()))
    if source.prefix_for is not None:
        try:
            prefix = source.prefix_for(row)
        except Exception:  # noqa: BLE001 - a malformed row must not stop the sweep
            logger.warning("demo_retention: could not derive a storage prefix for %s", source.kind, exc_info=True)
        else:
            if prefix:
                refs.append(BlobRef(kind="prefix", locator=prefix))
    return refs


async def _prefix_size(prefix: str) -> tuple[int, int] | None:
    """``(blob_count, bytes)`` under ``prefix``, or ``None`` when unmeasurable.

    ``(0, 0)`` and ``None`` are deliberately different answers, and confusing
    them is how the largest source on the disk would quietly stop being swept.
    ``(0, 0)`` means the prefix is genuinely empty and there is nothing to
    delete; ``None`` means the backend could not be asked - it does not
    implement bulk listing, or the probe failed - and the caller must still
    issue the delete, because by the time it asks, the row is already gone and
    a skipped delete is a permanent orphan.
    """
    from app.core.storage import get_storage_backend

    try:
        listing = await get_storage_backend().list_prefix(prefix)
    except NotImplementedError:
        logger.debug("demo_retention: backend cannot list %s; deleting it unmeasured", prefix)
        return None
    except Exception:  # noqa: BLE001 - a size probe must never abort a sweep
        logger.warning("demo_retention: could not size prefix %s", prefix, exc_info=True)
        return None
    return (len(listing), sum(size for _key, size in listing))


async def _delete_prefix(prefix: str) -> int:
    from app.core.storage import get_storage_backend

    return await get_storage_backend().delete_prefix(prefix)


# ── The sweep ───────────────────────────────────────────────────────────────


@dataclass
class _Candidate:
    """A row the policy has decided is a disposable visitor upload."""

    source: UploadSource
    row: Any
    row_id: uuid.UUID
    table: str
    blobs: list[BlobRef]


async def _collect(
    session: AsyncSession,
    source: UploadSource,
    *,
    cutoff: datetime,
    limit: int,
    outcome: SourceOutcome,
) -> list[_Candidate]:
    """Select the rows of one source that the window and the markers allow."""
    try:
        model = source.load_model()
    except ImportError as exc:
        outcome.errors.append(f"module not installed: {exc}")
        return []

    if not hasattr(model, "metadata_"):
        # Structural, not defensive: a model that cannot carry the seed marker
        # must never have been registered, and if one is, the sweep refuses it
        # rather than treating "no marker" as "not seeded".
        outcome.errors.append(f"{source.kind} has no metadata column; refusing to sweep it")
        return []

    stmt = select(model).where(model.created_at < cutoff).order_by(model.created_at).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()

    candidates: list[_Candidate] = []
    for row in rows:
        outcome.rows_examined += 1
        seeded = is_seeded_row(row)
        if seeded is None:
            outcome.rows_kept_unmarked += 1
            continue
        if seeded:
            outcome.rows_kept_seeded += 1
            continue
        candidates.append(
            _Candidate(
                source=source,
                row=row,
                row_id=row.id,
                table=model.__tablename__,
                blobs=_blob_refs(source, row),
            )
        )
    return candidates


async def _remove_blobs(
    session: AsyncSession,
    candidate: _Candidate,
    *,
    dry_run: bool,
    trash_paths: set[str],
    excluded: dict[str, set[uuid.UUID]],
    handled: set[str],
    outcome: SourceOutcome,
) -> None:
    """Delete (or, on a dry run, price) the blobs of an already-deleted row.

    ``handled`` carries the locators this run has already dealt with, so a blob
    two doomed rows share is counted once. Without it the two modes disagree:
    a real run unlinks the file for the first row and records the second as
    missing, while a dry run - which unlinks nothing - would count the same
    bytes twice and tell an operator it will free more than it can.
    """
    for ref in candidate.blobs:
        if ref.locator in handled:
            continue
        handled.add(ref.locator)

        if ref.kind == "prefix":
            measured = await _prefix_size(ref.locator)
            if measured == (0, 0):
                # Genuinely empty. Nothing to delete, nothing to report.
                outcome.blobs_missing += 1
                continue
            if measured is None:
                # The size probe failed or the backend cannot list. The row is
                # already deleted and committed, so skipping the delete here
                # would strand the prefix forever - issue it unmeasured and say
                # so, rather than reporting an orphan as "there was nothing there".
                outcome.errors.append(f"could not size prefix {ref.locator}; deleting it unmeasured")
                if dry_run:
                    continue
                outcome.blobs_deleted += await _delete_prefix(ref.locator)
                continue
            count, size = measured
            if dry_run:
                outcome.blobs_deleted += count
                outcome.bytes_freed += size
                continue
            removed = await _delete_prefix(ref.locator)
            outcome.blobs_deleted += removed
            outcome.bytes_freed += size
            continue

        path = Path(ref.locator)
        try:
            resolved = path.resolve()
        except OSError:
            outcome.blobs_kept_outside_data_dir += 1
            continue
        if not _is_inside_data_root(resolved):
            outcome.blobs_kept_outside_data_dir += 1
            continue
        if ref.locator in trash_paths:
            outcome.blobs_kept_referenced += 1
            continue
        if await _path_still_referenced(session, ref.locator, excluded=excluded):
            outcome.blobs_kept_referenced += 1
            continue
        if not resolved.is_file():
            outcome.blobs_missing += 1
            continue

        size = _file_size(resolved)
        if dry_run:
            outcome.blobs_deleted += 1
            outcome.bytes_freed += size
            continue
        try:
            resolved.unlink()
        except OSError as exc:
            outcome.errors.append(f"could not unlink {ref.locator}: {exc}")
            continue
        outcome.blobs_deleted += 1
        outcome.bytes_freed += size


async def sweep_demo_uploads(
    session: AsyncSession,
    *,
    retention_days: int | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    max_rows_per_source: int = MAX_ROWS_PER_SOURCE,
) -> RetentionReport:
    """Apply the retention policy once and report what happened.

    Returns a :class:`RetentionReport` in every case, including the case where
    this deployment is not a demo - then ``armed`` is ``False``,
    ``skipped_reason`` says why, and nothing was read or written.

    ``retention_days`` narrows or widens the window for this call only (the
    CLI's ``--days``); it cannot arm a deployment that is not armed.

    The caller's session is committed once per deleted row. In a test that
    wraps the session in an outer transaction, those commits become savepoint
    releases and are rolled back on teardown, as elsewhere in this suite.
    """
    from app.core.demo_read_only import _reset_write_scope, _set_write_scope

    started = datetime.now(UTC)
    window = retention_window_days() if retention_days is None else int(retention_days)

    if not demo_retention_enabled():
        report = RetentionReport(
            started_at=started,
            finished_at=datetime.now(UTC),
            dry_run=dry_run,
            window_days=window,
            armed=False,
            skipped_reason=(
                "not a read-only demo with a positive retention window "
                "(OE_DEMO_READ_ONLY and OE_DEMO_UPLOADS_RETENTION_DAYS)"
            ),
        )
        _log_report(report)
        _persist_report(report)
        return report

    if window <= 0:
        # Reachable only through an explicit ``retention_days=0`` argument,
        # which would mean "delete everything ever uploaded". Refuse it: a
        # window that keeps nothing is not a retention policy.
        report = RetentionReport(
            started_at=started,
            finished_at=datetime.now(UTC),
            dry_run=dry_run,
            window_days=window,
            armed=False,
            skipped_reason="retention window must be a positive number of days",
        )
        _log_report(report)
        _persist_report(report)
        return report

    cutoff = (now or datetime.now(UTC)) - timedelta(days=window)
    report = RetentionReport(
        started_at=started,
        dry_run=dry_run,
        window_days=window,
        armed=True,
        cutoff=cutoff,
    )

    # A background task inherits the context it was created in, and on a
    # read-only demo an inherited request scope would make the database
    # tripwire refuse this job's own DELETEs. Bind the scope to "no request in
    # scope" for the duration, which is what a scheduler, a seeder and the CLI
    # all run with anyway.
    scope_token = _set_write_scope(None)
    try:
        trash_paths = await _trash_referenced_paths(session)

        # Two phases on purpose. Collecting every candidate before deleting any
        # of them is what lets the reference check exclude the whole deletion
        # set, so a dry run and a real run agree about a blob that two doomed
        # rows share - the real run frees it once the second row goes, and the
        # dry run must say so too.
        plan: list[tuple[SourceOutcome, list[_Candidate]]] = []
        excluded: dict[str, set[uuid.UUID]] = {}
        for source in UPLOAD_SOURCES:
            outcome = SourceOutcome(kind=source.kind)
            report.sources.append(outcome)
            candidates = await _collect(
                session,
                source,
                cutoff=cutoff,
                limit=max_rows_per_source,
                outcome=outcome,
            )
            outcome.capped = len(candidates) >= max_rows_per_source
            plan.append((outcome, candidates))
            for candidate in candidates:
                excluded.setdefault(candidate.table, set()).add(candidate.row_id)

        handled: set[str] = set()
        for outcome, candidates in plan:
            for candidate in candidates:
                try:
                    if not dry_run:
                        # Row first, committed, then the blob. A kill here
                        # leaves at most one unreferenced blob behind; the
                        # other order would leave a row pointing at bytes that
                        # no longer exist, which nothing can repair.
                        model = candidate.source.load_model()
                        await session.execute(sql_delete(model).where(model.id == candidate.row_id))
                        await session.commit()
                    outcome.rows_deleted += 1
                    await _remove_blobs(
                        session,
                        candidate,
                        dry_run=dry_run,
                        trash_paths=trash_paths,
                        excluded=excluded,
                        handled=handled,
                        outcome=outcome,
                    )
                except Exception as exc:  # noqa: BLE001 - one bad row must not stop the run
                    outcome.errors.append(f"{candidate.table}/{candidate.row_id}: {exc}")
                    logger.exception("demo_retention: failed on %s/%s", candidate.table, candidate.row_id)
                    if not dry_run:
                        await session.rollback()
    finally:
        _reset_write_scope(scope_token)

    report.finished_at = datetime.now(UTC)
    _log_report(report)
    _persist_report(report)
    return report


# ── Entry points ────────────────────────────────────────────────────────────


async def run_sweep_once(
    *,
    dry_run: bool = False,
    retention_days: int | None = None,
) -> RetentionReport:
    """Open a short-lived session and run one sweep.

    The wrapper a scheduler tick, a Celery worker or the CLI script uses. Never
    raises: a sweep that fails wholesale still returns a report saying so, so
    the JSON artifact is written and the watchdog sees a run rather than
    silence.
    """
    from app.database import async_session_factory

    try:
        async with async_session_factory() as session:
            return await sweep_demo_uploads(session, dry_run=dry_run, retention_days=retention_days)
    except Exception as exc:  # noqa: BLE001 - the scheduler loop must survive
        logger.exception("demo_retention: sweep failed")
        report = RetentionReport(
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            dry_run=dry_run,
            window_days=retention_days if retention_days is not None else retention_window_days(),
            # armed=True: the deployment did want this run. What went wrong is
            # a failure, not a reason to skip, and the two must not collapse
            # into one signal an operator cannot act on.
            armed=demo_retention_enabled(),
            failure=f"sweep failed: {exc}",
        )
        _log_report(report)
        _persist_report(report)
        return report


# Cadence matches the other maintenance loops in ``app.main`` (KPI recalc,
# file-trash purge). Retention windows are measured in days, so a missed tick
# costs a day of stale blobs and nothing else.
_DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60
#: First tick well after boot, so a restart never runs a delete pass in the
#: same window as migrations and cache warm-ups.
_DEFAULT_FIRST_TICK_DELAY_SECONDS = 60 * 60

_ACTIVE_TASK: asyncio.Task[None] | None = None


async def _scheduler_loop(interval_seconds: int, first_tick_delay_seconds: int) -> None:
    await asyncio.sleep(first_tick_delay_seconds)
    while True:
        try:
            # Re-checked every tick rather than only at registration: the
            # arming predicate is the guard, and it is read per call.
            if demo_retention_enabled():
                await run_sweep_once()
        except asyncio.CancelledError:  # pragma: no cover - process shutdown
            raise
        except Exception:  # noqa: BLE001
            logger.exception("demo_retention scheduler tick failed")
        await asyncio.sleep(interval_seconds)


def register_jobs(
    *,
    interval_seconds: int = _DEFAULT_INTERVAL_SECONDS,
    first_tick_delay_seconds: int = _DEFAULT_FIRST_TICK_DELAY_SECONDS,
) -> asyncio.Task[None] | None:
    """Schedule the daily sweep, but only on an armed demo.

    Returns ``None`` and starts nothing when this deployment is not a
    read-only demo with a positive retention window, so a self-hosted install
    has no loop, no timer and nothing that could ever call the sweep. Idempotent
    in the same way ``app.modules.file_trash.jobs.register_jobs`` is: a live
    task is left alone, a finished or cancelled one is replaced.
    """
    global _ACTIVE_TASK
    if not demo_retention_enabled():
        logger.debug("demo_retention: not an armed demo, scheduler not started")
        return None
    if _ACTIVE_TASK is not None and not _ACTIVE_TASK.done():
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("demo_retention.register_jobs: no running event loop; scheduler not started")
        return None
    task = loop.create_task(_scheduler_loop(interval_seconds, first_tick_delay_seconds))
    _ACTIVE_TASK = task
    logger.info(
        "demo_retention scheduler registered (window=%d days, every %d s, first tick in %d s)",
        retention_window_days(),
        interval_seconds,
        first_tick_delay_seconds,
    )
    return task
