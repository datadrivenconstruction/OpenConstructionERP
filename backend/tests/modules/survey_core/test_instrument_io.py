"""Instrument point files (P0-4): GSI-8/16, JobXML and LandXML CgPoints with explicit units."""

from __future__ import annotations

import pytest

from app.modules.survey_core.instrument_io import (
    FT,
    FT_US,
    convert_points,
    detect_format,
    parse_gsi,
    parse_jobxml,
    parse_landxml_points,
    resolve_unit,
)


def _w8(wi: str, unit: str, value: int, sign: str = "+") -> str:
    return f"{wi}..4{unit}{sign}{abs(value):08d}"


def _w16(wi: str, unit: str, value: int, sign: str = "+") -> str:
    return f"{wi}..4{unit}{sign}{abs(value):016d}"


def _gsi8(pid: str, unit: str, e: int, n: int, z: int) -> str:
    return " ".join(["110001+" + pid.rjust(8, "0"), _w8("81", unit, e), _w8("82", unit, n), _w8("83", unit, z)]) + " "


def _gsi16(pid: str, unit: str, e: int, n: int, z: int) -> str:
    words = ["110001+" + pid.rjust(16, "0"), _w16("81", unit, e), _w16("82", unit, n), _w16("83", unit, z)]
    return "*" + " ".join(words) + " "


@pytest.mark.parametrize(
    ("unit", "e_raw", "e", "file_unit"),
    [
        ("0", 12345678, 12345.678, "m"),  # millimetres
        ("6", 12345678, 1234.5678, "m"),  # 0.1 mm
        ("8", 12345678, 123.45678, "m"),  # 0.01 mm
        ("1", 12345678, 12345.678, "feet"),  # 0.001 ft
        ("7", 12345678, 1234.5678, "feet"),  # 0.0001 ft
    ],
)
def test_gsi8_unit_digit_sets_the_scale(unit: str, e_raw: int, e: float, file_unit: str) -> None:
    out = parse_gsi(_gsi8("P1", unit, e_raw, e_raw, 1000))
    [p] = out.result.points
    assert p.point_id == "P1"
    assert p.e == pytest.approx(e) and p.n == pytest.approx(e)
    assert out.unit == file_unit


def test_gsi16_reads_national_size_coordinates() -> None:
    text = _gsi16("101", "6", 3890123450, 58190201110, 1205000) + "\n" + _gsi16("102", "6", 3891119660, 58190288270, 0)
    out = parse_gsi(text)
    assert [p.point_id for p in out.result.points] == ["101", "102"]
    assert out.result.points[0].e == pytest.approx(389012.345)
    assert out.result.points[0].n == pytest.approx(5819020.111)
    assert out.result.points[0].z == pytest.approx(120.5)
    assert detect_format(text) == "gsi"


def test_negative_heights_keep_their_sign() -> None:
    line = " ".join(["110001+00000007", _w8("81", "0", 1000), _w8("82", "0", 2000), _w8("83", "0", 1500, "-")])
    [p] = parse_gsi(line).result.points
    assert p.point_id == "7" and p.z == pytest.approx(-1.5)


def test_srv030_an_unknown_unit_code_names_the_word() -> None:
    out = parse_gsi(_gsi8("P1", "3", 1000, 2000, 0))
    assert out.result.points == []
    probs = [p for p in out.result.problems if p.rule_id == "SRV-030"]
    assert [p.detail for p in probs] == ["81:3", "82:3", "83:3"]
    assert all(p.point_id == "P1" and p.line == 1 for p in probs)


def test_srv030_metres_and_feet_in_one_file_read_nothing() -> None:
    out = parse_gsi(_gsi8("P1", "0", 1000, 2000, 0) + "\n" + _gsi8("P2", "1", 1000, 2000, 0))
    assert out.result.points == []
    assert any(p.rule_id == "SRV-030" and p.detail == "mixed" for p in out.result.problems)


def test_srv032_raw_observations_are_counted_and_skipped() -> None:
    raw = "110002+00000002 21.324+12345678 22.324+09000000 31..00+00012345 "
    out = parse_gsi(_gsi8("P1", "0", 1000, 2000, 0) + "\n" + raw)
    assert len(out.result.points) == 1
    assert out.raw_skipped == 1
    assert any(p.rule_id == "SRV-032" and p.detail == "1" for p in out.result.problems)


# -- units -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("file_unit", "project", "choice", "expected"),
    [
        ("m", "m", "", "m"),
        ("ftUS", "m", "", "ftUS"),
        ("feet", "ft", "", "ft"),
        ("feet", "ftUS", "", "ftUS"),
        ("feet", "m", "", None),  # SRV-031: a metre project must choose
        ("feet", "m", "ftUS", "ftUS"),
        ("feet", "m", "ft", "ft"),
    ],
)
def test_srv031_a_foot_is_chosen_never_guessed(file_unit: str, project: str, choice: str, expected: str | None) -> None:
    assert resolve_unit(file_unit, project, choice) == expected


