"""Worked numbers of the design estimate: a 10 x 5 m slab, 0.25 m thick, is 12.5 m3."""

from __future__ import annotations

from decimal import Decimal

import pytest


def _slab_rule(rate: str | None = "120") -> dict:
    body = {
        "id": "slab",
        "kind": "derived",
        "label": "Floor slab",
        "unit": "m3",
        "cost_group": "350",
        "formula": "length * width * thickness",
        "inputs": {
            "length": {"value": 10, "source": "brief"},
            "width": {"value": 5, "source": "brief"},
            "thickness": {"value": "0.25", "source": "brief"},
        },
    }
    if rate is not None:
        body["rate"] = {"value": rate, "source": "tender"}
    return body


def test_slab_volume_and_rate_are_exact_decimals():
    from app.modules.design.estimate import eval_derived_rule

    c = eval_derived_rule(_slab_rule(), {}, None, True)
    assert c.quantity == Decimal("12.5")
    assert isinstance(c.quantity, Decimal)
    assert c.unit_rate == Decimal("120")
    assert c.quantity * c.unit_rate == Decimal("1500")
    assert c.flags == []


def test_slab_without_rate_is_flagged_rate_missing():
    from app.modules.design.estimate import eval_derived_rule

    c = eval_derived_rule(_slab_rule(rate=None), {}, None, True)
    assert c.quantity == Decimal("12.5")
    assert "rate_missing" in c.flags


def _ctx(positions):
    from app.core.validation.engine import ValidationContext

    return ValidationContext(data={"positions": positions}, metadata={"locale": "en"})


def _pos(**kw):
    base = {"position_id": "p1", "rule": "slab", "description": "Floor slab", "unit": "m3"}
    return {**base, **kw}


@pytest.mark.asyncio
async def test_quantity_less_positions_are_flagged():
    from app.modules.design.validators import EstimateQuantityMissing

    rule = EstimateQuantityMissing()
    res = await rule.validate(
        _ctx(
            [
                _pos(position_id="ok", quantity="12.5", flags=[]),
                _pos(position_id="zero", quantity="0", flags=["no_match"]),
                _pos(position_id="partial", quantity="40", flags=["quantity_missing"]),
                _pos(position_id="kept", quantity="0", flags=["override"]),
            ]
        )
    )
    by = {r.element_ref: r for r in res}
    assert by["ok"].passed
    assert not by["zero"].passed
    assert not by["partial"].passed
    assert by["kept"].passed  # a person set zero on purpose
    assert "Floor slab" in by["zero"].message
    assert rule.rule_id == "design.estimate_quantity_missing"


@pytest.mark.asyncio
async def test_unpriced_slab_is_flagged_and_priced_passes():
    from app.modules.design.validators import EstimateUnpriced

    res = await EstimateUnpriced().validate(
        _ctx([_pos(position_id="a", unit_rate="0"), _pos(position_id="b", unit_rate="120.0000")])
    )
    by = {r.element_ref: r for r in res}
    assert not by["a"].passed
    assert by["b"].passed


def test_impact_prices_with_the_rule_rate_an_unpriced_position_will_get():
    from app.modules.design.estimate import _impact_rate

    assert _impact_rate(Decimal("0"), Decimal("120")) == Decimal("120.0000")
    assert _impact_rate(Decimal("95"), Decimal("120")) == Decimal("95.0000")
    assert _impact_rate(None, None) == Decimal("0")
