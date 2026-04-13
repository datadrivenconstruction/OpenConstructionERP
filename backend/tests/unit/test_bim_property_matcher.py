"""Unit tests for ``BIMHubService._property_value_matches``.

The helper is shared between two callers:
    1. The dynamic-element-group ``_matches`` predicate
       (resolves group membership from a property_filter)
    2. ``_rule_matches_element`` for the quantity-map rule engine
       (decides whether a rule fires on a given BIM element)

Both callers used to do dumb exact-equality / ``str(value)`` comparison,
which silently broke multi-valued IFC properties (lists), nested
property objects (dicts), and explicit "must not be set" filters.
This file pins the new type-aware behaviour so the regression can not
sneak back.
"""

from __future__ import annotations

from app.modules.bim_hub.service import BIMHubService

_match = BIMHubService._property_value_matches


# ── Scalar string matching (existing fnmatch behaviour) ───────────────────


def test_string_exact_match() -> None:
    assert _match("steel", "steel") is True


def test_string_case_insensitive() -> None:
    assert _match("STEEL", "steel") is True
    assert _match("Steel", "STEEL") is True


def test_string_wildcard_star() -> None:
    assert _match("concrete_c30_37", "concrete_*") is True
    assert _match("concrete_c30_37", "*_c30_*") is True


def test_string_wildcard_question() -> None:
    assert _match("F90", "F?0") is True


def test_string_no_match() -> None:
    assert _match("wood", "steel") is False


# ── List actual values (the bug v1.4.5 fixes) ─────────────────────────────


def test_list_membership_scalar_filter() -> None:
    """Multi-valued IFC properties — filter wants ``"steel"`` and the
    element has ``materials = ["steel", "concrete"]`` → match."""
    assert _match(["steel", "concrete"], "steel") is True
    assert _match(["wood", "drywall"], "steel") is False


def test_list_membership_with_wildcard() -> None:
    """Wildcard scalar filter applied to each list item."""
    assert _match(["concrete_c30_37", "steel_s355"], "concrete_*") is True


def test_list_intersection_with_list_filter() -> None:
    """Filter is also a list → non-empty intersection."""
    assert _match(["steel", "concrete"], ["steel", "wood"]) is True
    assert _match(["wood"], ["steel", "concrete"]) is False


def test_list_intersection_with_wildcards() -> None:
    """List vs list, with wildcards on the filter side."""
    assert _match(["F90", "F60"], ["F?0", "F30"]) is True


def test_empty_actual_list() -> None:
    assert _match([], "steel") is False
    assert _match([], ["steel"]) is False


# ── Dict actual values: recursive containment ────────────────────────────


def test_dict_recursive_containment() -> None:
    actual = {"layers": {"core": "steel", "finish": "paint"}, "thick_mm": 200}
    assert _match(actual, {"layers": {"core": "steel"}}) is True


def test_dict_partial_match() -> None:
    """Filter only specifies some keys — others on actual are ignored."""
    actual = {"a": 1, "b": 2, "c": 3}
    assert _match(actual, {"a": "1"}) is True


def test_dict_missing_key_in_actual() -> None:
    actual = {"a": 1}
    assert _match(actual, {"b": "2"}) is False


def test_dict_nested_mismatch() -> None:
    actual = {"layers": {"core": "wood"}}
    assert _match(actual, {"layers": {"core": "steel"}}) is False


# ── None handling ──────────────────────────────────────────────────────────


def test_explicit_must_not_be_set() -> None:
    """``expected is None`` means *the property must not be set*.  This
    is the only way to express that filter declaratively."""
    assert _match(None, None) is True
    assert _match("anything", None) is False


def test_actual_none_with_real_filter_fails() -> None:
    """If the filter wants a value but the element is missing it,
    that's a non-match — never a crash."""
    assert _match(None, "steel") is False
    assert _match(None, ["steel"]) is False
    assert _match(None, {"a": 1}) is False


# ── Mixed-type fallback ────────────────────────────────────────────────────


def test_int_actual_str_filter() -> None:
    assert _match(42, "42") is True
    assert _match(42, "43") is False


def test_bool_actual_str_filter() -> None:
    assert _match(True, "true") is True
    assert _match(False, "True") is False


def test_decimal_via_str_coercion() -> None:
    from decimal import Decimal

    assert _match(Decimal("12.5"), "12.5") is True


# ── No crash on weird inputs ──────────────────────────────────────────────


def test_no_crash_on_nested_list_of_lists() -> None:
    """Defensive: pathological IFC export shapes shouldn't blow up."""
    actual = [["a", "b"], ["c"]]
    # The intersection logic recurses but our helper handles list-of-list
    # by treating each inner list as an "actual" for membership.
    # We just want to verify no exception is raised.
    result = _match(actual, "a")
    assert isinstance(result, bool)
