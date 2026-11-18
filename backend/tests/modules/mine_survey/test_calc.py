# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The mine survey lessons from the shipped Riverside files: actual, compliance, trucks."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.mine_survey.calc import (
    compliance_pct,
    outside_band,
    parse_plan,
    parse_truck_loads,
    survey_tonnes,
    truck_factor_pct,
)
from app.modules.surfaces_volumes import volumes as vol
from app.modules.surfaces_volumes.tin import Tin

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["mine_survey"]


def _tin(name: str) -> Tin:
    e: list[float] = []
    n: list[float] = []
    z: list[float] = []
    with (DEMO / name).open(encoding="utf-8") as fh:
        for row in csv.reader(fh):
            n.append(float(row[1]))
            e.append(float(row[2]))
            z.append(float(row[3]))
    assert len(e) == 30
    return Tin.from_points(e, n, z)


@pytest.fixture(scope="module")
def actual():
    """Start of month against end of month: the surfaces_volumes engine, not a second implementation."""
    return vol.compute(_tin(EXPECTED["start_file"]), _tin(EXPECTED["end_file"]), vol.GRID, 10.0)


def test_lesson_1_plan_file_reads_the_bench() -> None:
    rows, problems = parse_plan((DEMO / EXPECTED["plan_file"]).read_text(encoding="utf-8"))
    assert problems == []
    [row] = rows
    assert (row.unit, row.unit_type) == (EXPECTED["unit"], EXPECTED["unit_type"])
    assert row.plan_m3 == Decimal(str(EXPECTED["lesson_1"]["plan_m3"]))
    assert row.plan_t == Decimal(str(EXPECTED["lesson_1"]["plan_t"]))
    assert row.density_t_m3 == Decimal(str(EXPECTED["lesson_1"]["density_t_m3"]))


def test_lesson_2_actual_is_11870_cubic_metres_on_full_coverage(actual) -> None:
    ex = EXPECTED["lesson_2"]
    assert round(actual.cut, 1) == ex["actual_m3"]
    assert actual.fill == 0
    assert actual.cell_size == ex["cell_size_m"]
    assert actual.coverage_pct == pytest.approx(ex["coverage_pct"])


def test_lesson_3_compliance_is_94_96_and_outside_the_band(actual) -> None:
    ex = EXPECTED["lesson_3"]
    pct = compliance_pct(round(actual.cut, 3), EXPECTED["lesson_1"]["plan_m3"])
    assert pct == Decimal(str(ex["compliance_pct"]))
    lo, hi = ex["band_pct"]
    assert outside_band(pct, lo, hi) is True
    assert outside_band(Decimal("95.00"), lo, hi) is False
    assert outside_band(Decimal("105.00"), lo, hi) is False
    assert outside_band(pct, None, None) is None


def test_lesson_4_trucks_24800_t_against_23740_t_is_plus_4_47(actual) -> None:
    ex = EXPECTED["lesson_4"]
    trucks = parse_truck_loads((DEMO / EXPECTED["truck_file"]).read_text(encoding="utf-8"), EXPECTED["unit"])
    assert trucks.problems == []
    assert trucks.loads == ex["loads"]
    assert trucks.tonnes == Decimal(str(ex["truck_t"]))
    t = survey_tonnes(round(actual.cut, 3), EXPECTED["lesson_1"]["density_t_m3"])
    assert t == Decimal("23740.00")
    assert truck_factor_pct(trucks.tonnes, t) == Decimal(str(ex["truck_factor_pct"]))


def test_domain_example_bench_compliance() -> None:
    assert compliance_pct(11870, 12500) == Decimal("94.96")


def test_truck_file_skips_other_units_and_reports_bad_rows() -> None:
    text = "date,unit,loads,payload_t\n2026-10-01,A,10,40\n2026-10-01,B,5,30\n2026-10-02,A,x,40\n2026-10-03,A,2.5,40\n"
    r = parse_truck_loads(text, "a")
    assert (r.loads, r.tonnes, r.rows) == (10, Decimal("400.00"), 1)
    assert r.problems == ["line 4", "line 5"]
    assert parse_truck_loads(text).loads == 15


def test_no_plan_or_no_survey_means_no_number() -> None:
    assert compliance_pct(None, 100) is None
    assert compliance_pct(5, 0) is None
    assert truck_factor_pct(100, None) is None
    assert survey_tonnes(None, 2) is None
