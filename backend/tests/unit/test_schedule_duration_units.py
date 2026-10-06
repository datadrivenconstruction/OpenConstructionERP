# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Q15: physical hour norms stay distinct from monetary resource allowances."""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from app.core.demo_projects import _enrich_position_metadata
from app.modules.schedule.service import _calc_duration_from_resources


def _duration(resources, **metadata):
    return _calc_duration_from_resources(
        {"resources": resources, **metadata},
        100,
        "m2",
        20000,
        20000,
        365,
        hours_per_day=8,
        work_days_per_week=5,
        assumed_workers=1,
    )


@pytest.mark.parametrize("kind", ["labor", "operator"])
@pytest.mark.parametrize(
    "unit",
    ["m2", "m³", "pcs", "lsum", "EUR", "%", "day", "days", "week", "hours/m2", "hourly", "kWh", "", None],
)
def test_non_hour_allowances_use_existing_fallback_without_mutation(kind, unit):
    resources = [{"type": kind, "unit": unit, "quantity": 2000, "unit_rate": 50, "estimated": True}]
    before = copy.deepcopy(resources)
    assert _duration(resources) == _duration([])
    assert _duration(resources)[1] == "estimated_fallback"
    assert resources == before


@pytest.mark.parametrize("kind", ["labor", "operator"])
@pytest.mark.parametrize(
    "unit",
    [
        "h",
        "hr",
        "hrs",
        "hour",
        "hours",
        " HR ",
        "Std.",
        "Stunde",
        "Stunden",
        "person-hour",
        "person-hours",
        "man-hour",
        "man-hours",
        "чел.-ч",
        "чел-ч",
        "чел.ч",
        "человеко-час",
        "chel.-ch",
        "chel-ch",
        "ч",
        "hod",
        "jam",
        "ora",
        "uur",
        "시간",
        "時間",
        "godz",
        "tim",
        "ชั่วโมง",
        "saat",
        "giờ",
    ],
)
def test_explicit_hour_units_preserve_physical_quantity(kind, unit):
    # Away from half-day rounding: 100 * 8 h / 8 h/day * 1.1 * 7/5 = 154.
    assert _duration([{"type": kind, "unit": unit, "quantity": "8"}]) == (154, "resource_sum")


def test_non_hour_labor_rows_do_not_invent_additional_workers():
    hourly = [{"type": "labor", "unit": "hr", "quantity": 8}]
    allowances = [{"type": "labor", "unit": "m2", "quantity": 1} for _ in range(30)]
    assert _duration(hourly + allowances) == _duration(hourly) == (154, "resource_sum")


def test_explicit_labor_hours_remains_primary_over_resource_units():
    resources = [{"type": "labor", "unit": "m2", "quantity": 99999}]
    assert _duration(resources, labor_hours=8, workers_per_unit=1) == (154, "labor_hours")


@pytest.mark.parametrize("kind", ["equipment", "machinery", "material", ""])
def test_plain_hr_non_labor_resources_keep_existing_exclusion(kind):
    assert _duration([{"type": kind, "unit": "hr", "quantity": 2000}]) == _duration([])


@pytest.mark.parametrize("unit", ["hrs", "hours", "person-hours", "man-hours", "machine-hours", "machine-hrs"])
def test_exact_legacy_hour_labels_keep_existing_non_labor_policy(unit):
    assert _duration([{"type": "equipment", "unit": unit, "quantity": 8}]) == (154, "resource_sum")


@pytest.mark.parametrize("unit", ["hours/m2", "hrs/week", "megahours", "hours-allowance"])
def test_legacy_hour_detection_does_not_match_substrings(unit):
    assert _duration([{"type": "equipment", "unit": unit, "quantity": 2000}]) == _duration([])


@pytest.mark.parametrize(
    "description",
    [
        "RCC M40 columns, ductile detailing",
        "Ductile-iron pipe",
        "Geotextile separation",
        "Textile finish",
        "Turnstile gates",
    ],
)
def test_tile_substrings_do_not_select_tilers(description):
    metadata = _enrich_position_metadata(description, "m2", 100, {})
    assert metadata["cwicr_ref"] != "CWICR-TIL-001"


@pytest.mark.parametrize(
    "description",
    [
        "Tile",
        "Tiles",
        "Floor TILE installation",
        "Anti-slip tiles",
        "Wall (tile)",
        "Wandfliesen",
        "Bodenfliesen",
        "Carrelage antidérapant",
        "Ceramic finish",
    ],
)
def test_real_tiling_words_and_existing_multilingual_stems_still_match(description):
    metadata = _enrich_position_metadata(description, "m2", 100, {})
    assert metadata["cwicr_ref"] == "CWICR-TIL-001"
    assert sum(Decimal(str(row["quantity"])) * Decimal(str(row["unit_rate"])) for row in metadata["resources"]) == 100
    labor = next(row for row in metadata["resources"] if row["type"] == "labor")
    assert labor["unit_rate"] == 46 and labor["unit"] == "hr"
