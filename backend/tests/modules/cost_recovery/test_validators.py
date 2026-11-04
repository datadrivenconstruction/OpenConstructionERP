# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Cost recovery rule set: each rule has a passing and a failing payload."""

from __future__ import annotations

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.cost_recovery.validators import (
    COST_RECOVERY_RULE_SET,
    ApportionmentTotalsRule,
    BackChargeCurrencyRule,
    BackChargeRangesRule,
    BackChargeReferencesRule,
    BackChargeStatusTransitionRule,
    register_cost_recovery_validation_rules,
)


def _bc(**kw: object) -> dict:
    base = {
        "id": "bc1",
        "project_id": "p1",
        "responsible_party": "Sub A",
        "gross_amount": "1000.00",
        "chargeable_pct": "0.5",
        "recovered_amount": "0",
        "currency": "USD",
        "status": "proposed",
    }
    base.update(kw)
    return base


def _share(**kw: object) -> dict:
    base = {"id": "s1", "party": "Sub A", "share_pct": "0.6", "share_amount": "300.00", "currency": "USD"}
    base.update(kw)
    return base


def _data(bc: dict | None = None, shares: list[dict] | None = None) -> dict:
    default = [_share(), _share(id="s2", party="B", share_pct="0.4", share_amount="200.00")]
    return {"back_charge": bc or _bc(), "apportionments": shares if shares is not None else default}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (ApportionmentTotalsRule, _data(), _data(shares=[_share(share_amount="100.00")])),
    (BackChargeRangesRule, _data(), _data(_bc(chargeable_pct="1.5"))),
    (BackChargeCurrencyRule, _data(), _data(_bc(currency=""))),
    (BackChargeReferencesRule, _data(), _data(_bc(responsible_party=" "))),
    (
        BackChargeStatusTransitionRule,
        _data(_bc(previous_status="proposed", status="agreed")),
        _data(_bc(previous_status="proposed", status="recovered")),
    ),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES, ids=lambda v: getattr(v, "__name__", ""))
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "money." not in failed[0].message


async def test_share_percentages_cannot_exceed_one() -> None:
    data = _data(shares=[_share(share_pct="0.7"), _share(id="s2", share_pct="0.7", share_amount="300.00")])
    assert any(not r.passed for r in await _run(ApportionmentTotalsRule(), data))


async def test_recovery_cannot_exceed_the_chargeable_amount() -> None:
    assert any(not r.passed for r in await _run(BackChargeRangesRule(), _data(_bc(recovered_amount="600"))))


async def test_share_currency_must_match_the_back_charge() -> None:
    results = await _run(BackChargeCurrencyRule(), _data(shares=[_share(currency="EUR")]))
    assert not results[0].passed


async def test_share_without_party_fails() -> None:
    assert any(not r.passed for r in await _run(BackChargeReferencesRule(), _data(shares=[_share(party="")])))


async def test_closed_back_charge_is_final() -> None:
    rule = BackChargeStatusTransitionRule()
    assert not (await _run(rule, _data(_bc(previous_status="waived", status="agreed"))))[0].passed


async def test_message_follows_locale() -> None:
    ru = await _run(BackChargeCurrencyRule(), _data(_bc(currency="")), locale="ru")
    assert "Валюта" in ru[0].message


def test_registered_under_rule_set() -> None:
    register_cost_recovery_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([COST_RECOVERY_RULE_SET])}
    assert len(ids) == 5
    assert "cost_recovery.apportionment_totals" in ids
