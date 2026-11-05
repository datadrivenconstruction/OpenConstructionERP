# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Allowance rules: each rule firing, a valid record passing, the API refusing a blocking one."""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.allowances.models import Allowance
from app.modules.allowances.permissions import register_allowances_permissions
from app.modules.allowances.router import router as allowances_router
from app.modules.allowances.validators import (
    ALLOWANCES_RULE_SET,
    AllowanceAmountsInRangeRule,
    AllowanceCurrencyRule,
    AllowanceOverdrawnRule,
    DrawdownExplainedRule,
    register_allowances_validation_rules,
)
from tests.modules._api_support import api_client, make_project


def _data(**kw: object) -> dict:
    base: dict = {
        "allowance": {"id": "a1", "label": "Provisional sum, M&E", "held_amount": "10000", "currency": "EUR"},
        "drawdowns": [{"id": "d1", "amount": "2500", "note": "Released to the chiller package"}],
    }
    base.update(kw)
    return base


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (
        AllowanceAmountsInRangeRule,
        _data(),
        _data(allowance={"id": "a1", "held_amount": "1e13", "currency": "EUR"}),
    ),
    (
        AllowanceAmountsInRangeRule,
        _data(),
        _data(drawdowns=[{"id": "d1", "amount": "-5", "note": "x"}]),
    ),
    (AllowanceCurrencyRule, _data(), _data(allowance={"id": "a1", "held_amount": "10000", "currency": ""})),
    (
        AllowanceOverdrawnRule,
        _data(),
        _data(drawdowns=[{"id": "d1", "amount": "9000", "note": "a"}, {"id": "d2", "amount": "2000", "note": "b"}]),
    ),
    (DrawdownExplainedRule, _data(), _data(drawdowns=[{"id": "d1", "amount": "100", "note": "  "}])),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "allowances." not in failed[0].message
    assert failed[0].suggestion and "allowances." not in failed[0].suggestion


@pytest.mark.asyncio
async def test_empty_context_passes_every_rule() -> None:
    for rule_cls, _, _ in CASES:
        assert all(r.passed for r in await _run(rule_cls(), {}))


@pytest.mark.asyncio
async def test_overdrawn_message_follows_locale_and_names_numbers() -> None:
    bad = _data(drawdowns=[{"id": "d1", "amount": "12000", "note": "a"}])
    de = (await _run(AllowanceOverdrawnRule(), bad, locale="de"))[0]
    assert "12" in de.message
    assert "Ansatz" in de.message


def test_registered_under_rule_set() -> None:
    register_allowances_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([ALLOWANCES_RULE_SET])}
    assert ids == {
        "allowances.amounts_in_range",
        "allowances.currency_stated",
        "allowances.not_overdrawn",
        "allowances.drawdown_explained",
    }


# ── API on real PostgreSQL ───────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ctx():
    async with api_client(
        allowances_router, "/v1/allowances", register_allowances_permissions, register_allowances_validation_rules
    ) as (client, session, user):
        yield client, session, await make_project(session, user)


@pytest.mark.asyncio
async def test_api_blocks_unit_slip_with_code(ctx) -> None:
    client, _, pid = ctx
    r = await client.post(
        f"/v1/allowances/projects/{pid}", json={"label": "PS", "held_amount": "10000000000000", "currency": "EUR"}
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "allowances.amounts_in_range"
    assert detail["error"] == "allowances_rules_failed"


@pytest.mark.asyncio
async def test_api_valid_allowance_and_warnings(ctx) -> None:
    client, _, pid = ctx
    ok = await client.post(
        f"/v1/allowances/projects/{pid}", json={"label": "PS", "held_amount": "1000", "currency": "EUR"}
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["warnings"] == []
    aid = ok.json()["id"]

    over = await client.post(f"/v1/allowances/items/{aid}/drawdowns", json={"amount": "1500"})
    assert over.status_code == 201, over.text
    assert {w["rule_id"] for w in over.json()["warnings"]} == {
        "allowances.not_overdrawn",
        "allowances.drawdown_explained",
    }

    noted = await client.post(f"/v1/allowances/items/{aid}/drawdowns", json={"amount": "10", "note": "Door package"})
    # The first drawdown is still unexplained, so the register keeps reporting it.
    assert {w["rule_id"] for w in noted.json()["warnings"]} == {
        "allowances.not_overdrawn",
        "allowances.drawdown_explained",
    }

    bare = await client.post(f"/v1/allowances/projects/{pid}", json={"label": "PC", "held_amount": "50"})
    assert bare.status_code == 201
    assert {w["rule_id"] for w in bare.json()["warnings"]} == {"allowances.currency_stated"}


@pytest.mark.asyncio
async def test_api_update_blocks_new_slip_but_legacy_record_stays_editable(ctx) -> None:
    client, session, pid = ctx
    from decimal import Decimal  # noqa: PLC0415

    legacy = Allowance(
        project_id=pid, label="Old", allowance_type="contingency", held_amount=Decimal("5e12"), currency="EUR"
    )
    session.add(legacy)
    await session.flush()

    relabel = await client.patch(f"/v1/allowances/items/{legacy.id}", json={"label": "Old, renamed"})
    assert relabel.status_code == 200, relabel.text
    assert relabel.json()["label"] == "Old, renamed"

    fresh = await client.post(
        f"/v1/allowances/projects/{pid}", json={"label": "New", "held_amount": "100", "currency": "EUR"}
    )
    r = await client.patch(f"/v1/allowances/items/{fresh.json()['id']}", json={"held_amount": "20000000000000"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "allowances.amounts_in_range"
