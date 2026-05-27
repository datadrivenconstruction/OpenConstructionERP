# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Smart-View evaluator tests — pure, no DB.

The evaluator is the highest-leverage part of the module: every render
of the BIM viewer hits it. Tests cover every operator + action + tie-
breaker + a couple of adversarial inputs (regex DoS, emoji property
values) to keep the engine boring.
"""

from __future__ import annotations

import re

import pytest

from app.modules.smart_views.evaluator import (
    _hash_to_hcl,
    evaluate_rules,
    evaluate_smart_view,
)
from app.modules.smart_views.schemas import (
    SmartViewActionArgs,
    SmartViewRule,
    SmartViewSelector,
)

# ── Fixtures (plain dict elements — no DB) ────────────────────────────────


def _el(
    stable_id: str,
    element_type: str = "",
    *,
    properties: dict | None = None,
) -> dict:
    """Minimal element mapping accepted by the evaluator."""
    return {
        "stable_id": stable_id,
        "element_type": element_type,
        "properties": properties or {},
    }


def _rule(
    rule_id: str,
    *,
    selector: dict,
    action: str = "hide",
    action_args: dict | None = None,
    order: int = 0,
) -> SmartViewRule:
    return SmartViewRule(
        id=rule_id,
        selector=SmartViewSelector(**selector),
        action=action,  # type: ignore[arg-type]
        action_args=SmartViewActionArgs(**(action_args or {})),
        order=order,
    )


@pytest.fixture
def model_elements() -> list[dict]:
    """A small mixed-discipline element list used across tests."""
    return [
        _el("W1", "IfcWall", properties={"FireRating": "F90", "Material": "Concrete"}),
        _el("W2", "IfcWall", properties={"FireRating": "F60", "Material": "Brick"}),
        _el("W3", "IfcWall", properties={"FireRating": "F30"}),
        _el("D1", "IfcDoor", properties={"Material": "Wood"}),
        _el("P1", "IfcPipeSegment", properties={"NominalDiameter": 200}),
        _el("P2", "IfcPipeSegment", properties={"NominalDiameter": 50}),
    ]


# ── 1. ifc_class selector hides matches; non-matches shown ────────────────


def test_ifc_class_selector_hides_matching(model_elements: list[dict]) -> None:
    rules = [_rule("r1", selector={"ifc_class": "IfcWall"}, action="hide")]
    states, _ = evaluate_rules(rules, model_elements)
    assert states["W1"].visible is False
    assert states["W2"].visible is False
    assert states["W3"].visible is False
    assert states["D1"].visible is True
    assert states["P1"].visible is True


# ── 2. property eq selector ───────────────────────────────────────────────


def test_property_eq_selector(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={"property": "FireRating", "operator": "eq", "value": "F90"},
            action="hide",
        )
    ]
    states, _ = evaluate_rules(rules, model_elements)
    assert states["W1"].visible is False
    assert states["W2"].visible is True
    assert states["W3"].visible is True
    # Door and pipes have no FireRating — not matched.
    assert states["D1"].visible is True


# ── 3. contains operator ─────────────────────────────────────────────────


def test_contains_operator(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={"property": "Material", "operator": "contains", "value": "Conc"},
            action="hide",
        )
    ]
    states, _ = evaluate_rules(rules, model_elements)
    assert states["W1"].visible is False  # Concrete
    assert states["W2"].visible is True  # Brick
    assert states["D1"].visible is True  # Wood


# ── 4. regex operator ────────────────────────────────────────────────────


def test_regex_operator(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={
                "property": "FireRating",
                "operator": "regex",
                "value": r"^F\d{2}$",
            },
            action="hide",
        )
    ]
    states, _ = evaluate_rules(rules, model_elements)
    assert states["W1"].visible is False  # F90
    assert states["W2"].visible is False  # F60
    assert states["W3"].visible is False  # F30
    assert states["D1"].visible is True


# ── 5. gt / lt operators ─────────────────────────────────────────────────


def test_gt_lt_operators(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={
                "property": "NominalDiameter",
                "operator": "gt",
                "value": 100,
            },
            action="hide",
        )
    ]
    states, _ = evaluate_rules(rules, model_elements)
    assert states["P1"].visible is False  # 200 > 100
    assert states["P2"].visible is True  # 50 not > 100
    assert states["W1"].visible is True  # no diameter

    # And the inverse — lt
    rules_lt = [
        _rule(
            "r2",
            selector={
                "property": "NominalDiameter",
                "operator": "lt",
                "value": 100,
            },
            action="hide",
        )
    ]
    states_lt, _ = evaluate_rules(rules_lt, model_elements)
    assert states_lt["P1"].visible is True
    assert states_lt["P2"].visible is False


# ── 6. between operator ──────────────────────────────────────────────────


def test_between_operator(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={
                "property": "NominalDiameter",
                "operator": "between",
                "value": [100, 300],
            },
            action="hide",
        )
    ]
    states, _ = evaluate_rules(rules, model_elements)
    assert states["P1"].visible is False  # 200 in [100,300]
    assert states["P2"].visible is True  # 50 outside


# ── 7. in operator ───────────────────────────────────────────────────────


def test_in_operator(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={
                "property": "FireRating",
                "operator": "in",
                "value": ["F60", "F30"],
            },
            action="hide",
        )
    ]
    states, _ = evaluate_rules(rules, model_elements)
    assert states["W1"].visible is True  # F90 not in list
    assert states["W2"].visible is False  # F60
    assert states["W3"].visible is False  # F30


# ── 8. exists operator ───────────────────────────────────────────────────


def test_exists_operator(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={"property": "FireRating", "operator": "exists"},
            action="hide",
        )
    ]
    states, _ = evaluate_rules(rules, model_elements)
    assert states["W1"].visible is False
    assert states["W2"].visible is False
    assert states["W3"].visible is False
    assert states["D1"].visible is True  # no FireRating
    assert states["P1"].visible is True


# ── 9. Rule order — later rule overrides earlier (last wins) ─────────────


def test_rule_order_last_wins(model_elements: list[dict]) -> None:
    # Order 0 hides all walls; order 10 re-shows F90 specifically.
    rules = [
        _rule("r2", selector={"ifc_class": "IfcWall"}, action="hide", order=0),
        _rule(
            "r1",
            selector={"property": "FireRating", "operator": "eq", "value": "F90"},
            action="show",
            order=10,
        ),
    ]
    states, _ = evaluate_rules(rules, model_elements)
    assert states["W1"].visible is True  # show wins
    assert states["W2"].visible is False  # only hide applied
    assert states["W3"].visible is False


# ── 10. color_by_property produces stable colours + legend ───────────────


def test_color_by_property_stable_and_legend(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={"ifc_class": "IfcWall", "property": "FireRating", "operator": "exists"},
            action="color",
            action_args={"color_by_property": "FireRating"},
        )
    ]
    states_a, legend_a = evaluate_rules(rules, model_elements)
    states_b, legend_b = evaluate_rules(rules, model_elements)

    # Stable across runs.
    assert legend_a == legend_b
    assert states_a["W1"].color == states_b["W1"].color

    # Distinct values → distinct legend entries (3 fire ratings).
    assert set(legend_a.keys()) == {"F90", "F60", "F30"}
    assert states_a["W1"].color != states_a["W2"].color
    assert states_a["W1"].color != states_a["W3"].color
    # And all hex format.
    for hex_str in legend_a.values():
        assert re.fullmatch(r"#[0-9A-F]{6}", hex_str)


# ── 11. default_action=hide_all + show rule = additive isolate ───────────


def test_default_hide_all_plus_show(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={"ifc_class": "IfcWall"},
            action="show",
        )
    ]
    states, _ = evaluate_rules(rules, model_elements, default_action="hide_all")
    assert states["W1"].visible is True
    assert states["W2"].visible is True
    assert states["D1"].visible is False  # untouched, default hide
    assert states["P1"].visible is False


# ── 12. default_action=show_all + hide rule = subtractive ────────────────


def test_default_show_all_plus_hide(model_elements: list[dict]) -> None:
    rules = [
        _rule("r1", selector={"ifc_class": "IfcDoor"}, action="hide"),
    ]
    states, _ = evaluate_rules(rules, model_elements, default_action="show_all")
    assert states["D1"].visible is False
    assert states["W1"].visible is True


# ── 13. Empty rules list = default action only ───────────────────────────


def test_empty_rules_uses_default(model_elements: list[dict]) -> None:
    states_show, _ = evaluate_rules([], model_elements, default_action="show_all")
    assert all(s.visible for s in states_show.values())
    states_hide, _ = evaluate_rules([], model_elements, default_action="hide_all")
    assert not any(s.visible for s in states_hide.values())


# ── 14. Unicode + emoji property values handled safely ───────────────────


def test_unicode_and_emoji_values_safe() -> None:
    elements = [
        _el("E1", "IfcSpace", properties={"Tag": "Büro-3"}),
        _el("E2", "IfcSpace", properties={"Tag": "Räume A"}),
        _el("E3", "IfcSpace", properties={"Tag": "Office 🚪"}),
        _el("E4", "IfcSpace", properties={"Tag": "普通"}),
    ]
    rules = [
        _rule(
            "r1",
            selector={"property": "Tag", "operator": "contains", "value": "🚪"},
            action="hide",
        )
    ]
    states, _ = evaluate_rules(rules, elements)
    assert states["E3"].visible is False
    assert states["E1"].visible is True
    assert states["E2"].visible is True
    assert states["E4"].visible is True

    # color_by_property must round-trip the emoji label into the legend.
    rules2 = [
        _rule(
            "r2",
            selector={"property": "Tag", "operator": "exists"},
            action="color",
            action_args={"color_by_property": "Tag"},
        )
    ]
    _, legend = evaluate_rules(rules2, elements)
    assert "Office 🚪" in legend
    assert "普通" in legend


# ── 15. Regex DoS pattern is rejected or bounded ─────────────────────────


def test_regex_dos_pattern_bounded() -> None:
    """A pathological regex over a moderate input must finish quickly.

    A real ReDoS string (e.g. ``(a+)+$`` against a long run of ``a``)
    would freeze the test for minutes if the engine ran it
    unrestricted. We do two checks:

    1. A pattern longer than MAX_REGEX_LENGTH is rejected at schema
       validation time, so the engine never sees it.
    2. A short-but-pathological pattern over a short input finishes
       (the schema length cap is the primary defence).
    """
    # 1. Schema rejects a > 512 char pattern.
    with pytest.raises(ValueError):
        SmartViewSelector(
            property="Tag",
            operator="regex",
            value="a" * 1024,
        )

    # 2. A merely-pathological pattern over short text returns deterministically.
    elements = [_el("E1", properties={"Tag": "aaaaaa!"})]
    rules = [
        _rule(
            "rdos",
            selector={"property": "Tag", "operator": "regex", "value": r"(a+)+!"},
            action="hide",
        )
    ]
    # Should match — and crucially, return.
    states, _ = evaluate_rules(rules, elements)
    assert states["E1"].visible is False


# ── 16. neq operator ─────────────────────────────────────────────────────


def test_neq_operator(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={"property": "Material", "operator": "neq", "value": "Wood"},
            action="hide",
        )
    ]
    states, _ = evaluate_rules(rules, model_elements)
    # Elements without Material (W3, P1, P2) — neq is False for missing.
    assert states["W3"].visible is True
    assert states["P1"].visible is True
    # W1 Concrete ≠ Wood → hide
    assert states["W1"].visible is False
    # D1 Wood == Wood → keep visible
    assert states["D1"].visible is True


# ── 17. isolate action hides the complement ──────────────────────────────


def test_isolate_action(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={"ifc_class": "IfcWall"},
            action="isolate",
        )
    ]
    states, _ = evaluate_rules(rules, model_elements)
    # Walls remain visible
    assert states["W1"].visible is True
    assert states["W2"].visible is True
    assert states["W3"].visible is True
    # Everything else is hidden
    assert states["D1"].visible is False
    assert states["P1"].visible is False
    assert states["P2"].visible is False


# ── 18. transparent action clamps opacity ────────────────────────────────


def test_transparent_action(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={"ifc_class": "IfcWall"},
            action="transparent",
            action_args={"opacity": 0.3},
        )
    ]
    states, _ = evaluate_rules(rules, model_elements)
    assert states["W1"].opacity == 0.3
    assert states["W1"].visible is True  # not hidden, just translucent
    assert states["D1"].opacity == 1.0


# ── 19. fixed-color action ───────────────────────────────────────────────


def test_color_fixed(model_elements: list[dict]) -> None:
    rules = [
        _rule(
            "r1",
            selector={"ifc_class": "IfcWall"},
            action="color",
            action_args={"color": "#FF00AA"},
        )
    ]
    states, _ = evaluate_rules(rules, model_elements)
    assert states["W1"].color == "#FF00AA"
    assert states["W2"].color == "#FF00AA"
    assert states["D1"].color is None


# ── 20. evaluate_smart_view convenience wrapper ──────────────────────────


def test_evaluate_smart_view_wrapper(model_elements: list[dict]) -> None:
    class FakeView:
        rules = [
            {
                "id": "r1",
                "selector": {"ifc_class": "IfcWall"},
                "action": "hide",
                "action_args": {},
                "order": 0,
            }
        ]
        default_action = "show_all"

    states, _ = evaluate_smart_view(FakeView(), model_elements)
    assert states["W1"].visible is False
    assert states["D1"].visible is True


# ── 21. _hash_to_hcl is deterministic + different inputs → different ─────


def test_hash_to_hcl_deterministic() -> None:
    a = _hash_to_hcl("FireRating-F90")
    b = _hash_to_hcl("FireRating-F90")
    c = _hash_to_hcl("FireRating-F30")
    assert a == b
    assert a != c
    assert re.fullmatch(r"#[0-9A-F]{6}", a)


# ── 22. Tie-breaker on same order: id lex ────────────────────────────────


def test_same_order_id_lex_tiebreak(model_elements: list[dict]) -> None:
    # Both rules at order=0; lex-earlier "a" runs first, then "b"
    # overrides — so the wall ends up shown.
    rules = [
        _rule("b", selector={"ifc_class": "IfcWall"}, action="show", order=0),
        _rule("a", selector={"ifc_class": "IfcWall"}, action="hide", order=0),
    ]
    states, _ = evaluate_rules(rules, model_elements)
    assert states["W1"].visible is True
