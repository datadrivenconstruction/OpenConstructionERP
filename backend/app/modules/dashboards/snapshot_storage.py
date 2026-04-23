"""Snapshot-file layout helpers.

Parquet blobs for each snapshot live under a deterministic key prefix on
the configured :class:`~app.core.storage.StorageBackend`:

    dashboards/<project_id>/<snapshot_id>/entities.parquet
    dashboards/<project_id>/<snapshot_id>/materials.parquet
    dashboards/<project_id>/<snapshot_id>/source_files.parquet
    dashboards/<project_id>/<snapshot_id>/attribute_value_index.parquet   # T03
    dashboards/<project_id>/<snapshot_id>/manifest.json

This module owns the *naming* of those keys, the *serialization* of
DataFrames to Parquet bytes, and a :func:`resolve_local_parquet_path`
helper that DuckDB needs to feed ``read_parquet(?)``.

DuckDB can read Parquet straight from S3 with the ``httpfs`` extension
enabled. The local backend path is kept as the fast-path for the
default deployment; the S3 path returns a presigned URL instead. Either
way :func:`resolve_local_parquet_path` returns a string DuckDB will
accept.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal
from uuid import UUID

from app.core.storage import LocalStorageBackend, StorageBackend, get_storage_backend

if TYPE_CHECKING:
    import pandas as pd  # noqa: F401  — only for type hints

logger = logging.getLogger(__name__)


# ── Constants ───────────────────────────────────────────────────────────────

SNAPSHOT_ROOT: Final = "dashboards"
"""Storage key prefix for every snapshot blob."""

ParquetKind = Literal[
    "entities",
    "materials",
    "source_files",
    "attribute_value_index",
]
"""The fixed set of Parquet files a snapshot can contain. Adding a new
kind requires updating this literal + the migration path in T01."""

MANIFEST_FILENAME: Final = "manifest.json"


# ── Key / path helpers ─────────────────────────────────────────────────────


def snapshot_prefix(project_id: str | UUID, snapshot_id: str | UUID) -> str:
    """Return the storage key prefix for a snapshot.

    The two ids are coerced to ``str`` so callers can pass UUID instances
    without boilerplate. Validation of the UUID format itself happens at
    the API boundary — here we only accept non-empty strings.
    """
    pid = str(project_id)
    sid = str(snapshot_id)
    if not pid or not sid:
        raise ValueError("project_id and snapshot_id must be non-empty")
    return f"{SNAPSHOT_ROOT}/{pid}/{sid}"


def parquet_key(project_id: str | UUID, snapshot_id: str | UUID, kind: ParquetKind) -> str:
    """Return the storage key for a specific Parquet file in a snapshot."""
    return f"{snapshot_prefix(project_id, snapshot_id)}/{kind}.parquet"


def manifest_key(project_id: str | UUID, snapshot_id: str | UUID) -> str:
    return f"{snapshot_prefix(project_id, snapshot_id)}/{MANIFEST_FILENAME}"


# ── Serialisation ──────────────────────────────────────────────────────────


def _dataframe_to_parquet_bytes(df: pd.DataFrame) -> bytes:
    """Serialise a DataFrame into a self-contained Parquet byte string.

    We go through ``pyarrow`` rather than ``df.to_parquet`` directly so
    the dependency on the ``fastparquet`` fallback engine (not in our
    base deps) never kicks in.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pandas(df, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


# ── High-level write helpers ───────────────────────────────────────────────


async def write_parquet(
    project_id: str | UUID,
    snapshot_id: str | UUID,
    kind: ParquetKind,
    df: pd.DataFrame,
    *,
    backend: StorageBackend | None = None,
) -> str:
    """Write a DataFrame to the snapshot's Parquet slot.

    Returns the storage key that was written (useful for logging and
    for tests that want to assert on the exact layout).
    """
    store = backend or get_storage_backend()
    payload = _dataframe_to_parquet_bytes(df)
    key = parquet_key(project_id, snapshot_id, kind)
    await store.put(key, payload)
    logger.debug(
        "dashboards.snapshot_storage.write_parquet kind=%s key=%s bytes=%d",
        kind, key, len(payload),
    )
    return key


async def write_manifest(
    project_id: str | UUID,
    snapshot_id: str | UUID,
    manifest: dict,
    *,
    backend: StorageBackend | None = None,
) -> str:
    store = backend or get_storage_backend()
    payload = json.dumps(manifest, indent=2, sort_keys=True, default=str).encode("utf-8")
    key = manifest_key(project_id, snapshot_id)
    await store.put(key, payload)
    return key


async def read_manifest(
    project_id: str | UUID,
    snapshot_id: str | UUID,
    *,
    backend: StorageBackend | None = None,
) -> dict:
    """Read the snapshot manifest back from storage.

    Raises :class:`FileNotFoundError` if the manifest does not exist.
    """
    store = backend or get_storage_backend()
    data = await store.get(manifest_key(project_id, snapshot_id))
    return json.loads(data.decode("utf-8"))


# ── DuckDB path resolution ─────────────────────────────────────────────────


class ParquetNotLocalError(RuntimeError):
    """Raised when a Parquet file can't be exposed as a local filesystem
    path and the DuckDB configuration lacks the fallback (httpfs
    extension for S3, presigned URL fetch, etc.).

    T00 deliberately does not wire S3-over-httpfs — the feature ships
    after local-filesystem snapshots work end-to-end. Callers catch this
    exception and return a structured 501 when the admin switched to S3
    without installing the DuckDB httpfs extension.
    """


async def resolve_local_parquet_path(
    project_id: str | UUID,
    snapshot_id: str | UUID,
    kind: ParquetKind,
    *,
    backend: StorageBackend | None = None,
) -> str:
    """Return a filesystem path (string) that DuckDB's ``read_parquet``
    can consume directly.

    For :class:`LocalStorageBackend` this is zero-copy: we compose the
    path via ``base_dir / key`` and return its string form. For S3 /
    other non-local backends this will eventually return a presigned
    URL and expect ``INSTALL httpfs`` at the DuckDB end — until that
    lands, non-local backends raise :class:`ParquetNotLocalError`.
    """
    store = backend or get_storage_backend()
    key = parquet_key(project_id, snapshot_id, kind)

    if isinstance(store, LocalStorageBackend):
        # Exact same resolution rules the backend uses internally, so
        # any key rejected by the backend is rejected identically here.
        path: Path = store._path_for(key)  # noqa: SLF001 — intentional reuse
        if not path.is_file():
            raise FileNotFoundError(f"No Parquet file at snapshot key: {key}")
        return str(path)

    raise ParquetNotLocalError(
        f"Storage backend {type(store).__name__} does not expose Parquet as a "
        "local path. S3 + DuckDB httpfs support is tracked for a follow-up; "
        "until then snapshots require STORAGE_BACKEND=local."
    )


# ── Deletion ───────────────────────────────────────────────────────────────


async def delete_snapshot_files(
    project_id: str | UUID,
    snapshot_id: str | UUID,
    *,
    backend: StorageBackend | None = None,
) -> int:
    """Delete every blob under a snapshot's prefix.

    Returns the number of blobs removed (per the
    :class:`StorageBackend.delete_prefix` contract). A missing prefix
    returns ``0`` rather than raising — the snapshot row in the DB is
    already the source of truth for existence.
    """
    store = backend or get_storage_backend()
    prefix = snapshot_prefix(project_id, snapshot_id)
    return await store.delete_prefix(prefix)
