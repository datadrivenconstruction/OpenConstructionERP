# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project catalogue rules: each rule firing on its worked example and staying quiet on a sound catalogue."""

from __future__ import annotations

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.messages import is_key_present
from app.modules.project_catalogue.validators import (
    PROJECT_CATALOGUE_RULE_SET,
    PROJECT_CATALOGUE_RULES,
    CurrencyMatchesProjectRule,
    CurrencyStatedRule,
    DuplicateCodeRule,
    OverridePlausibleRule,
    RateInRangeRule,
    SourceCurrentRule,
    UnitPresentRule,
    register_project_catalogue_validation_rules,
)


def _wall(**kw: object) -> dict:
    item: dict = {
        "id": "i1",
        "code": "C30-WALL",
        "unit": "m3",
        "rate": "172.50",
        "currency": "EUR",
        "source_type": "cost_item",
        "source_rate": "185.00",
        "current_source_rate": "185.00",
        "source_found": True,
    }
    item.update(kw)
    return item


def _data(*items: dict, currency: str = "EUR") -> dict:
    return {"project": {"id": "p1", "currency": currency}, "items": list(items) or [_wall()]}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (RateInRangeRule, _data(_wall(rate="-1"))),
    (UnitPresentRule, _data(_wall(unit=" "))),
    (CurrencyStatedRule, _data(_wall(currency=""))),
    (DuplicateCodeRule, _data(_wall(), _wall(id="i2", code="c30-wall"))),
    (CurrencyMatchesProjectRule, _data(_wall(currency="USD"))),
    (OverridePlausibleRule, _data(_wall(rate="1725.00"))),
    (SourceCurrentRule, _data(_wall(current_source_rate="190.00"))),
]


@pytest.mark.parametrize(("rule_class", "bad"), CASES, ids=[c[0].__name__ for c in CASES])
async def test_rule_passes_sound_catalogue_and_fires_on_its_case(rule_class, bad) -> None:
    rule = rule_class()
    good = await _run(rule, _data())
    assert all(r.passed for r in good), [r.message for r in good]
    fired = [r for r in await _run(rule, bad) if not r.passed]
    assert len(fired) == 1
    assert "{" not in fired[0].message, fired[0].message
    assert not fired[0].message.startswith("project_catalogue."), fired[0].message


async def test_override_message_names_the_distance() -> None:
    fired = [r for r in await _run(OverridePlausibleRule(), _data(_wall(rate="1725.00"))) if not r.passed]
    assert "832.4" in fired[0].message
    assert fired[0].severity is Severity.WARNING


async def test_ordinary_negotiated_rate_is_not_flagged() -> None:
    results = await _run(OverridePlausibleRule(), _data(_wall(rate="172.50")))
    assert all(r.passed for r in results)


async def test_moved_source_is_info_with_both_prices() -> None:
    fired = [r for r in await _run(SourceCurrentRule(), _data(_wall(current_source_rate="190.00"))) if not r.passed]
    assert fired[0].severity is Severity.INFO
    assert "185" in fired[0].message and "190" in fired[0].message


async def test_missing_source_and_manual_rows_are_not_reported_as_moved() -> None:
    data = _data(
        _wall(source_found=False, current_source_rate=None),
        _wall(id="i2", code="OWN-1", source_type="manual", source_rate=None, current_source_rate=None),
    )
    assert all(r.passed for r in await _run(SourceCurrentRule(), data))


async def test_project_without_currency_judges_no_currency_mix() -> None:
    assert all(r.passed for r in await _run(CurrencyMatchesProjectRule(), _data(_wall(currency="USD"), currency="")))


async def test_messages_are_translated_for_german_reader() -> None:
    fired = [r for r in await _run(UnitPresentRule(), _data(_wall(unit="")), locale="de") if not r.passed]
    en = [r for r in await _run(UnitPresentRule(), _data(_wall(unit="")), locale="en") if not r.passed]
    assert fired[0].message != en[0].message


def test_every_own_message_key_has_english_text() -> None:
    for key in ("unit_present", "duplicate_code", "currency_differs", "override_far", "source_changed"):
        for part in ("fail", "suggestion"):
            assert is_key_present(f"project_catalogue.{key}.{part}", "en"), key


def test_rule_set_registers_every_rule() -> None:
    register_project_catalogue_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([PROJECT_CATALOGUE_RULE_SET])}
    assert ids == {cls.rule_id for cls in PROJECT_CATALOGUE_RULES}
