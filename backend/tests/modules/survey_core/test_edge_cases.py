# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Point files that instruments and people get wrong: empty, garbled, swapped, repeated, huge, right-to-left."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.survey_core.point_io import (
    MAX_TEXT_BYTES,
    PRESETS,
    detect_delimiter,
    guess_preset,
    parse_geojson,
    parse_points,
    resolve_duplicates,
)
from app.modules.survey_core.schemas import ImportRequest
from app.modules.survey_core.service import SurveyService, _d

PENZD = PRESETS["PENZD"]
PNEZD = PRESETS["PNEZD"]


# -- empty and garbled ------------------------------------------------------------------------------------------


def test_empty_text_reads_nothing_and_guesses_nothing() -> None:
    parsed = parse_points("", columns=PENZD, delimiter=",")
    assert (parsed.rows_read, parsed.points, parsed.problems) == (0, [], [])
    assert detect_delimiter("") == (",", 0.0)
    assert guess_preset([]) == ("PENZD", 0.0)


def test_blank_lines_and_comments_are_not_rows() -> None:
    parsed = parse_points("\n   \n# exported by the total station\n\n", columns=PENZD, delimiter=",")
    assert parsed.rows_read == 0


def test_header_only_file_has_no_rows() -> None:
    parsed = parse_points("Point,Easting,Northing,Elevation\n", columns=PENZD, delimiter=",", has_header=True)
    assert (parsed.rows_read, parsed.points) == (0, [])


def test_garbled_rows_are_reported_one_by_one_and_the_good_row_survives() -> None:
    text = "@@@@\n\x00\x01;;;\nP1,389000.5,5819000.5,34\n,,,\nP2,east,north,up\n"
    parsed = parse_points(text, columns=PENZD, delimiter=",")
    assert [p.point_id for p in parsed.points] == ["P1"]
    assert [(p.rule_id, p.line) for p in parsed.problems] == [
        ("IMP-001", 1),
        ("IMP-001", 2),
        ("IMP-001", 4),
        ("IMP-001", 5),
    ]


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "1e999", "12.5 ft", "389000.5m", "1.234,5", "--5", "0x10"])
def test_a_number_that_is_not_a_number_is_a_row_problem(bad: str) -> None:
    parsed = parse_points(f"P1;{bad};5819000;34\n", columns=PENZD, delimiter=";")
    assert parsed.points == []
    assert parsed.problems[0].rule_id == "IMP-001"


def test_a_row_with_too_few_cells_is_a_problem_not_a_crash() -> None:
    parsed = parse_points("P1,389000.5\n", columns=PENZD, delimiter=",")
    assert parsed.points == []
    assert parsed.problems[0].rule_id == "IMP-001"


def test_height_is_optional_but_a_garbled_height_is_not_silently_dropped() -> None:
    parsed = parse_points("P1,1,2,\nP2,1,2,high\n", columns=PENZD, delimiter=",")
    assert [p.point_id for p in parsed.points] == ["P1"]
    assert parsed.points[0].z is None
    assert parsed.problems[0].line == 2


def test_quoted_cell_with_the_delimiter_inside_stays_one_cell() -> None:
    parsed = parse_points('P1,1,2,3,"pole, steel"\n', columns=PENZD, delimiter=",")
    assert parsed.points[0].code == "pole, steel"


def test_bom_does_not_stick_to_the_first_point_id() -> None:
    parsed = parse_points("﻿P1,1,2,3\n", columns=PENZD, delimiter=",")
    assert parsed.points[0].point_id == "P1"


def test_windows_line_endings() -> None:
    parsed = parse_points("P1,1,2,3\r\nP2,4,5,6\r\n", columns=PENZD, delimiter=",")
    assert [p.point_id for p in parsed.points] == ["P1", "P2"]
    assert parsed.points[1].z == 6.0


# -- zero, negative, decimal comma -------------------------------------------------------------------------------


