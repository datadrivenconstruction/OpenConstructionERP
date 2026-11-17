# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""VOL-001..004: each rule on its case, quiet on a sound result, messages in every locale."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.messages import is_key_present
from app.modules.surfaces_volumes.validators import (
    VOLUME_RULE_SET,
    BankVolumeRule,
    CoarseScanRule,
    CoverageRule,
    SurfacesOverlapRule,
    register_volume_validation_rules,
)
from app.modules.surfaces_volumes.volumes import confidence

MESSAGES = Path(__file__).resolve().parents[3] / "app" / "core" / "validation" / "messages"
KEYS = ("no_overlap", "low_coverage", "coarse_scan", "bank_volume")
SOUND = {"code": "V-001", "coverage_pct": 100.0, "coverage_min_pct": 90.0, "accuracy_tier": "survey"}


def _ctx(volume: dict, locale: str = "en") -> ValidationContext:
    return ValidationContext(data={"volume": volume}, metadata={"locale": locale})


@pytest.mark.asyncio
@pytest.mark.parametrize("rule_class", [SurfacesOverlapRule, CoverageRule, CoarseScanRule])
async def test_sound_result_passes(rule_class) -> None:
    assert all(r.passed for r in await rule_class().validate(_ctx(SOUND)))


@pytest.mark.asyncio
async def test_vol001_no_overlap_is_an_error_and_vol002_stays_quiet() -> None:
    v = {**SOUND, "coverage_pct": 0.4}
    [res] = await SurfacesOverlapRule().validate(_ctx(v))
    assert not res.passed
    assert res.severity == Severity.ERROR
    assert "0.4" in res.message
    assert all(r.passed for r in await CoverageRule().validate(_ctx(v)))


@pytest.mark.asyncio
async def test_vol002_uses_the_profile_floor_then_the_advisory_90() -> None:
    v = {**SOUND, "coverage_pct": 85.0}
    [res] = await CoverageRule().validate(_ctx(v))
    assert not res.passed
    assert res.severity == Severity.WARNING
    assert "85" in res.message
    assert "90" in res.message
    assert all(r.passed for r in await CoverageRule().validate(_ctx({**v, "coverage_min_pct": 80.0})))
    [default] = await CoverageRule().validate(_ctx({**v, "coverage_min_pct": None}))
    assert not default.passed


@pytest.mark.asyncio
async def test_vol003_coarse_scan_needs_a_reason() -> None:
    v = {**SOUND, "accuracy_tier": "coarse"}
    [res] = await CoarseScanRule().validate(_ctx(v))
    assert not res.passed
    assert res.severity == Severity.ERROR
    ok = await CoarseScanRule().validate(_ctx({**v, "override_reason": "Stockpile estimate only"}))
    assert all(r.passed for r in ok)


@pytest.mark.asyncio
async def test_vol004_says_bank_volume_until_loose_cut_is_sent() -> None:
    [res] = await BankVolumeRule().validate(_ctx(SOUND, "de"))
    assert res.severity == Severity.INFO
    assert "Auflockerungsfaktor" in res.message
    assert all(r.passed for r in await BankVolumeRule().validate(_ctx({**SOUND, "last_sent_quantity": "loose_cut"})))


def test_confidence_drops_for_coverage_coarse_scans_and_missing_crs() -> None:
    assert confidence(100.0, "survey", True) == pytest.approx(1.0)
    assert confidence(80.0, "survey", True) == pytest.approx(0.8)
    assert confidence(100.0, "coarse", True) == pytest.approx(0.6)
    assert confidence(100.0, "survey", False) == pytest.approx(0.5)


def test_every_locale_carries_every_volume_message() -> None:
    en = json.loads((MESSAGES / "en.json").read_text(encoding="utf-8"))["volumes"]
    for path in MESSAGES.glob("*.json"):
        bundle = json.loads(path.read_text(encoding="utf-8"))["volumes"]
        for key in KEYS:
            for part in ("fail", "suggestion"):
                assert is_key_present(f"volumes.{key}.{part}", path.stem), (path.name, key)
                if path.stem != "en":
                    assert bundle[key][part] != en[key][part], (path.name, key, part)
        assert ("{c}" in bundle["low_coverage"]["fail"]) and ("{min}" in bundle["low_coverage"]["fail"]), path.name
        assert "{p}" in bundle["no_overlap"]["fail"], path.name


def test_rules_register_under_the_volume_rule_set() -> None:
    register_volume_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([VOLUME_RULE_SET])}
    assert {"VOL-001", "VOL-002", "VOL-003", "VOL-004"} <= ids
