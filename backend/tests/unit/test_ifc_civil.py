"""Unit tests for IFC civil infrastructure support.

Verifies that the text-based IFC parser correctly handles IFC4x3 civil
entity types (bridges, roads, railways, alignments, earthworks, etc.)
that were previously ignored, causing the 'matrix of prismoidal objects'
rendering bug (GitHub issue #52).
"""

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.bim_hub.ifc_processor import (
    _classify_discipline,
    _simplify_type,
    process_ifc_file,
)


# ── Discipline classification ──────────────────────────────────────────────


class TestClassifyDiscipline:
    """Verify civil infrastructure types are classified correctly."""

    @pytest.mark.parametrize(
        "ifc_type, expected",
        [
            ("IFCWALL", "structural"),
            ("IFCWALLSTANDARDCASE", "structural"),
            ("IFCSLAB", "structural"),
            ("IFCCOLUMN", "structural"),
            ("IFCBEAM", "structural"),
            ("IFCFOOTING", "structural"),
            ("IFCPILE", "structural"),
            ("IFCPLATE", "structural"),
            ("IFCMEMBER", "structural"),
            ("IFCTENDON", "structural"),
            ("IFCBEARING", "structural"),
        ],
    )
    def test_structural(self, ifc_type: str, expected: str) -> None:
        assert _classify_discipline(ifc_type) == expected

    @pytest.mark.parametrize(
        "ifc_type, expected",
        [
            ("IFCDOOR", "architecture"),
            ("IFCWINDOW", "architecture"),
            ("IFCCURTAINWALL", "architecture"),
            ("IFCSPACE", "architecture"),
        ],
    )
    def test_architecture(self, ifc_type: str, expected: str) -> None:
        assert _classify_discipline(ifc_type) == expected

    @pytest.mark.parametrize(
        "ifc_type, expected",
        [
            ("IFCFLOWSEGMENT", "mep"),
            ("IFCFLOWTERMINAL", "mep"),
            ("IFCDISTRIBUTIONELEMENT", "mep"),
        ],
    )
    def test_mep(self, ifc_type: str, expected: str) -> None:
        assert _classify_discipline(ifc_type) == expected

    @pytest.mark.parametrize(
        "ifc_type, expected",
        [
            ("IFCALIGNMENT", "civil"),
            ("IFCBRIDGE", "civil"),
            ("IFCBRIDGEPART", "civil"),
            ("IFCROAD", "civil"),
            ("IFCROADPART", "civil"),
            ("IFCRAILWAY", "civil"),
            ("IFCPAVEMENT", "civil"),
            ("IFCKERB", "civil"),
            ("IFCCOURSE", "civil"),
            ("IFCEARTHWORKSFILL", "civil"),
            ("IFCEARTHWORKSCUT", "civil"),
            ("IFCCIVILELEMENT", "civil"),
            ("IFCGEOGRAPHICELEMENT", "civil"),
            ("IFCGEOTECHNICELEMENT", "civil"),
            ("IFCDEEPFOUNDATION", "civil"),
            ("IFCFACILITY", "civil"),
            ("IFCFACILITYPART", "civil"),
            ("IFCSURFACEFEATURE", "civil"),
            ("IFCTRANSPORTELEMENT", "civil"),
        ],
    )
    def test_civil(self, ifc_type: str, expected: str) -> None:
        assert _classify_discipline(ifc_type) == expected


# ── Type display names ──────────────────────────────────────────────────────


class TestSimplifyType:
    """Verify civil types get human-readable display names."""

    @pytest.mark.parametrize(
        "ifc_type, expected",
        [
            ("IFCWALLSTANDARDCASE", "Wall"),
            ("IFCALIGNMENT", "Alignment"),
            ("IFCBRIDGE", "Bridge"),
            ("IFCBRIDGEPART", "Bridge Part"),
            ("IFCROAD", "Road"),
            ("IFCROADPART", "Road Part"),
            ("IFCRAILWAY", "Railway"),
            ("IFCPAVEMENT", "Pavement"),
            ("IFCKERB", "Kerb"),
            ("IFCEARTHWORKSFILL", "Earthworks Fill"),
            ("IFCEARTHWORKSCUT", "Earthworks Cut"),
            ("IFCREINFORCEDSOIL", "Reinforced Soil"),
            ("IFCCIVILELEMENT", "Civil Element"),
            ("IFCFACILITY", "Facility"),
            ("IFCDEEPFOUNDATION", "Deep Foundation"),
            ("IFCBEARING", "Bearing"),
            ("IFCTENDON", "Tendon"),
            ("IFCGEOTECHNICELEMENT", "Geotechnic Element"),
        ],
    )
    def test_display_name(self, ifc_type: str, expected: str) -> None:
        assert _simplify_type(ifc_type) == expected

    def test_unknown_type_fallback(self) -> None:
        """Unknown types should strip 'IFC' prefix and title-case."""
        result = _simplify_type("IFCSOMENEWTHING")
        assert result == "Somenewthing"


# ── IFC parsing with civil elements ────────────────────────────────────────