def test_zero_coordinates_are_a_point_and_a_zero_height_is_not_missing() -> None:
    [p] = parse_points("O,0,0,0\n", columns=PENZD, delimiter=",").points
    assert (p.e, p.n, p.z) == (0.0, 0.0, 0.0)
    assert p.z is not None


def test_negative_coordinates_on_a_local_grid() -> None:
    [p] = parse_points("W1,-120.250,-35.5,-2.125\n", columns=PENZD, delimiter=",").points
    assert (p.e, p.n, p.z) == (-120.25, -35.5, -2.125)


def test_decimal_comma_with_spaces_as_thousands_separator() -> None:
    [p] = parse_points("P1;389 000,125;5 819 000,5;34,2\n", columns=PENZD, delimiter=";").points
    assert (p.e, p.n, p.z) == (389000.125, 5819000.5, 34.2)


def test_decimal_comma_in_a_blank_separated_file() -> None:
    [p] = parse_points("P1 389000,5 5819000,25 34,1\n", columns=PENZD, delimiter=" ").points
    assert (p.e, p.n) == (389000.5, 5819000.25)


def test_arabic_indic_digits_are_read_as_numbers() -> None:
    [p] = parse_points("P1,٣٨٩٠٠٠,٥٨١٩٠٠٠,٣٤\n", columns=PENZD, delimiter=",").points
    assert (p.e, p.n, p.z) == (389000.0, 5819000.0, 34.0)


# -- swapped XY --------------------------------------------------------------------------------------------------


def test_northing_first_and_easting_first_are_told_apart_by_magnitude() -> None:
    en = [["A", "389000.1", "5819000.2", "34"], ["B", "389010.1", "5819010.2", "35"]]
    ne = [["A", "5819000.2", "389000.1", "34"], ["B", "5819010.2", "389010.1", "35"]]
    assert guess_preset(en)[0] == "PENZD"
    assert guess_preset(ne)[0] == "PNEZD"
    assert guess_preset(en)[1] > 0.6
    assert guess_preset(ne)[1] > 0.6


def test_header_names_decide_even_when_the_magnitudes_say_otherwise() -> None:
    rows = [["Point", "Northing", "Easting", "Z"], ["A", "389000.1", "5819000.2", "34"]]
    assert guess_preset(rows)[0] == "PNEZD"


def test_a_local_grid_gets_a_low_confidence_so_the_person_decides() -> None:
    rows = [["A", "100.5", "120.5", "1"], ["B", "110.5", "130.5", "1"], ["C", "120.5", "99.5", "1"]]
    _preset, confidence = guess_preset(rows)
    assert confidence <= 0.5


def test_reading_a_northing_first_file_as_easting_first_swaps_the_axes() -> None:
    text = "A,5819000.2,389000.1,34\n"
    wrong = parse_points(text, columns=PENZD, delimiter=",").points[0]
    right = parse_points(text, columns=PNEZD, delimiter=",").points[0]
    assert (wrong.e, wrong.n) == (right.n, right.e)
    assert (right.e, right.n) == (389000.1, 5819000.2)


# -- duplicate ids -----------------------------------------------------------------------------------------------


def _dups():
    text = "A,10,20,1\nB,1,1,1\nA,10.5,20,1\nA,10,20,1\n"
    return parse_points(text, columns=PENZD, delimiter=",")


def test_a_conflicting_id_is_flagged_once_at_the_second_reading() -> None:
    parsed = _dups()
    assert [(p.rule_id, p.point_id, p.line) for p in parsed.problems] == [("SRV-003", "A", 3)]


def test_three_readings_keep_first_keep_last_and_skip() -> None:
    pts = _dups().points
    assert [(p.point_id, p.e) for p in resolve_duplicates(pts, "keep_first")] == [("A", 10.0), ("B", 1.0)]
    assert [(p.point_id, p.e) for p in resolve_duplicates(pts, "keep_last")] == [("B", 1.0), ("A", 10.0)]
    assert [p.point_id for p in resolve_duplicates(pts, "skip")] == ["B"]


