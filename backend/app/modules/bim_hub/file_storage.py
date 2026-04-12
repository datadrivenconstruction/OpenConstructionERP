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
# GLB is preferred: 8.8x faster browser loading than raw DAE.
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
) -> tuple[str, str] | None:
    """Return ``(key, ext)`` for the first geometry blob found, or ``None``.

    Geometry may have been uploaded as DAE / GLB / glTF.  We probe each
    candidate in priority order.
    """
    backend = _backend()
    for ext in GEOMETRY_EXTENSIONS:
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
