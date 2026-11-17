# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SET-001 / SET-002 and the tolerance profiles (demo, pack per market, project)."""

from __future__ import annotations

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.setting_out import tolerances as tol
from app.modules.setting_out.validators import RecordTraceableRule, StakeWithinToleranceRule


def _ctx(stakes: list[dict]) -> ValidationContext:
    return ValidationContext(data={"stakes": stakes}, metadata={"locale": "en"})


def _stake(**kw: object) -> dict:
    base = {
        "request": "SO-001",
        "point_id": "C-03",
        "measured": True,
        "verdict": "pass",
        "d_mm": 5.0,
        "dz_mm": None,
        "tol_h_mm": 10.0,
        "tol_v_mm": 10.0,
        "instrument": "TS",
        "control_ref": "CP1",
    }
    return {**base, **kw}


async def test_set_001_message_matches_the_course() -> None:
    results = await StakeWithinToleranceRule().validate(_ctx([_stake(verdict="fail", d_mm=15.0)]))
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].message == "Stake C-03 off by 15 mm, tolerance 10 mm"
    assert results[0].element_ref == "SO-001/C-03"


async def test_set_001_silent_on_pass_and_on_unmeasured() -> None:
    results = await StakeWithinToleranceRule().validate(_ctx([_stake(), _stake(measured=False, verdict="open")]))
    assert [r.passed for r in results] == [True]


async def test_set_001_reports_height_when_plan_is_within() -> None:
    results = await StakeWithinToleranceRule().validate(_ctx([_stake(verdict="fail", d_mm=1.0, dz_mm=-12.5)]))
    assert results[0].message == "Stake C-03 off by 12.5 mm, tolerance 10 mm"


@pytest.mark.parametrize(
    ("instrument", "control", "fires"), [("TS", "CP1", False), ("", "CP1", True), ("TS", " ", True)]
)
async def test_set_002(instrument: str, control: str, fires: bool) -> None:
    results = await RecordTraceableRule().validate(_ctx([_stake(instrument=instrument, control_ref=control)]))
    assert (not results[0].passed) is fires
    if fires:
        assert results[0].message == "Stakeout record C-03 has no instrument or control reference."


def test_demo_profile_is_labelled_and_global() -> None:
    assert tol.DEMO_PROFILE.name == "Demo 10 mm"
    assert tol.DEMO_PROFILE.reference == "Demo values, not a standard"
    assert tol.DEMO_PROFILE.for_item("column") == tol.Tolerance(10.0, 10.0)
    assert tol.builtin_profile("demo", ["*"]) is tol.DEMO_PROFILE


def test_pack_profiles_show_only_for_their_market() -> None:
    tol.clear_pack_tolerances()
    try:
        tol.register_pack_tolerance(
            "de",
            [tol.ToleranceProfile("pack:de_site", "DE site", "pack", {"column": tol.Tolerance(8.0)}, reference="ref")],
        )
        assert tol.pack_profiles_for(["*"]) == []
        assert tol.pack_profiles_for(["US"]) == []
        found = tol.pack_profiles_for(["DE"])
        assert [p.key for p in found] == ["pack:de_site"]
        assert found[0].country == "DE"
        assert found[0].for_item("column") == tol.Tolerance(8.0)
        assert found[0].for_item("kerb") is None
        assert tol.builtin_profile("pack:de_site", ["US"]) is None
    finally:
        tol.clear_pack_tolerances()


def test_pack_keys_are_namespaced() -> None:
    with pytest.raises(ValueError, match="pack:"):
        tol.register_pack_tolerance("DE", [tol.ToleranceProfile("plain", "x", "pack", {})])


def test_project_profile_from_json() -> None:
    p = tol.profile_from_items("project:1", "Mine", {"default": {"h_mm": 20, "v_mm": None}, "pile": {"h_mm": 50}})
    assert p.for_item("pile") == tol.Tolerance(50.0, None)
    assert p.for_item("wall") == tol.Tolerance(20.0, None)
