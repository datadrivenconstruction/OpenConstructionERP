"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the 8.6.1 dashboards-snapshot data-dir fallback fix.

Background
----------
The dashboard snapshot DuckDB local fast-path
(:func:`app.modules.dashboards.snapshot_storage.resolve_local_parquet_path`)
resolved the Parquet via ``LocalStorageBackend._path_for`` - the ACTIVE base
dir only, with NO fallback. So a snapshot whose Parquet was written under a
prior data-dir resolution (before ``OE_DATA_DIR`` was honoured, or under the
package-relative default a later ``pip install -U`` replaced) raised
``FileNotFoundError`` even though ``backend.get()`` would now find it via
:func:`app.core.storage.safe_data_roots`.

These tests pin the fix and are pure (no database, no app.config import). They
mirror ``tests/unit/test_bim_datadir_resolution.py``:

* a Parquet present only under a back-compat data root is still resolved;
* the active base is preferred when the Parquet lives there;
* a path-traversal key is rejected on the read path;
* a Parquet present nowhere raises ``FileNotFoundError``.
"""

from __future__ import annotations

import pytest

from app.core.storage import LocalStorageBackend
from app.modules.dashboards.snapshot_storage import (
    parquet_key,
    resolve_local_parquet_path,
)

_DATA_ENV_VARS = ("OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR")


def _clear_data_env(monkeypatch) -> None:
    for name in _DATA_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.asyncio
async def test_resolve_parquet_falls_back_to_backcompat_root(tmp_path, monkeypatch) -> None:
    """A Parquet present only under a back-compat data root is resolved.

    The backend's active base is an (empty) dir; the Parquet physically lives
    under ``legacy``, which is registered as a platform data root via
    ``OE_DATA_DIR`` so it appears in ``safe_data_roots()``.
    """
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OE_DATA_DIR", str(legacy))
    backend = LocalStorageBackend(active)

    pid, sid = "proj-1", "snap-abc"
    key = parquet_key(pid, sid, "entities")
    blob = legacy.joinpath(*key.split("/"))
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"PAR1-fallback")

    # Not under the active base, only under the back-compat root.
    assert not active.joinpath(*key.split("/")).exists()

    resolved = await resolve_local_parquet_path(pid, sid, "entities", backend=backend)
    assert resolved == str(blob.resolve())


@pytest.mark.asyncio
async def test_resolve_parquet_prefers_active_base(tmp_path, monkeypatch) -> None:
    """When the Parquet lives under the active base, that path is returned."""
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OE_DATA_DIR", str(legacy))
    backend = LocalStorageBackend(active)

    pid, sid = "proj-1", "snap-abc"
    key = parquet_key(pid, sid, "materials")
    active_blob = active.joinpath(*key.split("/"))
    active_blob.parent.mkdir(parents=True)
    active_blob.write_bytes(b"PAR1-active")
    # A stale copy under legacy must be ignored in favour of the active base.
    legacy_blob = legacy.joinpath(*key.split("/"))
    legacy_blob.parent.mkdir(parents=True)
    legacy_blob.write_bytes(b"PAR1-stale")

    resolved = await resolve_local_parquet_path(pid, sid, "materials", backend=backend)
    assert resolved == str(active_blob.resolve())


@pytest.mark.asyncio
async def test_resolve_parquet_missing_everywhere_raises(tmp_path, monkeypatch) -> None:
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "legacy"))
    backend = LocalStorageBackend(tmp_path / "active")
    with pytest.raises(FileNotFoundError):
        await resolve_local_parquet_path("p", "s", "entities", backend=backend)


@pytest.mark.asyncio
async def test_resolve_parquet_rejects_traversal(tmp_path) -> None:
    """A crafted project/snapshot id with ``..`` is rejected before any
    filesystem access (``_path_for`` -> ``_normalise_key`` raises)."""
    backend = LocalStorageBackend(tmp_path)
    with pytest.raises(ValueError):
        await resolve_local_parquet_path("..", "..", "entities", backend=backend)
