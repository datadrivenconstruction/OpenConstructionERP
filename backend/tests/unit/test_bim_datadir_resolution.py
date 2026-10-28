"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the 8.6.1 BIM data-dir resolution fix.

Background
----------
A BIM model could be marked ``ready`` in the database while the geometry
endpoint 404'd with "marked ready but its 3D geometry file is no longer on
the server" (Colin Tan, standalone Postgres deployment, cross-platform). Root
cause: :func:`app.core.storage.resolve_data_dir` (the WRITE location) ignored
``OE_DATA_DIR`` while the download allow-list, the demo seeder and the CLI all
honoured it - so geometry was written to one directory and read from another.

These tests pin the fix and are pure (no database, no app.config import):

* ``resolve_data_dir`` precedence ``OE_DATA_DIR > DATA_DIR > OE_CLI_DATA_DIR``
  then the package-relative ``<package>/data`` default.
* ``LocalStorageBackend`` reads fall back to back-compat data roots, so blobs
  written under the OLD resolution are still served; WRITES never fall back.
* ``safe_data_roots`` always includes the package-relative historical default.
* ``find_geometry_key`` matches ``geometry.<ext>`` case-insensitively (a
  converter on a case-sensitive filesystem may emit ``geometry.GLB``).
* ``geometry_key`` canonicalises the extension to lower case.
* Path-traversal keys are still rejected on the read path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import storage as storage_mod
from app.core.storage import (
    LocalStorageBackend,
    resolve_data_dir,
    safe_data_roots,
)
from app.modules.bim_hub import file_storage

_DATA_ENV_VARS = ("OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR")


def _clear_data_env(monkeypatch) -> None:
    for name in _DATA_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ──────────────────────────────────────────────────────────────────────────
# resolve_data_dir precedence
# ──────────────────────────────────────────────────────────────────────────


def test_resolve_data_dir_prefers_oe_data_dir(tmp_path, monkeypatch) -> None:
    """``OE_DATA_DIR`` wins over the other two env vars (the actual bug)."""
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "a"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "b"))
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path / "c"))
    assert resolve_data_dir() == Path(tmp_path / "a")


def test_resolve_data_dir_falls_to_data_dir(tmp_path, monkeypatch) -> None:
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "b"))
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path / "c"))
    assert resolve_data_dir() == Path(tmp_path / "b")


def test_resolve_data_dir_falls_to_cli_data_dir(tmp_path, monkeypatch) -> None:
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path / "c"))
    assert resolve_data_dir() == Path(tmp_path / "c")


def test_resolve_data_dir_default_is_package_relative(monkeypatch) -> None:
    """With no env override and a source checkout, resolve to ``<repo>/data``.

    (The test runs from a working tree, never ``site-packages``.)
    """
    _clear_data_env(monkeypatch)
    expected = Path(storage_mod.__file__).resolve().parents[3] / "data"
    assert resolve_data_dir() == expected


def test_resolve_data_dir_wheel_install_uses_persistent_home(tmp_path, monkeypatch) -> None:
    """A site-packages (wheel) install must NOT default to the ephemeral
    package dir (wiped on ``pip install -U``); it uses persistent
    ``~/.openestimate`` instead. This is the standalone-install failure mode."""
    _clear_data_env(monkeypatch)
    fake = tmp_path / "venv" / "Lib" / "site-packages" / "app" / "core" / "storage.py"
    monkeypatch.setattr(storage_mod, "__file__", str(fake))
    assert resolve_data_dir() == Path.home() / ".openestimate"


def test_resolve_data_dir_dist_packages_also_persistent(tmp_path, monkeypatch) -> None:
    """Debian's ``dist-packages`` layout is treated like ``site-packages``."""
    _clear_data_env(monkeypatch)
    fake = tmp_path / "usr" / "lib" / "python3" / "dist-packages" / "app" / "core" / "storage.py"
    monkeypatch.setattr(storage_mod, "__file__", str(fake))
    assert resolve_data_dir() == Path.home() / ".openestimate"


def test_resolve_data_dir_source_checkout_keeps_repo_data(tmp_path, monkeypatch) -> None:
    """A git/source checkout (the demo VPS) keeps the persistent ``<repo>/data``."""
    _clear_data_env(monkeypatch)
    fake = tmp_path / "OpenConstructionERP" / "backend" / "app" / "core" / "storage.py"
    monkeypatch.setattr(storage_mod, "__file__", str(fake))
    assert resolve_data_dir() == (tmp_path / "OpenConstructionERP" / "data").resolve()


def test_default_local_base_dir_is_alias(tmp_path, monkeypatch) -> None:
    """The legacy private helper must now mirror ``resolve_data_dir``."""
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "z"))
    assert storage_mod._default_local_base_dir() == resolve_data_dir()


# ──────────────────────────────────────────────────────────────────────────
# safe_data_roots always contains the package-relative historical default
# ──────────────────────────────────────────────────────────────────────────


