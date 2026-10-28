# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure decision-tree classification and label localization for project_route.

Pins the jurisdiction-neutral route maths: each work type resolves to the
expected generic route, the more-specific criteria rules win over the catch-all,
an unknown work type degrades to undetermined, and the confidence is a sane
0..1. Also checks the /meta label lookups localise with an English fallback and
never leak a raw code, and that the route_determined validation rule gates on a
confirmed, non-undetermined assessment. No DB, no clock.
"""

from __future__ import annotations

import asyncio

from app.core.validation.engine import ValidationContext
from app.modules.project_route import intl
from app.modules.project_route.service import DEFAULT_ROUTE_RULES, RouteRule, classify
from app.modules.project_route.validators import RouteDeterminedRule

# ── classify: default routes per work type ──────────────────────────────────


def test_new_build_default_is_full_permit() -> None:
    route, rationale, conf = classify("new_build", {})
    assert route == "full_permit"
    assert rationale
    assert 0.0 <= conf <= 1.0


def test_new_build_major_requires_expertise() -> None:
    route, _, conf = classify("new_build", {"scale": "major"})
    assert route == "expertise_required"
    assert conf >= 0.8


def test_new_build_heritage_requires_expertise() -> None:
    route, _, _ = classify("new_build", {"heritage_protected": True})
    assert route == "expertise_required"


def test_reconstruction_affecting_structure_needs_full_permit() -> None:
    assert classify("reconstruction", {"affects_structure": True})[0] == "full_permit"


def test_reconstruction_not_affecting_structure_is_notification() -> None:
    assert classify("reconstruction", {"affects_structure": False})[0] == "notification"


def test_capital_repair_not_structural_is_notification() -> None:
    assert classify("capital_repair", {})[0] == "notification"


def test_capital_repair_structural_is_full_permit() -> None:
    assert classify("capital_repair", {"affects_structure": True})[0] == "full_permit"


def test_re_equipment_is_exempt() -> None:
    assert classify("re_equipment", {})[0] == "exempt"


def test_re_equipment_structural_is_notification() -> None:
    assert classify("re_equipment", {"affects_structure": True})[0] == "notification"


def test_maintenance_is_exempt() -> None:
    assert classify("maintenance", {})[0] == "exempt"


def test_demolition_default_is_notification() -> None:
    assert classify("demolition", {})[0] == "notification"


def test_demolition_heritage_is_full_permit() -> None:
    assert classify("demolition", {"heritage_protected": True})[0] == "full_permit"


def test_change_of_use_within_limits_is_permitted_development() -> None:
    assert classify("change_of_use", {"within_permitted_limits": True})[0] == "permitted_development"


def test_change_of_use_beyond_limits_is_full_permit() -> None:
    assert classify("change_of_use", {})[0] == "full_permit"


def test_other_is_undetermined_low_confidence() -> None:
    route, _, conf = classify("other", {})
    assert route == "undetermined"
    assert conf < 0.5


def test_unknown_work_type_is_undetermined() -> None:
    route, _, conf = classify("no_such_type", {"scale": "major"})
    assert route == "undetermined"
    assert conf < 0.5


# ── classify: matching semantics ─────────────────────────────────────────────


def test_bool_criteria_matches_leniently() -> None:
    # "yes" / 1 read as true; the structural reconstruction rule should fire.
    assert classify("reconstruction", {"affects_structure": "yes"})[0] == "full_permit"
    assert classify("reconstruction", {"affects_structure": 1})[0] == "full_permit"


def test_missing_criterion_falls_through_to_catch_all() -> None:
    # No affects_structure key -> the {affects_structure: True} rule cannot fire.
    assert classify("reconstruction", {})[0] == "notification"


def test_none_criteria_is_treated_as_empty() -> None:
    assert classify("maintenance", None)[0] == "exempt"


def test_regional_pack_can_override_rule_set() -> None:
    # A pack hands its own tuple: maintenance now needs a full permit.
    pack = (RouteRule("maintenance", {}, "full_permit", "Local rule.", 0.99),)
    route, rationale, conf = classify("maintenance", {}, rules=pack)
    assert route == "full_permit"
    assert conf == 0.99
    assert rationale == "Local rule."


def test_every_work_type_has_a_catch_all() -> None:
    # Each built-in work type must resolve to something other than the global
    # undetermined fallback when given empty criteria (except 'other').
    covered = {r.work_type for r in DEFAULT_ROUTE_RULES if not r.conditions}
    for wt in (
        "new_build",
        "reconstruction",
        "capital_repair",
        "re_equipment",
        "maintenance",
        "demolition",
        "change_of_use",
        "other",
    ):
        assert wt in covered, f"{wt} has no catch-all rule"


# ── intl labels ──────────────────────────────────────────────────────────────


def test_work_type_labels_localise() -> None:
    assert intl.describe_work_type("new_build", "en") == "New build"
    assert intl.describe_work_type("new_build", "ru") == "Новое строительство"
    assert intl.describe_work_type("new_build", "de") == "Neubau"


def test_route_labels_localise() -> None:
    assert intl.describe_route("full_permit", "es") == "Permiso completo"
    assert intl.describe_route("exempt", "de") == "Genehmigungsfrei"


def test_unknown_locale_falls_back_to_english() -> None:
    assert intl.describe_work_type("demolition", "zz") == "Demolition"
    assert intl.describe_work_type("demolition", None) == "Demolition"


def test_unknown_code_is_humanised_not_raw() -> None:
    assert intl.describe_route("special_case_route", "en") == "Special Case Route"


# ── route_determined validation rule ─────────────────────────────────────────


def _run_rule(data: object, project_id: str | None = "p1") -> bool:
    rule = RouteDeterminedRule()
    ctx = ValidationContext(data=data, project_id=project_id)
    results = asyncio.run(rule.validate(ctx))
    assert len(results) == 1
    return results[0].passed


def test_route_rule_passes_on_confirmed_route() -> None:
    data = {"assessments": [{"status": "confirmed", "determined_route": "full_permit"}]}
    assert _run_rule(data) is True


def test_route_rule_fails_on_no_assessment() -> None:
    assert _run_rule({"assessments": []}) is False


def test_route_rule_fails_on_draft_only() -> None:
    data = {"assessments": [{"status": "draft", "determined_route": "full_permit"}]}
    assert _run_rule(data) is False


def test_route_rule_fails_on_confirmed_undetermined() -> None:
    data = {"assessments": [{"status": "confirmed", "determined_route": "undetermined"}]}
    assert _run_rule(data) is False


def test_route_rule_accepts_single_dict_and_list() -> None:
    single = {"status": "confirmed", "determined_route": "notification"}
    assert _run_rule(single) is True
    assert _run_rule([single]) is True
