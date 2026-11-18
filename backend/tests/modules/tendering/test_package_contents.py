# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What a tender package asks for, what it is budgeted at, and when it may go.

Worked example used throughout: a concrete wall, 10 m3 at 300 per m3. Per m3
the line consumes 1.0 m3 of concrete at 150, 0.1 t of rebar at 900 and 2 h of
labour at 30: 150 + 90 + 60 = 300. The contractor buys the rebar itself (long
lead time) and sends out the concrete and the labour: 210 per m3, 2100 for the
line. A labour-only package is 60 per m3, 600 for the line.

Run:
    cd backend
    python -m pytest tests/modules/tendering/test_package_contents.py -q
"""

from __future__ import annotations

import base64
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.validation.engine import ValidationContext
from app.modules.tendering.bid_portal import bidder_lines, decode_logo
from app.modules.tendering.package_contents import (
    SCOPE_KINDS,
    component_key,
    package_budget,
    read_override,
    read_scope,
    scope_to_metadata,
    scoped_line,
)
from app.modules.tendering.schemas import PackageUpdate
from app.modules.tendering.service import TenderingService, delete_refusal
from app.modules.tendering.validators import (
    BudgetOverrideNearComputed,
    PackageHasLines,
    ScopeCanSplitLine,
    ScopeLeavesCostOnLine,
)

WALL_ID = uuid.uuid4()
REBAR_KEY = component_key("material", "RB12", "Rebar B500", "t")


def _wall(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "id": WALL_ID,
        "parent_id": None,
        "ordinal": "01.010",
        "description": "Concrete wall C30/37",
        "unit": "m3",
        "quantity": "10",
        "unit_rate": "300",
        "total": "3000",
        "metadata_": {
            "resources": [
                {"name": "Concrete C30/37", "type": "material", "unit": "m3", "quantity": 1.0, "unit_rate": 150},
                {
                    "name": "Rebar B500",
                    "code": "RB12",
                    "type": "material",
                    "unit": "t",
                    "quantity": 0.1,
                    "unit_rate": 900,
                },
                {"name": "Formwork crew", "type": "labor", "unit": "h", "quantity": 2, "unit_rate": 30},
            ]
        },
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _scope(kinds: list[str], excluded: dict[str, list[str]] | None = None) -> dict[str, Any]:
    return {"resource_scope": scope_to_metadata(kinds, excluded or {})}


# ── Budget of a line ────────────────────────────────────────────────────────


def test_without_a_scope_the_line_is_budgeted_in_full() -> None:
    line = scoped_line(_wall(), None)

    assert (line.unit_rate, line.total, line.split) == (Decimal("300"), Decimal("3000"), False)
    assert [c.included for c in line.components] == [True, True, True]


def test_owner_supplied_rebar_leaves_concrete_and_labour() -> None:
    meta = _scope(["labor", "material"], {str(WALL_ID): [REBAR_KEY]})

    line = scoped_line(_wall(), read_scope(meta))

    assert line.unit_rate == Decimal("210")
    assert line.total == Decimal("2100")
    assert line.split is True
    assert [c.name for c in line.components if not c.included] == ["Rebar B500"]


def test_a_labour_only_package_prices_the_labour_share() -> None:
    line = scoped_line(_wall(), read_scope(_scope(["labor"])))

    assert (line.unit_rate, line.total) == (Decimal("60"), Decimal("600"))


def test_a_line_without_components_cannot_be_split_and_stays_whole() -> None:
    bare = _wall(metadata_={})

    line = scoped_line(bare, read_scope(_scope(["labor"])))

    assert (line.total, line.unsplittable, line.split) == (Decimal("3000"), True, False)


def test_every_kind_and_no_exclusion_is_no_scope_at_all() -> None:
    assert scope_to_metadata(SCOPE_KINDS, {}) is None
    assert read_scope({"resource_scope": {"kinds": list(SCOPE_KINDS), "excluded": {}}}) is None


# ── Budget of a package ─────────────────────────────────────────────────────


def test_an_entered_budget_is_in_force_and_the_sum_stays_visible() -> None:
    meta = {**_scope(["labor", "material"], {str(WALL_ID): [REBAR_KEY]}), "budget_override": "2500"}

    budget = package_budget([_wall()], meta)

    assert budget.computed == Decimal("2100")
    assert budget.override == Decimal("2500")
    assert budget.effective == Decimal("2500")


def test_a_cleared_budget_falls_back_to_the_sum() -> None:
    budget = package_budget([_wall()], {"budget_override": None})

    assert (budget.override, budget.effective) == (None, Decimal("3000"))
    assert read_override({"budget_override": "-5"}) is None


def test_a_negative_budget_is_refused_at_the_door() -> None:
    with pytest.raises(ValidationError):
        PackageUpdate(budget_override=Decimal("-1"))


def test_the_patch_folds_budget_and_scope_into_the_metadata() -> None:
    package = SimpleNamespace(status="draft", metadata_={})
    fields: dict[str, Any] = {
        "budget_override": Decimal("2500.50"),
        "resource_scope": {"kinds": ["labor"], "excluded": {}},
    }

    TenderingService._fold_budget_fields(package, fields)

    assert fields == {
        "metadata": {"budget_override": "2500.50", "resource_scope": {"kinds": ["labor"], "excluded": {}}}
    }


@pytest.mark.parametrize("package_status", ["awarded", "closed"])
def test_a_decided_package_keeps_its_budget(package_status: str) -> None:
    package = SimpleNamespace(status=package_status, metadata_={})

    with pytest.raises(HTTPException) as exc:
        TenderingService._fold_budget_fields(package, {"budget_override": Decimal("1")})

    assert exc.value.status_code == 409


# ── What the bidder sees ────────────────────────────────────────────────────


def test_the_bidder_is_told_which_components_others_supply() -> None:
    meta = _scope(["labor", "material"], {str(WALL_ID): [REBAR_KEY]})

    lines, priceable = bidder_lines([_wall()], meta)

    assert list(priceable) == [str(WALL_ID)]
    assert lines[0]["supplied_by_others"] == ["Rebar B500"]


def test_without_a_scope_nothing_is_named_as_supplied_by_others() -> None:
    lines, _ = bidder_lines([_wall()], {})

    assert lines[0]["supplied_by_others"] == []


# ── Delete or cancel ────────────────────────────────────────────────────────


def test_a_draft_that_reached_nobody_may_be_deleted() -> None:
    assert delete_refusal("draft", bids=0, sent=0, links=0, linked_bid_packages=0) is None


@pytest.mark.parametrize(
    ("package_status", "bids", "sent", "links", "linked", "reason"),
    [
        ("issued", 0, 0, 0, 0, "not_draft"),
        ("draft", 1, 0, 0, 0, "has_bids"),
        ("draft", 0, 2, 0, 0, "sent"),
        ("draft", 0, 0, 1, 0, "has_links"),
        ("draft", 0, 0, 0, 1, "linked_bid_package"),
    ],
)
def test_a_package_that_reached_a_firm_is_cancelled_not_deleted(
    package_status: str, bids: int, sent: int, links: int, linked: int, reason: str
) -> None:
    assert delete_refusal(package_status, bids, sent, links, linked) == reason


# ── Logo on the bidder page ─────────────────────────────────────────────────


def test_the_document_logo_is_served_as_its_own_image_type() -> None:
    png = b"\x89PNG\r\n\x1a\nfake"
    url = "data:image/png;base64," + base64.b64encode(png).decode()

    assert decode_logo(url) == (png, "image/png")


@pytest.mark.parametrize("value", ["", None, "https://example.com/logo.png", "data:image/png;base64,@@@"])
def test_no_usable_logo_is_no_logo(value: object) -> None:
    assert decode_logo(value) is None


# ── Rules ───────────────────────────────────────────────────────────────────


async def _run(rule: Any, data: dict[str, Any]) -> list[Any]:
    return await rule.validate(ValidationContext(data=data))


@pytest.mark.asyncio
async def test_a_package_without_lines_fails_and_one_with_lines_passes() -> None:
    assert [r.passed for r in await _run(PackageHasLines(), {"item_count": 0})] == [False]
    assert [r.passed for r in await _run(PackageHasLines(), {"item_count": 3})] == [True]


@pytest.mark.asyncio
async def test_an_entered_budget_far_from_the_sum_is_flagged() -> None:
    far = await _run(BudgetOverrideNearComputed(), {"budget_override": 1000.0, "budget_computed": 2100.0})
    near = await _run(BudgetOverrideNearComputed(), {"budget_override": 2300.0, "budget_computed": 2100.0})
    none = await _run(BudgetOverrideNearComputed(), {"budget_override": None, "budget_computed": 2100.0})

    assert ([r.passed for r in far], [r.passed for r in near], none) == ([False], [True], [])


@pytest.mark.asyncio
async def test_scope_rules_name_the_lines_they_concern() -> None:
    data = {
        "scope_active": True,
        "lines": [
            {"id": "a", "ordinal": "01", "split": True, "unsplittable": False, "budget_total": 0.0},
            {"id": "b", "ordinal": "02", "split": False, "unsplittable": True, "budget_total": 50.0},
            {"id": "c", "ordinal": "03", "split": True, "unsplittable": False, "budget_total": 10.0},
        ],
    }

    leaves = await _run(ScopeLeavesCostOnLine(), data)
    split = await _run(ScopeCanSplitLine(), data)

    assert [(r.element_ref, r.passed) for r in leaves] == [("line:a", False), ("line:c", True)]
    assert [r.element_ref for r in split] == ["line:b"]
