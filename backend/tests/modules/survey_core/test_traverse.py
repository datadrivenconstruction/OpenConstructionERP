# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lesson 4: the Riverside traverse closes at 1:11,731; SRV-010 and SRV-011 judge against the profile."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.survey_core.traverse import (
    FAIL,
    NO_PROFILE,
    PASS,
    close_traverse,
    level_verdict,
    parse_legs,
    traverse_verdict,
)
from app.modules.survey_core.validators import LevelRunRule, TraverseClosureRule

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["survey_register"]["lesson_4"]


def test_riverside_traverse_matches_lesson_4() -> None:
    legs = parse_legs((DEMO / "traverse_legs.csv").read_text(encoding="utf-8"))
    r = close_traverse(legs)
    assert len(legs) == 4
    assert r.length_m == pytest.approx(EXPECTED["length_m"], abs=1e-6)
    assert r.f_e == pytest.approx(EXPECTED["f_e_m"], abs=5e-4)
    assert r.f_n == pytest.approx(EXPECTED["f_n_m"], abs=5e-4)
    assert r.misclosure_m == pytest.approx(EXPECTED["misclosure_m"], abs=5e-4)
    # 612.40 / 0.052202 = 11,731.5: the specs' 1:11,732 rounds the wrong way.
    assert r.ratio == 11731
    c_e, c_n = r.corrections[0]
    assert c_e == pytest.approx(-0.0109, abs=1e-4)
    assert c_n == pytest.approx(0.0080, abs=1e-4)
    assert sum(c[0] for c in r.corrections) == pytest.approx(-r.f_e, abs=1e-9)


def test_verdicts_follow_the_profile_and_say_so_without_one() -> None:
    assert traverse_verdict(11731, 10000) == PASS
    assert traverse_verdict(11731, 20000) == FAIL
    assert traverse_verdict(11731, None) == NO_PROFILE
    allowed, verdict = level_verdict(9.0, 4.0, 4.0)
    assert allowed == pytest.approx(8.0)
    assert verdict == FAIL
    assert level_verdict(9.0, 4.0, None) == (None, NO_PROFILE)


def test_parse_legs_refuses_a_file_without_the_columns() -> None:
    with pytest.raises(ValueError):
        parse_legs("a,b,c\n1,2,3\n")


def _ctx(traverses: list[dict], locale: str = "en") -> ValidationContext:
    return ValidationContext(data={"traverses": traverses}, metadata={"locale": locale})


@pytest.mark.asyncio
async def test_srv010_fires_below_the_profile_ratio_only() -> None:
    row = {"id": "t1", "name": "Loop A", "kind": "traverse", "ratio": 11731, "profile_ratio": 20000}
    [res] = await TraverseClosureRule().validate(_ctx([row]))
    assert not res.passed
    assert res.severity == Severity.ERROR
    assert "11,731" in res.message
    assert "20,000" in res.message
    ok = await TraverseClosureRule().validate(_ctx([{**row, "profile_ratio": 10000}]))
    assert all(r.passed for r in ok)
    # No profile: no core default, no finding.
    none = await TraverseClosureRule().validate(_ctx([{**row, "profile_ratio": None}]))
    assert all(r.passed for r in none)


@pytest.mark.asyncio
async def test_srv011_warns_on_a_level_run_over_allowance() -> None:
    row = {"id": "l1", "name": "Run", "kind": "level", "misclosure_mm": 9.0, "allowed_mm": 8.0, "k_mm": 4.0}
    [res] = await LevelRunRule().validate(_ctx([row], "de"))
    assert not res.passed
    assert res.severity == Severity.WARNING
    assert "9.0" in res.message
    assert "Nivellement" in res.message
