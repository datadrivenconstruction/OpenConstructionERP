# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""STK-001 and STK-002 on the lesson numbers, and the messages in every locale."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.messages import is_key_present
from app.modules.stockpiles.validators import (
    STOCKPILE_RULE_SET,
    BookVarianceRule,
    DensitySourceRule,
    register_stockpile_validation_rules,
)

MESSAGES = Path(__file__).resolve().parents[3] / "app" / "core" / "validation" / "messages"
KEYS = ("density_assumed", "variance_high")


def _ctx(survey: dict, locale: str = "en") -> ValidationContext:
    return ValidationContext(data={"survey": survey}, metadata={"locale": locale})


@pytest.mark.asyncio
async def test_stk001_flags_an_assumed_density_only() -> None:
    [res] = await DensitySourceRule().validate(_ctx({"code": "SP-001", "density_source": "assumed"}))
    assert not res.passed
    assert res.severity == Severity.WARNING
    for source in ("measured", "supplier"):
        assert all(r.passed for r in await DensitySourceRule().validate(_ctx({"density_source": source})))


@pytest.mark.asyncio
async def test_stk002_lesson_3_is_beyond_the_default_3_percent() -> None:
    [res] = await BookVarianceRule().validate(_ctx({"code": "SP-001", "variance_pct": -3.73, "tolerance_pct": None}))
    assert not res.passed
    assert "3.73" in res.message
    assert "3" in res.message


@pytest.mark.asyncio
async def test_stk002_respects_a_wider_tolerance_and_a_missing_book() -> None:
    wide = {"variance_pct": -3.73, "tolerance_pct": 5}
    assert all(r.passed for r in await BookVarianceRule().validate(_ctx(wide)))
    assert all(r.passed for r in await BookVarianceRule().validate(_ctx({"variance_pct": None})))
    edge = {"variance_pct": 3.0, "tolerance_pct": None}
    assert all(r.passed for r in await BookVarianceRule().validate(_ctx(edge)))


@pytest.mark.asyncio
async def test_stk002_message_is_translated() -> None:
    [res] = await BookVarianceRule().validate(_ctx({"variance_pct": -3.73}, "de"))
    assert not res.passed
    assert "Buchbestand" in res.message


def test_every_locale_carries_every_stockpile_message() -> None:
    en = json.loads((MESSAGES / "en.json").read_text(encoding="utf-8"))["stockpiles"]
    for path in MESSAGES.glob("*.json"):
        bundle = json.loads(path.read_text(encoding="utf-8"))["stockpiles"]
        for key in KEYS:
            for part in ("fail", "suggestion"):
                assert is_key_present(f"stockpiles.{key}.{part}", path.stem), (path.name, key)
                if path.stem != "en":
                    assert bundle[key][part] != en[key][part], (path.name, key, part)
        assert "{v}" in bundle["variance_high"]["fail"], path.name
        assert "{t}" in bundle["variance_high"]["fail"], path.name


def test_rules_register_under_the_stockpile_rule_set() -> None:
    register_stockpile_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([STOCKPILE_RULE_SET])}
    assert {"STK-001", "STK-002"} <= ids
