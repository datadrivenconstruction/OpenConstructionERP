# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rules V1 to V5 of the cost structure: each one fails on its defect and passes on a clean structure."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.costmodel.structure_rules import (
    PAYLOAD_KEY,
    RULE_SET,
    AccountCodesRule,
    AllocationCompleteRule,
    PostedToPostableRule,
    RollupRule,
    VectorInheritedRule,
)

pytestmark = pytest.mark.asyncio


def _acct(id_: str, code: str, parent: str | None = None, **extra: Any) -> dict[str, Any]:
    row = {
        "id": id_,
        "code": code,
        "parent_id": parent,
        "standard": "din276",
        "level": 1 if parent is None else 2,
        "own_amount": "0",
        "is_leaf_postable": True,
        "status": "open",
    }
    row.update(extra)
    return row


def _clean() -> dict[str, Any]:
    return {
        "accounts": [_acct("a", "300"), _acct("b", "330", "a")],
        "depth_limits": {"din276": 3},
        "lines": [{"id": "l1", "code": "L1", "account_id": "b", "amount": "100.00"}],
        "allocations": [
            {"position_id": "p1", "ordinal": "01", "quantity": "10", "modes": ["percent"], "shares": ["60", "40"]}
        ],
        "inherited": [
            {
                "id": "c1",
                "code": "C1",
                "position_id": "p1",
                "cost_line_id": "l1",
                "vector": ["l1"],
                "override_audited": False,
            }
        ],
        "reported_total": "100.00",
        "currency": "EUR",
    }


async def _run(rule_cls: type, payload: dict[str, Any], locale: str = "en") -> list:
    context = ValidationContext(data={PAYLOAD_KEY: payload}, metadata={"locale": locale})
    return [r for r in await rule_cls().validate(context) if not r.passed]


@pytest.mark.parametrize(
    "rule_cls", [AccountCodesRule, PostedToPostableRule, RollupRule, AllocationCompleteRule, VectorInheritedRule]
)
async def test_a_clean_structure_passes_every_rule(rule_cls: type) -> None:
    context = ValidationContext(data={PAYLOAD_KEY: _clean()})
    results = await rule_cls().validate(context)
    assert results and all(r.passed for r in results)


async def test_rules_are_silent_on_other_data() -> None:
    assert await AccountCodesRule().validate(ValidationContext(data={"positions": []})) == []


async def test_the_rule_set_holds_the_five_rules() -> None:
    import app.modules.costmodel.validators  # noqa: F401 - registers on import

    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([RULE_SET])}
    assert ids == {
        "cost_structure.account_codes",
        "cost_structure.posted_to_postable",
        "cost_structure.rollup",
        "cost_structure.allocation_complete",
        "cost_structure.vector_inherited",
    }


async def test_v1_duplicate_code_mixed_lists_loop_and_depth() -> None:
    payload = _clean()
    payload["accounts"] += [
        _acct("c", "330", "a"),
        _acct("d", "B10", standard="uniformat"),
        _acct("e", "X", "f", standard=""),
        _acct("f", "Y", "e", standard=""),
        _acct("g", "3311", "b", level=4),
    ]
    found = await _run(AccountCodesRule, payload)
    problems = sorted(r.details["problem"] for r in found)
    assert problems == ["account_code_duplicate", "account_parent_cycle", "account_too_deep", "mixed_standard"]
    duplicate = next(r for r in found if r.details["problem"] == "account_code_duplicate")
    assert "330" in duplicate.message and duplicate.element_ref == "c"


async def test_v2_money_on_no_account_and_on_a_closed_one() -> None:
    payload = _clean()
    payload["accounts"].append(_acct("z", "390", "a", status="closed"))
    payload["lines"] += [
        {"id": "l2", "code": "L2", "account_id": None, "amount": "40.00"},
        {"id": "l3", "code": "L3", "account_id": "gone", "amount": "2.50"},
        {"id": "l4", "code": "L4", "account_id": "z", "amount": "7.00"},
    ]
    found = await _run(PostedToPostableRule, payload)
    by_problem = {r.details["problem"]: r for r in found}
    assert by_problem["no_account"].details["count"] == "2"
    assert by_problem["no_account"].details["amount"] == "42.50"
    assert by_problem["invalid_account"].details["count"] == "1"
    # The sentence spells the money in its currency; details keep the raw decimal.
    assert "42.50 EUR" in by_problem["no_account"].message


