# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SRV-001..003 on the cases DOMAIN.md names, at their edges, and in every language."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.survey_core.survey_math import SAME_POINT_TOLERANCE_M
from app.modules.survey_core.validators import (
    SURVEY_RULE_SET,
    CrsConfirmedRule,
    DuplicatePointRule,
    PointSetHasCrsRule,
    register_survey_validation_rules,
)

MESSAGES = Path(__file__).resolve().parents[3] / "app" / "core" / "validation" / "messages"
LOCALES = sorted(p.stem for p in MESSAGES.glob("*.json"))


def _ctx(data: dict, locale: str = "en") -> ValidationContext:
    return ValidationContext(data=data, metadata={"locale": locale})


def _pts(*rows: tuple) -> dict:
    return {"points": [{"point_id": r[0], "e": r[1], "n": r[2], "z": r[3] if len(r) > 3 else None} for r in rows]}


# -- SRV-001 -----------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_srv001_names_every_set_that_has_no_system() -> None:
    data = {
        "crs": {"horizontal_epsg": 32633},
        "point_sets": [
            {"id": "a", "name": "a.csv", "stored_epsg": None},
            {"id": "b", "name": "b.csv", "stored_epsg": 32633},
            {"id": "c", "name": "c.csv", "stored_epsg": 0},
        ],
    }
    results = await PointSetHasCrsRule().validate(_ctx(data))
    assert [r.element_ref for r in results] == ["a", "c"]
    assert all(r.severity == Severity.ERROR and not r.passed for r in results)


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [{}, {"point_sets": []}, {"crs": {}, "point_sets": None}])
async def test_srv001_passes_on_an_empty_project(data: dict) -> None:
    assert all(r.passed for r in await PointSetHasCrsRule().validate(_ctx(data)))


@pytest.mark.asyncio
async def test_srv001_fires_when_the_project_has_no_crs_row_at_all() -> None:
    data = {"point_sets": [{"id": "a", "name": "a.csv", "stored_epsg": None}]}
    [r] = await PointSetHasCrsRule().validate(_ctx(data))
    assert not r.passed


# -- SRV-002 -----------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "crs",
    [
        {"source": "user", "confirmed": False},
        {"source": "user", "confirmed": True},
        {"source": "detected", "confirmed": True, "detected_confidence": 0.5},
        {},
    ],
)
async def test_srv002_only_an_unconfirmed_detection_fires(crs: dict) -> None:
    assert all(r.passed for r in await CrsConfirmedRule().validate(_ctx({"crs": crs})))


@pytest.mark.asyncio
@pytest.mark.parametrize(("confidence", "shown"), [(0.0, "0.00"), (1, "1.00"), (0.8, "0.80"), (None, "?"), ("x", "?")])
async def test_srv002_shows_the_confidence_or_a_question_mark(confidence, shown: str) -> None:
    data = {"crs": {"horizontal_epsg": 32633, "source": "detected", "detected_confidence": confidence}}
    [r] = await CrsConfirmedRule().validate(_ctx(data))
    assert not r.passed
    assert r.severity == Severity.WARNING
    assert shown in r.message


# -- SRV-003 -----------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_srv003_a_millimetre_is_the_same_point_and_a_bit_more_is_not() -> None:
    tol = SAME_POINT_TOLERANCE_M
    same = _pts(("A", 100.0, 200.0, 5.0), ("A", 100.0 + tol * 0.9, 200.0 - tol * 0.9, 5.0 + tol * 0.9))
    other = _pts(("A", 100.0, 200.0, 5.0), ("A", 100.0 + tol * 1.5, 200.0, 5.0))
    assert all(r.passed for r in await DuplicatePointRule().validate(_ctx(same)))
    assert [r.element_ref for r in await DuplicatePointRule().validate(_ctx(other))] == ["A"]


@pytest.mark.asyncio
async def test_srv003_height_alone_makes_two_positions() -> None:
    [r] = await DuplicatePointRule().validate(_ctx(_pts(("A", 1.0, 2.0, 3.0), ("A", 1.0, 2.0, 3.5))))
    assert not r.passed


@pytest.mark.asyncio
async def test_srv003_a_missing_height_is_not_the_same_as_a_height() -> None:
    [r] = await DuplicatePointRule().validate(_ctx(_pts(("A", 1.0, 2.0), ("A", 1.0, 2.0, 0.0))))
    assert not r.passed


@pytest.mark.asyncio
async def test_srv003_three_readings_of_one_id_are_one_finding() -> None:
    data = _pts(("A", 1.0, 2.0), ("A", 5.0, 2.0), ("A", 9.0, 2.0), ("B", 1.0, 1.0))
    results = await DuplicatePointRule().validate(_ctx(data))
    assert [r.element_ref for r in results] == ["A"]


