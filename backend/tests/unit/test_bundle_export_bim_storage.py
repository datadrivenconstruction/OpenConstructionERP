"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the 8.6.1 BIM data-dir fix as it touches project-bundle export.

Background
----------
``app.modules.projects.bundle_export`` collected BIM geometry by treating
``BIMModel.canonical_file_path`` as a filesystem path and probing it with
``os.path.exists`` / ``open`` relative to the process CWD. But that column holds
a storage KEY (``bim/{project}/{model}/geometry.glb``), not a filesystem path -
so on any deployment where CWD != data root (standalone / external-Postgres,
Docker, macOS) the geometry was recorded ``{"missing": true}`` and silently
dropped from the ``.ocep`` zip, and it could NEVER resolve under an S3 backend.

The fix reads BIM geometry through the storage backend (``backend.get(key)``)
and writes the bytes into the zip with ``zf.writestr``. These tests pin that
behaviour:

* a present geometry key is read CWD-independently (the actual bug),
* the bytes read through the backend are exactly what gets hashed,
* a truly-absent key resolves to ``None`` (recorded as missing, not crashing),
* a path-traversal key is rejected, not served.

The module is import-coupled to PostgreSQL (``app.database`` at import time), so
the import is guarded with ``importorskip`` - the test runs on CI (py3.11 with
embedded PG) and skips cleanly on a no-DB local box.
"""

from __future__ import annotations

import os

import pytest

bundle_export = pytest.importorskip(
    "app.modules.projects.bundle_export",
    reason="bundle_export imports app.database (PostgreSQL) at import time",
)

from app.core.storage import LocalStorageBackend  # noqa: E402

_DATA_ENV_VARS = ("OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR")


def _clear_data_env(monkeypatch) -> None:
    for name in _DATA_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _install_backend(monkeypatch, base_dir) -> LocalStorageBackend:
    """Point ``bundle_export``'s lazily-resolved storage backend at ``base_dir``."""
    backend = LocalStorageBackend(base_dir)
    import app.core.storage as storage_mod

    monkeypatch.setattr(storage_mod, "get_storage_backend", lambda: backend)
    return backend


@pytest.mark.asyncio
async def test_read_storage_key_returns_bytes_cwd_independent(tmp_path, monkeypatch) -> None:
    """A present BIM geometry key is read regardless of the process CWD.

    This is the regression: the old code ran ``os.path.exists(canonical)`` from
    CWD, so a deployment whose CWD differed from the data root dropped present
    geometry as "missing". Reading through the storage backend is CWD-agnostic.
    """
    _clear_data_env(monkeypatch)
    data_root = tmp_path / "data"
    _install_backend(monkeypatch, data_root)

    key = "bim/proj-1/model-abc/geometry.glb"
    payload = b"GLB\x00real-geometry-bytes"
    blob = data_root / "bim" / "proj-1" / "model-abc" / "geometry.glb"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(payload)

    # Run from an unrelated CWD - the bug only surfaced when CWD != data root.
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    prev = os.getcwd()
    os.chdir(other_cwd)
    try:
        assert not os.path.exists(key)  # the old os.path probe would have failed
        data = await bundle_export._read_storage_key(key)
    finally:
        os.chdir(prev)

    assert data == payload
    # The bytes hashed for the index come straight from the backend read.
    digest, size = bundle_export._sha256_of_bytes(data)
    import hashlib

    assert digest == hashlib.sha256(payload).hexdigest()
    assert size == len(payload)


@pytest.mark.asyncio
async def test_read_storage_key_absent_returns_none(tmp_path, monkeypatch) -> None:
    """A key with no blob anywhere resolves to ``None`` (recorded missing)."""
    _clear_data_env(monkeypatch)
    _install_backend(monkeypatch, tmp_path / "data")
    assert await bundle_export._read_storage_key("bim/none/none/geometry.glb") is None


@pytest.mark.asyncio
async def test_read_storage_key_rejects_traversal(tmp_path, monkeypatch) -> None:
    """A path-traversal key is rejected, never served, and does not crash export."""
    _clear_data_env(monkeypatch)
    _install_backend(monkeypatch, tmp_path / "data")
    assert await bundle_export._read_storage_key("bim/../../../etc/passwd") is None


@pytest.mark.asyncio
async def test_read_storage_key_honours_backcompat_root(tmp_path, monkeypatch) -> None:
    """A blob written under a prior data-dir resolution is still read.

    The active backend base is empty; the blob lives under a back-compat data
    root registered via ``OE_DATA_DIR`` - the local backend's read fallback
    (``_existing_path_for``) finds it, so the bundle includes geometry written
    before the operator started honouring ``OE_DATA_DIR``.
    """
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OE_DATA_DIR", str(legacy))
    _install_backend(monkeypatch, active)

    key = "bim/p/m/geometry.glb"
    payload = b"back-compat-glb"
    blob = legacy / "bim" / "p" / "m" / "geometry.glb"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(payload)

    assert not (active / "bim" / "p" / "m" / "geometry.glb").exists()
    assert await bundle_export._read_storage_key(key) == payload
