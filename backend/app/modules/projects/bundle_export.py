# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project-bundle export (Issue #109).

Generates a ``.ocep`` zip - *OpenConstructionERP Project* - for a single
project. Supports split-scope bundles so users with large BIM/DWG attachments
can email the metadata-only zip while sharing geometry separately:

* ``metadata_only`` - DB rows only (projects, BOQ, schedule, risks, …)
* ``documents``     - metadata + Document/Photo/Sheet rows and their files
* ``bim``           - metadata-of-bim + every BIMModel.canonical_file_path file
                      (BIMElement rows are off by default - they can balloon
                      to 50k+ rows; user toggle covers them)
* ``dwg``           - metadata + DwgDrawing rows + their .dwg/.dxf files
* ``full``          - every attachment kind in one bundle

Bundle layout (POSIX paths, always forward-slash):

    <bundle.ocep>
    ├── manifest.json
    ├── tables/
    │   ├── projects.json
    │   ├── boqs.json
    │   └── ...
    ├── attachments/
    │   ├── documents/{uuid}/{filename}
    │   ├── photos/{uuid}/{filename}
    │   ├── photos/thumbs/{uuid}/{filename}
    │   ├── sheets/thumbs/{uuid}.png
    │   ├── bim/{model_uuid}/{geometry.glb,...}
    │   └── dwg/{drawing_uuid}.{ext}
    ├── attachments/index.json    # sha256 + size + original_path per binary
    └── README.md

Authentication / per-project gating happens at the router layer; this module
is pure orchestration over a SQLAlchemy session.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup.router import serialize_row
from app.modules.projects.file_manager_schemas import (
    BundleManifest,
    BundleScope,
    ExportOptions,
    ExportPreview,
)

logger = logging.getLogger(__name__)


BUNDLE_FORMAT = "ocep"
BUNDLE_FORMAT_VERSION = "1.0.0"
ENGINE_VERSION = "2.9.4"


# ── Table registry ───────────────────────────────────────────────────────
# Listed in FK-dependency order so that import inserts parents before
# children. Each entry: (key, module_path, class_name, optional flag).
# The "optional" flag means we silently skip the table if its module is
# not loaded - keeps the bundle viable when the user has disabled a
# regional / heavy module.

_BUNDLE_TABLES_CORE: list[tuple[str, str, str, bool]] = [
    ("projects", "app.modules.projects.models", "Project", False),
    ("project_wbs", "app.modules.projects.models", "ProjectWBS", True),
    ("project_milestones", "app.modules.projects.models", "ProjectMilestone", True),
    ("boqs", "app.modules.boq.models", "BOQ", True),
    ("positions", "app.modules.boq.models", "Position", True),
    ("markups", "app.modules.boq.models", "BOQMarkup", True),
    ("assemblies", "app.modules.assemblies.models", "Assembly", True),
    ("assembly_components", "app.modules.assemblies.models", "Component", True),
    ("schedules", "app.modules.schedule.models", "Schedule", True),
    ("activities", "app.modules.schedule.models", "Activity", True),
    ("budget_lines", "app.modules.costmodel.models", "BudgetLine", True),
    ("cash_flows", "app.modules.costmodel.models", "CashFlow", True),
    ("cost_snapshots", "app.modules.costmodel.models", "CostSnapshot", True),
    ("risks", "app.modules.risk.models", "RiskItem", True),
    ("change_orders", "app.modules.changeorders.models", "ChangeOrder", True),
    ("change_order_items", "app.modules.changeorders.models", "ChangeOrderItem", True),
    ("tender_packages", "app.modules.tendering.models", "TenderPackage", True),
    ("tender_bids", "app.modules.tendering.models", "TenderBid", True),
]

_BUNDLE_TABLES_DOCUMENTS: list[tuple[str, str, str, bool]] = [
    ("documents", "app.modules.documents.models", "Document", True),
    ("photos", "app.modules.documents.models", "ProjectPhoto", True),
    ("sheets", "app.modules.documents.models", "Sheet", True),
    ("document_bim_links", "app.modules.documents.models", "DocumentBIMLink", True),
]

_BUNDLE_TABLES_BIM: list[tuple[str, str, str, bool]] = [
    ("bim_models", "app.modules.bim_hub.models", "BIMModel", True),
    ("bim_elements", "app.modules.bim_hub.models", "BIMElement", True),
]

