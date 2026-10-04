# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The reported takeoff quantity, server side.

``effective_takeoff_quantity`` mirrors the frontend ``effectiveQuantity`` /
``effectiveUnit``: a linear row with a wall height reports wall area (length x
height minus openings), then slope, wastage and the typical multiplier apply.
Both sides run the SAME case table
(``frontend/src/features/takeoff/__tests__/fixtures/wall-quantity-cases.json``)
so the figure the takeoff ledger shows and the figure a new bill position gets
cannot drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.takeoff.service import _pick_takeoff_value, effective_takeoff_quantity

_CASES_PATH = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "features"
    / "takeoff"
    / "__tests__"
    / "fixtures"
    / "wall-quantity-cases.json"
)


def _row(case: dict[str, Any]) -> SimpleNamespace:
    """A stored measurement row as the service sees it."""
    mtype = case["type"]
    value = case["value"]
    return SimpleNamespace(
        id="m1",
        type=mtype,
        measurement_value=None if mtype == "count" else value,
        count_value=int(value) if mtype == "count" else None,
        volume=None,
        measurement_unit=case["unit"],
        is_deduction=False,
        metadata_=case["metadata"],
    )


def _load_cases() -> list[dict[str, Any]]:
    if not _CASES_PATH.is_file():
        return []
    return json.loads(_CASES_PATH.read_text(encoding="utf-8"))["cases"]


# Parametrized from the file at collection time, so a case added for the
# frontend is a case the backend runs too, with no slot count to keep in step.
_CASES = _load_cases()


def test_case_table_is_present_and_non_trivial() -> None:
    if not _CASES_PATH.is_file():
        pytest.skip("shared case table lives in the frontend tree, which is not checked out here")
    assert len(_CASES) >= 10
    assert any(c["expected_unit"] != c["unit"] for c in _CASES), "the table must include a wall (unit changes)"


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_matches_the_shared_case_table(case: dict[str, Any]) -> None:
    value, unit = effective_takeoff_quantity(_row(case))
    assert value == pytest.approx(case["expected_value"], abs=1e-4), case["name"]
    assert unit == case["expected_unit"], case["name"]


def test_raw_pick_stays_raw_geometry() -> None:
    """DWG takeoff and the revision compare read the raw value; a wall must not change it."""
    row = SimpleNamespace(
        id="w",
        type="distance",
        measurement_value=12.5,
        count_value=None,
        volume=None,
        measurement_unit="m",
        is_deduction=False,
        metadata_={"wall_height": 2.8},
    )
    assert _pick_takeoff_value(row) == 12.5
    assert effective_takeoff_quantity(row) == (35.0, "m2")


def test_a_deduction_has_no_reported_quantity() -> None:
    row = SimpleNamespace(
        id="d",
        type="area",
        measurement_value=3.0,
        count_value=None,
        volume=None,
        measurement_unit="m2",
        is_deduction=True,
        metadata_={},
    )
    assert effective_takeoff_quantity(row) == (None, None)


@pytest.mark.parametrize(
    "meta",
    [
        {"wall_height": True},
        {"wall_height": "2.8"},
        {"wall_height": float("nan")},
        {"wall_height": -1},
        {"multiplier": True, "wastage_pct": "10"},
    ],
)
def test_malformed_metadata_falls_back_to_the_raw_length(meta: dict[str, Any]) -> None:
    """The blob is client-written; junk must never turn into a quantity."""
    row = SimpleNamespace(
        id="x",
        type="distance",
        measurement_value=4.0,
        count_value=None,
        volume=None,
        measurement_unit="m",
        is_deduction=False,
        metadata_=meta,
    )
    assert effective_takeoff_quantity(row) == (4.0, "m")


def test_malformed_openings_are_ignored() -> None:
    row = SimpleNamespace(
        id="x",
        type="distance",
        measurement_value=10.0,
        count_value=None,
        volume=None,
        measurement_unit="m",
        is_deduction=False,
        metadata_={
            "wall_height": 2.0,
            "openings": ["junk", None, {"width": "1", "height": 2}, {"width": 1, "height": 1}],
        },
    )
    # 20 - (0 for the string width) - 1 = 19
    assert effective_takeoff_quantity(row) == (19.0, "m2")
