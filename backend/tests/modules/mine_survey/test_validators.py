# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""MIN-001 and MIN-002 on the lesson numbers, and the messages in every locale."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.messages import is_key_present
from app.modules.mine_survey.validators import (
    MINE_RULE_SET,
    ComplianceBandRule,
    TruckCountRule,
    register_mine_validation_rules,
)

MESSAGES = Path(__file__).resolve().parents[3] / "app" / "core" / "validation" / "messages"
KEYS = ("compliance_outside", "truck_differs")


def _ctx(entry: dict, locale: str = "en") -> ValidationContext:
    return ValidationContext(data={"entry": entry}, metadata={"locale": locale})


@pytest.mark.asyncio
async def test_min001_lesson_3_is_outside_the_95_105_band() -> None:
    entry = {"unit": "Pit N Bench 2", "compliance_pct": 94.96, "band_lo": 95, "band_hi": 105}
    [res] = await ComplianceBandRule().validate(_ctx(entry))
    assert not res.passed
    assert res.severity == Severity.WARNING
    assert "94.96" in res.message


@pytest.mark.asyncio
async def test_min001_is_silent_inside_the_band_and_without_a_profile() -> None:
    inside = {"compliance_pct": 100, "band_lo": 95, "band_hi": 105}
    assert all(r.passed for r in await ComplianceBandRule().validate(_ctx(inside)))
    edge = {"compliance_pct": 95, "band_lo": 95, "band_hi": 105}
    assert all(r.passed for r in await ComplianceBandRule().validate(_ctx(edge)))
    no_profile = {"compliance_pct": 40, "band_lo": None, "band_hi": None}
    assert all(r.passed for r in await ComplianceBandRule().validate(_ctx(no_profile)))


@pytest.mark.asyncio
async def test_min002_lesson_4_trucks_differ_by_4_47_percent_against_a_3_percent_check() -> None:
    entry = {"unit": "Pit N Bench 2", "truck_factor_pct": 4.47, "truck_tolerance_pct": 3}
    [res] = await TruckCountRule().validate(_ctx(entry))
    assert not res.passed
    assert "4.47" in res.message


@pytest.mark.asyncio
async def test_min002_respects_the_check_and_stays_silent_without_one() -> None:
    assert all(
        r.passed for r in await TruckCountRule().validate(_ctx({"truck_factor_pct": -2.9, "truck_tolerance_pct": 3}))
    )
    assert all(
        r.passed for r in await TruckCountRule().validate(_ctx({"truck_factor_pct": 9, "truck_tolerance_pct": None}))
    )


def test_rules_register_under_the_mine_survey_set() -> None:
    register_mine_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([MINE_RULE_SET])}
    assert {"MIN-001", "MIN-002"} <= ids


def test_every_locale_carries_both_messages() -> None:
    en = json.loads((MESSAGES / "en.json").read_text(encoding="utf-8"))["mine_survey"]
    for path in MESSAGES.glob("*.json"):
        bundle = json.loads(path.read_text(encoding="utf-8"))["mine_survey"]
        for key in KEYS:
            for part in ("fail", "suggestion"):
                assert is_key_present(f"mine_survey.{key}.{part}", path.stem), (path.name, key)
                if path.stem != "en":
                    assert bundle[key][part] != en[key][part], (path.name, key, part)
        assert "{c}" in bundle["compliance_outside"]["fail"], path.name
        assert "{v}" in bundle["truck_differs"]["fail"], path.name