def test_a_repeat_with_only_another_height_is_a_conflict() -> None:
    parsed = parse_points("A,10,20,1\nA,10,20,2\n", columns=PENZD, delimiter=",")
    assert [p.rule_id for p in parsed.problems] == ["SRV-003"]


def test_a_repeat_without_a_height_differs_from_one_with_a_height() -> None:
    parsed = parse_points("A,10,20,1\nA,10,20,\n", columns=PENZD, delimiter=",")
    assert [p.rule_id for p in parsed.problems] == ["SRV-003"]


def test_skip_keeps_a_harmless_repeat_once() -> None:
    parsed = parse_points("A,10,20,1\nA,10,20,1\n", columns=PENZD, delimiter=",")
    assert len(resolve_duplicates(parsed.points, "skip")) == 1


def test_ids_without_a_column_are_numbered_so_none_collide() -> None:
    parsed = parse_points("1,2,3\n1,2,3\n", columns=PRESETS["ENZ"], delimiter=",")
    assert [p.point_id for p in parsed.points] == ["1", "2"]
    assert parsed.problems == []


# -- mixed kinds -------------------------------------------------------------------------------------------------


def test_codes_name_their_kind_and_a_kind_column_wins() -> None:
    cols = ["point_id", "e", "n", "z", "code", "kind"]
    text = "A,1,2,3,cp,\nB,1,2,3,BM,\nC,1,2,3,CP,stake\nD,1,2,3,TREE,weird\nE,1,2,3,,asbuilt\n"
    kinds = [p.kind for p in parse_points(text, columns=cols, delimiter=",", default_kind="topo").points]
    assert kinds == ["control", "benchmark", "stake", "topo", "asbuilt"]


def test_an_unknown_default_kind_falls_back_to_topo() -> None:
    [p] = parse_points("A,1,2,3\n", columns=PENZD, delimiter=",", default_kind="nonsense").points
    assert p.kind == "topo"


# -- large input -------------------------------------------------------------------------------------------------


def test_a_hundred_thousand_rows_read_in_one_pass() -> None:
    text = "".join(f"P{i},{389000 + i % 977}.123,{5819000 + i % 983}.456,{34 + i % 7}.1\n" for i in range(100_000))
    assert len(text.encode()) < MAX_TEXT_BYTES
    parsed = parse_points(text, columns=PENZD, delimiter=",")
    assert (parsed.rows_read, len(parsed.points)) == (100_000, 100_000)
    assert parsed.problems == []


