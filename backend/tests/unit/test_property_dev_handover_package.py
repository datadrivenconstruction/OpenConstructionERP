"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the digital handover / closeout-package assembly (item #25).

Targets the pure helpers in :mod:`app.modules.property_dev.service`:

  * ``build_handover_package_zip`` produces a valid ZIP with the expected
    folder layout (MANIFEST.txt + certificates/ + docs/ + snags/), and
    de-duplicates colliding entry names.
  * ``_safe_zip_name`` neutralises path-traversal / separator payloads so a
    hostile ``file_url`` or photo path can never escape its folder
    (Zip-Slip) inside the archive.

These run without a DB or network — they exercise the in-memory packaging
logic directly, which is the load-bearing part of the export.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

from app.modules.property_dev.service import (
    _safe_zip_name,
    build_handover_package_zip,
)


def test_build_zip_layout_and_manifest() -> None:
    zip_bytes = build_handover_package_zip(
        plot_number="A-12",
        date_iso="2026-06-04",
        manifest_text="DIGITAL HANDOVER PACKAGE\nPlot: A-12\n",
        certificates=[("handover_certificate.pdf", b"%PDF-cert1")],
        documents=[("warranty_warranty.pdf", b"warrantybytes")],
        snag_photos=[("abc123_photo.jpg", b"\xff\xd8\xffphoto")],
    )
    assert zip_bytes.startswith(b"PK"), "not a ZIP archive"

    zf = zipfile.ZipFile(BytesIO(zip_bytes))
    names = set(zf.namelist())
    assert "MANIFEST.txt" in names
    assert "certificates/handover_certificate.pdf" in names
    assert "docs/warranty_warranty.pdf" in names
    assert "snags/abc123_photo.jpg" in names

    assert zf.read("certificates/handover_certificate.pdf") == b"%PDF-cert1"
    assert b"Plot: A-12" in zf.read("MANIFEST.txt")


def test_build_zip_empty_still_valid() -> None:
    """A handover with no docs/snags still yields a valid manifest-only ZIP."""
    zip_bytes = build_handover_package_zip(
        plot_number="EMPTY",
        date_iso="2026-06-04",
        manifest_text="nothing here\n",
        certificates=[],
        documents=[],
        snag_photos=[],
    )
    zf = zipfile.ZipFile(BytesIO(zip_bytes))
    assert zf.namelist() == ["MANIFEST.txt"]


def test_build_zip_embeds_machine_readable_manifest_json() -> None:
    """When ``manifest_json`` is supplied it lands as a parseable manifest.json."""
    import json

    payload = json.dumps({"kind": "handover_closeout_package", "plot": "A-12"})
    zip_bytes = build_handover_package_zip(
        plot_number="A-12",
        date_iso="2026-06-04",
        manifest_text="DIGITAL HANDOVER\n",
        certificates=[],
        documents=[],
        snag_photos=[],
        manifest_json=payload,
    )
    zf = zipfile.ZipFile(BytesIO(zip_bytes))
    names = set(zf.namelist())
    assert "MANIFEST.txt" in names
    assert "manifest.json" in names
    parsed = json.loads(zf.read("manifest.json"))
    assert parsed["kind"] == "handover_closeout_package"
    assert parsed["plot"] == "A-12"


def test_build_zip_dedupes_colliding_names() -> None:
    zip_bytes = build_handover_package_zip(
        plot_number="DUP",
        date_iso="2026-06-04",
        manifest_text="m\n",
        certificates=[],
        documents=[("manual.pdf", b"a"), ("manual.pdf", b"b")],
        snag_photos=[],
    )
    zf = zipfile.ZipFile(BytesIO(zip_bytes))
    names = set(zf.namelist())
    assert "docs/manual.pdf" in names
    assert "docs/manual (2).pdf" in names
    # Both payloads survive the rename.
    assert zf.read("docs/manual.pdf") == b"a"
    assert zf.read("docs/manual (2).pdf") == b"b"


def test_safe_zip_name_strips_traversal() -> None:
    assert _safe_zip_name("../../etc/passwd") == "passwd"
    assert _safe_zip_name("uploads/snag/photos/x.jpg") == "x.jpg"
    assert _safe_zip_name("..\\..\\windows\\system32\\evil.dll") == "evil.dll"
    # Empty / pure-traversal collapses to the fallback.
    assert _safe_zip_name("", fallback="file") == "file"
    assert _safe_zip_name("../", fallback="file") == "file"
    # Disallowed characters are replaced, the extension is kept.
    cleaned = _safe_zip_name("we;ird name?.pdf")
    assert "/" not in cleaned and "\\" not in cleaned
    assert cleaned.endswith(".pdf")


def test_safe_zip_name_entries_cannot_escape_in_archive() -> None:
    """Even a traversal-laden entry name lands inside its folder."""
    zip_bytes = build_handover_package_zip(
        plot_number="X",
        date_iso="2026-06-04",
        manifest_text="m\n",
        certificates=[],
        documents=[("../../escape.pdf", b"x")],
        snag_photos=[],
    )
    zf = zipfile.ZipFile(BytesIO(zip_bytes))
    for name in zf.namelist():
        assert ".." not in name
        assert not name.startswith("/")
