# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The stockpile lessons from the shipped Riverside files: volume, tonnes, variance."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.stockpiles.calc import pile_volume, tonnes, variance
from app.modules.surfaces_volumes.tin import Tin

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["stockpiles"]
BOOK = Decimal("8400")


def _tin(name: str) -> Tin:
    e: list[float] = []
    n: list[float] = []
    z: list[float] = []
    with (DEMO / name).open(encoding="utf-8") as fh:
        for row in csv.reader(fh):
            n.append(float(row[1]))
            e.append(float(row[2]))
            z.append(float(row[3]))
    assert len(e) == 81
    return Tin.from_points(e, n, z)


@pytest.fixture(scope="module")
def result():
    return pile_volume(_tin(EXPECTED["survey_file"]), _tin(EXPECTED["base_file"]))


def test_lesson_2_volume_is_4992_on_a_full_grid(result) -> None:
    ex = EXPECTED["lesson_2"]
    assert float(result.cut) == pytest.approx(ex["volume_m3"], abs=0.05)
    assert result.cell_size == ex["cell_size_m"]
    assert result.coverage_pct == pytest.approx(ex["coverage_pct"])


def test_lesson_2_assumed_density_gives_7987_20_and_minus_4_91_percent(result) -> None:
    ex = EXPECTED["lesson_2"]
    t = tonnes(round(float(result.cut), 1), Decimal(str(ex["density_t_m3"])))
    assert t == Decimal("7987.20")
    v = variance(t, BOOK)
    assert v is not None
    assert (v.delta_t, v.pct) == (Decimal("-412.80"), Decimal("-4.91"))


def test_lesson_3_measured_density_gives_8087_04_and_minus_3_73_percent(result) -> None:
    ex = EXPECTED["lesson_3"]
    t = tonnes(round(float(result.cut), 1), Decimal(str(ex["density_t_m3"])))
    assert t == Decimal("8087.04")
    v = variance(t, BOOK)
    assert v is not None
    assert (v.delta_t, v.pct) == (Decimal("-312.96"), Decimal("-3.73"))


def test_lesson_4_adjustment_brings_book_to_the_surveyed_tonnes() -> None:
    ex = EXPECTED["lesson_4"]
    assert BOOK + Decimal(str(ex["signed_t"])) == Decimal(str(ex["book_after_t"]))


def test_variance_is_none_without_a_book_and_pct_none_on_zero_book() -> None:
    assert variance(Decimal("10"), None) is None
    zero = variance(Decimal("10"), Decimal(0))
    assert zero is not None
    assert zero.pct is None
    assert zero.delta_t == Decimal("10.00")


def test_tonnes_rounds_half_up_to_two_decimals() -> None:
    assert tonnes(Decimal("1.005"), Decimal("1")) == Decimal("1.01")
    assert tonnes(1000.0, 1.62) == Decimal("1620.00")
