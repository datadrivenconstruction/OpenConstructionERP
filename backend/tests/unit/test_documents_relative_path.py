"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression test for documents/router.py download containment check.

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
        resolved = _resolve_under_base("demo/medical-us/tender.pdf", upload_base.resolve())
    finally:
        os.chdir(cwd_before)

    assert _is_inside(resolved, upload_base.resolve()), (
        f"Relative demo path escaped upload_base: resolved={resolved}, base={upload_base.resolve()}"
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
    assert not _is_inside(resolved, upload_base), "Absolute path outside upload_base must be rejected by containment."


# ── Sanity: the resolver is the canonical fix ───────────────────────────────


def test_router_uses_normalized_resolution() -> None:
    """Source-level guard: the documents router must combine ``upload_base``
    with relative ``file_path`` *before* calling ``.resolve()``. If a
    future refactor removes that step, this test fails fast.
    """
    router_path = Path(__file__).resolve().parent.parent.parent / "app" / "modules" / "documents" / "router.py"
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
def test_parametrised_relative_inputs(tmp_path: Path, stored: str, expected_inside: bool) -> None:
    upload_base = (tmp_path / "uploads").resolve()
    upload_base.mkdir()
    resolved = _resolve_under_base(stored, upload_base)
    assert _is_inside(resolved, upload_base) is expected_inside


# ── Served content type resolution (video-playback fix) ─────────────────────
#
# A file stored with an ``application/octet-stream`` mime type (what a browser
# sends when it uploads a video without a type) used to be served back with
# that same generic type, so the media player and the client portal viewer
# could not play it. ``_serve_media_type`` now falls back to guessing from the
# file name when the stored type is missing or generic, so mp4/mov/webm play
# and images render. Replicated here (same style as ``_resolve_under_base``) so
# the contract is pinned without importing the FastAPI app graph.


def _serve_media_type_replica(name: str | None, stored_mime: str | None) -> str:
    import mimetypes

    generic = "application/octet-stream"
    if stored_mime and stored_mime.lower() != generic:
        return stored_mime
    guessed, _ = mimetypes.guess_type(name or "")
    return guessed or generic


def test_specific_stored_mime_is_preserved() -> None:
    """A real, specific stored mime always wins, even with an odd file name."""
    assert _serve_media_type_replica("no_extension_here", "application/pdf") == "application/pdf"


def test_generic_octet_stream_is_overridden_by_extension() -> None:
    """The fix: a generic octet-stream stored mime is replaced by the guess
    from the file name so the browser knows how to render it."""
    assert _serve_media_type_replica("floorplan.png", "application/octet-stream") == "image/png"


def test_missing_stored_mime_is_guessed_from_name() -> None:
    assert _serve_media_type_replica("report.pdf", None) == "application/pdf"


def test_video_extension_resolves_to_a_video_type() -> None:
    """An uploaded clip stored as octet-stream must serve as a video/* type so
    the <video> element plays it instead of offering an opaque download."""
    import mimetypes

    # Guarantee the common video type is registered in this process so the test
    # is deterministic on a minimal CI image; harmless if already present.
    mimetypes.add_type("video/mp4", ".mp4")
    resolved = _serve_media_type_replica("site-walk.mp4", "application/octet-stream")
    assert resolved.startswith("video/"), resolved


def test_unknown_extension_falls_back_to_octet_stream() -> None:
    """When neither the stored mime nor the name is informative, the safe
    generic type is kept rather than inventing one."""
    assert _serve_media_type_replica("mystery.zzz", "application/octet-stream") == "application/octet-stream"


def test_router_serves_files_through_media_type_resolver() -> None:
    """Source-level guard: both file-serving responses (download and share
    link) must resolve the content type through ``_serve_media_type`` rather
    than emit the raw ``doc.mime_type or 'application/octet-stream'`` that left
    videos unplayable. If a refactor drops the helper, this fails fast."""
    router_path = Path(__file__).resolve().parent.parent.parent / "app" / "modules" / "documents" / "router.py"
    src = router_path.read_text(encoding="utf-8")
    assert src.count("_serve_media_type(doc.name, doc.mime_type)") >= 2, (
        "Expected both the download and share-link FileResponses to serve via "
        "`_serve_media_type(doc.name, doc.mime_type)`. Without it a video "
        "stored as application/octet-stream will not play."
    )
