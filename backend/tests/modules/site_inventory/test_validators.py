# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Site inventory rule set: each rule fires, a valid record passes, a blocking rule rejects the API write."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.site_inventory.permissions import register_site_inventory_permissions
from app.modules.site_inventory.router import router as inventory_router
from app.modules.site_inventory.validators import (
    SITE_INVENTORY_RULE_SET,
    CostNeedsCurrencyRule,
    MovementNotFutureRule,
    StockNotNegativeRule,
    WasteAllowanceRule,
    register_site_inventory_validation_rules,
)
from tests._pg import transactional_session
from tests.modules._site_api import build_app, http, make_project

pytestmark = pytest.mark.asyncio

NOW = datetime.now(UTC)


def _mv(**kw: object) -> dict:
    base = {
        "movement_type": "CONSUMPTION",
        "quantity": "4",
        "unit_cost": "0",
        "currency": "EUR",
        "item_currency": "EUR",
        "occurred_at": NOW.isoformat(),
        "has_history": True,
        "on_hand": "10",
        "inbound_total": "100",
        "waste_total": "0",
    }
    base.update(kw)
    return {"movement": base}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (StockNotNegativeRule, _mv(), _mv(quantity="11")),
    (MovementNotFutureRule, _mv(), _mv(occurred_at=(NOW + timedelta(days=4)).isoformat())),
    (WasteAllowanceRule, _mv(movement_type="WASTE", quantity="5"), _mv(movement_type="WASTE", quantity="11")),
    (CostNeedsCurrencyRule, _mv(unit_cost="12.50"), _mv(unit_cost="12.50", currency="", item_currency="")),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES, ids=lambda v: getattr(v, "__name__", ""))
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "site." not in failed[0].message and "money." not in failed[0].message


async def test_first_movement_of_an_item_is_not_judged_against_an_empty_ledger() -> None:
    first = _mv(has_history=False, on_hand="0", quantity="50")
    assert all(r.passed for r in await _run(StockNotNegativeRule(), first))
    assert all(r.passed for r in await _run(WasteAllowanceRule(), _mv(movement_type="WASTE", inbound_total="0")))
    inbound = _mv(movement_type="INBOUND", quantity="500", on_hand="0")
    assert all(r.passed for r in await _run(StockNotNegativeRule(), inbound))


async def test_registration_and_severities() -> None:
    assert WasteAllowanceRule.severity == Severity.WARNING
    register_site_inventory_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([SITE_INVENTORY_RULE_SET])}
    assert len(ids) == 4


async def test_message_follows_locale() -> None:
    de = await _run(StockNotNegativeRule(), CASES[0][2], locale="de")
    assert "überschreitet" in de[0].message


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_site_inventory_permissions()
    async with transactional_session() as s:
        yield s


async def test_api_blocks_with_coded_422_and_accepts_valid(db_session) -> None:
    uid, pid = await make_project(db_session)
    base = f"/v1/site-inventory/projects/{pid}"
    async with http(build_app(db_session, uid, inventory_router, "/v1/site-inventory")) as c:
        r = await c.post(f"{base}/items", json={"name": "Rebar B500B 12", "unit": "t", "currency": "EUR"})
        assert r.status_code == 201, r.text
        item = r.json()["id"]

        # No receipt booked yet: the first consumption is accepted, not judged against an empty ledger.
        r = await c.post(f"{base}/movements", json={"item_id": item, "movement_type": "CONSUMPTION", "quantity": "1"})
        assert r.status_code == 201, r.text

        r = await c.post(f"{base}/movements", json={"item_id": item, "movement_type": "INBOUND", "quantity": "10"})
        assert r.status_code == 201, r.text

        r = await c.post(f"{base}/movements", json={"item_id": item, "movement_type": "CONSUMPTION", "quantity": "15"})
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "site_inventory.stock_not_negative"

        r = await c.post(f"{base}/movements", json={"item_id": item, "movement_type": "CONSUMPTION", "quantity": "4"})
        assert r.status_code == 201, r.text

        # Waste above the allowance is a warning: reported, not blocking.
        r = await c.post(f"{base}/movements", json={"item_id": item, "movement_type": "WASTE", "quantity": "3"})
        assert r.status_code == 201, r.text

        r = await c.post(f"{base}/items", json={"name": "Anchor bolt M16", "unit": "pcs"})
        bare = r.json()["id"]
        r = await c.post(
            f"{base}/movements",
            json={"item_id": bare, "movement_type": "INBOUND", "quantity": "100", "unit_cost": "1.20"},
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "site_inventory.cost_needs_currency"
