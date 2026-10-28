"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the 8.6.1 DWG/DXF takeoff data-dir resolution fix.

Background
----------
The DWG takeoff module computed its blob base via its own ``_dwg_data_base()``
which ignored ``OE_DATA_DIR`` and defaulted to ``os.getcwd()/data``. That
default is never a member of :func:`app.core.storage.safe_data_roots`, so a
genuinely-"ready" drawing's download was rejected by the safe-root gate in the
router and served as a fake placeholder DXF (or 404'd), and entities/thumbnail
reads missed after a CWD change.

The fix routes ``_dwg_data_base()`` through the unified
:func:`app.core.storage.resolve_data_dir` (so WRITES land under the single
platform root that ``safe_data_roots()`` always contains) and adds a READ-ONLY
fallback (``_dwg_existing_path`` / ``resolve_source_drawing_path``) across
``safe_data_roots()`` so blobs written under a prior resolution are still
served.

These tests are pure (no DB writes). NOTE: ``app.modules.dwg_takeoff.service``
imports ``app.database`` at module top, which requires a live PostgreSQL URL -
so on a bare local box (no embedded PG running) the import raises and these
tests SKIP. They run in CI where embedded/external PG is configured. The DB
coupling is a pre-existing module property, not something this fix introduced.
"""

from __future__ import annotations

import os

import pytest

# The service module is import-coupled to PostgreSQL (``from app.database
# import async_session_factory`` at module top). Skip the whole file when that
# import is unavailable locally rather than failing spuriously.
service = pytest.importorskip(
    "app.modules.dwg_takeoff.service",
    reason="dwg_takeoff.service imports app.database (needs a PostgreSQL URL)",
)

_DATA_ENV_VARS = ("OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR")


def _clear_data_env(monkeypatch) -> None:
    for name in _DATA_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ──────────────────────────────────────────────────────────────────────────
# _dwg_data_base honours OE_DATA_DIR and ignores the CWD
# ──────────────────────────────────────────────────────────────────────────


def test_dwg_data_base_honours_oe_data_dir(tmp_path, monkeypatch) -> None:
    """The active write root must equal resolve_data_dir() == OE_DATA_DIR.

    This is the core regression: the old body ignored OE_DATA_DIR entirely.
    """
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "active"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "b"))
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path / "c"))
    assert service._dwg_data_base() == str(tmp_path / "active")


def test_dwg_data_base_is_in_safe_roots(tmp_path, monkeypatch) -> None:
    """The DWG write base must be a member of safe_data_roots().

    Without this the router's download gate (is_within_safe_root) rejects a
    real "ready" drawing and serves a placeholder.
    """
    from app.core.storage import safe_data_roots

    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "active"))
    base = os.path.realpath(service._dwg_data_base())
    roots = {os.path.realpath(str(r)) for r in safe_data_roots()}
    assert base in roots


def test_dwg_data_base_reevaluated_per_call(tmp_path, monkeypatch) -> None:
    """Changing OE_DATA_DIR between calls is reflected (no import-time cache)."""
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "one"))
    assert service._dwg_data_base() == str(tmp_path / "one")
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "two"))
    assert service._dwg_data_base() == str(tmp_path / "two")


# ──────────────────────────────────────────────────────────────────────────
# _dwg_existing_path read fallback + traversal safety
# ──────────────────────────────────────────────────────────────────────────


def test_existing_path_prefers_active_root(tmp_path, monkeypatch) -> None:
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    monkeypatch.setenv("OE_DATA_DIR", str(active))
    blob = active / "dwg_entities" / "ent.json"
    blob.parent.mkdir(parents=True)
    blob.write_text("[]", encoding="utf-8")
    got = service._dwg_existing_path("dwg_entities", "ent.json")
    assert got is not None
    assert os.path.realpath(got) == os.path.realpath(str(blob))


def test_existing_path_falls_back_to_backcompat_root(tmp_path, monkeypatch) -> None:
    """A blob present only under a back-compat data root is still found."""
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    # OE_DATA_DIR -> active write root; register legacy via DATA_DIR so it is a
    # safe_data_root but NOT the active resolve_data_dir() (OE_DATA_DIR wins).
    monkeypatch.setenv("OE_DATA_DIR", str(active))
    monkeypatch.setenv("DATA_DIR", str(legacy))
    blob = legacy / "dwg_thumbnails" / "t.svg"
    blob.parent.mkdir(parents=True)
    blob.write_text("<svg/>", encoding="utf-8")
    # Not under the active root.
    assert not (active / "dwg_thumbnails" / "t.svg").exists()
    got = service._dwg_existing_path("dwg_thumbnails", "t.svg")
    assert got is not None
    assert os.path.realpath(got) == os.path.realpath(str(blob))


def test_existing_path_missing_everywhere_returns_none(tmp_path, monkeypatch) -> None:
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "active"))
    assert service._dwg_existing_path("dwg_entities", "nope.json") is None


def test_existing_path_rejects_traversal(tmp_path, monkeypatch) -> None:
    """A key with ``..`` (or an absolute path) can never escape a data root."""
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "active"))
    # Plant a file outside the roots and try to reach it via traversal.
    secret = tmp_path / "secret.txt"
    secret.write_text("x", encoding="utf-8")
    assert service._dwg_existing_path("dwg_entities", "../../secret.txt") is None
    assert service._dwg_existing_path("dwg_entities", str(secret)) is None


# ──────────────────────────────────────────────────────────────────────────
# resolve_source_drawing_path
# ──────────────────────────────────────────────────────────────────────────


def test_resolve_source_returns_stored_when_inside_safe_root(tmp_path, monkeypatch) -> None:
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    monkeypatch.setenv("OE_DATA_DIR", str(active))
    blob = active / "dwg_uploads" / "abc.dxf"
    blob.parent.mkdir(parents=True)
    blob.write_text("0", encoding="utf-8")
    got = service.resolve_source_drawing_path(str(blob))
    assert got is not None
    assert os.path.realpath(got) == os.path.realpath(str(blob))


def test_resolve_source_recovers_by_basename_across_roots(tmp_path, monkeypatch) -> None:
    """A drawing whose stored absolute path points at an old root is recovered.

    Simulates a drawing uploaded when the (CWD-based) default put the file
    under ``legacy``; the row still records that absolute path, but the active
    root is now ``active``. The blob must be recovered by basename.
    """
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OE_DATA_DIR", str(active))
    monkeypatch.setenv("DATA_DIR", str(legacy))
    real = legacy / "dwg_uploads" / "moved.dxf"
    real.parent.mkdir(parents=True)
    real.write_text("0", encoding="utf-8")
    # Stored path points at the active root where the file does NOT exist.
    stored = str(active / "dwg_uploads" / "moved.dxf")
    assert not os.path.exists(stored)
    got = service.resolve_source_drawing_path(stored)
    assert got is not None
    assert os.path.realpath(got) == os.path.realpath(str(real))


def test_resolve_source_none_when_absent(tmp_path, monkeypatch) -> None:
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "active"))
    assert service.resolve_source_drawing_path(str(tmp_path / "active" / "dwg_uploads" / "x.dxf")) is None
    assert service.resolve_source_drawing_path("") is None
    assert service.resolve_source_drawing_path(None) is None
