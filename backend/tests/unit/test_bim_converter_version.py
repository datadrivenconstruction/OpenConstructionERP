"""‌⁠‍Unit tests for the BIM converter-version surfacing path.

v3.12.0 / Stream D — the BIM hub's ``_try_cad2data`` success path attaches
the installed DDC converter's version + source onto its result dict so the
frontend can render a "Processed with DDC v{X}" badge on the model card.
Detection itself lives in ``app.modules.boq.cad_import.detect_converter_version``
(covered by ``test_cad_diagnostics.py``); these tests pin the *integration*
between that helper and the BIM hub processor — the result dict shape, the
graceful degradation when the helper fails, and the platform-specific
``source`` field.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.bim_hub import ifc_processor
from app.modules.boq import cad_import


def _stub_subprocess_run(monkeypatch: pytest.MonkeyPatch, *, returncode: int, stdout: bytes) -> None:
    """‌⁠‍Replace ``subprocess.run`` with a stub that returns a canned response."""
    import subprocess as _subprocess

    class _Proc:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = b""

    def fake_run(*_args: object, **_kwargs: object) -> _Proc:
        return _Proc()

    monkeypatch.setattr(_subprocess, "run", fake_run)


def test_detect_converter_version_safe_linux_dpkg_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍Linux + dpkg available → ``_detect_converter_version_safe`` mirrors
    the apt-package version verbatim and tags the source as ``dpkg:…``."""
    fake_bin = tmp_path / "RvtExporter"
    fake_bin.write_bytes(b"x" * 2048)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: fake_bin)
    monkeypatch.setattr(cad_import.sys, "platform", "linux")
    _stub_subprocess_run(monkeypatch, returncode=0, stdout=b"18.0.1\n")

    info = ifc_processor._detect_converter_version_safe("rvt")

    assert info["version"] == "18.0.1"
    assert info["source"] == "dpkg:ddc-rvtconverter"
    assert info["binary_path"] == str(fake_bin)


def test_detect_converter_version_safe_windows_parent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍Windows path (no dpkg) → falls back to the install dir name and tags
    the source as ``binary_metadata``."""
    install_dir = tmp_path / "rvt_windows_v18.0.0"
    install_dir.mkdir()
    fake_bin = install_dir / "RvtExporter.exe"
    fake_bin.write_bytes(b"x" * 2048)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: fake_bin)
    monkeypatch.setattr(cad_import.sys, "platform", "win32")

    info = ifc_processor._detect_converter_version_safe("rvt")

    assert info["source"] == "binary_metadata"
    assert info["version"] == "rvt_windows_v18.0.0"
    assert info["binary_path"] == str(fake_bin)


def test_detect_converter_version_safe_missing_converter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """‌⁠‍When the converter binary isn't installed at all, the helper returns
    an all-None dict (and the frontend hides the badge)."""
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: None)

    info = ifc_processor._detect_converter_version_safe("ifc")

    assert info == {"version": None, "source": None, "binary_path": None}


def test_detect_converter_version_safe_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """‌⁠‍``_detect_converter_version_safe`` must swallow any exception from
    the underlying helper so a diagnostic failure never blocks an otherwise
    successful BIM import.  We force a ``RuntimeError`` from
    ``detect_converter_version`` and assert the wrapper returns the
    canonical all-None dict instead of propagating."""

    def boom(_ext: str) -> dict[str, str | None]:
        raise RuntimeError("simulated detection failure")

    monkeypatch.setattr(cad_import, "detect_converter_version", boom)

    info = ifc_processor._detect_converter_version_safe("rvt")

    assert info == {"version": None, "source": None, "binary_path": None}


def test_excel_result_round_trip_carries_converter_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍Integration check: the dict returned by ``_excel_elements_to_bim_result``
    is the same shape that ``_try_cad2data`` augments with the converter
    fields before returning. We verify the converter fields can be attached
    without disturbing the canonical keys (geometry_type, geometry_quality,
    elements, …)."""
    out_dir = tmp_path / "work"
    out_dir.mkdir()
    raw = [
        {
            "category": "OST_Walls",
            "name": "W-01",
            "uniqueid": "abc",
            "level": "L1",
            "length": "5.0",
            "area": "12.5",
            "volume": "1.5",
        },
    ]
    result = ifc_processor._excel_elements_to_bim_result(raw, out_dir, real_dae_path=None)

    # Sanity — canonical keys must be present so the badge augmentation
    # downstream doesn't shadow critical fields.
    assert "elements" in result
    assert "geometry_type" in result
    assert "geometry_quality" in result

    # Attach converter fields the same way ``_try_cad2data`` does. This is
    # the contract the router consumes — see router.py "DDC converter
    # version stamp".
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: None)
    conv_info = ifc_processor._detect_converter_version_safe("rvt")
    assert conv_info["version"] is None  # converter missing → no badge

    if conv_info.get("version"):
        result["converter_version"] = conv_info["version"]
    if conv_info.get("source"):
        result["converter_source"] = conv_info["source"]

    assert "converter_version" not in result  # safely omitted
    assert "converter_source" not in result


def test_excel_result_with_installed_converter_attaches_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """‌⁠‍End-to-end: with a fake DDC binary present on Linux and a dpkg-style
    version reply, the augmented result dict carries the badge metadata in
    the exact shape the router expects (string version, string source
    starting with ``dpkg:``)."""
    out_dir = tmp_path / "work"
    out_dir.mkdir()
    fake_bin = tmp_path / "RvtExporter"
    fake_bin.write_bytes(b"x" * 2048)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: fake_bin)
    monkeypatch.setattr(cad_import.sys, "platform", "linux")
    _stub_subprocess_run(monkeypatch, returncode=0, stdout=b"3.12.0\n")

    raw = [
        {
            "category": "OST_Walls",
            "name": "W-01",
            "uniqueid": "abc",
            "level": "L1",
            "length": "5.0",
        },
    ]
    result = ifc_processor._excel_elements_to_bim_result(raw, out_dir, real_dae_path=None)
    conv_info = ifc_processor._detect_converter_version_safe("rvt")

    if conv_info.get("version"):
        result["converter_version"] = conv_info["version"]
    if conv_info.get("source"):
        result["converter_source"] = conv_info["source"]

    assert result["converter_version"] == "3.12.0"
    assert isinstance(result["converter_source"], str)
    assert result["converter_source"].startswith("dpkg:")
