"""Unit tests for the BIM/RVT converter diagnostic helpers.

These helpers exist so the UI can show a real reason ("File saved with
Revit 2024 but installed converter is 18.x") instead of the generic
"Converter Required" message users used to see.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.boq import cad_import

# ── read_rvt_revit_version ────────────────────────────────────────────────


def _write_ole_with_basicfileinfo(path: Path, *, format_year: str, build: str) -> None:
    """‌⁠‍Write a minimal stub that looks like an OLE Compound File and
    contains a BasicFileInfo-style UTF-16-LE blob the version reader can
    find.

    We don't build a fully-valid CFB — just enough that the magic-byte
    sniff passes and the UTF-16 scan locates the Format/Build lines.
    """
    blob = (f"Format: {format_year}\r\nRevit Build: (Autodesk Revit {format_year} (ENU)) {build}\r\n").encode(
        "utf-16-le"
    )
    # OLE magic + 504 bytes of padding to get past the header, then blob.
    payload = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + (b"\x00" * 504) + blob
    path.write_bytes(payload)


def test_read_rvt_version_extracts_format_and_app(tmp_path: Path) -> None:
    rvt = tmp_path / "sample.rvt"
    _write_ole_with_basicfileinfo(rvt, format_year="2024", build="24.0.11.21")

    info = cad_import.read_rvt_revit_version(rvt)

    assert info["format"] == "2024"
    assert info["build"] is not None
    assert "24.0.11.21" in info["build"]
    assert info["app_name"] == "Revit 2024"


def test_read_rvt_version_rejects_non_ole(tmp_path: Path) -> None:
    # A plain text file is not a Compound File — the magic check should bail.
    not_rvt = tmp_path / "fake.rvt"
    not_rvt.write_bytes(b"Format: 2025\r\nRevit Build: (Revit 2025) 25.0.0.0")

    info = cad_import.read_rvt_revit_version(not_rvt)

    # No magic → no scan → all fields stay None.
    assert info == {"format": None, "build": None, "app_name": None}


def test_read_rvt_version_missing_file_returns_all_none(tmp_path: Path) -> None:
    info = cad_import.read_rvt_revit_version(tmp_path / "does-not-exist.rvt")
    assert info == {"format": None, "build": None, "app_name": None}


def test_read_rvt_version_no_marker_returns_none_fields(tmp_path: Path) -> None:
    # Valid OLE magic but no BasicFileInfo strings → scan finds nothing.
    rvt = tmp_path / "blank.rvt"
    rvt.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 4096)

    info = cad_import.read_rvt_revit_version(rvt)

    assert info["format"] is None
    assert info["build"] is None
    assert info["app_name"] is None


# ── detect_converter_version ──────────────────────────────────────────────


def test_detect_converter_version_no_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: None)

    info = cad_import.detect_converter_version("rvt")

    assert info == {"version": None, "source": None, "binary_path": None}


def test_detect_converter_version_dpkg_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bin = tmp_path / "RvtExporter"
    fake_bin.write_bytes(b"x" * 2048)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: fake_bin)
    monkeypatch.setattr(cad_import.sys, "platform", "linux")

    # Stub subprocess.run to mimic a successful dpkg-query response.
    import subprocess as _subprocess

    class _Proc:
        returncode = 0
        stdout = b"18.0.0.0\n"
        stderr = b""

    def fake_run(*_args: object, **_kwargs: object) -> _Proc:
        return _Proc()

    monkeypatch.setattr(_subprocess, "run", fake_run)

    info = cad_import.detect_converter_version("rvt")

    assert info["version"] == "18.0.0.0"
    assert info["source"] == "dpkg:ddc-rvtconverter"
    assert info["binary_path"] == str(fake_bin)


def test_detect_converter_version_dpkg_missing_falls_back_to_parent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate Windows-style per-format install dir
    install_dir = tmp_path / "rvt_windows_v18.0.0"
    install_dir.mkdir()
    fake_bin = install_dir / "RvtExporter.exe"
    fake_bin.write_bytes(b"x" * 2048)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: fake_bin)
    monkeypatch.setattr(cad_import.sys, "platform", "win32")

    info = cad_import.detect_converter_version("rvt")

    # On Windows we don't try dpkg — we just expose the parent dir name as
    # a best-effort fingerprint.
    assert info["source"] == "binary_metadata"
    assert info["version"] == "rvt_windows_v18.0.0"
    assert info["binary_path"] == str(fake_bin)