def test_a_file_just_over_the_limit_is_refused() -> None:
    line = "P1,389000.123,5819000.456,34.1\n"
    ok = line * (MAX_TEXT_BYTES // len(line))
    parse_points(ok, columns=PENZD, delimiter=",")
    with pytest.raises(ValueError, match="5 MB"):
        parse_points(ok + line * 2, columns=PENZD, delimiter=",")


def test_the_limit_counts_bytes_not_characters() -> None:
    text = "P1,1,2,3," + "ж" * (MAX_TEXT_BYTES // 2 + 10) + "\n"
    assert len(text) < MAX_TEXT_BYTES
    with pytest.raises(ValueError, match="5 MB"):
        parse_points(text, columns=PENZD, delimiter=",")


def test_import_request_refuses_text_over_the_schema_limit() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ImportRequest(text="x" * 6_000_001)


def test_a_file_over_five_megabytes_without_a_stated_delimiter_is_a_422_not_a_crash() -> None:
    """Preview and import guess the delimiter first; that step must answer like the parse step does."""
    req = ImportRequest(text="P1,389000.123,5819000.456,34.1\n" * 180_000)
    assert len(req.text.encode()) > MAX_TEXT_BYTES
    with pytest.raises(HTTPException) as err:
        SurveyService(None)._parse(req)  # type: ignore[arg-type]
    assert err.value.status_code == 422


# -- values the register cannot store ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row",
    [
        "P1,1e10,5,3",  # E is Numeric(14,4): ten integer digits at most
        "P1,5,-1e10,3",
        "P1,5,5,1e6",  # Z is Numeric(10,4): six integer digits at most
        "P1,5,5,3,,,10000",  # sigma is Numeric(8,4): four integer digits at most
    ],
)
def test_a_value_beyond_the_column_is_a_row_problem_not_a_database_error(row: str) -> None:
    cols = ["point_id", "e", "n", "z", "code", "description", "sigma"]
    parsed = parse_points(row + "\n", columns=cols, delimiter=",")
    assert parsed.points == []
    assert parsed.problems[0].rule_id == "IMP-001"


def test_the_largest_storable_values_still_import() -> None:
    cols = ["point_id", "e", "n", "z", "code", "description", "sigma"]
    parsed = parse_points("P1,9999999999.9999,-9999999999.9999,999999.9999,,,9999.9999\n", columns=cols, delimiter=",")
    assert len(parsed.points) == 1


def test_geojson_nan_and_infinity_are_row_problems() -> None:
    point = '{"type":"Feature","geometry":{"type":"Point","coordinates":%s},"properties":{}}'
    text = '{"type":"FeatureCollection","features":[' + point % "[NaN,52.5]" + "," + point % "[13.4,Infinity]" + "]}"
    parsed, _epsg = parse_geojson(text)
    assert parsed.points == []
    assert [p.rule_id for p in parsed.problems] == ["IMP-001", "IMP-001"]


def test_coordinates_are_kept_as_decimals_to_a_tenth_of_a_millimetre() -> None:
    assert _d(0.1 + 0.2) == Decimal("0.3000")
    assert _d(389000.1234) == Decimal("389000.1234")
    assert _d(-0.00004) == Decimal("0.0000")
    assert _d(None) is None
    assert isinstance(_d(1.5), Decimal)


# -- right-to-left text ------------------------------------------------------------------------------------------


def test_arabic_and_hebrew_ids_codes_and_descriptions_round_trip() -> None:
    text = "نقطة-١,389000,5819000,34,CP,عمود\nנקודה-2,389010,5819010,35,BM,מפלס\n"
    a, b = parse_points(text, columns=[*PENZD, "description"], delimiter=",").points
    assert (a.point_id, a.description, a.kind) == ("نقطة-١", "عمود", "control")
    assert (b.point_id, b.description, b.kind) == ("נקודה-2", "מפלס", "benchmark")


def test_a_long_right_to_left_id_is_cut_at_the_column_width() -> None:
    [p] = parse_points("ب" * 100 + ",1,2,3\n", columns=PENZD, delimiter=",").points
    assert len(p.point_id) == 64


def test_geojson_with_right_to_left_names() -> None:
    doc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [46.7, 24.7]},
                "properties": {"name": "الرياض"},
            }
        ],
    }
    parsed, epsg = parse_geojson(json.dumps(doc, ensure_ascii=False))
    assert (parsed.points[0].point_id, epsg) == ("الرياض", 4326)


# -- GeoJSON edges -----------------------------------------------------------------------------------------------


def test_empty_feature_collection_reads_nothing() -> None:
    parsed, epsg = parse_geojson('{"type":"FeatureCollection","features":[]}')
    assert (parsed.rows_read, parsed.points, epsg) == (0, [], 4326)


def test_multipoint_gets_numbered_ids() -> None:
    doc = {
        "type": "Feature",
        "geometry": {"type": "MultiPoint", "coordinates": [[1, 2], [3, 4, 5]]},
        "properties": {"name": "M"},
    }
    parsed, _ = parse_geojson(json.dumps(doc))
    assert [(p.point_id, p.z) for p in parsed.points] == [("M-1", None), ("M-2", 5.0)]


@pytest.mark.parametrize("text", ["[]", '"x"', '{"type":"Topology"}', "", "{"])
def test_geojson_that_is_not_a_feature_collection_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse_geojson(text)


def test_geojson_point_without_coordinates_is_a_row_problem() -> None:
    doc = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": {"type": "Point"}, "properties": {}}],
    }
    parsed, _ = parse_geojson(json.dumps(doc))
    assert parsed.points == []
    assert len(parsed.problems) == 1