_BUNDLE_TABLES_DWG: list[tuple[str, str, str, bool]] = [
    ("dwg_drawings", "app.modules.dwg_takeoff.models", "DwgDrawing", True),
    ("dwg_drawing_versions", "app.modules.dwg_takeoff.models", "DwgDrawingVersion", True),
]


def _import_class(module_path: str, class_name: str) -> type | None:
    import importlib

    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)
    except (ImportError, AttributeError):
        return None


# ── Scope helpers ────────────────────────────────────────────────────────


def _options_from_scope(opts: ExportOptions) -> ExportOptions:
    """Translate a high-level scope to per-flag choices, keeping any
    explicit flags the caller already set."""
    scope = opts.scope
    if scope == "metadata_only":
        return opts
    if scope == "documents":
        return opts.model_copy(
            update={
                "include_documents": True,
                "include_photos": True,
                "include_sheets": True,
            }
        )
    if scope == "bim":
        return opts.model_copy(
            update={
                "include_bim_models": True,
                "include_bim_geometry": True,
            }
        )
    if scope == "dwg":
        return opts.model_copy(
            update={
                "include_dwg_drawings": True,
            }
        )
    if scope == "full":
        return opts.model_copy(
            update={
                "include_documents": True,
                "include_photos": True,
                "include_sheets": True,
                "include_bim_models": True,
                "include_bim_geometry": True,
                "include_bim_elements": True,
                "include_dwg_drawings": True,
                "include_takeoff": True,
                "include_reports": True,
            }
        )
    return opts


def _enabled_table_keys(opts: ExportOptions) -> set[str]:
    """Resolve which table-keys land in the bundle based on flags."""
    keys: set[str] = {k for k, *_rest in _BUNDLE_TABLES_CORE}
    if opts.include_documents or opts.include_photos or opts.include_sheets:
        for k, *_ in _BUNDLE_TABLES_DOCUMENTS:
            keys.add(k)
    if opts.include_bim_models:
        keys.add("bim_models")
        if opts.include_bim_elements:
            keys.add("bim_elements")
    if opts.include_dwg_drawings:
        for k, *_ in _BUNDLE_TABLES_DWG:
            keys.add(k)
    return keys


# ── Row collection ────────────────────────────────────────────────────────


async def _rows_for_table(
    session: AsyncSession,
    project_id: str,
    key: str,
    module_path: str,
    class_name: str,
) -> list[dict[str, Any]]:
    """Pull rows for one table scoped to ``project_id``.

    The "projects" table itself is filtered by id; everything else by
    project_id; BIM elements are filtered by their model_id being in the
    project's set; assembly_components are filtered by their parent
    assembly's project; same for change_order_items / tender_bids /
    dwg_drawing_versions.
    """
    cls = _import_class(module_path, class_name)
    if cls is None:
        return []
    pid_col = getattr(cls, "project_id", None)

    if key == "projects":
        rows = (
            (
                await session.execute(
                    select(cls).where(cls.id == project_id),
                )
            )
            .scalars()
            .all()
        )
    elif key == "bim_elements":
        BIMModel = _import_class("app.modules.bim_hub.models", "BIMModel")
        if BIMModel is None:
            return []
        model_ids = (
            (
                await session.execute(
                    select(BIMModel.id).where(BIMModel.project_id == project_id),
                )
            )
            .scalars()
            .all()
        )
        if not model_ids:
            return []
        rows = (
            (
                await session.execute(
                    select(cls).where(cls.model_id.in_(model_ids)),
                )
            )
            .scalars()
            .all()
        )
    elif key == "assembly_components":
        Assembly = _import_class("app.modules.assemblies.models", "Assembly")
        if Assembly is None:
            return []
        assembly_ids = (
            (
                await session.execute(
                    select(Assembly.id).where(Assembly.project_id == project_id),
                )
            )
            .scalars()
            .all()
        )
        if not assembly_ids:
            return []
        rows = (
            (
                await session.execute(
                    select(cls).where(cls.assembly_id.in_(assembly_ids)),
                )
            )
            .scalars()
            .all()
        )
    elif key == "change_order_items":
        ChangeOrder = _import_class(
            "app.modules.changeorders.models",
            "ChangeOrder",
        )
        if ChangeOrder is None:
            return []
        co_ids = (
            (
                await session.execute(
                    select(ChangeOrder.id).where(
                        ChangeOrder.project_id == project_id,
                    ),
                )
            )
            .scalars()
            .all()
        )
        if not co_ids:
            return []
        rows = (
            (
                await session.execute(
                    select(cls).where(cls.change_order_id.in_(co_ids)),
                )
            )
            .scalars()
            .all()
        )
    elif key == "tender_bids":
        TenderPackage = _import_class(
            "app.modules.tendering.models",
            "TenderPackage",
        )
        if TenderPackage is None:
            return []
        pkg_ids = (
            (
                await session.execute(
                    select(TenderPackage.id).where(
                        TenderPackage.project_id == project_id,
                    ),
                )
            )
            .scalars()
            .all()
        )
        if not pkg_ids:
            return []
        rows = (
            (
                await session.execute(
                    select(cls).where(cls.package_id.in_(pkg_ids)),
                )
            )
            .scalars()
            .all()
        )
    elif key == "dwg_drawing_versions":
        DwgDrawing = _import_class(
            "app.modules.dwg_takeoff.models",
            "DwgDrawing",
        )
        if DwgDrawing is None:
            return []
        drw_ids = (
            (
                await session.execute(
                    select(DwgDrawing.id).where(
                        DwgDrawing.project_id == project_id,
                    ),
                )
            )
            .scalars()
            .all()
        )
        if not drw_ids:
            return []
        rows = (
            (
                await session.execute(
                    select(cls).where(cls.drawing_id.in_(drw_ids)),
                )
            )
            .scalars()
            .all()
        )
    elif key == "document_bim_links":
        Document = _import_class("app.modules.documents.models", "Document")
        if Document is None:
            return []
        doc_ids = (
            (
                await session.execute(
                    select(Document.id).where(Document.project_id == project_id),
                )
            )
            .scalars()
            .all()
        )
        if not doc_ids:
            return []
        rows = (
            (
                await session.execute(
                    select(cls).where(cls.document_id.in_(doc_ids)),
                )
            )
            .scalars()
            .all()
        )
    elif pid_col is not None:
        rows = (
            (
                await session.execute(
                    select(cls).where(cls.project_id == project_id),
                )
            )
            .scalars()
            .all()
        )
    else:
        return []

    return [serialize_row(r) for r in rows]


