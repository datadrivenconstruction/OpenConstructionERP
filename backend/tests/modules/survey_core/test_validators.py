# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SRV-001..003: each rule firing on its case and staying quiet on a sound register."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.messages import is_key_present
from app.modules.survey_core.validators import (
    SURVEY_RULE_SET,
    SURVEY_RULES,
    CrsConfirmedRule,
    DuplicatePointRule,
    PointSetHasCrsRule,
    register_survey_validation_rules,
)

MESSAGES = Path(__file__).resolve().parents[3] / "app" / "core" / "validation" / "messages"


def _ctx(data: dict, locale: str = "en") -> ValidationContext:
    return ValidationContext(data=data, metadata={"locale": locale})


SOUND = {
    "crs": {"horizontal_epsg": 32633, "is_local_grid": False, "source": "user", "confirmed": True},
    "point_sets": [{"id": "s1", "name": "control.csv", "stored_epsg": 32633}],
    "points": [
        {"point_id": "CP1", "e": 388990.0, "n": 5818990.0, "z": 33.9},
        {"point_id": "CP2", "e": 389110.0, "n": 5818990.0, "z": 35.1},
    ],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("rule_class", SURVEY_RULES)
async def test_sound_register_passes_every_rule(rule_class) -> None:
    results = await rule_class().validate(_ctx(SOUND))
    assert all(r.passed for r in results)


@pytest.mark.asyncio
async def test_srv001_point_set_without_crs_is_an_error() -> None:
    data = {**SOUND, "point_sets": [{"id": "s2", "name": "field.csv", "stored_epsg": None}]}
    [result] = await PointSetHasCrsRule().validate(_ctx(data))
    assert not result.passed
    assert result.severity == Severity.ERROR
    assert "field.csv" in result.message
    assert "no CRS" in result.message


@pytest.mark.asyncio
async def test_srv001_is_quiet_on_a_local_grid_project() -> None:
    data = {
        "crs": {"is_local_grid": True, "source": "user", "confirmed": True},
        "point_sets": [{"id": "s2", "name": "field.csv", "stored_epsg": None}],
    }
    assert all(r.passed for r in await PointSetHasCrsRule().validate(_ctx(data)))


@pytest.mark.asyncio
async def test_srv002_detected_crs_needs_confirmation() -> None:
    data = {"crs": {"horizontal_epsg": 32633, "source": "detected", "detected_confidence": 0.92, "confirmed": False}}
    [result] = await CrsConfirmedRule().validate(_ctx(data))
    assert not result.passed
    assert result.severity == Severity.WARNING
    assert "0.92" in result.message


@pytest.mark.asyncio
async def test_srv002_confirmed_detection_passes() -> None:
    data = {"crs": {"horizontal_epsg": 32633, "source": "detected", "detected_confidence": 0.92, "confirmed": True}}
    assert all(r.passed for r in await CrsConfirmedRule().validate(_ctx(data)))


@pytest.mark.asyncio
async def test_srv003_riverside_eg045_duplicate() -> None:
    data = {
        "points": [
            {"point_id": "EG-045", "e": 389000.0, "n": 5819040.0, "z": 34.0},
            {"point_id": "EG-045", "e": 389000.5, "n": 5819040.0, "z": 34.0},
            {"point_id": "EG-046", "e": 389010.0, "n": 5819040.0, "z": 34.1},
            {"point_id": "EG-046", "e": 389010.0, "n": 5819040.0, "z": 34.1},
        ]
    }
    results = await DuplicatePointRule().validate(_ctx(data))
    assert [r.element_ref for r in results] == ["EG-045"]
    assert results[0].severity == Severity.ERROR
    assert "EG-045" in results[0].message


@pytest.mark.asyncio
async def test_messages_answer_in_the_callers_language() -> None:
    data = {**SOUND, "point_sets": [{"id": "s2", "name": "field.csv", "stored_epsg": None}]}
    [result] = await PointSetHasCrsRule().validate(_ctx(data, "de"))
    assert "Koordinatensystem" in result.message


def test_every_locale_carries_every_survey_message() -> None:
    keys = [
        f"survey.{k}.{part}"
        for k in ("no_crs", "crs_unconfirmed", "duplicate_point")
        for part in ("fail", "suggestion")
    ]
    for path in MESSAGES.glob("*.json"):
        bundle = json.loads(path.read_text(encoding="utf-8"))
        assert set(bundle["survey"]) == {"no_crs", "crs_unconfirmed", "duplicate_point"}, path.name
        for key in keys:
            assert is_key_present(key, path.stem), (path.name, key)


def test_rules_register_under_the_survey_rule_set() -> None:
    register_survey_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([SURVEY_RULE_SET])}
    assert {"SRV-001", "SRV-002", "SRV-003"} <= ids
