# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Point file reading on the Riverside Yard demo files and on the formats instruments write."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.survey_core.point_io import (
    PRESETS,
    detect_delimiter,
    guess_preset,
    parse_geojson,
    parse_points,
    resolve_duplicates,
)

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"


def _demo(name: str) -> str:
    return (DEMO / name).read_text(encoding="utf-8")


def test_control_file_reads_four_control_points() -> None:
    parsed = parse_points(_demo("control.csv"), columns=PRESETS["PNEZD"], delimiter=",")
    assert parsed.rows_read == 4
    assert parsed.problems == []
    assert [p.kind for p in parsed.points] == ["control"] * 4
    cp2 = next(p for p in parsed.points if p.point_id == "CP2")
    assert (cp2.e, cp2.n) == (389110.0, 5818990.0)


def test_existing_ground_reports_one_duplicate_and_keeps_the_first() -> None:
    parsed = parse_points(_demo("existing_ground.csv"), columns=PRESETS["PNEZD"], delimiter=",")
    assert parsed.rows_read == 78
    assert len(parsed.problems) == 1
    problem = parsed.problems[0]
    assert problem.rule_id == "SRV-003"
    assert problem.point_id == "EG-045"
    kept = resolve_duplicates(parsed.points, "keep_first")
    assert len(kept) == 77
    assert next(p for p in kept if p.point_id == "EG-045").e == 389000.0
    assert next(p for p in resolve_duplicates(parsed.points, "keep_last") if p.point_id == "EG-045").e == 389000.5


def test_identical_repeat_is_merged_without_a_problem() -> None:
    text = "A,10,20,1\nA,10,20,1\n"
    parsed = parse_points(text, columns=["point_id", "e", "n", "z"], delimiter=",")
    assert parsed.problems == []
    assert len(resolve_duplicates(parsed.points, "keep_first")) == 1


def test_delimiter_detection_on_the_demo_and_on_a_tab_file() -> None:
    assert detect_delimiter(_demo("control.csv"))[0] == ","
    delim, confidence = detect_delimiter("P1\t100.0\t200.0\t3.0\nP2\t101.0\t201.0\t3.1\n")
    assert delim == "\t"
    assert confidence >= 0.8


def test_whitespace_separated_txt() -> None:
    parsed = parse_points("1  389000.0  5819000.0  34.0  TOPO\n", columns=PRESETS["PENZD"], delimiter=" ")
    assert parsed.points[0].e == 389000.0
    assert parsed.points[0].kind == "topo"


def test_semicolon_file_with_decimal_comma() -> None:
    parsed = parse_points("P1;389000,125;5819000,5;34,2\n", columns=PRESETS["PENZD"][:4], delimiter=";")
    assert parsed.points[0].e == 389000.125
    assert parsed.points[0].z == 34.2


def test_northing_first_is_recognised_from_magnitudes() -> None:
    preset, confidence = guess_preset([r.split(",") for r in _demo("control.csv").splitlines()])
    assert preset == "PNEZD"
    assert confidence > 0.5


def test_header_row_names_the_columns() -> None:
    preset, confidence = guess_preset(
        [["Point", "Easting", "Northing", "Elevation", "Code"], ["1", "2", "3", "4", "x"]]
    )
    assert preset == "PENZD"
    assert confidence >= 0.9


def test_unreadable_number_is_a_problem_not_a_crash() -> None:
    parsed = parse_points(
        "P1,abc,5819000,34\nP2,389000,5819000,34\n", columns=["point_id", "e", "n", "z"], delimiter=","
    )
    assert parsed.rows_read == 2
    assert len(parsed.points) == 1
    assert parsed.problems[0].rule_id == "IMP-001"
    assert parsed.problems[0].line == 1


def test_header_row_is_skipped_on_request() -> None:
    parsed = parse_points("P,N,E,Z\nA,2,1,3\n", columns=PRESETS["PNEZD"][:4], delimiter=",", has_header=True)
    assert parsed.rows_read == 1
    assert parsed.points[0].e == 1.0


def test_enz_without_ids_numbers_the_points() -> None:
    parsed = parse_points("1,2,3\n4,5,6\n", columns=PRESETS["ENZ"], delimiter=",")
    assert [p.point_id for p in parsed.points] == ["1", "2"]


def test_mapping_needs_both_plan_coordinates() -> None:
    with pytest.raises(ValueError):
        parse_points("1,2\n", columns=["point_id", "e"], delimiter=",")


def test_geojson_points_default_to_wgs84_and_read_properties() -> None:
    doc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [13.38, 52.51, 34.0]},
                "properties": {"name": "CP9", "code": "CP"},
            },
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "properties": {}},
        ],
    }
    parsed, epsg = parse_geojson(json.dumps(doc))
    assert epsg == 4326
    assert parsed.rows_read == 2
    assert parsed.points[0].point_id == "CP9"
    assert parsed.points[0].kind == "control"
    assert parsed.problems[0].rule_id == "IMP-002"


def test_geojson_legacy_crs_member_is_honoured() -> None:
    doc = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32633"}},
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [389000, 5819000]}, "properties": {}}
        ],
    }
    parsed, epsg = parse_geojson(json.dumps(doc))
    assert epsg == 32633
    assert parsed.points[0].z is None
    assert parsed.points[0].point_id == "1"


def test_geojson_that_is_not_json_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_geojson("not json")