async def test_v3_lost_money_is_an_error_and_own_amount_on_a_parent_a_warning() -> None:
    payload = _clean()
    payload["accounts"][0]["own_amount"] = "50.00"
    payload["reported_total"] = "100.00"  # should be 150.00
    found = await _run(RollupRule, payload)
    by_problem = {r.details["problem"]: r for r in found}
    assert by_problem["rollup_mismatch"].severity.value == "error"
    assert by_problem["rollup_mismatch"].details["difference"] == "-50.00"
    assert by_problem["own_amount_on_parent"].severity.value == "warning"

    payload["reported_total"] = "150.00"
    found = await _run(RollupRule, payload)
    assert [r.details["problem"] for r in found] == ["own_amount_on_parent"]


async def test_v4_shares_that_miss_and_mixed_modes() -> None:
    payload = _clean()
    payload["allocations"] = [
        {"position_id": "p1", "ordinal": "01", "quantity": "10", "modes": ["percent"], "shares": ["60", "39.9"]},
        {"position_id": "p2", "ordinal": "02", "quantity": "10", "modes": ["quantity"], "shares": ["4", "5"]},
        {
            "position_id": "p3",
            "ordinal": "03",
            "quantity": "10",
            "modes": ["percent", "quantity"],
            "shares": ["5", "5"],
        },
        {"position_id": "p4", "ordinal": "04", "quantity": "10", "modes": ["percent"], "shares": ["60", "39.995"]},
    ]
    found = await _run(AllocationCompleteRule, payload)
    assert [(r.element_ref, r.details["problem"]) for r in found] == [
        ("p1", "allocation_incomplete"),
        ("p2", "allocation_incomplete"),
        ("p3", "allocation_mixed_modes"),
    ]
    assert "99.9" in found[0].message and "%" in found[0].message


async def test_v5_a_contract_line_off_its_positions_vector_unless_overridden_with_a_reason() -> None:
    payload = _clean()
    payload["inherited"] = [
        {"id": "c1", "code": "C1", "position_id": "p1", "cost_line_id": "l9", "vector": ["l1", "l2"]},
        {
            "id": "c2",
            "code": "C2",
            "position_id": "p1",
            "cost_line_id": "l9",
            "vector": ["l1"],
            "override_audited": True,
        },
    ]
    found = await _run(VectorInheritedRule, payload)
    assert [r.element_ref for r in found] == ["c1"]
    assert found[0].severity.value == "warning"


async def test_v5_reads_the_split_of_a_line_that_has_no_single_cost_line() -> None:
    payload = _clean()
    payload["inherited"] = [
        {"id": "s1", "code": "S1", "cost_line_id": None, "cost_line_ids": ["l1", "l2"], "vector": ["l1", "l2"]},
        {"id": "s2", "code": "S2", "cost_line_id": None, "cost_line_ids": ["l1", "l9"], "vector": ["l1", "l2"]},
        {"id": "s3", "code": "S3", "cost_line_id": None, "cost_line_ids": [], "vector": ["l1"]},
    ]
    found = await _run(VectorInheritedRule, payload)
    assert [r.element_ref for r in found] == ["s2"]


async def test_messages_follow_the_callers_locale() -> None:
    payload = _clean()
    payload["lines"].append({"id": "l2", "code": "L2", "account_id": None, "amount": "40.00"})
    en = (await _run(PostedToPostableRule, payload, "en"))[0]
    de = (await _run(PostedToPostableRule, payload, "de"))[0]
    assert en.message != de.message
    assert "40.00 EUR" in de.message
    assert not en.message.startswith("cost_structure.")
