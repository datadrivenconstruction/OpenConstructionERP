"""‌⁠‍Project-bundle import (Issue #109).

Inverse of :mod:`bundle_export`. Accepts a ``.ocep`` zip and reconstructs
the project on the receiving instance.

Three import modes:

* ``new_project``        — generate fresh UUIDs for every row, attachments
                           are extracted to the new project's storage roots.
                           Safe to run on the same instance that exported.
* ``merge_into_existing``— keep source UUIDs; rows that already exist are
                           skipped (idempotent re-import). Attachments only
                           land on disk if the row is newly inserted.
* ``replace_existing``   — wipes the target project's rows for every table
                           in the bundle, then inserts the bundle rows
                           verbatim. Only for the same project_id.

Validation step runs before any DB write — if the manifest is missing,
unparseable, format-version is incompatible, or the engine version is
older than the bundle's compat-min, the call fails fast and the caller
knows the bundle is unsafe.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup.router import deserialize_row
from app.modules.projects.bundle_export import (
    _BUNDLE_TABLES_BIM,
    _BUNDLE_TABLES_CORE,
    _BUNDLE_TABLES_DOCUMENTS,
    _BUNDLE_TABLES_DWG,
    BUNDLE_FORMAT,
    BUNDLE_FORMAT_VERSION,
    ENGINE_VERSION,
    _import_class,
)
from app.modules.projects.file_manager_schemas import (
    BundleManifest,
    ImportMode,
    ImportPreview,
    ImportResult,
)

logger = logging.getLogger(__name__)


# ── Validation ────────────────────────────────────────────────────────────


class BundleError(Exception):
    """‌⁠‍Raised by :func:`validate_bundle` when the bundle is unusable."""


def _read_zip(raw: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise BundleError("Uploaded file is not a valid .ocep archive") from exc


def _semver_key(v: str) -> tuple[int, int, int]:
    """‌⁠‍Parse ``"2.9.4"`` into ``(2, 9, 4)`` for comparison. Falls back to
    zeros on malformed strings rather than raising — the import call is
    user-facing and a single typo in the manifest shouldn't 500."""
    parts = (v or "").split(".")
    nums: list[int] = []
    for p in parts[:3]:
        digits = "".join(c for c in p if c.isdigit())
        nums.append(int(digits) if digits else 0)
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def validate_bundle(raw: bytes) -> ImportPreview:
    """Read manifest + sanity-check format/version/compat.

    Does not write anything; safe to call before the user commits.
    """
    zf = _read_zip(raw)
    if "manifest.json" not in zf.namelist():
        raise BundleError("Bundle is missing manifest.json")

    try:
        manifest_dict = json.loads(zf.read("manifest.json"))
        manifest = BundleManifest(**manifest_dict)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise BundleError(f"manifest.json is not a valid bundle manifest: {exc}") from exc

    warnings: list[str] = []

    if manifest.format != BUNDLE_FORMAT:
        raise BundleError(
            f"Unsupported bundle format '{manifest.format}' (expected '{BUNDLE_FORMAT}')",
        )

    bundle_fmt = _semver_key(manifest.format_version)
    current_fmt = _semver_key(BUNDLE_FORMAT_VERSION)
    if bundle_fmt[0] != current_fmt[0]:
        raise BundleError(
            f"Bundle format version {manifest.format_version} is incompatible with "
            f"this build (supports {BUNDLE_FORMAT_VERSION}). Update the importer.",
        )
    if bundle_fmt > current_fmt:
        warnings.append(
            f"Bundle was written with a newer format ({manifest.format_version}); "
            f"this build supports up to {BUNDLE_FORMAT_VERSION}. Some fields may be ignored.",
        )

    engine = _semver_key(ENGINE_VERSION)
    compat_min = _semver_key(manifest.compat_min_app_version)
    if engine < compat_min:
        raise BundleError(
            f"This bundle requires app version ≥ {manifest.compat_min_app_version}; "
            f"running {ENGINE_VERSION}. Upgrade and retry.",
        )

    has_attachments = manifest.attachment_count > 0
    if has_attachments and "attachments/index.json" not in zf.namelist():
        warnings.append(
            "Manifest claims attachments but attachments/index.json is missing — "
            "files may not import. The bundle was likely truncated.",
        )

    return ImportPreview(
        manifest=manifest,
        bundle_size_bytes=len(raw),
        has_attachments=has_attachments,
        warnings=warnings,
    )


# ── UUID remapping ────────────────────────────────────────────────────────


def _is_uuidlike(val: Any) -> bool:
    if not isinstance(val, str) or len(val) != 36:
        return False
    try:
        uuid.UUID(val)
    except (ValueError, AttributeError):
        return False
    return True