_MINIMAL_CIVIL_IFC = (
    "ISO-10303-21;\n"
    "HEADER;\n"
    "FILE_DESCRIPTION(('ViewDefinition [CoordinationView_V2.0]'),'2;1');\n"
    "FILE_NAME('test_civil.ifc','2024-01-01',(''),(''),'','','');\n"
    "FILE_SCHEMA(('IFC4X3'));\n"
    "ENDSEC;\n"
    "DATA;\n"
    "#1= IFCPROJECT('0001',#2,'Civil Test',$,$,$,$,$,#10);\n"
    "#2= IFCOWNERHISTORY(#3,#4,$,.NOCHANGE.,$,$,$,0);\n"
    "#3= IFCPERSONANDORGANIZATION(#5,#6,$);\n"
    "#5= IFCPERSON($,'Test','User',$,$,$,$,$);\n"
    "#6= IFCORGANIZATION($,'TestOrg',$,$,$);\n"
    "#4= IFCAPPLICATION(#6,'1.0','TestApp','TestApp');\n"
    "#10= IFCUNITASSIGNMENT((#11));\n"
    "#11= IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);\n"
    "#20= IFCSITE('site01',#2,'Site',$,$,$,$,$,.ELEMENT.,$,$,$,$,$);\n"
    "#30= IFCFACILITY('fac01',#2,'MSE Wall Facility',$,$,$,$,$,.ELEMENT.);\n"
    "#31= IFCFACILITYPART('fp01',#2,'Section A',$,$,$,$,$,.ELEMENT.,.BELOWGROUND.);\n"
    "#40= IFCREINFORCEDSOIL('rs01',#2,'MSE Wall Panel 1',$,$,#100,$,$,$);\n"
    "#41= IFCREINFORCEDSOIL('rs02',#2,'MSE Wall Panel 2',$,$,#101,$,$,$);\n"
    "#42= IFCEARTHWORKSFILL('ef01',#2,'Backfill Zone 1',$,$,#102,$,$,$);\n"
    "#43= IFCPAVEMENT('pv01',#2,'Access Road Pavement',$,$,#103,$,$,$,$);\n"
    "#44= IFCKERB('kb01',#2,'Road Kerb',$,$,#104,$,$,$,$);\n"
    "#45= IFCALIGNMENT('al01',#2,'Road Alignment CL',$,$,$,$,$,$);\n"
    "#50= IFCRELCONTAINEDINSPATIALSTRUCTURE('rel01',#2,$,$,(#40,#41,#42,#43,#44,#45),#31);\n"
    "#100= IFCLOCALPLACEMENT($,#110);\n"
    "#101= IFCLOCALPLACEMENT($,#111);\n"
    "#102= IFCLOCALPLACEMENT($,#112);\n"
    "#103= IFCLOCALPLACEMENT($,#113);\n"
    "#104= IFCLOCALPLACEMENT($,#114);\n"
    "#110= IFCAXIS2PLACEMENT3D(#120,$,$);\n"
    "#111= IFCAXIS2PLACEMENT3D(#121,$,$);\n"
    "#112= IFCAXIS2PLACEMENT3D(#122,$,$);\n"
    "#113= IFCAXIS2PLACEMENT3D(#123,$,$);\n"
    "#114= IFCAXIS2PLACEMENT3D(#124,$,$);\n"
    "#120= IFCCARTESIANPOINT((0.0,0.0,0.0));\n"
    "#121= IFCCARTESIANPOINT((5.0,0.0,0.0));\n"
    "#122= IFCCARTESIANPOINT((0.0,5.0,0.0));\n"
    "#123= IFCCARTESIANPOINT((10.0,0.0,0.0));\n"
    "#124= IFCCARTESIANPOINT((15.0,0.0,0.0));\n"
    "ENDSEC;\n"
    "END-ISO-10303-21;\n"
)


def test_civil_ifc_parsing(tmp_path: Path) -> None:
    """Parse a minimal IFC4x3 file with civil infrastructure elements."""
    ifc_file = tmp_path / "civil_test.ifc"
    ifc_file.write_text(_MINIMAL_CIVIL_IFC, encoding="utf-8")

    result = process_ifc_file(ifc_file, tmp_path / "output")

    assert result["element_count"] >= 3, f"Expected ≥3 civil elements, got {result['element_count']}"

    # Collect element types (may be mixed case if DDC converter is installed)
    types_lower = {e["element_type"].lower() for e in result["elements"]}
    assert any("reinforcedsoil" in t or "reinforced soil" in t for t in types_lower), (
        f"Missing Reinforced Soil in {types_lower}"
    )
    assert any("earthworks" in t for t in types_lower), f"Missing Earthworks in {types_lower}"
    assert any("pavement" in t for t in types_lower), f"Missing Pavement in {types_lower}"

    disciplines = {e["discipline"] for e in result["elements"]}
    assert "civil" in disciplines, f"Expected 'civil' discipline in {disciplines}"


def test_civil_ifc_elements_have_geometry(tmp_path: Path) -> None:
    """Verify that parsed civil elements get bounding boxes for 3D preview."""
    ifc_file = tmp_path / "civil_test.ifc"
    ifc_file.write_text(_MINIMAL_CIVIL_IFC, encoding="utf-8")

    result = process_ifc_file(ifc_file, tmp_path / "output")

    # Elements should have at least bounding_box or mesh_ref for 3D rendering.
    # When DDC converter is available, elements may have mesh_ref from the
    # converter output.  When using the text parser fallback, elements get
    # bounding_box from placeholder COLLADA generation.
    has_geo = [
        e for e in result["elements"]
        if e.get("bounding_box") or e.get("mesh_ref")
    ]
    assert len(has_geo) >= 1, (
        f"Expected ≥1 elements with geometry info, got {len(has_geo)}"
    )


def test_civil_ifc_geometry_generated(tmp_path: Path) -> None:
    """Verify COLLADA geometry is generated for civil IFC elements."""
    ifc_file = tmp_path / "civil_test.ifc"
    ifc_file.write_text(_MINIMAL_CIVIL_IFC, encoding="utf-8")

    result = process_ifc_file(ifc_file, tmp_path / "output")

    assert result["has_geometry"] is True
    geo_path = Path(result["geometry_path"])
    assert geo_path.exists()
    assert geo_path.stat().st_size > 100

    # Elements should have mesh_ref
    for elem in result["elements"]:
        assert elem.get("mesh_ref") is not None, f"Element {elem['name']} missing mesh_ref"
