# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Point export (CSV, DXF, LandXML), control check residuals and SRV-012, without a database."""

from __future__ import annotations

import io

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.survey_core.point_export import ExportPoint, _layer, to_csv, to_dxf, to_landxml
from app.modules.survey_core.register_service import residual, verdict
from app.modules.survey_core.validators import ControlCheckRule

POINTS = [
    ExportPoint("CP1", 388990.0, 5818990.0, 33.9, "CP", "Control NW"),
    ExportPoint("101", 389001.25, 5819002.5, None, "TOE"),
]


def test_csv_pnezd_writes_north_before_east_and_keeps_an_empty_height() -> None:
    text = to_csv(POINTS, "PNEZD", header=False)
    assert text.splitlines() == [
        "CP1,5818990.0000,388990.0000,33.9000,CP",
        "101,5819002.5000,389001.2500,,TOE",
    ]


def test_csv_penzd_with_header_and_semicolon() -> None:
    lines = to_csv(POINTS, "PENZD", ";", header=True).splitlines()
    assert lines[0] == "P;E;N;Z;D"
    assert lines[1].startswith("CP1;388990.0000;5818990.0000;33.9000")


def test_csv_refuses_an_unknown_preset() -> None:
    with pytest.raises(ValueError, match="preset"):
        to_csv(POINTS, "XYZQ")


def test_landxml_round_trips_through_the_surface_reader() -> None:
    from app.modules.surfaces_volumes.landxml import parse_landxml

    xml = to_landxml(POINTS, epsg=32633)
    assert '<CoordinateSystem epsgCode="32633"/>' in xml
    assert '<CgPoint name="CP1" code="CP" desc="Control NW">5818990.0000 388990.0000 33.9000</CgPoint>' in xml
    parsed = parse_landxml(xml)
    assert parsed.epsg == 32633


def test_dxf_has_a_layer_per_code_and_a_label_per_point() -> None:
    import ezdxf

    doc = ezdxf.read(io.StringIO(to_dxf(POINTS)))
    msp = doc.modelspace()
    points = list(msp.query("POINT"))
    assert {p.dxf.layer for p in points} == {"SURVEY_CP", "SURVEY_TOE"}
    assert points[0].dxf.location.z == pytest.approx(33.9)
    assert sorted(t.dxf.text for t in msp.query("TEXT")) == ["101", "CP1"]


def test_layer_names_lose_characters_dxf_forbids() -> None:
    assert _layer("A/B:C") == "SURVEY_A_B_C"
    assert _layer("") == "SURVEY"


def test_residual_is_measured_minus_known_in_millimetres() -> None:
    r = residual((1000.0, 2000.0, 50.0), (1000.006, 1999.996, 50.003))
    assert (r["de_mm"], r["dn_mm"], r["dz_mm"], r["d2d_mm"]) == (6.0, -4.0, 3.0, 7.2)
    assert residual((0.0, 0.0, None), (0.027, 0.012, 1.0))["dz_mm"] is None


def test_demo_check_shots_one_inside_one_outside_the_demo_tolerance() -> None:
    cp1 = residual((388990.0, 5818990.0, 33.9), (388990.006, 5818989.996, 33.903))
    cp3 = residual((389110.0, 5819070.0, 35.1), (389110.027, 5819070.012, 35.092))
    assert verdict(cp1["d2d_mm"], 20) == "pass"
    assert cp3["d2d_mm"] == 29.5
    assert verdict(cp3["d2d_mm"], 20) == "fail"
    assert verdict(cp3["d2d_mm"], None) == "no_tolerance"


def _ctx(data: dict) -> ValidationContext:
    return ValidationContext(data=data, metadata={"locale": "en"})


@pytest.mark.asyncio
async def test_srv_012_fires_only_beyond_the_profile_tolerance() -> None:
    rule = ControlCheckRule()
    out = await rule.validate(
        _ctx(
            {
                "control_checks": [
                    {"point_id": "CP1", "d2d_mm": 7.2, "tol_mm": 20},
                    {"point_id": "CP3", "d2d_mm": 29.5, "tol_mm": 20},
                    {"point_id": "CP4", "d2d_mm": 90.0, "tol_mm": None},
                ]
            }
        )
    )
    failed = [r for r in out if not r.passed]
    assert len(failed) == 1
    assert failed[0].element_ref == "CP3"
    assert "29.5 mm" in failed[0].message
    assert "20 mm" in failed[0].message
