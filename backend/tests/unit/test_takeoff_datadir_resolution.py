"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the takeoff-PDF data-dir resolution fix (8.6.1 follow-up).

Background
----------
Takeoff PDFs were written to a hard-coded ``~/.openestimator/takeoff_documents``
(the WRONG brand namespace, ignoring ``OE_DATA_DIR`` / ``DATA_DIR`` /
``OE_CLI_DATA_DIR`` and never touching the storage backend). On a container or
external-Postgres redeploy the bytes were lost while the ``TakeoffDocument`` row
stayed present, so the download endpoint 404'd "PDF file not found on disk".

The fix anchors the documents dir under
:func:`app.core.storage.resolve_data_dir` (lazy, per-call) for WRITES, and adds a
READ-ONLY back-compat resolver that also probes
:func:`app.core.storage.safe_data_roots` and the legacy ``~/.openestimator`` path
so existing PDFs are still found. The download route's path-containment guard
moved to :func:`app.core.storage.is_within_safe_root` (``relative_to``-based)
instead of a brittle ``str.startswith`` prefix check.

These tests are pure (no database). The takeoff service module is import-coupled
to PostgreSQL/Settings at import time, so the tests that exercise the actual
helpers are best-effort: they skip when the local interpreter cannot import the
module (e.g. local py3.11 / no embedded PG). The storage-layer invariants the
helpers rely on are pinned unconditionally against ``app.core.storage``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.storage import (
    is_within_safe_root,
    resolve_data_dir,
    safe_data_roots,
)

_DATA_ENV_VARS = ("OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR")
_SUBDIR = "takeoff_documents"


def _clear_data_env(monkeypatch) -> None:
    for name in _DATA_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _import_service_or_skip():
    """Import the takeoff service module, skipping when PG-coupled import fails."""
    try:
        from app.modules.takeoff import service as svc
    except Exception as exc:  # pragma: no cover - depends on local interpreter
        pytest.skip(f"takeoff.service not importable in this environment: {exc!r}")
    return svc


# ──────────────────────────────────────────────────────────────────────────
# Storage-layer invariants the takeoff helpers rely on (always run)
# ──────────────────────────────────────────────────────────────────────────


def test_documents_dir_anchors_under_oe_data_dir(tmp_path, monkeypatch) -> None:
    """The active write dir must follow ``OE_DATA_DIR`` - not a hard-coded home.

    This pins the contract ``_takeoff_documents_dir`` depends on: it is
    ``resolve_data_dir() / 'takeoff_documents'``, and ``resolve_data_dir``
    honours ``OE_DATA_DIR`` first.
    """
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "vol"))
    assert resolve_data_dir() / _SUBDIR == Path(tmp_path / "vol") / _SUBDIR


def test_safe_roots_cover_active_documents_dir(tmp_path, monkeypatch) -> None:
    """A PDF written under the active root passes the containment guard."""
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "vol"))
    pdf = (resolve_data_dir() / _SUBDIR / "abc.pdf").resolve()
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4 test")
    assert is_within_safe_root(pdf) is True


def test_containment_guard_rejects_outside_path(tmp_path, monkeypatch) -> None:
    """A path outside every platform-owned data root is denied.

    Also pins that the new ``relative_to`` guard is not fooled by a sibling
    directory whose name merely shares a string prefix with a safe root.
    """
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "vol"))
    outside = (tmp_path / "elsewhere" / "etc_passwd").resolve()
    assert is_within_safe_root(outside) is False
    # Prefix-sharing sibling (``vol`` vs ``vol-evil``) must NOT pass.
    sibling = (tmp_path / "vol-evil" / "x.pdf").resolve()
    assert is_within_safe_root(sibling) is False


def test_safe_roots_include_legacy_brand_home(monkeypatch) -> None:
    """The legacy ``~/.openestimator`` namespace stays a back-compat read root."""
    legacy = (Path.home() / ".openestimator").resolve()
    assert legacy in safe_data_roots()


# ──────────────────────────────────────────────────────────────────────────
# Actual helper behaviour (best-effort: skips if service import is PG-coupled)
# ──────────────────────────────────────────────────────────────────────────


def test_takeoff_documents_dir_honours_env(tmp_path, monkeypatch) -> None:
    """``_takeoff_documents_dir`` re-resolves per call and honours OE_DATA_DIR."""
    svc = _import_service_or_skip()
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "vol"))
    assert svc._takeoff_documents_dir() == Path(tmp_path / "vol") / _SUBDIR
    # Per-call re-resolution: flipping the env after first call takes effect.
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "vol2"))
    assert svc._takeoff_documents_dir() == Path(tmp_path / "vol2") / _SUBDIR


def test_find_existing_pdf_in_active_root(tmp_path, monkeypatch) -> None:
    svc = _import_service_or_skip()
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "active"))
    doc_id = "11111111-1111-1111-1111-111111111111"
    pdf = svc._takeoff_documents_dir() / f"{doc_id}.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4 active")
    found = svc._find_existing_takeoff_pdf(doc_id)
    assert found is not None
    assert found.read_bytes() == b"%PDF-1.4 active"


def test_find_existing_pdf_back_compat_fallback(tmp_path, monkeypatch) -> None:
    """A PDF present only under a back-compat data root is still located."""
    svc = _import_service_or_skip()
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    # ``legacy`` is registered as a platform data root via DATA_DIR so it shows
    # up in safe_data_roots(); the ACTIVE write root is OE_DATA_DIR=active.
    monkeypatch.setenv("OE_DATA_DIR", str(active))
    monkeypatch.setenv("DATA_DIR", str(legacy))
    doc_id = "22222222-2222-2222-2222-222222222222"
    blob = legacy / _SUBDIR / f"{doc_id}.pdf"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"%PDF-1.4 legacy")
    # Not under the active root.
    assert not (active / _SUBDIR / f"{doc_id}.pdf").exists()
    found = svc._find_existing_takeoff_pdf(doc_id)
    assert found is not None
    assert found.read_bytes() == b"%PDF-1.4 legacy"


def test_find_existing_pdf_missing_everywhere(tmp_path, monkeypatch) -> None:
    svc = _import_service_or_skip()
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "active"))
    assert svc._find_existing_takeoff_pdf("33333333-3333-3333-3333-333333333333") is None