@pytest.mark.asyncio
async def test_srv003_ids_are_compared_exactly_after_trimming() -> None:
    assert [
        r.element_ref for r in await DuplicatePointRule().validate(_ctx(_pts((" A ", 1.0, 2.0), ("A", 9.0, 2.0))))
    ] == ["A"]
    assert all(r.passed for r in await DuplicatePointRule().validate(_ctx(_pts(("A", 1.0, 2.0), ("a", 9.0, 2.0)))))


@pytest.mark.asyncio
async def test_srv003_ignores_rows_it_cannot_read() -> None:
    data = {
        "points": [
            {"point_id": "", "e": 1.0, "n": 2.0},
            {"point_id": "A", "e": None, "n": 2.0},
            {"point_id": "A", "e": "abc", "n": 2.0},
            {"point_id": "A", "e": 1.0, "n": 2.0},
        ]
    }
    assert all(r.passed for r in await DuplicatePointRule().validate(_ctx(data)))


@pytest.mark.asyncio
async def test_srv003_decimals_from_the_database_are_read_like_floats() -> None:
    from decimal import Decimal

    data = _pts(("A", Decimal("389000.1234"), Decimal("5819000.5000"), Decimal("34.0000")))
    data["points"].append({"point_id": "A", "e": Decimal("389000.1300"), "n": Decimal("5819000.5000"), "z": None})
    assert [r.element_ref for r in await DuplicatePointRule().validate(_ctx(data))] == ["A"]


@pytest.mark.asyncio
async def test_srv003_twenty_thousand_points_pass_quickly() -> None:
    data = _pts(*((f"P{i}", 389000.0 + i, 5819000.0, 34.0) for i in range(20_000)))
    assert all(r.passed for r in await DuplicatePointRule().validate(_ctx(data)))


# -- every language ----------------------------------------------------------------------------------------------


def _failing_contexts() -> dict[str, tuple[type, dict]]:
    return {
        "SRV-001": (PointSetHasCrsRule, {"point_sets": [{"id": "a", "name": "field.csv", "stored_epsg": None}]}),
        "SRV-002": (
            CrsConfirmedRule,
            {"crs": {"horizontal_epsg": 32633, "source": "detected", "detected_confidence": 0.9}},
        ),
        "SRV-003": (DuplicatePointRule, _pts(("EG-045", 1.0, 2.0), ("EG-045", 3.0, 2.0))),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("rule_id", ["SRV-001", "SRV-002", "SRV-003"])
async def test_every_rule_speaks_every_locale_with_its_values_filled_in(rule_id: str, locale: str) -> None:
    rule_class, data = _failing_contexts()[rule_id]
    [result] = await rule_class().validate(_ctx(data, locale))
    assert not result.passed
    assert result.message and "{" not in result.message and "survey." not in result.message
    assert result.suggestion and "{" not in result.suggestion
    named = {"SRV-001": "field.csv", "SRV-002": "0.90", "SRV-003": "EG-045"}[rule_id]
    assert named in result.message


@pytest.mark.asyncio
@pytest.mark.parametrize(("locale", "script"), [("ar", "؀"), ("he", "֐"), ("fa", "؀"), ("ur", "؀")])
async def test_right_to_left_locales_answer_in_their_own_script(locale: str, script: str) -> None:
    rule_class, data = _failing_contexts()["SRV-003"]
    [result] = await rule_class().validate(_ctx(data, locale))
    assert any(script <= ch <= chr(ord(script) + 0xFF) for ch in result.message)


@pytest.mark.asyncio
async def test_an_unknown_locale_falls_back_to_english() -> None:
    rule_class, data = _failing_contexts()["SRV-001"]
    [result] = await rule_class().validate(_ctx(data, "xx"))
    assert "no CRS" in result.message


# -- registry ----------------------------------------------------------------------------------------------------


def test_the_survey_rule_set_holds_exactly_the_three_rules_with_their_severities() -> None:
    register_survey_validation_rules()
    rules = {r.rule_id: r for r in rule_registry.get_rules_for_sets([SURVEY_RULE_SET])}
    assert {k: rules[k].severity for k in ("SRV-001", "SRV-002", "SRV-003")} == {
        "SRV-001": Severity.ERROR,
        "SRV-002": Severity.WARNING,
        "SRV-003": Severity.ERROR,
    }


def test_survey_rules_do_not_leak_into_other_rule_sets() -> None:
    register_survey_validation_rules()
    other = {r.rule_id for r in rule_registry.get_rules_for_sets(["boq_quality"])}
    assert not {i for i in other if i.startswith("SRV-")}


def test_the_messages_bundle_has_the_same_keys_in_every_locale() -> None:
    reference = json.loads((MESSAGES / "en.json").read_text(encoding="utf-8"))["survey"]
    for locale in LOCALES:
        bundle = json.loads((MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))["survey"]
        assert {k: set(v) for k, v in bundle.items()} == {k: set(v) for k, v in reference.items()}, locale
