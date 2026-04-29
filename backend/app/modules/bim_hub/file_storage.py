"""BIM Hub file-storage helper.

Thin wrapper around :mod:`app.core.storage` that owns the key layout
for BIM model blobs.  Lives in its own module so the refactor that
moves BIM file I/O off the local filesystem stays isolated from
``service.py`` / ``router.py`` — both of which are currently being
edited by another agent for the Element Groups feature.

Key layout
----------
::

    bim/{project_id}/{model_id}/geometry.glb   (preferred — 8.8x faster)
    bim/{project_id}/{model_id}/geometry.dae   (fallback for pre-v1.5 models)
    bim/{project_id}/{model_id}/original.{ext}

The storage backend is resolved via
:func:`app.core.storage.get_storage_backend`, so switching to S3 is
a single ``STORAGE_BACKEND=s3`` environment variable away.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Final

from app.core.storage import StorageBackend, get_storage_backend

logger = logging.getLogger(__name__)

_BIM_PREFIX: Final[str] = "bim"

# Geometry files the viewer can load (order = lookup priority).
# GLB is preferred: 2x smaller transfer, faster browser parsing.
# Node names are preserved via post-processing of the GLB JSON chunk
# after trimesh conversion (see ifc_processor._convert_dae_to_glb).
GEOMETRY_EXTENSIONS: Final[tuple[str, ...]] = (".glb", ".dae", ".gltf")

GEOMETRY_MEDIA_TYPES: Final[dict[str, str]] = {
    ".dae": "model/vnd.collada+xml",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
}


# ──────────────────────────────────────────────────────────────────────────
# Key helpers
# ──────────────────────────────────────────────────────────────────────────


def _stringify(value: uuid.UUID | str) -> str:
    return str(value)


def bim_model_prefix(project_id: uuid.UUID | str, model_id: uuid.UUID | str) -> str:
    """Return the storage prefix holding every blob for a given model."""
    return f"{_BIM_PREFIX}/{_stringify(project_id)}/{_stringify(model_id)}"


def geometry_key(
    project_id: uuid.UUID | str,
    model_id: uuid.UUID | str,
    ext: str,
) -> str:
    """Return the storage key for a geometry file with extension ``ext``.

    ``ext`` may be given with or without a leading dot.
    """
    clean_ext = ext if ext.startswith(".") else f".{ext}"
    return f"{bim_model_prefix(project_id, model_id)}/geometry{clean_ext}"


def original_cad_key(
    project_id: uuid.UUID | str,
    model_id: uuid.UUID | str,
    ext: str,
) -> str:
    """Return the storage key for the ``original.{ext}`` CAD upload."""
    clean_ext = ext if ext.startswith(".") else f".{ext}"
    return f"{bim_model_prefix(project_id, model_id)}/original{clean_ext}"


# ──────────────────────────────────────────────────────────────────────────
# Operations
# ──────────────────────────────────────────────────────────────────────────


def _backend() -> StorageBackend:
    return get_storage_backend()


async def save_geometry(
    project_id: uuid.UUID | str,
    model_id: uuid.UUID | str,
    ext: str,
    content: bytes,
) -> str:
    """Persist a geometry blob for a model and return the storage key."""
    key = geometry_key(project_id, model_id, ext)
    await _backend().put(key, content)
    logger.info("Saved BIM geometry to key=%s (%d bytes)", key, len(content))
    return key


async def save_original_cad(
    project_id: uuid.UUID | str,
    model_id: uuid.UUID | str,
    ext: str,
    content: bytes,
) -> str:
    """Persist an original CAD upload and return the storage key."""
    key = original_cad_key(project_id, model_id, ext)
    await _backend().put(key, content)
    logger.info("Saved original CAD to key=%s (%d bytes)", key, len(content))
    return key


async def find_geometry_key(
    project_id: uuid.UUID | str,
    model_id: uuid.UUID | str,
    prefer_ext: str | None = None,
) -> tuple[str, str] | None:
    """Return ``(key, ext)`` for the first geometry blob found, or ``None``.

    Geometry may have been uploaded as DAE / GLB / glTF.  We probe each
    candidate in priority order.

    When *prefer_ext* is set (e.g. ``".dae"``), that extension is tried
    first before falling back to the default priority order.  This lets
    the frontend force DAE when the GLB has scrambled node names.
    """
    backend = _backend()
    exts = list(GEOMETRY_EXTENSIONS)
    if prefer_ext and prefer_ext in exts:
        exts.remove(prefer_ext)
        exts.insert(0, prefer_ext)
    for ext in exts:
        key = geometry_key(project_id, model_id, ext)
        if await backend.exists(key):
            return key, ext
    return None


def open_geometry_stream(key: str) -> AsyncIterator[bytes]:
    """Return an async iterator streaming a geometry blob.

    Not ``async`` — the underlying ``open_stream`` is itself an async
    generator, so we just hand its iterator back to the caller.
    """
    return _backend().open_stream(key)


def presigned_geometry_url(key: str, *, expires_in: int = 3600) -> str | None:
    """Return a presigned URL for the blob (S3 only).

    ``None`` means the backend cannot presign — the caller should
    stream via :func:`open_geometry_stream` instead.
    """
    return _backend().url_for(key, expires_in=expires_in)


async def delete_model_blobs(
    project_id: uuid.UUID | str,
    model_id: uuid.UUID | str,
) -> int:
    """Delete every blob belonging to a model.  Returns count removed."""
    prefix = bim_model_prefix(project_id, model_id)
    try:
        removed = await _backend().delete_prefix(prefix)
    except Exception as exc:  # noqa: BLE001 - blob cleanup must not block delete
        logger.warning("Failed to delete BIM blobs at prefix=%s: %s", prefix, exc)
        return 0
    if removed:
        logger.info("Removed %d BIM blob(s) at prefix=%s", removed, prefix)
    return removed


# ──────────────────────────────────────────────────────────────────────────
# Persistence-policy helpers (v2.6.29)
# ──────────────────────────────────────────────────────────────────────────


# Extensions of files we treat as "conversion artifacts" — these are kept
# forever so the /bim page can serve them instantly without re-conversion.
_ARTIFACT_EXTENSIONS: Final[tuple[str, ...]] = (
    ".glb",
    ".dae",
    ".gltf",
    ".json",
    ".parquet",
    ".png",
    ".jpg",
    ".pdf",
)


async def delete_original_cad(
    project_id: uuid.UUID | str,
    model_id: uuid.UUID | str,
    ext: str,
) -> bool:
    """Delete the raw uploaded ``original.{ext}`` blob.

    Returns ``True`` if a blob existed and was removed, ``False`` if no
    blob was present.  Errors are swallowed and logged — the storage
    cleanup must never block conversion success.

    Used by the post-conversion success path when
    ``settings.keep_original_cad`` is False (production default).
    """
    backend = _backend()
    key = original_cad_key(project_id, model_id, ext)
    try:
        if not await backend.exists(key):
            return False
        await backend.delete(key)
        logger.info("Deleted original CAD blob key=%s (storage policy)", key)
        return True
    except Exception as exc:  # noqa: BLE001 - never block conversion success
        logger.warning("Failed to delete original CAD blob key=%s: %s", key, exc)
        return False


async def has_original_cad(
    project_id: uuid.UUID | str,
    model_id: uuid.UUID | str,
    ext: str,
) -> bool:
    """Return True iff the raw upload is still on storage."""
    if not ext:
        return False
    backend = _backend()
    key = original_cad_key(project_id, model_id, ext)
    try:
        return await backend.exists(key)
    except Exception:  # noqa: BLE001 - probing the backend must never raise
        logger.exception("has_original_cad probe failed for key=%s", key)
        return False


async def compute_artifact_size_bytes(
    project_id: uuid.UUID | str,
    model_id: uuid.UUID | str,
) -> int:
    """Return total bytes of conversion artifacts for a single model.

    For the local backend this walks the model directory on disk
    (excluding ``original.*``).  For S3 this would be a ``list_objects_v2``
    sweep — we fall back to counting the geometry-key candidates only,
    which keeps the call cheap for the common case (single GLB).
    """
    backend = _backend()
    prefix = bim_model_prefix(project_id, model_id)

    # Fast path — local backend has a base_dir we can walk directly.
    base_dir = getattr(backend, "base_dir", None)
    if base_dir is not None:
        from pathlib import Path  # local import: avoids broadening top-of-module deps

        root = Path(str(base_dir))
        for part in prefix.split("/"):
            root = root / part
        if not root.is_dir():
            return 0
        total = 0
        for child in root.rglob("*"):
            if not child.is_file():
                continue
            # Exclude raw uploads; everything else is treated as an artifact.
            if child.name.lower().startswith("original."):
                continue
            try:
                total += child.stat().st_size
            except OSError:
                continue
        return total

    # Fallback (S3 etc.) — probe the well-known geometry keys.
    total = 0
    for ext in _ARTIFACT_EXTENSIONS:
        if ext not in GEOMETRY_EXTENSIONS:
            continue
        key = geometry_key(project_id, model_id, ext)
        try:
            if await backend.exists(key):
                total += await backend.size(key)
        except Exception:  # noqa: BLE001 - best-effort sizing
            continue
    return total


def bim_root_label() -> str:
    """Return a short human-readable label for where BIM blobs live.

    The header chip on the BIM page surfaces this so users can see at a
    glance whether the instance is on local disk or pushing to S3.
    """
    backend = _backend()
    base_dir = getattr(backend, "base_dir", None)
    if base_dir is not None:
        # Trim to the conventional "data/bim/" suffix to keep the chip short.
        return "data/bim/"
    bucket = getattr(backend, "_bucket", None)
    if bucket:
        return f"s3://{bucket}/{_BIM_PREFIX}/"
    return f"{_BIM_PREFIX}/"
