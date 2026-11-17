# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reading readings files: the demo files, delimiters, decimal commas, dates and bad rows (no database)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.monitoring.readings_io import MAX_TEXT_BYTES, parse_decimal, parse_readings, parse_when
from app.modules.monitoring.service import infer_axis, usable

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "monitoring" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["monitoring"]


def test_lesson_1_file_reads_six_rows_in_three_epochs() -> None:
    result = parse_readings((DEMO / EXPECTED["lesson_1"]["file"]).read_text(encoding="utf-8"))
    assert result.rows_read == EXPECTED["lesson_1"]["rows_read"]
    assert result.problems == []
    assert len({r.at for r in result.readings}) == EXPECTED["lesson_1"]["epochs"]
    assert {r.point for r in result.readings} == {"MP-01", "MP-02"}
    first = next(r for r in result.readings if r.point == "MP-01")
    assert (first.z, first.at) == (Decimal("34.512"), datetime(2026, 10, 9, tzinfo=UTC))


def test_lesson_3_file_is_one_new_epoch() -> None:
    result = parse_readings((DEMO / EXPECTED["lesson_3"]["file"]).read_text(encoding="utf-8"))
    assert [(r.point, r.z, r.at.day) for r in result.readings] == [
        ("MP-01", Decimal("34.489"), 30),
        ("MP-02", Decimal("34.297"), 30),
    ]


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_delimiters_are_detected(delimiter: str) -> None:
    text = delimiter.join(["point", "date", "z"]) + "\n" + delimiter.join(["P1", "2026-10-09", "1.5"]) + "\n"
    result = parse_readings(text)
    assert [r.z for r in result.readings] == [Decimal("1.5")]


def test_decimal_comma_and_dotted_date_with_a_semicolon_file() -> None:
    result = parse_readings("Point;Date;E;N;Z\nPR-1;09.10.2026;389010,1234;5819020,5;34,512\n")
    r = result.readings[0]
    assert (r.e, r.n, r.z) == (Decimal("389010.1234"), Decimal("5819020.5000"), Decimal("34.5120"))
    assert r.at == datetime(2026, 10, 9, tzinfo=UTC)


def test_header_synonyms_and_a_byte_order_mark() -> None:
    result = parse_readings("﻿id,observed,height,reading\nA,2026-10-09T08:30,10.0,2.5\n")
    r = result.readings[0]
    assert (r.point, r.z, r.value, r.at.hour) == ("A", Decimal("10.0000"), Decimal("2.5000"), 8)


def test_values_are_rounded_half_up_to_four_places() -> None:
    assert parse_decimal("1.23455") == Decimal("1.2346")
    assert parse_decimal("-1.23455") == Decimal("-1.2346")


@pytest.mark.parametrize("raw", ["", "abc", "nan", "inf", "1e12", "1.2.3"])
def test_not_a_usable_number(raw: str) -> None:
    assert parse_decimal(raw) is None


def test_a_time_zone_is_converted_to_utc() -> None:
    assert parse_when("2026-10-09T10:00:00+02:00") == datetime(2026, 10, 9, 8, 0, tzinfo=UTC)
    assert parse_when("31.02.2026") is None
    assert parse_when("yesterday") is None


def test_bad_rows_are_reported_with_their_line_and_the_rest_still_reads() -> None:
    text = "\n".join(
        [
            "point,date,z",
            "P1,2026-10-09,1.000",
            "P2,not-a-date,1.000",
            "P3,2026-10-09,abc",
            "P4,2026-10-09,",
            ",2026-10-09,1.000",
            "P1,2026-10-09,2.000",
            "P5,2026-10-16,1.100",
        ]
    )
    result = parse_readings(text)
    assert result.rows_read == 7
    assert [r.point for r in result.readings] == ["P1", "P5"]
    assert [(p.line, p.point_id) for p in result.problems] == [(3, "P2"), (4, "P3"), (5, "P4"), (6, ""), (7, "P1")]
    assert "not a date" in result.problems[0].message
    assert "twice" in result.problems[-1].message


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("", "empty"),
        ("date,z\n2026-10-09,1\n", "point id"),
        ("point,z\nP1,1\n", "date"),
        ("point,date\nP1,2026-10-09\n", "E, N, Z or value"),
    ],
)
def test_a_header_without_the_needed_columns_stops_the_file(text: str, needle: str) -> None:
    result = parse_readings(text)
    assert result.readings == []
    assert needle in result.problems[0].message


def test_a_file_over_five_megabytes_is_refused() -> None:
    with pytest.raises(ValueError, match="5 MB"):
        parse_readings("point,date,z\n" + "P," * MAX_TEXT_BYTES)


def test_a_new_point_takes_its_axis_from_its_first_reading() -> None:
    def row(data: str):  # noqa: ANN202
        return parse_readings("point,date,e,n,z,value\n" + data + "\n").readings[0]

    assert infer_axis(row("A,2026-10-09,1,2,3,")) == ("3d", "prism")
    assert infer_axis(row("A,2026-10-09,1,2,,")) == ("horizontal", "prism")
    assert infer_axis(row("A,2026-10-09,,,3,")) == ("z", "settlement_pin")
    assert infer_axis(row("A,2026-10-09,,,,4")) == ("value", "convergence_chord")
    assert usable("z", row("A,2026-10-09,,,3,"))
    assert not usable("3d", row("A,2026-10-09,1,2,,"))
