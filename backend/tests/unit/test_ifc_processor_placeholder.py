"""Tests for placeholder-geometry tagging in ``ifc_processor``.

Issue #53 — H1: when DDC ``cad2data`` is unavailable the text-IFC parser
falls back to synthesizing 0.3×3.0×1.0 m boxes and laying them out in a
storey-stacked discipline grid.  Without an explicit signal the frontend
renders these as if they were the real model, which is misleading.

These tests assert that:

1. The text-fallback path tags both the model-level result and every
   element with ``geometry_quality="placeholder"`` / ``is_placeholder=True``
   so the frontend can show a non-blocking warning banner.
2. The DDC happy path (real COLLADA written to disk) tags the result
   with ``geometry_quality="real"`` and does NOT add ``is_placeholder``
   to elements.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from app.modules.bim_hub.ifc_processor import (
    _excel_elements_to_bim_result,
    process_ifc_file,
)


MINIMAL_IFC = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('test.ifc','2026-04-26',('Test'),('OE'),'','OE','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1= IFCORGANIZATION($,'OE',$,$,$);
#2= IFCAPPLICATION(#1,'1.0','OE','OE');
#5= IFCOWNERHISTORY(#1,#2,$,.READWRITE.,$,$,$,0);
#10= IFCPROJECT('0001',#5,'TestProject',$,$,$,$,$,$);
#40= IFCBUILDINGSTOREY('0004',#5,'Ground Floor',$,$,$,$,$,.ELEMENT.,0.0);
#50= IFCWALL('0010',#5,'External Wall A',$,$,$,$,$);
#51= IFCWALL('0011',#5,'External Wall B',$,$,$,$,$);
#52= IFCSLAB('0012',#5,'Floor Slab',$,$,$,$,$);
#60= IFCRELCONTAINEDINSPATIALSTRUCTURE('0020',#5,'Floor1','Contains',#50,#51,#52,#40);
ENDSEC;
END-ISO-10303-21;
"""


@pytest.fixture()
def temp_dir():
    d = Path(tempfile.mkdtemp(prefix="bim_placeholder_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def minimal_ifc_file(temp_dir):
    f = temp_dir / "test.ifc"
    f.write_text(MINIMAL_IFC, encoding="utf-8")
    return f


# ── Text-fallback path ─────────────────────────────────────────────────────


def test_text_fallback_marks_result_as_placeholder(minimal_ifc_file, temp_dir, monkeypatch):
    """When DDC is unavailable, ``geometry_quality`` must be ``"placeholder"``."""
    out_dir = temp_dir / "out"
    out_dir.mkdir()

    # Force the text-parser fallback by stubbing find_converter -> None.
    monkeypatch.setattr(
        "app.modules.boq.cad_import.find_converter",
        lambda _ext: None,
    )

    result = process_ifc_file(minimal_ifc_file, out_dir)

    assert result["geometry_type"] == "placeholder"
    assert result["geometry_quality"] == "placeholder"
    assert result["element_count"] >= 3
    # Every element produced by the text fallback must be flagged so the
    # frontend / validation rules can spot synthesised boxes individually.
    assert all(e.get("is_placeholder") is True for e in result["elements"])


def test_text_fallback_still_emits_geometry_for_preview(minimal_ifc_file, temp_dir, monkeypatch):
    """The fallback must keep producing a .dae so the viewer renders SOMETHING."""
    out_dir = temp_dir / "out"
    out_dir.mkdir()

    monkeypatch.setattr(
        "app.modules.boq.cad_import.find_converter",
        lambda _ext: None,
    )

    result = process_ifc_file(minimal_ifc_file, out_dir)

    assert result["has_geometry"] is True
    assert result["geometry_path"] is not None
    assert Path(result["geometry_path"]).exists()


# ── DDC happy path ─────────────────────────────────────────────────────────


def test_ddc_real_geometry_not_marked_placeholder(temp_dir):
    """When a real DDC COLLADA file exists, the result must be ``"real"``."""
    out_dir = temp_dir / "out"
    out_dir.mkdir()

    # Synthesize the contract that the DDC pass produces: a non-empty
    # geometry.dae sitting in output_dir + a tiny raw_elements list shaped
    # like a DDC Excel row.  _excel_elements_to_bim_result is the helper
    # that turns those into a canonical processor result.
    real_dae = out_dir / "geometry.dae"
    real_dae.write_text(
        '<?xml version="1.0"?><COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" '
        'version="1.4.1"><library_geometries/><library_visual_scenes>'
        '<visual_scene id="Scene"/></library_visual_scenes>'
        '<scene><instance_visual_scene url="#Scene"/></scene></COLLADA>',
        encoding="utf-8",
    )

    raw_elements = [
        {
            "id": "1001",
            "uniqueid": "abc-1001",
            "category": "Walls",
            "name": "Wall-001",
            "level": "L1",
            "Length": "5.0",
            "Width": "0.3",
            "Height": "3.0",
        },
    ]

    result = _excel_elements_to_bim_result(
        raw_elements,
        out_dir,
        real_dae_path=real_dae,
    )

    assert result["geometry_type"] == "real"
    assert result["geometry_quality"] == "real"
    # Real-geometry path must NOT flag elements as placeholders.
    assert not any(e.get("is_placeholder") for e in result["elements"])


def test_ddc_path_without_real_dae_falls_back_to_placeholder(temp_dir):
    """Excel-only DDC pass (no .dae) should be flagged placeholder."""
    out_dir = temp_dir / "out"
    out_dir.mkdir()

    raw_elements = [
        {
            "id": "1002",
            "uniqueid": "abc-1002",
            "category": "Walls",
            "name": "Wall-002",
            "level": "L1",
            "Length": "5.0",
            "Width": "0.3",
            "Height": "3.0",
        },
    ]

    result = _excel_elements_to_bim_result(
        raw_elements,
        out_dir,
        real_dae_path=None,
    )

    assert result["geometry_quality"] == "placeholder"
    assert all(e.get("is_placeholder") is True for e in result["elements"])
