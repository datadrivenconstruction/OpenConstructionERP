"""Regression test for documents/router.py download containment check.

Background
----------
Before v2.6.40, the download endpoint did::

    file_path = Path(doc.file_path).resolve()
    upload_base = Path(UPLOAD_BASE).resolve()
    file_path.relative_to(upload_base)

For demo seed records that store ``file_path`` as a *relative* path like
``demo/medical-us/foo.pdf``, ``Path.resolve()`` resolves against the
*current working directory*, not against ``UPLOAD_BASE``. The path
escapes the base, ``relative_to`` raises ``ValueError``, and the user
sees an unconditional 403 on every demo download.

The fix prefixes relative paths with ``upload_base`` *before* resolving::

    raw = Path(doc.file_path)
    file_path = (raw if raw.is_absolute() else upload_base / raw).resolve()

This test verifies the containment check accepts relatives, accepts
in-base absolutes, and still rejects path-traversal escapes.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def _resolve_under_base(stored_path: str, upload_base: Path) -> Path:
    """Replicate the exact normalization performed by ``download_document``.

    Kept as a helper so the test pinpoints the policy without spinning up
    the full FastAPI dependency graph.
    """
    raw = Path(stored_path)
    return (raw if raw.is_absolute() else upload_base / raw).resolve()


def _is_inside(p: Path, base: Path) -> bool:
    """Equivalent of the router's ``file_path.relative_to(upload_base)``."""
    try:
        p.relative_to(base)
        return True
    except ValueError:
        return False


# ── Relative paths (the v2.6.40 regression scenario) ────────────────────────


def test_relative_path_resolves_under_upload_base(tmp_path: Path) -> None:
    """A relative ``file_path`` (demo seed) must resolve INSIDE upload_base
    regardless of the current working directory."""
    upload_base = tmp_path / "uploads"
    upload_base.mkdir()
    project_dir = upload_base / "demo" / "medical-us"
    project_dir.mkdir(parents=True)
    (project_dir / "tender.pdf").write_bytes(b"%PDF-1.4 stub")

    # Run the resolver from a *different* working directory to prove that
    # CWD does not influence the outcome.
    cwd_before = os.getcwd()
    foreign_cwd = tmp_path / "elsewhere"
    foreign_cwd.mkdir()
    os.chdir(foreign_cwd)
    try:
        resolved = _resolve_under_base(
            "demo/medical-us/tender.pdf", upload_base.resolve()
        )
    finally:
        os.chdir(cwd_before)

    assert _is_inside(resolved, upload_base.resolve()), (
        f"Relative demo path escaped upload_base: resolved={resolved}, "
        f"base={upload_base.resolve()}"
    )
    assert resolved.exists(), "Resolver must point at the actual file on disk"


def test_relative_path_with_windows_separators(tmp_path: Path) -> None:
    """Windows-style separators in stored relative paths must still resolve
    under upload_base. ``Path()`` normalizes them on POSIX as a single
    component, but the containment check should still hold."""
    upload_base = (tmp_path / "uploads").resolve()
    upload_base.mkdir()

    resolved = _resolve_under_base("demo\\foo\\bar.pdf", upload_base)
    assert _is_inside(resolved, upload_base) or os.name != "nt", (
        "On Windows, backslash-separated relatives must land inside "
        "upload_base. (POSIX may treat the whole string as one filename, "
        "which is fine — still contained.)"
    )


# ── Absolute paths (real uploads) ───────────────────────────────────────────


def test_absolute_path_inside_base_is_accepted(tmp_path: Path) -> None:
    """A real upload stored as an absolute path inside upload_base must
    still be accepted by the containment check."""
    upload_base = (tmp_path / "uploads").resolve()
    upload_base.mkdir()
    project_dir = upload_base / "abc-123"
    project_dir.mkdir()
    real_file = project_dir / "real.pdf"
    real_file.write_bytes(b"%PDF-1.4")

    resolved = _resolve_under_base(str(real_file), upload_base)
    assert _is_inside(resolved, upload_base)
    assert resolved == real_file.resolve()


# ── Security: path-traversal attempts must STILL be rejected ────────────────


def test_traversal_attempt_with_relative_dotdot(tmp_path: Path) -> None:
    """A relative path with ``..`` segments must NOT escape upload_base
    after resolution. The fix must not weaken the existing security
    posture — it just stops crashing on legitimate relatives.
    """
    upload_base = (tmp_path / "uploads").resolve()
    upload_base.mkdir()

    # Try to climb out of upload_base via dot-dot.
    malicious = "../../etc/passwd"
    resolved = _resolve_under_base(malicious, upload_base)
    assert not _is_inside(resolved, upload_base), (
        f"Traversal escape NOT blocked: resolved={resolved} is inside "
        f"upload_base={upload_base}. The fix must not relax the "
        f"containment check."
    )


def test_traversal_attempt_with_absolute_outside_base(tmp_path: Path) -> None:
    """An absolute file_path pointing OUTSIDE upload_base must be rejected
    (e.g. ``/etc/passwd`` on POSIX, ``C:\\Windows\\system32\\...`` on
    Windows). The router catches this via ``relative_to``."""
    upload_base = (tmp_path / "uploads").resolve()
    upload_base.mkdir()

    outside = tmp_path / "elsewhere" / "secret.txt"
    outside.parent.mkdir()
    outside.write_text("nope")

    resolved = _resolve_under_base(str(outside), upload_base)
    assert not _is_inside(resolved, upload_base), (
        "Absolute path outside upload_base must be rejected by containment."
    )


# ── Sanity: the resolver is the canonical fix ───────────────────────────────


def test_router_uses_normalized_resolution() -> None:
    """Source-level guard: the documents router must combine ``upload_base``
    with relative ``file_path`` *before* calling ``.resolve()``. If a
    future refactor removes that step, this test fails fast.
    """
    router_path = (
        Path(__file__).resolve().parent.parent.parent
        / "app" / "modules" / "documents" / "router.py"
    )
    src = router_path.read_text(encoding="utf-8")
    # The fix introduces this exact branch — keep it grep-able.
    assert "raw if raw.is_absolute() else upload_base / raw" in src, (
        "Expected normalization expression "
        "`raw if raw.is_absolute() else upload_base / raw` was removed "
        "from documents/router.py. This is the v2.6.40 fix — without it, "
        "all demo-seed downloads return 403."
    )


@pytest.mark.parametrize(
    "stored,expected_inside",
    [
        ("demo/uk/spec.pdf", True),
        ("a.pdf", True),
        ("../leak.txt", False),
        ("foo/../bar.pdf", True),  # collapses to bar.pdf — still inside
    ],
)
def test_parametrised_relative_inputs(
    tmp_path: Path, stored: str, expected_inside: bool
) -> None:
    upload_base = (tmp_path / "uploads").resolve()
    upload_base.mkdir()
    resolved = _resolve_under_base(stored, upload_base)
    assert _is_inside(resolved, upload_base) is expected_inside
