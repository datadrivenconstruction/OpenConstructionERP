"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Contract-side items of module 2: rules, catalogue kinds, request schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.delivery_model import rules
from app.modules.delivery_model.catalogue import (
    CATALOGUE_DIR,
    CONTRACT_GROUPS,
    DeliveryFormsCatalogue,
    validate_delivery_forms,
)
from app.modules.delivery_model.schemas import ContractItemIn, ContractItemPatch

KINDS = [
    {"group": "contract_form", "code": "construction_contract"},
    {"group": "land_tenure", "code": "leasehold"},
    {"group": "partner_structure", "code": "project_company"},
    {"group": "partner_structure", "code": "joint_venture"},
]
PACK_CATALOGUE = next(
    p
    for p in Path(__file__)
    .resolve()
    .parents[3]
    .glob("packs/eleven-areas-framework/src/*/catalogues/delivery_forms/*.json")
)


def _item(code: str, group: str, kind: str, **extra: Any) -> dict[str, Any]:
    return {
        "code": code,
        "group_code": group,
        "kind_code": kind,
        "counterparty": "Someone",
        "status": "draft",
        "start_date": None,
        "end_date": None,
        "price_basis": None,
        "share_percent": None,
        **extra,
    }


def _codes(items: list[dict[str, Any]], *, released: bool = False, form: Any = None) -> list[str]:
    return [f.code for f in rules.contract_item_findings(items, KINDS, form, procurement_released=released)]


def test_unknown_kind_and_inverted_dates_are_errors() -> None:
    items = [
        _item("A", "land_tenure", "squatting"),
        _item("B", "land_tenure", "leasehold", start_date="2027-02-01", end_date="2027-01-01"),
    ]
    assert _codes(items) == ["contract_item_kind_unknown", "contract_item_dates_invalid"]


def test_an_agreed_item_needs_a_counterparty() -> None:
    assert _codes([_item("A", "land_tenure", "leasehold", status="signed", counterparty=" ")]) == [
        "contract_item_without_counterparty"
    ]
    assert _codes([_item("A", "land_tenure", "leasehold", status="draft", counterparty="")]) == []


def test_partner_shares_must_add_up_to_100() -> None:
    a = _item("P1", "partner_structure", "project_company", share_percent="70")
    assert _codes([a, _item("P2", "partner_structure", "joint_venture", share_percent="20")]) == [
        "partner_shares_not_100"
    ]
    assert _codes([a, _item("P2", "partner_structure", "joint_venture", share_percent="30")]) == []
    # A terminated partner no longer holds a share.
    assert _codes([a, _item("P2", "partner_structure", "joint_venture", share_percent="30", status="terminated")]) == [
        "partner_shares_not_100"
    ]


def test_missing_groups_warn_only_once_procurement_is_released() -> None:
    items = [_item("A", "land_tenure", "leasehold")]
    assert _codes(items) == []
    assert _codes(items, released=True) == ["contract_group_missing", "contract_group_missing"]
    refs = [f.ref for f in rules.contract_item_findings(items, KINDS, None, procurement_released=True)]
    assert refs == ["utility_contract", "partner_structure"]


def test_schema_keeps_price_basis_and_share_on_their_own_group() -> None:
    base = {"code": "X1", "kind_code": "leasehold"}
    with pytest.raises(ValidationError):
        ContractItemIn(group_code="land_tenure", price_basis="lump_sum", **base)
    with pytest.raises(ValidationError):
        ContractItemIn(group_code="land_tenure", share_percent="10", **base)
    with pytest.raises(ValidationError):
        ContractItemIn(group_code="partner_structure", share_percent="100.5", **base)
    with pytest.raises(ValidationError):
        ContractItemIn(group_code="partner_structure", share_percent=12.5, **base)
    assert ContractItemIn(group_code="partner_structure", share_percent="12.5", **base).share_percent == "12.5"
    with pytest.raises(ValidationError):
        ContractItemPatch.model_validate({"title": None})


@pytest.mark.parametrize("path", [CATALOGUE_DIR / "neutral.json", PACK_CATALOGUE])
def test_shipped_catalogues_carry_every_group_and_validate(path: Path) -> None:
    body = DeliveryFormsCatalogue.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert {k.group for k in body.contract_kinds} == set(CONTRACT_GROUPS)
    source = "shipped" if path.name == "neutral.json" else "tenant"
    assert validate_delivery_forms(body, source) == []


def test_a_duplicate_contract_kind_is_refused() -> None:
    body = DeliveryFormsCatalogue.model_validate(
        json.loads((CATALOGUE_DIR / "neutral.json").read_text(encoding="utf-8"))
    )
    twice = body.model_copy(update={"contract_kinds": (*body.contract_kinds, body.contract_kinds[0])})
    assert any(e.startswith("duplicate_contract_kind") for e in validate_delivery_forms(twice, "shipped"))