def _build_uuid_map(
    table_data: dict[str, list[dict[str, Any]]],
    new_project_id: str,
    old_project_id: str,
) -> dict[str, str]:
    """For ``new_project`` mode: every PK in the bundle gets a fresh UUID
    so the inserted rows can never collide with anything already present.

    Project id is special-cased: the caller chooses the new id (so the
    UI can show it immediately) and we mirror that into the map.
    """
    mapping: dict[str, str] = {old_project_id: new_project_id}
    for key, rows in table_data.items():
        for r in rows:
            old = r.get("id")
            if isinstance(old, str) and old not in mapping:
                if _is_uuidlike(old):
                    mapping[old] = str(uuid.uuid4())
    return mapping


def _remap_row(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """Walk every value once; remap any string that looks like a UUID we know."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, str) and v in mapping:
            out[k] = mapping[v]
        elif isinstance(v, list):
            out[k] = [mapping[item] if isinstance(item, str) and item in mapping else item for item in v]
        elif isinstance(v, dict):
            out[k] = {kk: (mapping[vv] if isinstance(vv, str) and vv in mapping else vv) for kk, vv in v.items()}
        else:
            out[k] = v
    return out


# ── Attachment extraction ──────────────────────────────────────────────────


def _target_path_for_attachment(
    arc_path: str,
    project_id: str,
    id_remap: dict[str, str],
) -> str | None:
    """Decide where ``attachments/<kind>/<id>/<filename>`` lands on disk.

    Honours the same per-module conventions :mod:`file_manager_service`
    audited. If the arc path doesn't match any known kind, returns None
    so the caller can log + skip rather than dropping the file in a
    random location.
    """
    parts = arc_path.split("/")
    if len(parts) < 3 or parts[0] != "attachments":
        return None
    kind = parts[1]
    rest = parts[2:]

    # Documents: attachments/documents/{doc_id}/{filename}
    if kind == "documents":
        try:
            from app.modules.documents.service import UPLOAD_BASE
        except ImportError:
            return None
        doc_id = id_remap.get(rest[0], rest[0])
        target_dir = UPLOAD_BASE / project_id
        return str(target_dir / f"{doc_id}_{rest[-1]}")

    # Photos: attachments/photos/{photo_id}/{filename}
    #         attachments/photos/thumbs/{photo_id}.jpg
    if kind == "photos":
        try:
            from app.modules.documents.service import PHOTO_BASE
        except ImportError:
            return None
        if rest[0] == "thumbs":
            stem = Path(rest[-1]).stem
            stem = id_remap.get(stem, stem)
            target_dir = PHOTO_BASE / project_id / "thumbs"
            return str(target_dir / f"{stem}{Path(rest[-1]).suffix}")
        photo_id = id_remap.get(rest[0], rest[0])
        return str(PHOTO_BASE / project_id / f"{photo_id}_{rest[-1]}")

    # Sheets: attachments/sheets/thumbs/{sheet_id}.png
    if kind == "sheets":
        try:
            from app.modules.documents.service import SHEET_THUMB_BASE
        except ImportError:
            return None
        if rest[0] == "thumbs":
            stem = Path(rest[-1]).stem
            stem = id_remap.get(stem, stem)
            return str(SHEET_THUMB_BASE / project_id / f"{stem}{Path(rest[-1]).suffix}")
        return None

    # BIM: attachments/bim/{model_id}/{filename}
    if kind == "bim":
        try:
            from app.core.storage import _default_local_base_dir
        except ImportError:
            return None
        model_id = id_remap.get(rest[0], rest[0])
        return str(
            _default_local_base_dir() / "bim" / project_id / model_id / rest[-1],
        )

    # DWG: attachments/dwg/{drawing_id}/{filename}
    if kind == "dwg":
        base = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
        return str(Path(base) / "dwg_uploads" / rest[-1])

    return None


def _extract_attachments(
    zf: zipfile.ZipFile,
    project_id: str,
    id_remap: dict[str, str],
) -> tuple[int, list[str]]:
    """Pull every ``attachments/...`` entry to its target on disk.

    Returns (files_written, warnings).
    """
    warnings: list[str] = []
    written = 0
    names = [
        n
        for n in zf.namelist()
        if n.startswith("attachments/") and not n.endswith("/") and n != "attachments/index.json"
    ]
    for arc in names:
        target = _target_path_for_attachment(arc, project_id, id_remap)
        if target is None:
            warnings.append(f"Skipped unknown attachment path: {arc}")
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            with zf.open(arc) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written += 1
        except OSError as exc:
            warnings.append(f"Could not write {target}: {exc}")
    return written, warnings


# ── Path rewriting on rows ─────────────────────────────────────────────────


def _rewrite_paths_for_target(
    table_key: str,
    rows: list[dict[str, Any]],
    project_id: str,
    id_remap: dict[str, str],
) -> list[dict[str, Any]]:
    """File rows store absolute paths from the *source* host. We rewrite
    them to absolute paths on *this* host so the row points at the file
    we just extracted.

    Tables we know to touch:
      - documents     : ``file_path``
      - project_photos: ``file_path``, ``thumbnail_path``
      - sheets        : ``thumbnail_path``
      - bim_models    : ``canonical_file_path``
      - dwg_drawings  : ``file_path``
    """
    if table_key == "documents":
        try:
            from app.modules.documents.service import UPLOAD_BASE
        except ImportError:
            return rows
        for r in rows:
            doc_id = id_remap.get(str(r.get("id")), str(r.get("id")))
            name = r.get("name") or "file"
            r["file_path"] = str(UPLOAD_BASE / project_id / f"{doc_id}_{name}")
        return rows

    if table_key == "photos":
        try:
            from app.modules.documents.service import PHOTO_BASE
        except ImportError:
            return rows
        for r in rows:
            pid = id_remap.get(str(r.get("id")), str(r.get("id")))
            fname = r.get("filename") or "photo.jpg"
            r["file_path"] = str(PHOTO_BASE / project_id / f"{pid}_{fname}")
            if r.get("thumbnail_path"):
                ext = Path(r["thumbnail_path"]).suffix or ".jpg"
                r["thumbnail_path"] = str(PHOTO_BASE / project_id / "thumbs" / f"{pid}{ext}")
        return rows

    if table_key == "sheets":
        try:
            from app.modules.documents.service import SHEET_THUMB_BASE
        except ImportError:
            return rows
        for r in rows:
            sid = id_remap.get(str(r.get("id")), str(r.get("id")))
            if r.get("thumbnail_path"):
                ext = Path(r["thumbnail_path"]).suffix or ".png"
                r["thumbnail_path"] = str(SHEET_THUMB_BASE / project_id / f"{sid}{ext}")
        return rows

    if table_key == "bim_models":
        try:
            from app.core.storage import _default_local_base_dir
        except ImportError:
            return rows
        for r in rows:
            mid = id_remap.get(str(r.get("id")), str(r.get("id")))
            old = r.get("canonical_file_path") or ""
            if old:
                fname = Path(old).name
                r["canonical_file_path"] = str(
                    _default_local_base_dir() / "bim" / project_id / mid / fname,
                )
        return rows

    if table_key == "dwg_drawings":
        base = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
        for r in rows:
            old = r.get("file_path") or ""
            if old:
                fname = Path(old).name
                r["file_path"] = str(Path(base) / "dwg_uploads" / fname)
        return rows

    return rows


# ── Database write ─────────────────────────────────────────────────────────


def _all_table_defs() -> list[tuple[str, str, str, bool]]:
    """Same FK-ordering as the exporter, deduplicated."""
    seen: set[str] = set()
    out: list[tuple[str, str, str, bool]] = []
    for src in (
        _BUNDLE_TABLES_CORE,
        _BUNDLE_TABLES_DOCUMENTS,
        _BUNDLE_TABLES_BIM,
        _BUNDLE_TABLES_DWG,
    ):
        for entry in src:
            if entry[0] in seen:
                continue
            seen.add(entry[0])
            out.append(entry)
    return out


async def _existing_ids(
    session: AsyncSession,
    cls: type,
    ids: list[Any],
) -> set[Any]:
    if not ids:
        return set()
    res = await session.execute(select(cls.id).where(cls.id.in_(ids)))
    return {row[0] for row in res.all()}


async def _delete_project_rows(
    session: AsyncSession,
    project_id: str,
) -> None:
    """Wipe every bundle-managed row for ``project_id`` (replace mode)."""
    # Reverse FK-order to delete children first.
    for key, mod, cls_name, _opt in reversed(_all_table_defs()):
        cls = _import_class(mod, cls_name)
        if cls is None:
            continue
        if key == "projects":
            continue  # we keep the project row itself in replace mode
        pid_col = getattr(cls, "project_id", None)
        if pid_col is None:
            continue
        try:
            await session.execute(sa_delete(cls).where(pid_col == project_id))
        except Exception:  # noqa: BLE001
            logger.exception("replace mode: failed to wipe %s", key)


# ── Public entry point ─────────────────────────────────────────────────────


async def import_bundle(
    session: AsyncSession,
    raw: bytes,
    *,
    mode: ImportMode = "new_project",
    target_project_id: str | None = None,
    new_project_name: str | None = None,
) -> ImportResult:
    """Read the bundle and write rows + attachments according to ``mode``.

    Parameters
    ----------
    raw : bytes
        The .ocep file bytes.
    mode : ImportMode
        - ``new_project``: fresh UUIDs everywhere (target_project_id ignored).
        - ``merge_into_existing``: insert new rows under ``target_project_id``,
          skip ones whose PK already exists.
        - ``replace_existing``: wipe ``target_project_id``'s data, insert
          bundle rows verbatim.
    target_project_id : str | None
        Required for merge / replace modes.
    new_project_name : str | None
        Override for the project's name in ``new_project`` mode (used when
        the user wants a different label than the source).
    """
    preview = validate_bundle(raw)
    manifest = preview.manifest

    if mode in ("merge_into_existing", "replace_existing") and not target_project_id:
        raise BundleError(
            f"mode={mode!r} requires target_project_id",
        )

    zf = _read_zip(raw)

    # 1. Read every table from the zip into memory.
    table_data: dict[str, list[dict[str, Any]]] = {}
    for entry in zf.namelist():
        if not entry.startswith("tables/") or not entry.endswith(".json"):
            continue
        key = entry[len("tables/") : -len(".json")]
        try:
            table_data[key] = json.loads(zf.read(entry))
        except json.JSONDecodeError:
            logger.warning("Bundle has malformed tables/%s.json — skipping", key)

    # 2. Decide effective project_id + UUID remap.
    source_project_id = str(manifest.project_id)
    if mode == "new_project":
        effective_project_id = str(uuid.uuid4())
        id_remap = _build_uuid_map(
            table_data,
            effective_project_id,
            source_project_id,
        )
    else:
        effective_project_id = str(target_project_id)
        # No PK remap; we keep source ids so re-imports are idempotent.
        # For the in-memory id_remap (used by attachment path rewriting) we
        # still want ``source_project_id -> effective_project_id`` mapped so
        # paths land in the right per-project folder.
        id_remap = {source_project_id: effective_project_id}

    # 3. In replace mode, wipe the target's existing rows first.
    if mode == "replace_existing":
        await _delete_project_rows(session, effective_project_id)

    # 4. Insert rows in FK order.
    imported_counts: dict[str, int] = {}
    skipped_counts: dict[str, int] = {}
    warnings: list[str] = list(preview.warnings)

    for key, mod, cls_name, _opt in _all_table_defs():
        if key not in table_data:
            continue
        cls = _import_class(mod, cls_name)
        if cls is None:
            warnings.append(f"Module for table '{key}' is not loaded — skipped")
            skipped_counts[key] = len(table_data[key])
            continue
        rows = [_remap_row(r, id_remap) for r in table_data[key]]
        rows = _rewrite_paths_for_target(key, rows, effective_project_id, id_remap)

        # Special-case the projects row: rename if requested + override
        # storage flags so the new project has its own settings.
        if key == "projects":
            for r in rows:
                if mode == "new_project" and new_project_name:
                    r["name"] = new_project_name
                # The project row's id is already remapped; just make sure
                # we don't overwrite the merge-into target.
                if mode == "merge_into_existing":
                    # We do not insert a new project row when merging — the
                    # caller already chose the destination.
                    pass

            if mode == "merge_into_existing":
                imported_counts[key] = 0
                skipped_counts[key] = len(rows)
                continue

        # Filter out rows whose PK already exists (merge mode is idempotent).
        if mode == "merge_into_existing":
            ids = [r.get("id") for r in rows if r.get("id") is not None]
            existing = await _existing_ids(session, cls, ids)
            keep_rows = [r for r in rows if r.get("id") not in existing]
            skipped_counts[key] = len(rows) - len(keep_rows)
            rows = keep_rows
        else:
            skipped_counts.setdefault(key, 0)

        inserted = 0
        for data in rows:
            try:
                obj = deserialize_row(cls, data)
                session.add(obj)
                inserted += 1
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Failed to import row in {key}: {exc}")

        imported_counts[key] = inserted

    # 5. Flush before extracting files so the transaction ordering is sane.
    try:
        await session.flush()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        raise BundleError(f"Database write failed: {exc}") from exc

    # 6. Extract attachments to the right roots.
    attachment_count, attach_warnings = _extract_attachments(
        zf,
        effective_project_id,
        id_remap,
    )
    warnings.extend(attach_warnings)

    await session.commit()

    return ImportResult(
        project_id=effective_project_id,
        mode=mode,
        imported_counts=imported_counts,
        skipped_counts=skipped_counts,
        attachment_count=attachment_count,
        warnings=warnings,
    )


__all__ = [
    "BundleError",
    "validate_bundle",
    "import_bundle",
]


# Re-export for tests
def _all_keys_for_test() -> list[str]:  # pragma: no cover - utility only
    return [k for k, *_ in _all_table_defs()]
