"""Exports (P0-9): CSV presets, GeoJSON, GSI-16, LandXML and DXF, each read back."""

from __future__ import annotations

import io
import json

import pytest

from app.modules.survey_core.instrument_io import parse_gsi, parse_landxml_points
from app.modules.survey_core.point_export import (
    ExportPoint,
    ExportSurface,
    export_filename,
    to_csv,
    to_dxf,
    to_geojson,
    to_gsi16,
    to_landxml,
)

PTS = [
    ExportPoint("CP1", 389012.345, 5819020.111, 120.5, "CTRL", "control"),
    ExportPoint("T2", 389111.966, 5819028.827, -1.25, "TREE"),
    ExportPoint("S3", 389055.183, 5819104.166, None),
]
TIN = ExportSurface("Existing", [(0.0, 0.0, 1.0), (10.0, 0.0, 2.0), (0.0, 10.0, 3.0)], [(0, 1, 2)])


@pytest.mark.parametrize(
    ("preset", "first"),
    [
        ("PNEZD", "CP1,5819020.1110,389012.3450,120.5000,CTRL"),
        ("PENZD", "CP1,389012.3450,5819020.1110,120.5000,CTRL"),
        ("ENZ", "389012.3450,5819020.1110,120.5000"),
        ("NEZ", "5819020.1110,389012.3450,120.5000"),
    ],
)
def test_csv_presets(preset: str, first: str) -> None:
    lines = to_csv(PTS, preset).splitlines()
    assert lines[1] == first
    assert len(lines) == 4


def test_csv_delimiter_and_no_header() -> None:
    text = to_csv(PTS, "PNEZD", ";", header=False)
    assert text.splitlines()[0].startswith("CP1;5819020.1110;")
    assert "\t" in to_csv(PTS, "ENZ", "\\t")
    with pytest.raises(ValueError):
        to_csv(PTS, "XYZ")


def test_geojson_in_wgs84_and_a_local_grid_says_so() -> None:
    doc = json.loads(to_geojson(PTS, lambda es, ns: [(13.0 + i, 52.0) for i in range(len(es))]))
    assert doc["features"][0]["geometry"]["coordinates"] == [13.0, 52.0, 120.5]
    assert doc["features"][2]["geometry"]["coordinates"] == [15.0, 52.0]
    assert "crs" not in doc
    local = json.loads(to_geojson(PTS, None, "Site grid"))
    assert local["crs"]["properties"]["name"] == "Site grid"
    assert local["features"][0]["geometry"]["coordinates"][0] == 389012.345


@pytest.mark.parametrize(("unit", "file_unit"), [("m", "m"), ("ft", "feet"), ("ftUS", "feet")])
def test_gsi16_round_trip(unit: str, file_unit: str) -> None:
    out = parse_gsi(to_gsi16(PTS, unit))
    assert out.unit == file_unit
    got = {p.point_id: (p.e, p.n, p.z) for p in out.result.points}
    assert got["CP1"] == pytest.approx((389012.345, 5819020.111, 120.5), abs=1e-4)
    assert got["T2"][2] == pytest.approx(-1.25, abs=1e-4)
    assert got["S3"][2] is None


@pytest.mark.parametrize(("unit", "file_unit"), [("m", "m"), ("ftUS", "ftUS"), ("ft", "feet")])
def test_landxml_round_trip_keeps_the_unit(unit: str, file_unit: str) -> None:
    text = to_landxml(PTS, [TIN], unit=unit, epsg=32633, project_name="Yard")
    assert "EPSG:32633" in text or 'epsgCode="32633"' in text
    assert "<Surface" in text and "<F>" in text
    out = parse_landxml_points(text)
    assert out.unit == file_unit
    got = {p.point_id: (p.e, p.n) for p in out.result.points}
    assert got["CP1"] == pytest.approx((389012.345, 5819020.111), abs=1e-4)


def test_dxf_is_readable_with_layers_per_code_and_3d_faces() -> None:
    import ezdxf

    doc = ezdxf.read(io.StringIO(to_dxf(PTS, [TIN])))
    msp = doc.modelspace()
    points = list(msp.query("POINT"))
    assert len(points) == 3
    assert {e.dxf.layer for e in points} == {"SURVEY_CTRL", "SURVEY_TREE", "SURVEY"}
    assert points[0].dxf.location.x == pytest.approx(389012.345)
    assert len(list(msp.query("TEXT"))) == 3
    [face] = list(msp.query("3DFACE"))
    assert face.dxf.layer == "SURFACE_EXISTING"
    assert face.dxf.vtx2.z == pytest.approx(3.0)


def test_export_filename_is_safe() -> None:
    assert export_filename("survey points/../x", "landxml") == "survey_points____x.xml"
    assert export_filename("", "dxf") == "survey.dxf"