# ── Attachment collection ────────────────────────────────────────────────


def _sha256_of(path: str) -> tuple[str, int]:
    """Return (hex-digest, size) for ``path``; ('', 0) on failure."""
    h = hashlib.sha256()
    size = 0
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(64 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
        return h.hexdigest(), size
    except OSError:
        return "", 0


def _sha256_of_bytes(data: bytes) -> tuple[str, int]:
    """Return (hex-digest, size) for an in-memory blob."""
    return hashlib.sha256(data).hexdigest(), len(data)


# The packing helpers below are the CPU and disk half of the export: they run
# in a worker thread, one at a time, while the queries and storage reads stay
# on the event loop. A full-scope bundle hashes and deflates every document,
# photo, drawing and model of the project, and on the loop that froze every
# other request on the worker for as long as it took. The zip is only ever
# touched by one thread at a time because each call is awaited before the next.


def _write_table(zf: zipfile.ZipFile, key: str, rows: list[dict[str, Any]]) -> None:
    """Encode one table's rows as JSON and deflate them into the bundle."""
    zf.writestr(f"tables/{key}.json", json.dumps(rows, indent=2, ensure_ascii=False, default=str))


def _pack_file(zf: zipfile.ZipFile, origin: str, arc: str) -> tuple[str, int]:
    """Hash a file on disk and deflate it into the bundle.

    Returns ('', 0) without writing when the file cannot be read, which the
    caller records as a missing attachment.
    """
    digest, size = _sha256_of(origin)
    if size == 0 and not digest:
        return "", 0
    zf.write(origin, arc)
    return digest, size


def _pack_bytes(zf: zipfile.ZipFile, arc: str, data: bytes) -> tuple[str, int]:
    """Hash an in-memory blob and deflate it into the bundle."""
    digest, size = _sha256_of_bytes(data)
    zf.writestr(arc, data)
    return digest, size


# An attachment is described by ``(path_in_zip, source, origin)`` where
# ``source`` is either ``"fs"`` (``origin`` is an absolute filesystem path -
# legacy document/photo/sheet/dwg uploads) or ``"key"`` (``origin`` is a
# storage-backend key, e.g. ``bim/{p}/{m}/geometry.glb``). BIM geometry is
# recorded as a storage KEY, never a filesystem path: on any deployment where
# the process CWD differs from the data root - standalone / external-Postgres,
# Docker, macOS - resolving it with ``os.path`` against CWD fails, and it can
# never be a filesystem path at all under an S3 backend. Routing it through the
# storage backend is the only correct option for both local and S3.
_Attachment = tuple[str, str, str]


async def _collect_attachment_paths(
    session: AsyncSession,
    project_id: str,
    opts: ExportOptions,
) -> list[_Attachment]:
    """Return ``[(path_in_zip, source, origin), ...]`` for every binary that
    ``opts`` says should be in the bundle.

    ``source`` distinguishes a filesystem path (``"fs"``) from a storage-backend
    key (``"key"``); see :data:`_Attachment`. Missing binaries are silently
    skipped so a half-cleaned-up project still exports successfully - we'd
    rather lose a file than the whole bundle.
    """
    out: list[_Attachment] = []

    if opts.include_documents:
        Document = _import_class("app.modules.documents.models", "Document")
        if Document is not None:
            rows = (
                await session.execute(
                    select(Document.id, Document.file_path, Document.name).where(Document.project_id == project_id),
                )
            ).all()
            for doc_id, path, name in rows:
                if not path or not os.path.exists(path):
                    continue
                fname = name or Path(path).name
                out.append((f"attachments/documents/{doc_id}/{fname}", "fs", path))

    if opts.include_photos:
        ProjectPhoto = _import_class(
            "app.modules.documents.models",
            "ProjectPhoto",
        )
        if ProjectPhoto is not None:
            rows = (
                await session.execute(
                    select(
                        ProjectPhoto.id,
                        ProjectPhoto.file_path,
                        ProjectPhoto.thumbnail_path,
                        ProjectPhoto.filename,
                    ).where(ProjectPhoto.project_id == project_id),
                )
            ).all()
            for pid, path, thumb, fname in rows:
                if path and os.path.exists(path):
                    out.append((f"attachments/photos/{pid}/{fname}", "fs", path))
                if thumb and os.path.exists(thumb):
                    out.append(
                        (f"attachments/photos/thumbs/{pid}.jpg", "fs", thumb),
                    )

    if opts.include_sheets:
        Sheet = _import_class("app.modules.documents.models", "Sheet")
        if Sheet is not None:
            rows = (
                await session.execute(
                    select(Sheet.id, Sheet.thumbnail_path).where(Sheet.project_id == project_id),
                )
            ).all()
            for sid, thumb in rows:
                if thumb and os.path.exists(thumb):
                    out.append((f"attachments/sheets/thumbs/{sid}.png", "fs", thumb))

    if opts.include_bim_models and opts.include_bim_geometry:
        BIMModel = _import_class("app.modules.bim_hub.models", "BIMModel")
        if BIMModel is not None:
            rows = (
                await session.execute(
                    select(BIMModel.id, BIMModel.canonical_file_path).where(BIMModel.project_id == project_id),
                )
            ).all()
            for mid, canonical in rows:
                # ``canonical_file_path`` is a storage KEY (e.g.
                # ``bim/{p}/{m}/geometry.glb``), not a filesystem path. Record it
                # as such so the zip writer reads it through the storage backend
                # (the only path that works under an S3 backend or when CWD !=
                # data root). The original ``os.path.exists(canonical)`` probe
                # ran against CWD and dropped present geometry as "missing" on
                # every non-CWD deployment.
                if canonical:
                    fname = Path(canonical).name
                    out.append(
                        (f"attachments/bim/{mid}/{fname}", "key", canonical),
                    )

    if opts.include_dwg_drawings:
        DwgDrawing = _import_class(
            "app.modules.dwg_takeoff.models",
            "DwgDrawing",
        )
        if DwgDrawing is not None:
            rows = (
                await session.execute(
                    select(
                        DwgDrawing.id,
                        DwgDrawing.file_path,
                        DwgDrawing.filename,
                    ).where(DwgDrawing.project_id == project_id),
                )
            ).all()
            for did, path, fname in rows:
                if path and os.path.exists(path):
                    safe = fname or Path(path).name
                    out.append((f"attachments/dwg/{did}/{safe}", "fs", path))

    return out


async def _read_storage_key(key: str) -> bytes | None:
    """Return the bytes stored under a storage ``key``, or ``None`` if absent.

    Lazily resolves the active storage backend (local or S3) per call so
    ``OE_DATA_DIR`` / a test monkeypatch takes effect, mirroring how
    ``bim_hub`` resolves the data dir at call time rather than import time. The
    backend's own read fallback (``LocalStorageBackend._existing_path_for``)
    means a blob written under a prior data-dir resolution is still found.
    Path-traversal keys are rejected inside the backend (``_normalise_key``).
    """
    from app.core.storage import get_storage_backend

    backend = get_storage_backend()
    try:
        return await backend.get(key)
    except (FileNotFoundError, ValueError):
        # Absent blob, or a key that fails normalisation/containment - skip it
        # rather than abort the whole export.
        return None
    except Exception:  # pragma: no cover - defensive: never sink the bundle
        logger.warning("bundle export: failed reading storage key %r", key, exc_info=True)
        return None


# ── Public API ────────────────────────────────────────────────────────────


async def export_bundle(
    session: AsyncSession,
    project_id: str,
    project_name: str,
    project_currency: str | None,
    user_email: str | None,
    options: ExportOptions,
) -> bytes:
    """Build the .ocep zip for one project and return its bytes.

    For projects with multi-GB attachments callers should split scope -
    e.g. ship metadata_only over email, then bim separately.
    """
    opts = _options_from_scope(options)

    # 1. Collect every table.
    all_tables: list[tuple[str, str, str, bool]] = list(_BUNDLE_TABLES_CORE)
    if opts.include_documents or opts.include_photos or opts.include_sheets:
        all_tables += _BUNDLE_TABLES_DOCUMENTS
    if opts.include_bim_models:
        all_tables += [row for row in _BUNDLE_TABLES_BIM if row[0] != "bim_elements" or opts.include_bim_elements]
    if opts.include_dwg_drawings:
        all_tables += _BUNDLE_TABLES_DWG

    table_data: dict[str, list[dict[str, Any]]] = {}
    record_counts: dict[str, int] = {}
    for key, mod, cls, _opt in all_tables:
        rows = await _rows_for_table(session, project_id, key, mod, cls)
        if rows:
            table_data[key] = rows
        record_counts[key] = len(rows)

    # 2. Collect attachments (paths only - we hash + read inside the zip
    # writer so streaming-friendly memory profile).
    attachments = await _collect_attachment_paths(session, project_id, opts)

    # 3. Build the manifest.
    manifest = BundleManifest(
        exported_at=datetime.now(UTC),
        exported_by_email=user_email,
        project_id=str(project_id),
        project_name=project_name,
        project_currency=project_currency,
        scope=opts.scope,
        tables=sorted(table_data.keys()),
        record_counts=record_counts,
        attachment_count=len(attachments),
        attachment_total_bytes=0,  # filled in below as we read
        engine_version=ENGINE_VERSION,
    )

    # 4. Stream into a zip.
    buf = io.BytesIO()
    attachments_index: list[dict[str, Any]] = []
    total_bytes = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for key, rows in table_data.items():
            await asyncio.to_thread(_write_table, zf, key, rows)

        for arc, source, origin in attachments:
            if source == "key":
                # Storage-backed blob (BIM geometry): read the bytes through the
                # backend and write them into the zip directly - correct for both
                # the local backend (CWD-independent) and S3.
                data = await _read_storage_key(origin)
                if data is None:
                    attachments_index.append(
                        {
                            "path": arc,
                            "original_path": origin,
                            "size_bytes": 0,
                            "sha256": "",
                            "missing": True,
                        }
                    )
                    continue
                digest, size = await asyncio.to_thread(_pack_bytes, zf, arc, data)
                total_bytes += size
                attachments_index.append(
                    {
                        "path": arc,
                        "original_path": origin,
                        "size_bytes": size,
                        "sha256": digest,
                    }
                )
                continue

            digest, size = await asyncio.to_thread(_pack_file, zf, origin, arc)
            if size == 0 and not digest:
                # File vanished between scan and write; record the gap.
                attachments_index.append(
                    {
                        "path": arc,
                        "original_path": origin,
                        "size_bytes": 0,
                        "sha256": "",
                        "missing": True,
                    }
                )
                continue
            total_bytes += size
            attachments_index.append(
                {
                    "path": arc,
                    "original_path": origin,
                    "size_bytes": size,
                    "sha256": digest,
                }
            )

        manifest.attachment_total_bytes = total_bytes
        zf.writestr(
            "attachments/index.json",
            json.dumps(attachments_index, indent=2, ensure_ascii=False),
        )
        zf.writestr(
            "manifest.json",
            json.dumps(
                manifest.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            ),
        )
        zf.writestr(
            "README.md",
            _readme_md(manifest, len(attachments)),
        )
    return buf.getvalue()


async def preview_bundle(
    session: AsyncSession,
    project_id: str,
    options: ExportOptions,
) -> ExportPreview:
    """Cheap pre-flight: return table counts and attachment size estimate
    without actually packing the zip."""
    opts = _options_from_scope(options)

    all_tables: list[tuple[str, str, str, bool]] = list(_BUNDLE_TABLES_CORE)
    if opts.include_documents or opts.include_photos or opts.include_sheets:
        all_tables += _BUNDLE_TABLES_DOCUMENTS
    if opts.include_bim_models:
        all_tables += [row for row in _BUNDLE_TABLES_BIM if row[0] != "bim_elements" or opts.include_bim_elements]
    if opts.include_dwg_drawings:
        all_tables += _BUNDLE_TABLES_DWG

    counts: dict[str, int] = {}
    estimated_table_size = 0
    for key, mod, cls, _opt in all_tables:
        rows = await _rows_for_table(session, project_id, key, mod, cls)
        counts[key] = len(rows)
        # Quick row-size estimate - JSON tends to be ~120 bytes/row median;
        # we sample the first row to get a closer figure.
        if rows:
            sample = json.dumps(rows[0], default=str).encode("utf-8")
            estimated_table_size += len(sample) * len(rows)

    paths = await _collect_attachment_paths(session, project_id, opts)
    attachment_size = 0
    backend = None
    for _arc, source, origin in paths:
        if source == "key":
            # Probe the storage backend for the blob's size; this is a cheap
            # HEAD on S3 and a stat on the local backend. Resolve the backend
            # lazily and reuse it across rows.
            if backend is None:
                from app.core.storage import get_storage_backend

                backend = get_storage_backend()
            try:
                attachment_size += await backend.size(origin)
            except (FileNotFoundError, ValueError):
                continue
            continue
        try:
            attachment_size += os.path.getsize(origin)
        except OSError:
            continue

    return ExportPreview(
        scope=opts.scope,
        table_counts=counts,
        attachment_count=len(paths),
        estimated_size_bytes=estimated_table_size + attachment_size,
        bundle_format=BUNDLE_FORMAT,
        bundle_format_version=BUNDLE_FORMAT_VERSION,
    )


def _readme_md(manifest: BundleManifest, attachment_count: int) -> str:
    """Plain-text README packed inside the bundle for the recipient."""
    lines = [
        "# OpenConstructionERP Project Bundle",
        "",
        f"Project: **{manifest.project_name}**",
        f"Scope: **{manifest.scope}**",
        f"Exported: {manifest.exported_at.isoformat()}",
        f"Engine: {manifest.engine_name} v{manifest.engine_version}",
        "",
        f"This zip contains {sum(manifest.record_counts.values())} rows "
        f"across {len(manifest.tables)} tables and {attachment_count} attachment(s).",
        "",
        "## How to open",
        "",
        "1. Install OpenConstructionERP - `pip install openconstructionerp` or download from openconstructionerp.com.",
        "2. Run `openconstructionerp serve` and sign in.",
        "3. Use **Files → Import project bundle** and select this `.ocep` file.",
        "",
        "## Compatibility",
        "",
        f"Format version: {manifest.format_version} · Minimum app version: {manifest.compat_min_app_version}.",
    ]
    return "\n".join(lines)


def filename_for_bundle(project_name: str, scope: BundleScope) -> str:
    """Conventional filename: <slug>_<scope>_<YYYYMMDD>.ocep."""
    slug = "".join(c if c.isalnum() else "_" for c in project_name).strip("_") or "project"
    today = datetime.now(UTC).strftime("%Y%m%d")
    return f"{slug[:60]}_{scope}_{today}.ocep"


__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_FORMAT_VERSION",
    "export_bundle",
    "preview_bundle",
    "filename_for_bundle",
]


def _all_table_keys() -> Iterable[str]:  # convenience for tests
    yield from (k for k, *_ in _BUNDLE_TABLES_CORE)
    yield from (k for k, *_ in _BUNDLE_TABLES_DOCUMENTS)
    yield from (k for k, *_ in _BUNDLE_TABLES_BIM)
    yield from (k for k, *_ in _BUNDLE_TABLES_DWG)
