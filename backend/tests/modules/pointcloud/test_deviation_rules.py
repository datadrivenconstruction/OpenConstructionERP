# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Scan-vs-design validation rules PCD-001..003, with messages in two locales."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.pointcloud.deviation_rules import (
    OutOfToleranceShareRule,
    ScanCoverageRule,
    ScanOverDesignRule,
)

MESSAGES = Path(__file__).resolve().parents[3] / "app" / "core" / "validation" / "messages"


def _ctx(locale: str = "en", **dev: object) -> ValidationContext:
    base = {"ref": "SV-001 Pad", "points_compared": 24321, "tolerance_mm": 10.0, "coverage_pct": 100.0}
    return ValidationContext(data={"deviation": {**base, **dev}}, metadata={"locale": locale})


async def test_riverside_share_fires_pcd_001() -> None:
    (r,) = await OutOfToleranceShareRule().validate(_ctx(out_pct=6.91, threshold_pct=5.0))
    assert not r.passed
    assert r.severity == Severity.WARNING
    assert r.message == ("6.9 % of the scan points over SV-001 Pad lie outside the ±10 mm tolerance; the limit is 5 %.")
    assert r.element_ref == "SV-001 Pad"
    assert r.suggestion and "heatmap" in r.suggestion


async def test_share_at_the_limit_passes() -> None:
    (r,) = await OutOfToleranceShareRule().validate(_ctx(out_pct=5.0, threshold_pct=5.0))
    assert r.passed


async def test_default_threshold_is_five_percent() -> None:
    (r,) = await OutOfToleranceShareRule().validate(_ctx(out_pct=5.5))
    assert not r.passed


async def test_message_is_localised() -> None:
    (r,) = await OutOfToleranceShareRule().validate(_ctx("de", out_pct=12.0, threshold_pct=5.0))
    assert r.message.startswith("12 % der Scanpunkte über SV-001 Pad")


@pytest.mark.parametrize(("coverage", "passed"), [(79.9, False), (80.0, True)])
async def test_coverage_floor(coverage: float, passed: bool) -> None:
    (r,) = await ScanCoverageRule().validate(_ctx(coverage_pct=coverage))
    assert r.passed is passed
    if not passed:
        assert "79.9 %" in r.message
        assert "SV-001 Pad" in r.message


async def test_no_overlap_is_an_error() -> None:
    (r,) = await ScanOverDesignRule().validate(_ctx(points_compared=0, coverage_pct=0.0))
    assert not r.passed
    assert r.severity == Severity.ERROR
    assert r.message == "No scan point lies over design surface SV-001 Pad."
    (cov,) = await ScanCoverageRule().validate(_ctx(points_compared=0, coverage_pct=0.0))
    assert cov.passed  # one finding for one cause


def test_every_bundle_has_the_messages_with_the_same_placeholders() -> None:
    en = json.loads((MESSAGES / "en.json").read_text(encoding="utf-8"))
    bundles = sorted(MESSAGES.glob("*.json"))
    assert len(bundles) >= 38
    for path in bundles:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, msg in en["pointcloud"].items():
            for field in ("fail", "suggestion"):
                for ph in ("{surface}", "{share}", "{tol}", "{limit}", "{floor}"):
                    assert (ph in msg[field]) == (ph in data["pointcloud"][key][field]), (path.name, key, ph)
        assert set(data["pointcloud_report"]) == set(en["pointcloud_report"]), path.name
