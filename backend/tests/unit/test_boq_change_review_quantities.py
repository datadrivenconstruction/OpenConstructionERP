"""Quantity rules behind the BIM quantity proposals.

The proposal must compute a linked position's quantity exactly the way the BIM
Hub set it when the link was made, otherwise the first look at an untouched
model already reports a change. These tests pin the unit-to-dimension rule,
the quantity-map rule, and the element pairing that decides what changed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.modules.boq.change_review import (
    _Elem,
    _Pair,
    _Tip,
    bim_flag_key,
    document_flag_key,
    rule_method_quantity,
    unit_method_quantity,
)

_MODEL_V1 = uuid.uuid4()
_MODEL_V2 = uuid.uuid4()


def _e(sid: str, quantities: dict | None = None, *, model: uuid.UUID = _MODEL_V1, ghash: str | None = "h") -> _Elem:
    return _Elem(
        element_id=uuid.uuid4(),
        model_id=model,
        stable_id=sid,
        geometry_hash=ghash,
        quantities=quantities or {},
        properties={"fire_rating": "60"},
    )


# ── unit method ───────────────────────────────────────────────────────────


def test_volume_sums_the_volume_key_only():
    elems = [_e("a", {"volume_m3": 2.5, "area_m2": 99}), _e("b", {"Volume": "1.25"})]
    assert unit_method_quantity("m3", elems) == Decimal("3.7500")
    # The superscript spelling resolves to the same unit.
    assert unit_method_quantity("m³", elems) == Decimal("3.7500")


def test_count_unit_counts_elements_and_never_takes_a_volume():
    elems = [_e("a", {"volume_m3": 7.5}), _e("b", {"volume_m3": 2})]
    assert unit_method_quantity("pcs", elems) == Decimal("2")
    assert unit_method_quantity("Stk", elems) == Decimal("2")


def test_tonnes_divide_kilograms_by_a_thousand():
    elems = [_e("a", {"weight_kg": 4000}), _e("b", {"weight_kg": "500"})]
    assert unit_method_quantity("t", elems) == Decimal("4.5000")
    assert unit_method_quantity("kg", elems) == Decimal("4500.0000")


def test_missing_wrong_or_non_finite_values_add_nothing():
    elems = [
        _e("a", {"area_m2": 10}),
        _e("b", {"length_m": 5}),  # wrong dimension for m2
        _e("c", {"area_m2": "abc"}),
        _e("d", {"area_m2": "NaN"}),
        _e("e", {"area_m2": -3}),
    ]
    assert unit_method_quantity("m2", elems) == Decimal("10.0000")


def test_unit_without_a_dimension_has_no_figure():
    assert unit_method_quantity("lsum_unknown_unit", [_e("a", {"volume_m3": 1})]) is None
    assert unit_method_quantity("h", [_e("a", {"volume_m3": 1})]) is None


def test_empty_element_list():
    assert unit_method_quantity("m3", []) == Decimal("0.0000")
    assert unit_method_quantity("pcs", []) == Decimal("0")


# ── rule method ───────────────────────────────────────────────────────────


def test_rule_applies_multiplier_and_waste():
    rule = SimpleNamespace(quantity_source="area_m2", multiplier="2", waste_factor_pct="10")
    elems = [_e("a", {"area_m2": 10}), _e("b", {"area_m2": 5}), _e("c", {})]
    # (10 + 5) * 2 * 1.10 = 33
    assert rule_method_quantity(rule, elems) == Decimal("33.0000")


def test_rule_count_and_property_sources():
    count_rule = SimpleNamespace(quantity_source="count", multiplier="1", waste_factor_pct="0")
    assert rule_method_quantity(count_rule, [_e("a"), _e("b"), _e("c")]) == Decimal("3.0000")
    prop_rule = SimpleNamespace(quantity_source="property:fire_rating", multiplier="1", waste_factor_pct="0")
    assert rule_method_quantity(prop_rule, [_e("a")]) == Decimal("60.0000")


def test_rule_with_unparseable_factors_has_no_figure():
    rule = SimpleNamespace(quantity_source="area_m2", multiplier="x", waste_factor_pct="0")
    assert rule_method_quantity(rule, [_e("a", {"area_m2": 1})]) is None


# ── pairing ───────────────────────────────────────────────────────────────


def _pair(old: _Elem, new: _Elem | None) -> _Pair:
    return _Pair(stable_id=old.stable_id, old=old, new=new, tip=_Tip(tip_id=_MODEL_V2, name="M", version="2"))


def test_pair_detects_deleted_modified_and_unchanged():
    old = _e("w", {"volume_m3": 1}, ghash="a")
    assert _pair(old, None).deleted
    assert _pair(old, _e("w", {"volume_m3": 2}, model=_MODEL_V2, ghash="a")).modified
    assert _pair(old, _e("w", {"volume_m3": 1}, model=_MODEL_V2, ghash="b")).modified
    same = _pair(old, _e("w", {"volume_m3": 1}, model=_MODEL_V2, ghash="a"))
    assert not same.modified and not same.deleted and same.crosses_version


def test_element_already_in_the_newest_version_is_never_a_change():
    current = _e("w", {"volume_m3": 1}, model=_MODEL_V2)
    pair = _Pair(stable_id="w", old=current, new=current, tip=_Tip(tip_id=_MODEL_V2, name="M", version="2"))
    assert not pair.crosses_version
    assert not pair.modified
    assert not pair.deleted


# ── keys ──────────────────────────────────────────────────────────────────


def test_flag_keys_are_stable_and_bounded():
    assert bim_flag_key(_MODEL_V2) == f"bim:{_MODEL_V2}"
    assert document_flag_key("doc", "v2") == "document:doc:v2"
    assert document_flag_key("doc", "v2") != document_flag_key("doc", "v3")
    assert len(document_flag_key("d" * 300, "B")) == 255
