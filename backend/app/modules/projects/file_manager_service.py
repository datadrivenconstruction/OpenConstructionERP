"""‌⁠‍File-manager aggregation service (Issue #109).

The file manager surfaces every binary that belongs to a project — across
multiple modules — under a single API. Each module owns its own table /
storage root; the service queries them independently and degrades
gracefully when an optional module is disabled (e.g. ``oe_dwg_takeoff``,
``oe_bim_hub``).

Storage root reality check (audited 2026-05-05):

* Documents  : ``~/.openestimator/uploads/{project_id}/{uuid}_{filename}``
* Photos     : ``~/.openestimator/photos/{project_id}/{uuid}_{filename}``
* Sheets     : ``~/.openestimator/sheets/{project_id}/...``
* BIM        : ``<repo>/data/bim/{project_id}/{model_id}/{geometry.glb,...}``
* DWG/DXF    : ``${DATA_DIR or ./data}/dwg_uploads/{drawing_id}.{ext}`` (flat)

Note the documents service uses ``~/.openestimator`` (with ``r``) while
the CLI canonical data dir is ``~/.openestimate`` (no ``r``). The file
manager honestly surfaces whichever path the row was actually written to,
plus a ``notes`` flag when the mismatch is detected, instead of papering
over it.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.file_manager_schemas import (
    FileKind,
    FileListResponse,
    FileRow,
    FileTreeNode,
    StorageLocations,
)

logger = logging.getLogger(__name__)


# Hard cap per collector. The file manager aggregates across 7 modules and
# returns the union to the client; without a cap, a project with 50k photos
# would block the request thread loading every row before serialising. The
# UI paginates client-side so 5k is plenty for one collector.
_PER_COLLECTOR_LIMIT = 5_000


# Stable category labels — UI re-translates them via i18n keys
# ``files.category.<id>`` and falls back to these defaults.
_CATEGORY_LABELS: dict[FileKind, str] = {
    "document": "Documents",
    "photo": "Photos",
    "sheet": "Drawing sheets",
    "bim_model": "BIM models",
    "dwg_drawing": "DWG / DXF drawings",
    "takeoff": "Takeoffs",
    "report": "Reports",
    "markup": "Markups",
}

# MIME-type guesses keyed on extension. Kept tight on purpose — the front-end
# only needs enough to pick the right icon and decide whether to inline-preview.
_MIME_BY_EXT: dict[str, str] = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "gif": "image/gif",
    "webp": "image/webp",
    "heic": "image/heic",
    "heif": "image/heif",
    "dwg": "application/acad",
    "dxf": "image/vnd.dxf",
    "ifc": "application/x-step",
    "rvt": "application/octet-stream",
    "dgn": "application/octet-stream",
    "glb": "model/gltf-binary",
    "gltf": "model/gltf+json",
    "dae": "model/vnd.collada+xml",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "csv": "text/csv",
    "json": "application/json",
    "xml": "application/xml",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _ext_of(name: str | None) -> str | None:
    """‌⁠‍Lower-cased extension without the leading dot, or None."""
    if not name:
        return None
    _, _, ext = name.rpartition(".")
    if not ext or ext == name:
        return None
    return ext.lower()


def _mime_of(name: str | None, fallback: str | None = None) -> str | None:
    ext = _ext_of(name)
    if ext and ext in _MIME_BY_EXT:
        return _MIME_BY_EXT[ext]
    return fallback


def _file_size(path: str | None) -> int:
    """‌⁠‍Size in bytes; 0 if path is missing or unreadable.

    Stat-failures are silently absorbed so a single deleted file never
    breaks the whole listing — the row still appears with ``size=0`` and
    the UI can decide how to render it.
    """
    if not path:
        return 0
    try:
        stat = os.stat(path)
    except (OSError, ValueError):
        return 0
    return int(stat.st_size)


def _file_mtime(path: str | None) -> datetime | None:
    if not path:
        return None
    try:
        ts = os.stat(path).st_mtime
    except (OSError, ValueError):
        return None
    return datetime.fromtimestamp(ts, tz=UTC)


_EPOCH_UTC = datetime.fromtimestamp(0, tz=UTC)


def _as_aware_utc(value: datetime | None) -> datetime:
    """Coerce a possibly-naive / possibly-None datetime to an aware-UTC one.

    Document ORM rows carry NAIVE ``created_at``/``updated_at`` (SQLite) while
    the photo→document cross-link historically wrote an AWARE ISO timestamp.
    Mixing the two in a sort key raises ``TypeError`` (offset-naive vs
    offset-aware) → HTTP 500. Normalising every value to aware-UTC here makes
    the sort key total-ordered regardless of how the row was ingested.
    """
    if value is None:
        return _EPOCH_UTC
    if value.tzinfo is None:
        # Stored as naive UTC everywhere in this codebase — assume UTC.
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _relative_path(path: str | Path | None, project_id: str) -> str:
    """Best-effort breadcrumb path. Falls back to the absolute path when
    the file lives outside any known root."""
    if not path:
        return ""
    p = str(path)
    pid = str(project_id)
    if pid in p:
        idx = p.index(pid) + len(pid) + 1  # include trailing separator
        return p[idx:].replace("\\", "/")
    return Path(p).name


def _safe_count(seq: Sequence[Any] | None) -> int:
    return len(seq) if seq is not None else 0


# ── Per-module collectors ────────────────────────────────────────────────


async def _collect_documents(
    session: AsyncSession,
    project_id: str,
) -> list[FileRow]:
    try:
        from app.modules.documents.models import Document
    except ImportError:
        return []
    rows = (
        (
            await session.execute(
                select(Document).where(Document.project_id == project_id).limit(_PER_COLLECTOR_LIMIT),
            )
        )
        .scalars()
        .all()
    )
    out: list[FileRow] = []
    for r in rows:
        path = r.file_path or ""
        out.append(
            FileRow(
                id=str(r.id),
                kind="document",
                name=r.name,
                project_id=str(project_id),
                size_bytes=int(r.file_size or 0) or _file_size(path),
                mime_type=r.mime_type or _mime_of(r.name),
                extension=_ext_of(r.name),
                modified_at=getattr(r, "updated_at", None) or getattr(r, "created_at", None),
                physical_path=path,
                relative_path=_relative_path(path, project_id),
                download_url=f"/api/v1/documents/{r.id}/download/",
                preview_url=None,
                category=r.category,
                discipline=r.discipline,
                extra={
                    "version": r.version,
                    "revision_code": r.revision_code,
                    "drawing_number": r.drawing_number,
                    "cde_state": r.cde_state,
                },
            ),
        )
    return out


async def _collect_photos(
    session: AsyncSession,
    project_id: str,
) -> list[FileRow]:
    try:
        from app.modules.documents.models import ProjectPhoto
    except ImportError:
        return []
    rows = (
        (
            await session.execute(
                select(ProjectPhoto).where(ProjectPhoto.project_id == project_id).limit(_PER_COLLECTOR_LIMIT),
            )
        )
        .scalars()
        .all()
    )
    out: list[FileRow] = []
    for r in rows:
        path = r.file_path
        out.append(
            FileRow(
                id=str(r.id),
                kind="photo",
                name=r.filename,
                project_id=str(project_id),
                size_bytes=_file_size(path),
                mime_type=_mime_of(r.filename),
                extension=_ext_of(r.filename),
                modified_at=r.taken_at or getattr(r, "created_at", None),
                physical_path=path,
                relative_path=_relative_path(path, project_id),
                download_url=f"/api/v1/documents/photos/{r.id}/file/",
                preview_url=(f"/api/v1/documents/photos/{r.id}/thumb/" if r.thumbnail_path else None),
                thumbnail_url=(f"/api/v1/documents/photos/{r.id}/thumb/" if r.thumbnail_path else None),
                category=r.category,
                extra={
                    "gps_lat": r.gps_lat,
                    "gps_lon": r.gps_lon,
                    "thumbnail_path": r.thumbnail_path,
                },
            ),
        )
    return out


async def _collect_sheets(
    session: AsyncSession,
    project_id: str,
) -> list[FileRow]:
    try:
        from app.modules.documents.models import Document, Sheet
    except ImportError:
        return []
    rows = (
        (
            await session.execute(
                select(Sheet).where(Sheet.project_id == project_id).limit(_PER_COLLECTOR_LIMIT),
            )
        )
        .scalars()
        .all()
    )
    # A sheet's only physical artifact is its thumbnail PNG, which is
    # frequently absent (snapshot-seeded data, lazy thumbnailing). Rather
    # than report a misleading 0, fall back to an even per-page share of
    # the parent PDF's size — so the column is plausible and the per-doc
    # rows still sum to ≈ the source document size.
    doc_ids = {r.document_id for r in rows if r.document_id}
    doc_size: dict[str, int] = {}
    sheets_per_doc: dict[str, int] = {}
    for r in rows:
        if r.document_id:
            sheets_per_doc[r.document_id] = sheets_per_doc.get(r.document_id, 0) + 1
    if doc_ids:
        for did, fsize in (
            await session.execute(
                select(Document.id, Document.file_size).where(
                    Document.id.in_(doc_ids),
                ),
            )
        ).all():
            doc_size[str(did)] = int(fsize or 0)
    out: list[FileRow] = []
    for r in rows:
        path = r.thumbnail_path or ""
        # Sheets are extracted pages of a parent PDF document. The "physical
        # file" here is the thumbnail PNG; the source PDF is reachable via
        # r.document_id and shows up under the documents collector.
        name = r.sheet_title or (f"Sheet {r.sheet_number}" if r.sheet_number else f"Page {r.page_number}")
        out.append(
            FileRow(
                id=str(r.id),
                kind="sheet",
                name=name,
                project_id=str(project_id),
                size_bytes=(
                    _file_size(path)
                    or (
                        doc_size.get(str(r.document_id), 0) // max(sheets_per_doc.get(r.document_id, 1), 1)
                        if r.document_id
                        else 0
                    )
                ),
                mime_type="image/png",
                extension="png",
                modified_at=r.revision_date or getattr(r, "created_at", None),
                physical_path=path,
                relative_path=_relative_path(path, project_id),
                download_url=None,
                preview_url=path or None,
                discipline=r.discipline,
                extra={
                    "page_number": r.page_number,
                    "sheet_number": r.sheet_number,
                    "revision": r.revision,
                    "scale": r.scale,
                    "is_current": r.is_current,
                    "document_id": r.document_id,
                },
            ),
        )
    return out


async def _collect_bim_models(
    session: AsyncSession,
    project_id: str,
) -> list[FileRow]:
    try:
        from app.modules.bim_hub import file_storage as bim_file_storage
        from app.modules.bim_hub.models import BIMModel
    except ImportError:
        return []
    rows = (
        (
            await session.execute(
                select(BIMModel).where(BIMModel.project_id == project_id).limit(_PER_COLLECTOR_LIMIT),
            )
        )
        .scalars()
        .all()
    )
    out: list[FileRow] = []
    for r in rows:
        path = r.canonical_file_path or ""
        # The canonical source file is frequently absent (snapshot-seeded
        # models, S3-only deployments) yet the model still renders because
        # its converted geometry (GLB/DAE) lives in BIM storage. Report the
        # size of that real on-disk artifact rather than a misleading 0.
        size = _file_size(path)
        if not size:
            try:
                size = await bim_file_storage.compute_artifact_size_bytes(
                    project_id,
                    r.id,
                )
            except Exception:  # noqa: BLE001 - best-effort sizing
                size = 0
        out.append(
            FileRow(
                id=str(r.id),
                kind="bim_model",
                name=r.name,
                project_id=str(project_id),
                size_bytes=size,
                mime_type=_mime_of(r.name),
                extension=_ext_of(r.name) or r.model_format,
                modified_at=getattr(r, "updated_at", None) or getattr(r, "created_at", None),
                physical_path=path,
                relative_path=_relative_path(path, project_id),
                download_url=(f"/api/v1/bim_hub/models/{r.id}/download/" if path else None),
                preview_url=None,
                discipline=r.discipline,
                extra={
                    "model_format": r.model_format,
                    "version": r.version,
                    "status": r.status,
                    "element_count": r.element_count,
                    "storey_count": r.storey_count,
                },
            ),
        )
    return out


async def _collect_dwg_drawings(
    session: AsyncSession,
    project_id: str,
) -> list[FileRow]:
    try:
        from app.modules.dwg_takeoff.models import DwgDrawing
    except ImportError:
        return []
    rows = (
        (
            await session.execute(
                select(DwgDrawing).where(DwgDrawing.project_id == project_id).limit(_PER_COLLECTOR_LIMIT),
            )
        )
        .scalars()
        .all()
    )
    out: list[FileRow] = []
    for r in rows:
        path = r.file_path
        out.append(
            FileRow(
                id=str(r.id),
                kind="dwg_drawing",
                name=r.name,
                project_id=str(project_id),
                size_bytes=int(r.size_bytes or 0) or _file_size(path),
                mime_type=_mime_of(r.filename),
                extension=_ext_of(r.filename) or r.file_format,
                modified_at=getattr(r, "updated_at", None) or getattr(r, "created_at", None),
                physical_path=path,
                # DWG storage is currently FLAT (not per-project); we still
                # keep the file id in the breadcrumb so the path bar is
                # informative.
                relative_path=Path(path).name if path else "",
                download_url=f"/api/v1/dwg-takeoff/drawings/{r.id}/download/",
                preview_url=(f"/api/v1/dwg-takeoff/drawings/{r.id}/thumbnail/" if r.thumbnail_key else None),
                thumbnail_url=(f"/api/v1/dwg-takeoff/drawings/{r.id}/thumbnail/" if r.thumbnail_key else None),
                discipline=r.discipline,
                extra={
                    "file_format": r.file_format,
                    "status": r.status,
                    "sheet_number": r.sheet_number,
                    "scale_denominator": r.scale_denominator,
                },
            ),
        )
    return out


# ── Public API ───────────────────────────────────────────────────────────


async def list_project_files(
    session: AsyncSession,
    project_id: str,
    *,
    category: FileKind | None = None,
    extension: str | None = None,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: str = "modified",
) -> FileListResponse:
    """Aggregate every file that belongs to ``project_id`` across modules.

    Each module is queried independently — failure or absence of one module
    only loses its slice; the other slices still surface.
    """
    collectors = (
        ("document", _collect_documents),
        ("photo", _collect_photos),
        ("sheet", _collect_sheets),
        ("bim_model", _collect_bim_models),
        ("dwg_drawing", _collect_dwg_drawings),
    )
    rows: list[FileRow] = []
    for kind, fn in collectors:
        if category and category != kind:
            continue
        try:
            rows.extend(await fn(session, project_id))
        except Exception:  # noqa: BLE001 — see docstring
            logger.exception(
                "file-manager: %s collector failed for project %s — skipped",
                kind,
                project_id,
            )

    # Filters
    if extension:
        ext = extension.lstrip(".").lower()
        rows = [r for r in rows if (r.extension or "").lower() == ext]
    if query:
        q = query.lower()
        rows = [r for r in rows if q in r.name.lower()]

    # Sort
    if sort == "name":
        rows.sort(key=lambda r: r.name.lower())
    elif sort == "size":
        rows.sort(key=lambda r: r.size_bytes, reverse=True)
    elif sort == "kind":
        rows.sort(key=lambda r: (r.kind, r.name.lower()))
    else:  # modified — most recent first; rows with no mtime sink to the bottom
        # ``_as_aware_utc`` normalises naive (SQLite ORM) and aware (photo
        # cross-link) timestamps to a single comparable type so a project
        # with BOTH never raises TypeError → 500.
        rows.sort(
            key=lambda r: _as_aware_utc(r.modified_at),
            reverse=True,
        )

    total = len(rows)
    paged = rows[offset : offset + limit]
    return FileListResponse(
        project_id=str(project_id),
        items=paged,
        total=total,
        limit=limit,
        offset=offset,
    )


async def file_tree(
    session: AsyncSession,
    project_id: str,
    *,
    query: str | None = None,
    extension: str | None = None,
) -> list[FileTreeNode]:
    """Build the left-pane tree: one node per category + count + size.

    When ``query`` or ``extension`` is provided the counts reflect the
    same filters the file list uses, so the sidebar can't promise a
    category has 9 files when a free-text search would return 0 — the
    historical UX bug where users clicked "Documents 9" with ``?q=foo``
    active and saw an empty list with no explanation.
    """
    listing = await list_project_files(
        session,
        project_id,
        query=query,
        extension=extension,
        limit=100_000,
        offset=0,
    )
    by_kind: dict[FileKind, list[FileRow]] = {}
    for r in listing.items:
        by_kind.setdefault(r.kind, []).append(r)

    tree: list[FileTreeNode] = []
    for kind in (
        "document",
        "photo",
        "sheet",
        "bim_model",
        "dwg_drawing",
        "takeoff",
        "report",
        "markup",
    ):
        kind_rows = by_kind.get(kind, [])  # type: ignore[arg-type]
        if not kind_rows:
            continue
        # Pick the deepest common parent — anchors the path-bar header.
        first_path = kind_rows[0].physical_path
        physical_parent = str(Path(first_path).parent) if first_path else None
        tree.append(
            FileTreeNode(
                # id IS the FileKind so the UI can reuse it as a filter
                # category — the typed `kind` field carries the node-class
                # ("category"|"folder"|...) separately. An earlier draft
                # prefixed this with "category:" but that broke
                # FolderCardGrid icon lookup and selection-equality.
                id=kind,
                label=_CATEGORY_LABELS.get(kind, kind.replace("_", " ").title()),  # type: ignore[arg-type]
                kind="category",
                file_count=len(kind_rows),
                total_bytes=sum(r.size_bytes for r in kind_rows),
                physical_path=physical_parent,
            ),
        )
    return tree


def resolve_storage_locations(
    project_id: str,
    project_name: str,
    *,
    settings: Any | None = None,
) -> StorageLocations:
    """Where does this project's data actually live on disk?

    Mirrors the per-module conventions verified during the audit. ``settings``
    is the FastAPI Settings object — used to detect the configured DB path
    and storage backend; passing None falls back to module-default paths.
    """
    # Documents / photos / sheets — use the path constants that the documents
    # service hard-codes today. We import inside the function so the module
    # being optionally disabled doesn't crash this call.
    uploads_root: str | None = None
    photos_root: str | None = None
    sheets_root: str | None = None
    notes: list[str] = []
    try:
        from app.modules.documents.service import (
            PHOTO_BASE,
            SHEET_THUMB_BASE,
            UPLOAD_BASE,
        )

        uploads_root = str(UPLOAD_BASE / project_id)
        photos_root = str(PHOTO_BASE / project_id)
        sheets_root = str(SHEET_THUMB_BASE / project_id)

        # Detect the .openestimator-vs-.openestimate typo and warn so users
        # who land in the file manager understand why their attachments are
        # split between two folders. We do not "fix" it here — that lives in
        # a dedicated migration ticket.
        canonical = Path.home() / ".openestimate"
        if "openestimator" in str(UPLOAD_BASE) and canonical.exists():
            notes.append(
                "Attachments live under ~/.openestimator (with 'r') while the "
                "CLI canonical data dir is ~/.openestimate. Both are real on "
                "disk; the file manager surfaces whichever each row was "
                "written to.",
            )
    except ImportError:
        pass

    # BIM — repo-relative data/bim/{project_id}.
    bim_root: str | None = None
    try:
        from app.core.storage import _default_local_base_dir

        bim_root = str(_default_local_base_dir() / "bim" / project_id)
    except ImportError:
        pass

    # DWG — DATA_DIR + dwg_uploads (flat layout, not per-project — flagged).
    data_dir = os.environ.get("DATA_DIR") or os.path.join(os.getcwd(), "data")
    dwg_root = os.path.join(data_dir, "dwg_uploads")
    notes.append(
        "DWG / DXF drawings are currently stored flat under "
        f"{dwg_root} — each drawing's filename embeds its UUID rather than "
        "living in a per-project folder.",
    )

    # DB
    db_path: str | None = None
    if settings is not None:
        url = getattr(settings, "database_url", "") or ""
        if "sqlite" in url and "///" in url:
            _, _, p = url.rpartition("///")
            db_path = p

    backend_name = "local"
    if settings is not None:
        backend_name = (getattr(settings, "storage_backend", "local") or "local").lower()

    return StorageLocations(
        project_id=str(project_id),
        project_name=project_name,
        storage_uses_default=True,
        storage_path_override=None,
        storage_backend=backend_name if backend_name in {"local", "s3"} else "local",  # type: ignore[arg-type]
        db_path=db_path,
        uploads_root=uploads_root,
        photos_root=photos_root,
        sheets_root=sheets_root,
        bim_root=bim_root,
        dwg_root=dwg_root,
        extras={},
        notes=notes,
    )


__all__ = [
    "list_project_files",
    "file_tree",
    "resolve_storage_locations",
]


def _kinds() -> Iterable[FileKind]:  # convenience for tests
    return ("document", "photo", "sheet", "bim_model", "dwg_drawing")
