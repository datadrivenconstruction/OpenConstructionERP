"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the 8.6.1 BIM data-dir fix - back-compat-root LISTING gap.

Background
----------
The first cut of the fix gave READS a back-compat fallback
(:meth:`LocalStorageBackend._existing_path_for` walks
:func:`app.core.storage.safe_data_roots`), but the BULK listing primitive
(:meth:`LocalStorageBackend.list_prefix`) still walked only the active
``base_dir``. So:

* :func:`find_geometry_key`'s case-insensitive rescue (which lists the model
  prefix to match ``geometry.<ext>`` ignoring case) never consulted the
  back-compat roots the exact-case ``exists()`` probe already covered - an
  uppercase ``geometry.GLB`` stranded under a pre-8.6.1 default root was
  ready-in-DB but 404'd.
* :func:`compute_artifact_size_bytes` / :func:`bulk_model_storage_summary`
  under-reported size/geometry for blobs under a back-compat root.

These pure tests (no database, no app.config import) pin the opt-in
``list_prefix(include_backcompat_roots=True)`` multi-root read mode and its use
by the BIM helpers. They mirror ``test_bim_datadir_resolution.py``.
"""

from __future__ import annotations

import pytest

from app.core.storage import LocalStorageBackend
from app.modules.bim_hub import file_storage

_DATA_ENV_VARS = ("OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR")


def _clear_data_env(monkeypatch) -> None:
    for name in _DATA_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ──────────────────────────────────────────────────────────────────────────
# list_prefix multi-root read mode
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_prefix_active_root_only_by_default(tmp_path, monkeypatch) -> None:
    """Without the opt-in flag, only the active base_dir is walked."""
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OE_DATA_DIR", str(legacy))
    backend = LocalStorageBackend(active)

    blob = legacy / "bim" / "p" / "m" / "geometry.glb"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"legacy")

    assert await backend.list_prefix("bim/p/m") == []


@pytest.mark.asyncio
async def test_list_prefix_includes_backcompat_root_when_opted_in(tmp_path, monkeypatch) -> None:
    """With the flag, a blob only under a back-compat root is listed."""
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OE_DATA_DIR", str(legacy))
    backend = LocalStorageBackend(active)

    blob = legacy / "bim" / "p" / "m" / "geometry.GLB"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"UPPER")

    entries = await backend.list_prefix("bim/p/m", include_backcompat_roots=True)
    assert ("bim/p/m/geometry.GLB", len(b"UPPER")) in entries


@pytest.mark.asyncio
async def test_list_prefix_active_root_wins_dedup(tmp_path, monkeypatch) -> None:
    """The same key under both roots resolves to the active root's size."""
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OE_DATA_DIR", str(legacy))
    backend = LocalStorageBackend(active)

    key_rel = ("bim", "p", "m", "geometry.glb")
    a = active.joinpath(*key_rel)
    a.parent.mkdir(parents=True)
    a.write_bytes(b"active-bytes-longer")
    legacy_blob = legacy.joinpath(*key_rel)
    legacy_blob.parent.mkdir(parents=True)
    legacy_blob.write_bytes(b"short")

    entries = dict(await backend.list_prefix("bim/p/m", include_backcompat_roots=True))
    assert entries["bim/p/m/geometry.glb"] == len(b"active-bytes-longer")


@pytest.mark.asyncio
async def test_list_prefix_rejects_traversal(tmp_path) -> None:
    backend = LocalStorageBackend(tmp_path)
    with pytest.raises(ValueError):
        await backend.list_prefix("bim/../../../etc", include_backcompat_roots=True)


# ──────────────────────────────────────────────────────────────────────────
# find_geometry_key rescue spans back-compat roots
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_geometry_key_uppercase_under_backcompat_root(tmp_path, monkeypatch) -> None:
    """An uppercase ``geometry.GLB`` stranded under a back-compat root is found.

    This is the reporter's standalone/Docker/macOS case: the exact lowercase
    probes miss (different case) and the active base_dir is empty, but the blob
    physically lives under a pre-8.6.1 default root.
    """
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OE_DATA_DIR", str(legacy))
    backend = LocalStorageBackend(active)
    monkeypatch.setattr(file_storage, "_backend", lambda: backend)

    payload = b"UPPER-CASE-GLB"
    blob = legacy / "bim" / "p" / "m" / "geometry.GLB"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(payload)

    result = await file_storage.find_geometry_key("p", "m")
    assert result is not None
    key, ext = result
    assert ext == ".glb"
    # The returned key resolves to the stranded blob (READ falls back across
    # back-compat roots). On a case-sensitive FS the exact probes miss and the
    # list_prefix rescue returns the REAL upper-case key; on a case-insensitive
    # FS the exact lowercase probe already resolves to the file. Either way the
    # bytes must be served - which is the actual ready-but-404 guarantee.
    assert await backend.get(key) == payload


# ──────────────────────────────────────────────────────────────────────────
# size / bulk summary count back-compat-root blobs
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compute_artifact_size_counts_backcompat_root(tmp_path, monkeypatch) -> None:
    """Artifact size includes a geometry blob living only under a back-compat root."""
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OE_DATA_DIR", str(legacy))
    backend = LocalStorageBackend(active)
    monkeypatch.setattr(file_storage, "_backend", lambda: backend)

    model_dir = legacy / "bim" / "p" / "m"
    model_dir.mkdir(parents=True)
    (model_dir / "geometry.glb").write_bytes(b"x" * 100)
    (model_dir / "original.ifc").write_bytes(b"y" * 50)  # excluded

    total = await file_storage.compute_artifact_size_bytes("p", "m")
    assert total == 100


@pytest.mark.asyncio
async def test_bulk_summary_counts_backcompat_root(tmp_path, monkeypatch) -> None:
    """Bulk summary reports geometry + size for a model under a back-compat root."""
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OE_DATA_DIR", str(legacy))
    backend = LocalStorageBackend(active)
    monkeypatch.setattr(file_storage, "_backend", lambda: backend)

    model_dir = legacy / "bim" / "proj-9" / "model-z"
    model_dir.mkdir(parents=True)
    (model_dir / "geometry.glb").write_bytes(b"z" * 42)

    summary = await file_storage.bulk_model_storage_summary("proj-9")
    info = summary.get("model-z")
    assert info is not None
    assert info["artifact_size_bytes"] == 42
    assert ".glb" in info["geometry_exts"]
