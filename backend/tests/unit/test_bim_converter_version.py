"""Unit tests for the BIM converter-version surfacing path.

The BIM hub's ``_try_cad2data`` success path attaches the installed DDC
converter's version + source onto its result dict so the frontend can render a
"Processed with DDC v{X}" badge on the model card. Detection itself lives in
``app.modules.boq.cad_import.detect_converter_version``; these tests pin the
*integration* between that helper and the BIM hub processor - the result dict
shape, the graceful degradation when the helper fails, and the ``source``
field, which is read from the stamp the installer writes beside a package.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.converter_source import INSTALL_STAMP_NAME, PACKAGES
from app.modules.bim_hub import ifc_processor
from app.modules.boq import cad_import


def _installed_rvt(tmp_path: Path, *, stamp: dict[str, str] | None) -> Path:
    root = tmp_path / "rvt_windows"
    (root / "cli").mkdir(parents=True)
    exe = root / "cli" / "RVTconverter.exe"
    exe.write_bytes(b"x" * 2048)
    if stamp is not None:
        (root / INSTALL_STAMP_NAME).write_text(json.dumps(stamp), encoding="utf-8")
    return exe


def test_version_comes_from_the_install_stamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = _installed_rvt(tmp_path, stamp={"version": "2.0.0", "tag": "v2026.10.0", "sha256": PACKAGES["rvt"].sha256})
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: exe)

    info = ifc_processor._detect_converter_version_safe("rvt")

    assert info["version"] == "2.0.0"
    assert info["source"] == "release:v2026.10.0"
    assert info["binary_path"] == str(exe)


def test_an_unstamped_copy_reports_the_version_declared_for_the_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A copy bundled with the desktop installer or unpacked by hand has no stamp."""
    exe = _installed_rvt(tmp_path, stamp=None)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: exe)

    info = ifc_processor._detect_converter_version_safe("rvt")

    assert info["version"] == PACKAGES["rvt"].version
    assert info["source"] == "package"


def test_detect_converter_version_safe_missing_converter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: None)
    info = ifc_processor._detect_converter_version_safe("rvt")
    assert info == {"version": None, "source": None, "binary_path": None}


def test_detect_converter_version_safe_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A diagnostics failure must never turn into a failed BIM import."""

    def boom(_ext: str) -> dict[str, str | None]:
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(cad_import, "detect_converter_version", boom)
    info = ifc_processor._detect_converter_version_safe("rvt")
    assert info == {"version": None, "source": None, "binary_path": None}


def test_excel_result_round_trip_carries_converter_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The dict returned by ``_excel_elements_to_bim_result`` is the shape
    ``_try_cad2data`` augments with the converter fields before returning; the
    converter fields can be attached without disturbing the canonical keys."""
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

    assert "elements" in result
    assert "geometry_type" in result
    assert "geometry_quality" in result

    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: None)
    conv_info = ifc_processor._detect_converter_version_safe("rvt")
    assert conv_info["version"] is None  # converter missing -> no badge

    if conv_info.get("version"):
        result["converter_version"] = conv_info["version"]
    if conv_info.get("source"):
        result["converter_source"] = conv_info["source"]

    assert "converter_version" not in result
    assert "converter_source" not in result


def test_excel_result_with_installed_converter_attaches_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With an installed, stamped converter the augmented result carries the
    badge metadata in the exact shape the router expects."""
    out_dir = tmp_path / "work"
    out_dir.mkdir()
    exe = _installed_rvt(tmp_path, stamp={"version": "2.0.0", "tag": "v2026.10.0"})
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: exe)

    raw = [{"category": "OST_Walls", "name": "W-01", "uniqueid": "abc", "level": "L1", "length": "5.0"}]
    result = ifc_processor._excel_elements_to_bim_result(raw, out_dir, real_dae_path=None)
    conv_info = ifc_processor._detect_converter_version_safe("rvt")

    if conv_info.get("version"):
        result["converter_version"] = conv_info["version"]
    if conv_info.get("source"):
        result["converter_source"] = conv_info["source"]

    assert result["converter_version"] == "2.0.0"
    assert isinstance(result["converter_source"], str)
    assert result["converter_source"].startswith("release:")
