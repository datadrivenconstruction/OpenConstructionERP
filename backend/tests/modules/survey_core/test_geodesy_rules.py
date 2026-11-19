"""Geodesy rules SRV-020..025, 030..032 and 110: each fires on its case, passes otherwise, speaks every locale."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.survey_core.validators import (
    IMPORT_MESSAGE_KEYS,
    ExportCrsRule,
    FootDefinitionRule,
    GeoidInstalledRule,
    GroundGridRule,
    GsiUnitRule,
    LegacyGridRule,
    LocalGridPointsRule,
    LocalGridResidualRule,
    LocalGridScaleRule,
    RawObservationsRule,
)

MESSAGES = Path(__file__).resolve().parents[3] / "app" / "core" / "validation" / "messages"
LOCALES = sorted(p.stem for p in MESSAGES.glob("*.json"))
KEYS = (
    "geoid_missing",
    "legacy_grid",
    "local_grid_points",
    "local_grid_residual",
    "local_grid_scale",
    "ground_grid",
    "gsi_unit",
    "foot_definition",
    "raw_skipped",
    "export_crs",
)


def _ctx(data: dict, locale: str = "en") -> ValidationContext:
    return ValidationContext(data=data, metadata={"locale": locale})


async def _one(rule, data: dict, locale: str = "en"):  # noqa: ANN001, ANN202
    return await rule.validate(_ctx(data, locale))


@pytest.mark.parametrize("locale", LOCALES)
def test_every_locale_words_every_geodesy_key(locale: str) -> None:
    data = json.loads((MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))
    for key in KEYS:
        entry = data["survey"][key]
        assert entry["fail"].strip() and entry["suggestion"].strip(), (locale, key)
    sheet = data["setting_out"]["sheet"]
    for name in ("{csf}", "{grid}", "{ground}"):
        assert name in sheet["scale_line"], (locale, name)
    en = json.loads((MESSAGES / "en.json").read_text(encoding="utf-8"))["survey"]
    for key in KEYS:
        placeholders = {
            p
            for p in (
                "{v}",
                "{g}",
                "{epsg}",
                "{country}",
                "{p}",
                "{n}",
                "{r}",
                "{id}",
                "{t}",
                "{s}",
                "{d}",
                "{mm}",
                "{wi}",
                "{u}",
                "{a}",
                "{b}",
            )
            if p in en[key]["fail"]
        }
        for p in placeholders:
            assert p in data["survey"][key]["fail"], (locale, key, p)


@pytest.mark.asyncio
async def test_srv020_a_missing_geoid_warns_with_its_grid() -> None:
    [r] = await _one(
        GeoidInstalledRule(), {"crs": {"vertical_epsg": 7837, "geoid_available": False, "geoid_grid": "GCG2016"}}
    )
    assert not r.passed and r.severity == Severity.WARNING
    assert "7837" in r.message and "GCG2016" in r.message


@pytest.mark.asyncio
@pytest.mark.parametrize("crs", [{}, {"vertical_epsg": 7837}, {"vertical_epsg": 7837, "geoid_available": True}])
async def test_srv020_passes_without_a_height_system_or_with_the_grid(crs: dict) -> None:
    assert all(r.passed for r in await _one(GeoidInstalledRule(), {"crs": crs}))


@pytest.mark.asyncio
async def test_srv021_a_legacy_grid_names_the_primary() -> None:
    [r] = await _one(LegacyGridRule(), {"crs": {"legacy": {"epsg": 31467, "country": "DE", "primary": 25832}}})
    assert not r.passed and r.severity == Severity.INFO
    assert "31467" in r.message and "25832" in r.message
    assert all(r.passed for r in await _one(LegacyGridRule(), {"crs": {"horizontal_epsg": 25832}}))


@pytest.mark.asyncio
@pytest.mark.parametrize(("fitted", "passed"), [(0, False), (1, False), (2, True), (5, True)])
async def test_srv022_two_common_points(fitted: int, passed: bool) -> None:
    [r] = await _one(LocalGridPointsRule(), {"local_grid": {"fitted": fitted}})
    assert r.passed is passed
    if not passed:
        assert r.severity == Severity.ERROR


@pytest.mark.asyncio
async def test_srv022_no_local_grid_no_finding() -> None:
    assert all(r.passed for r in await _one(LocalGridPointsRule(), {}))


@pytest.mark.asyncio
async def test_srv023_only_with_a_configured_tolerance() -> None:
    grid = {"residuals": [{"point_id": "C", "r_mm": 5.1}, {"point_id": "A", "r_mm": 0.4}]}
    assert all(r.passed for r in await _one(LocalGridResidualRule(), {"local_grid": grid}))
    [r] = await _one(LocalGridResidualRule(), {"local_grid": {**grid, "residual_tol_mm": 3}})
    assert not r.passed and "5.1" in r.message and "C" in r.message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("grid", "passed"),
    [
        ({"scale": 1.0000156}, True),
        ({"scale": 1.0000156, "scale_tol_ppm": 10}, False),
        ({"scale": 1.0000156, "scale_tol_ppm": 50}, True),
        ({"scale": 0.3048}, False),  # feet read as metres, no tolerance needed
        ({}, True),
    ],
)
async def test_srv024_scale_far_from_one(grid: dict, passed: bool) -> None:
    [r] = await _one(LocalGridScaleRule(), {"local_grid": grid})
    assert r.passed is passed


@pytest.mark.asyncio
async def test_srv025_the_worked_example_warns_67_mm() -> None:
    [r] = await _one(GroundGridRule(), {"scale": {"diff_mm": 67.0, "distance_m": 250.0}})
    assert not r.passed and "67" in r.message and "250" in r.message
    assert all(x.passed for x in await _one(GroundGridRule(), {"scale": {"diff_mm": 0.4, "distance_m": 100}}))
    assert all(x.passed for x in await _one(GroundGridRule(), {}))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rule", "rule_id", "params", "needle"),
    [
        (GsiUnitRule(), "SRV-030", {"wi": "81", "u": "3"}, "81"),
        (FootDefinitionRule(), "SRV-031", {}, ""),
        (RawObservationsRule(), "SRV-032", {"n": 4}, "4"),
    ],
)
async def test_import_rules_word_the_parser_problems(rule, rule_id: str, params: dict, needle: str) -> None:  # noqa: ANN001
    data = {"import_problems": [{"rule_id": rule_id, "point_id": "P1", "params": params}, {"rule_id": "IMP-001"}]}
    [r] = await _one(rule, data)
    assert not r.passed and needle in r.message
    assert all(x.passed for x in await _one(rule, {"import_problems": []}))
    assert rule_id in IMPORT_MESSAGE_KEYS


@pytest.mark.asyncio
async def test_srv110_export_in_another_crs() -> None:
    [r] = await _one(ExportCrsRule(), {"export": {"epsg": 4326, "project_epsg": 25832}})
    assert not r.passed and "4326" in r.message and "25832" in r.message
    assert all(x.passed for x in await _one(ExportCrsRule(), {"export": {"epsg": 25832, "project_epsg": 25832}}))


@pytest.mark.asyncio
async def test_messages_are_translated_not_english_in_german() -> None:
    [r] = await _one(GroundGridRule(), {"scale": {"diff_mm": 67.0, "distance_m": 250.0}}, "de")
    assert "Gitter" in r.message
