# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""MON-001, the threshold profiles (demo, pack per market, project) and the report PDF (no database)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.monitoring import profiles
from app.modules.monitoring.monitoring_math import Thresholds
from app.modules.monitoring.report_pdf import build_alarm_report
from app.modules.monitoring.schemas import Finding, PointOut, ProfileCreate
from app.modules.monitoring.validators import PointLevelRule

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "monitoring" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["monitoring"]


def _ctx(points: list[dict], locale: str = "en") -> ValidationContext:
    return ValidationContext(data={"points": points}, metadata={"locale": locale})


def _point(**kw: object) -> dict:
    return {"code": "MP-01", "level": "action", "displacement_mm": -23.0, "rate_mm_day": -1.14, **kw}


async def test_mon_001_message_matches_the_course() -> None:
    results = await PointLevelRule().validate(_ctx([_point()]))
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].message == EXPECTED["lesson_3"]["finding"]
    assert results[0].rule_id == EXPECTED["lesson_3"]["rule"]
    assert results[0].element_ref == "MP-01"


@pytest.mark.parametrize(
    ("level", "severity"),
    [("alert", Severity.WARNING), ("action", Severity.ERROR), ("alarm", Severity.ERROR)],
)
async def test_mon_001_severity_follows_the_level(level: str, severity: Severity) -> None:
    results = await PointLevelRule().validate(_ctx([_point(level=level)]))
    assert results[0].severity == severity


@pytest.mark.parametrize("level", ["ok", "none"])
async def test_mon_001_is_silent_below_alert_and_without_a_profile(level: str) -> None:
    results = await PointLevelRule().validate(_ctx([_point(level=level), _point(code="MP-02", level=level)]))
    assert [r.passed for r in results] == [True]


async def test_mon_001_reads_in_the_callers_language() -> None:
    results = await PointLevelRule().validate(
        _ctx([_point(level="alarm", displacement_mm=-31.2, rate_mm_day=None)], "de")
    )
    assert "-31.2" in results[0].message
    assert "-" in results[0].message


def test_the_demo_profile_is_labelled_and_offered_to_everyone() -> None:
    assert profiles.builtin_profile("demo", ["*"]) is profiles.DEMO_PROFILE
    assert profiles.DEMO_PROFILE.source == "demo"
    assert profiles.DEMO_PROFILE.country == ""


def test_a_pack_profile_shows_only_in_its_own_market() -> None:
    profiles.clear_pack_profiles()
    try:
        pack = profiles.MonitoringProfile("pack:de.wall", "DE wall", "pack", Thresholds(alert_mm=Decimal(5)))
        profiles.register_pack_profile("de", [pack])
        assert [p.key for p in profiles.pack_profiles_for(["DE"])] == ["pack:de.wall"]
        assert profiles.pack_profiles_for(["US"]) == []
        assert profiles.pack_profiles_for(["*"]) == []
        assert profiles.builtin_profile("pack:de.wall", ["US"]) is None
        with pytest.raises(ValueError, match="pack:"):
            profiles.register_pack_profile("DE", [profiles.MonitoringProfile("wall", "x", "pack", Thresholds())])
    finally:
        profiles.clear_pack_profiles()


def test_a_project_profile_needs_rising_thresholds_and_at_least_one() -> None:
    assert ProfileCreate(name="x", alert_mm=5, action_mm=10).alert_mm == 5
    with pytest.raises(ValueError, match="rise"):
        ProfileCreate(name="x", alert_mm=10, action_mm=5)
    with pytest.raises(ValueError, match="at least one"):
        ProfileCreate(name="x")


def _out(code: str, level: str, displacement: float, ack: str = "none") -> PointOut:
    return PointOut.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "project_id": "00000000-0000-0000-0000-000000000002",
            "code": code,
            "name": "",
            "point_type": "settlement_pin",
            "axis": "z",
            "location": "",
            "epochs": 4,
            "baseline_value": 34.512,
            "latest_value": 34.489,
            "displacement_mm": displacement,
            "rate_mm_day": -1.14,
            "level": level,
            "ack_state": ack,
        }
    )


def test_the_alarm_report_renders_in_english_and_in_another_script() -> None:
    from app.modules.monitoring.schemas import ProfileOut, ThresholdsOut

    profile = ProfileOut(
        key="demo", name="Demo wall profile", source="demo", reference="Demo values, not a standard",
        thresholds=ThresholdsOut(alert_mm=10, action_mm=20, alarm_mm=30),
    )  # fmt: skip
    points = [_out("MP-01", "action", -23.0, "pending"), _out("MP-02", "ok", -3.0)]
    finding = Finding(rule_id="MON-001", severity="error", message=EXPECTED["lesson_3"]["finding"])
    for locale in ("en", "ru", "ar"):
        pdf = build_alarm_report(points, project_name="Riverside Yard", crs_label="EPSG 32633", profile=profile,
                                 findings=[finding], locale=locale)  # fmt: skip
        assert pdf.startswith(b"%PDF")
    assert build_alarm_report([], project_name="P", crs_label="", profile=None, findings=[]).startswith(b"%PDF")