def test_the_two_feet_differ_by_two_ppm() -> None:
    assert FT == 0.3048
    ppm = (FT_US / FT - 1) * 1e6
    assert ppm == pytest.approx(2.0, abs=0.01)
    out = parse_gsi(_gsi8("P1", "1", 1_000_000_000 // 1000, 0, 0))
    convert_points(out.result.points, "ftUS", "m")
    assert out.result.points[0].e == pytest.approx(1_000_000 / 1000 * FT_US, abs=1e-4)


# -- JobXML ------------------------------------------------------------------------------------------------------

JOBXML_REDUCED = """<?xml version="1.0"?>
<JOBFile jobName="site" version="5.6">
  <FieldBook>
    <PointRecord ID="1"><Name>RAW1</Name></PointRecord>
  </FieldBook>
  <Reductions>
    <Point><Name>CP1</Name><Code>CTRL</Code>
      <Grid><North>5819020.111</North><East>389012.345</East><Elevation>120.5</Elevation></Grid></Point>
    <Point><Name>CP2</Name><Code></Code>
      <Grid><North>5819028.827</North><East>389111.966</East><Elevation></Elevation></Grid></Point>
  </Reductions>
</JOBFile>"""

JOBXML_FIELDBOOK = """<?xml version="1.0"?>
<JOBFile jobName="site" version="5.6"><FieldBook>
  <PointRecord ID="1"><Name>A</Name><Grid><North>100</North><East>200</East><Elevation>3</Elevation></Grid></PointRecord>
  <PointRecord ID="2"><Name>B</Name><ComputedGrid><North>110</North><East>210</East></ComputedGrid></PointRecord>
  <PointRecord ID="3"><Name>OBS</Name><Circle><HorizontalCircle>12.3</HorizontalCircle></Circle></PointRecord>
  <PointRecord ID="4" Deleted="true"><Name>GONE</Name><Grid><North>1</North><East>2</East></Grid></PointRecord>
</FieldBook></JOBFile>"""


def test_jobxml_reads_reductions_first_in_metres() -> None:
    out = parse_jobxml(JOBXML_REDUCED)
    assert out.unit == "m"
    assert [(p.point_id, p.e, p.n, p.z) for p in out.result.points] == [
        ("CP1", 389012.345, 5819020.111, 120.5),
        ("CP2", 389111.966, 5819028.827, None),
    ]
    assert detect_format(JOBXML_REDUCED) == "jobxml"


def test_jobxml_field_book_skips_raw_and_deleted_records() -> None:
    out = parse_jobxml(JOBXML_FIELDBOOK)
    assert [p.point_id for p in out.result.points] == ["A", "B"]
    assert out.raw_skipped == 1


# -- LandXML -----------------------------------------------------------------------------------------------------


def _landxml(units: str, body: str) -> str:
    return (
        '<?xml version="1.0"?><LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">'
        f"<Units>{units}</Units><CgPoints>{body}</CgPoints></LandXML>"
    )


@pytest.mark.parametrize(
    ("units", "expected"),
    [
        ('<Metric linearUnit="meter"/>', "m"),
        ('<Imperial linearUnit="USSurveyFoot"/>', "ftUS"),
        ('<Imperial linearUnit="internationalFoot"/>', "ft"),
        ('<Imperial linearUnit="foot"/>', "feet"),
    ],
)
def test_landxml_declares_its_linear_unit(units: str, expected: str) -> None:
    out = parse_landxml_points(_landxml(units, '<CgPoint name="1">100 200 3</CgPoint>'))
    assert out.unit == expected
    [p] = out.result.points
    assert (p.n, p.e, p.z) == (100.0, 200.0, 3.0)


def test_landxml_cgpoint_text_is_north_east_and_refs_resolve() -> None:
    body = '<CgPoint name="A" code="TREE">5819020.111 389012.345 120.5</CgPoint><CgPoint name="A2" pntRef="A"/>'
    out = parse_landxml_points(_landxml('<Metric linearUnit="meter"/>', body))
    a, a2 = out.result.points
    assert (a.e, a.n, a.code) == (389012.345, 5819020.111, "TREE")
    assert (a2.e, a2.n) == (a.e, a.n)


def test_xml_with_entities_is_refused() -> None:
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><LandXML>&a;</LandXML>'
    with pytest.raises(ValueError):
        parse_landxml_points(bomb)