def test_safe_data_roots_includes_package_default_even_with_oe_data_dir(tmp_path, monkeypatch) -> None:
    """The package-relative ``<package>/data`` is a permanent read root.

    This is what lets a blob written under the old default be served once an
    operator starts setting ``OE_DATA_DIR``.
    """
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "active"))
    pkg_default = (Path(storage_mod.__file__).resolve().parents[3] / "data").resolve()
    assert pkg_default in safe_data_roots()


# ──────────────────────────────────────────────────────────────────────────
# LocalStorageBackend read fallback
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_falls_back_to_backcompat_root(tmp_path, monkeypatch) -> None:
    """A blob present only under a back-compat data root is still served."""
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    # Register ``legacy`` as a platform data root via OE_DATA_DIR so it appears
    # in safe_data_roots(); the backend's own base is the (empty) active dir.
    monkeypatch.setenv("OE_DATA_DIR", str(legacy))
    backend = LocalStorageBackend(active)

    key = "bim/proj-1/model-abc/geometry.glb"
    payload = b"GLB\x00fallback-bytes"
    blob = legacy / "bim" / "proj-1" / "model-abc" / "geometry.glb"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(payload)

    # The blob is NOT under the active base, only under the back-compat root.
    assert not (active / "bim" / "proj-1" / "model-abc" / "geometry.glb").exists()

    assert await backend.exists(key) is True
    assert await backend.get(key) == payload
    assert await backend.size(key) == len(payload)

    chunks: list[bytes] = []
    async for chunk in backend.open_stream(key):
        chunks.append(chunk)
    assert b"".join(chunks) == payload


@pytest.mark.asyncio
async def test_write_never_falls_back(tmp_path, monkeypatch) -> None:
    """Writes always land under the active base, never a back-compat root."""
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OE_DATA_DIR", str(legacy))
    backend = LocalStorageBackend(active)

    key = "bim/p/m/geometry.glb"
    await backend.put(key, b"new-bytes")

    assert (active / "bim" / "p" / "m" / "geometry.glb").is_file()
    assert not (legacy / "bim" / "p" / "m" / "geometry.glb").exists()


@pytest.mark.asyncio
async def test_missing_everywhere_returns_false(tmp_path, monkeypatch) -> None:
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "legacy"))
    backend = LocalStorageBackend(tmp_path / "active")
    assert await backend.exists("bim/none/none/geometry.glb") is False
    with pytest.raises(FileNotFoundError):
        await backend.get("bim/none/none/geometry.glb")


@pytest.mark.asyncio
async def test_read_path_rejects_traversal(tmp_path) -> None:
    """A key with ``..`` segments is rejected before any filesystem access."""
    backend = LocalStorageBackend(tmp_path)
    with pytest.raises(ValueError):
        await backend.get("bim/../../../etc/passwd")
    with pytest.raises(ValueError):
        await backend.exists("bim/../../../etc/passwd")


# ──────────────────────────────────────────────────────────────────────────
# geometry_key lower-casing + find_geometry_key case-insensitive match
# ──────────────────────────────────────────────────────────────────────────


def test_geometry_key_lowercases_extension() -> None:
    assert file_storage.geometry_key("p", "m", "GLB") == "bim/p/m/geometry.glb"
    assert file_storage.geometry_key("p", "m", ".DAE") == "bim/p/m/geometry.dae"
    assert file_storage.geometry_key("p", "m", ".gltf") == "bim/p/m/geometry.gltf"


@pytest.mark.asyncio
async def test_find_geometry_key_exact_lowercase(tmp_path, monkeypatch) -> None:
    """Baseline: a normally-written lowercase blob is found by exact probe."""
    backend = LocalStorageBackend(tmp_path)
    monkeypatch.setattr(file_storage, "_backend", lambda: backend)
    await file_storage.save_geometry("p", "m", "glb", b"bytes")

    result = await file_storage.find_geometry_key("p", "m")
    assert result is not None
    key, ext = result
    assert ext == ".glb"
    assert await backend.get(key) == b"bytes"


@pytest.mark.asyncio
async def test_find_geometry_key_case_insensitive_fallback(tmp_path, monkeypatch) -> None:
    """A converter that wrote ``geometry.GLB`` is still located.

    The exact (lower-case) probes are forced to miss so the case-insensitive
    ``list_prefix`` branch runs deterministically on every OS - on a
    case-insensitive filesystem the exact probe would otherwise succeed.
    """
    backend = LocalStorageBackend(tmp_path)
    monkeypatch.setattr(file_storage, "_backend", lambda: backend)

    payload = b"UPPER-CASE-GLB"
    blob = tmp_path / "bim" / "p" / "m" / "geometry.GLB"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(payload)

    async def _always_missing(_key: str) -> bool:
        return False

    monkeypatch.setattr(backend, "exists", _always_missing)

    result = await file_storage.find_geometry_key("p", "m")
    assert result is not None
    key, ext = result
    assert ext == ".glb"
    assert key.endswith("geometry.GLB")  # the REAL stored key, original case
    assert await backend.get(key) == payload
