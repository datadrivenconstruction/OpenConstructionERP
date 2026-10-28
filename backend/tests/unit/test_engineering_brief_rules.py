# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Engineering brief rules, catalogues, lifecycle and wiring, without a database.

Each test names the rule and carries the case that would pass if the rule were missing: a gate with no
milestone, a milestone dated after the date its successor needs, a chain that loops back, a must
requirement nobody answers.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from app.core.fsm import FSMError
from app.modules.engineering_brief import rules
from app.modules.engineering_brief.catalogue import ENGINEERING_BRIEF_KIND, register_kinds
from app.modules.engineering_brief.fsm import BRIEF_FSM, CONCEPT_FSM

D = date
_MODULE = Path(__file__).resolve().parents[2] / "app" / "modules" / "engineering_brief"


def _shipped():
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

    register_kinds()
    return list(get_catalogue_kind(ENGINEERING_BRIEF_KIND).shipped())


def _cat(cid: str = "neutral"):
    return next(c for c in _shipped() if c.id == cid)


def _req(rid="r1", **kw):
    base = {
        "id": rid,
        "category": "performance",
        "priority": "must",
        "verification_method": "test",
        "originator": "Owner",
        "source_ref": "",
    }
    return {**base, **kw}


def _ms(mid, kind="construction_start", on=None, succ=None, lead=0, gate=None, **kw):
    return {
        "id": mid,
        "code": mid.upper(),
        "kind_code": kind,
        "planned_date": on,
        "lead_days": lead,
        "successor_id": succ,
        "gate_code": gate,
        **kw,
    }


def _codes(findings) -> list[str]:
    return [f.code for f in findings]


# ── catalogues ─────────────────────────────────────────────────────────────


def test_both_shipped_catalogues_load_and_validate() -> None:
    assert {c.id for c in _shipped()} >= {"neutral", "de"}


def test_label_keys_exist_in_en_and_de() -> None:
    en = json.loads((_MODULE / "messages" / "en.json").read_text(encoding="utf-8"))
    de = json.loads((_MODULE / "messages" / "de.json").read_text(encoding="utf-8"))
    assert set(en) == set(de)
    for c in _shipped():
        body = c.model_dump(mode="json")
        keys = [body["name_key"]]
        for group in (
            "requirement_categories",
            "concept_topics",
            "programme_kinds",
            "milestone_kinds",
            "milestone_templates",
        ):
            keys += [item["name_key"] for item in body[group]]
        assert not [k for k in keys if k not in en], keys


def test_milestone_templates_end_in_the_anchor() -> None:
    cat = _cat()
    anchor = [t for t in cat.milestone_templates if t.successor is None]
    assert [t.kind for t in anchor] == [cat.anchor_kind]


# ── requirements ───────────────────────────────────────────────────────────


def test_empty_brief_has_no_requirements_and_uncovered_categories() -> None:
    found = _codes(rules.requirement_findings(_cat(), []))
    assert "no_requirements" in found
    assert "category_uncovered" in found


def test_must_requirement_without_verification_is_flagged_but_not_blocking() -> None:
    found = rules.requirement_findings(_cat(), [_req(verification_method="")])
    hit = next(f for f in found if f.code == "requirement_unverifiable")
    assert hit.severity == rules.WARNING


def test_should_requirement_needs_no_verification() -> None:
    found = rules.requirement_findings(_cat(), [_req(priority="should", verification_method="")])
    assert "requirement_unverifiable" not in _codes(found)


# ── concept ────────────────────────────────────────────────────────────────


def test_required_topic_without_decision_is_undecided() -> None:
    cat = _cat()
    topic = next(t for t in cat.concept_topics if t.required)
    items = [{"id": "c1", "topic_code": topic.code, "decision": "  ", "requirement_ids": []}]
    found = rules.concept_findings(cat, items, [])
    assert ("topic_undecided", topic.code) in [(f.code, f.ref) for f in found]


def test_must_requirement_nobody_answers_is_reported() -> None:
    found = rules.concept_findings(_cat(), [], [_req("r1")])
    assert "requirement_unanswered" in _codes(found)


def test_concept_pointing_at_a_missing_requirement_is_blocking() -> None:
    cat = _cat()
    items = [{"id": "c1", "topic_code": cat.concept_topics[0].code, "decision": "x", "requirement_ids": ["gone"]}]
    found = rules.concept_findings(cat, items, [_req("r1")])
    assert next(f for f in found if f.code == "concept_requirement_missing").severity == rules.ERROR


# ── programme ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("qty", "unit", "expected"),
    [
        ("100", "m2", []),
        ("0", "m2", ["programme_quantity_invalid"]),
        ("-5", "m2", ["programme_quantity_invalid"]),
        ("abc", "m2", ["programme_quantity_invalid"]),
        ("100", " ", ["programme_unit_missing"]),
    ],
)
def test_programme_line_values(qty, unit, expected) -> None:
    cat = _cat()
    line = {"id": "p1", "kind_code": cat.programme_kinds[0].code, "unit": unit, "quantity": qty}
    assert _codes(rules.programme_findings(cat, [line])) == expected


def test_empty_programme_is_reported() -> None:
    assert _codes(rules.programme_findings(_cat(), [])) == ["programme_missing"]


# ── framework schedule ─────────────────────────────────────────────────────


def test_chain_cycles_finds_a_loop_and_leaves_a_chain_alone() -> None:
    loop = [_ms("a", succ="b"), _ms("b", succ="a"), _ms("c")]
    assert rules.chain_cycles(loop) == {"a", "b"}
    assert rules.chain_cycles([_ms("a", succ="b"), _ms("b")]) == set()


def test_milestone_dated_after_what_its_successor_allows_is_too_late() -> None:
    cat = _cat()
    ms = [
        _ms("a", on=D(2027, 3, 1), succ="b", lead=60),
        _ms("b", kind=cat.anchor_kind, on=D(2027, 4, 1)),
    ]
    found = rules.schedule_findings(cat, ms, [], operation_proof_date=D(2027, 4, 1))
    assert "milestone_too_late" in _codes(found)
    ok = rules.schedule_findings(
        cat, [{**ms[0], "planned_date": D(2027, 1, 1)}, ms[1]], [], operation_proof_date=D(2027, 4, 1)
    )
    assert "milestone_too_late" not in _codes(ok)


def test_missing_anchor_and_proof_date_are_blocking() -> None:
    found = rules.schedule_findings(_cat(), [], [], operation_proof_date=None)
    assert {"operation_proof_missing", "anchor_milestone_missing"} <= set(_codes(found))


def test_anchor_must_carry_the_operating_proof_date() -> None:
    cat = _cat()
    ms = [_ms("z", kind=cat.anchor_kind, on=D(2027, 5, 1))]
    found = rules.schedule_findings(cat, ms, [], operation_proof_date=D(2027, 4, 1))
    assert "anchor_date_differs" in _codes(found)


def _gate(code, order, target, status="open", activity=None):
    return {"code": code, "order": order, "target_date": target, "status": status, "schedule_activity_id": activity}


def test_every_gate_needs_exactly_one_milestone() -> None:
    cat = _cat()
    gates = [_gate("G1", 1, D(2026, 12, 1)), _gate("G2", 2, D(2027, 6, 1))]
    one = [_ms("m1", kind=cat.gate_kind, on=D(2026, 12, 1), gate="G1")]
    assert ("gate_without_milestone", "G2") in [(f.code, f.ref) for f in rules.gate_binding_findings(cat, one, gates)]
    two = [*one, _ms("m2", kind=cat.gate_kind, on=D(2026, 12, 1), gate="G1")]
    assert "gate_milestone_duplicate" in _codes(rules.gate_binding_findings(cat, two, gates))


def test_gates_out_of_order_is_blocking() -> None:
    cat = _cat()
    gates = [_gate("G1", 1, None), _gate("G2", 2, None)]
    ms = [
        _ms("m1", kind=cat.gate_kind, on=D(2027, 6, 1), gate="G1"),
        _ms("m2", kind=cat.gate_kind, on=D(2027, 1, 1), gate="G2"),
    ]
    assert "gates_out_of_order" in _codes(rules.gate_binding_findings(cat, ms, gates))


def test_gate_code_on_a_non_gate_milestone_and_gate_milestone_without_code() -> None:
    cat = _cat()
    found = rules.gate_binding_findings(
        cat,
        [_ms("a", kind="delivery", gate="G1"), _ms("b", kind=cat.gate_kind)],
        [_gate("G1", 1, None)],
    )
    assert {"gate_code_on_wrong_kind", "gate_milestone_without_gate"} <= set(_codes(found))


def test_gate_date_difference_is_a_warning_and_ignored_once_decided() -> None:
    cat = _cat()
    ms = [_ms("m1", kind=cat.gate_kind, on=D(2027, 1, 1), gate="G1")]
    open_ = rules.gate_binding_findings(cat, ms, [_gate("G1", 1, D(2027, 2, 1))])
    assert next(f for f in open_ if f.code == "gate_date_differs").severity == rules.WARNING
    decided = rules.gate_binding_findings(cat, ms, [_gate("G1", 1, D(2027, 2, 1), status="decided")])
    assert "gate_date_differs" not in _codes(decided)


def test_published_gate_milestone_must_be_the_gates_schedule_activity() -> None:
    cat = _cat()
    ms = [_ms("m1", kind=cat.gate_kind, on=D(2027, 1, 1), gate="G1", activity_id="act-1")]
    unbound = rules.gate_binding_findings(cat, ms, [_gate("G1", 1, D(2027, 1, 1))])
    assert "gate_not_bound_to_schedule" in _codes(unbound)
    bound = rules.gate_binding_findings(cat, ms, [_gate("G1", 1, D(2027, 1, 1), activity="act-1")])
    assert "gate_not_bound_to_schedule" not in _codes(bound)


# ── backplan ───────────────────────────────────────────────────────────────


def test_backplan_dates_a_chain_backwards_from_the_anchor() -> None:
    ms = [
        _ms("a", kind="design_freeze", on=D(2020, 1, 1), succ="b", lead=100),
        _ms("b", kind="construction_start", on=None, succ="c", lead=30),
        _ms("c", kind="operation_proof", on=D(2027, 6, 30)),
    ]
    changes, unreached = rules.backplan(ms, anchor_kind="operation_proof", gate_kind="gate")
    got = {c["id"]: c["to"] for c in changes}
    assert got == {"b": "2027-05-31", "a": "2027-02-20"}
    assert unreached == []


def test_backplan_keeps_gate_dates_and_reports_unreached() -> None:
    ms = [
        _ms("g", kind="gate", on=D(2027, 1, 1), gate="G1", succ=None),
        _ms("x", kind="delivery", on=D(2027, 3, 1), succ=None),
        _ms("y", kind="award", on=D(2027, 2, 1), succ="g", lead=10),
    ]
    changes, unreached = rules.backplan(ms, anchor_kind="operation_proof", gate_kind="gate")
    assert unreached == ["x"]
    assert [(c["id"], c["to"]) for c in changes] == [("y", "2026-12-22")]


def test_backplan_terminates_on_a_cycle() -> None:
    ms = [_ms("a", succ="b"), _ms("b", succ="a")]
    changes, unreached = rules.backplan(ms, anchor_kind="operation_proof", gate_kind="gate")
    assert changes == [] and sorted(unreached) == ["a", "b"]


# ── approval ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("action", "status", "can_edit", "expected"),
    [
        ("submit", "draft", True, None),
        ("submit", "revising", True, None),
        ("submit", "in_review", True, "brief_not_editable"),
        ("submit", "draft", False, rules.NO_EDIT),
        ("return", "in_review", True, None),
        ("return", "draft", True, "brief_not_in_review"),
        ("edit", "in_review", True, "brief_in_review"),
        ("edit", "draft", True, None),
    ],
)
def test_brief_action_refusal(action, status, can_edit, expected) -> None:
    assert rules.brief_action_refusal(action, status, can_edit=can_edit) == expected


def test_submission_needs_a_frame_document_only_when_gates_are_used() -> None:
    kw = {"can_edit": True, "has_frame_document": False}
    assert rules.brief_action_refusal("submit", "draft", gates_in_use=True, **kw) == "frame_document_missing"
    assert rules.brief_action_refusal("submit", "draft", gates_in_use=False, **kw) is None


# ── lifecycle ──────────────────────────────────────────────────────────────


def test_brief_lifecycle_has_no_shortcut_from_draft_to_approved() -> None:
    with pytest.raises(FSMError):
        BRIEF_FSM.validate("draft", "approved")
    BRIEF_FSM.validate("draft", "in_review")
    BRIEF_FSM.validate("in_review", "approved")
    BRIEF_FSM.validate("binding", "revising")


def test_concept_item_can_be_reopened() -> None:
    CONCEPT_FSM.validate("agreed", "open")


# ── messages cover every code the module can raise ─────────────────────────


def _source(name: str) -> str:
    return (_MODULE / name).read_text(encoding="utf-8")


def test_every_error_and_finding_code_has_a_message_in_both_languages() -> None:
    codes: set[str] = set()
    for name in ("service.py", "router.py", "rules.py", "hosting.py", "permissions.py"):
        src = _source(name)
        codes |= set(re.findall(r"(?:EngineeringBriefError|conflict|not_found|forbidden)\(\s*\"([a-z_]+)\"", src))
    assert len(codes) > 20
    for locale in ("en", "de"):
        bundle = json.loads((_MODULE / "messages" / f"{locale}.json").read_text(encoding="utf-8"))
        missing = sorted(c for c in codes if f"engineering_brief.errors.{c}" not in bundle)
        assert not missing, (locale, missing)


def test_every_finding_code_is_judged_by_a_registered_rule() -> None:
    from app.modules.engineering_brief import validators

    src = _source("rules.py")
    findings = set(re.findall(r"Finding\(\s*\"([a-z_]+)\"", src))
    judged: set[str] = set()
    for cls in vars(validators).values():
        if isinstance(cls, type) and issubclass(cls, validators._BriefRule) and cls is not validators._BriefRule:
            judged |= set(cls.codes)
    assert findings - judged == set()


def test_every_rule_has_message_keys_in_both_languages() -> None:
    from app.modules.engineering_brief import validators

    for locale in ("en", "de"):
        bundle = json.loads((_MODULE / "messages" / f"{locale}.json").read_text(encoding="utf-8"))
        for cls in vars(validators).values():
            if isinstance(cls, type) and issubclass(cls, validators._BriefRule) and cls is not validators._BriefRule:
                assert f"engineering_brief.rules.{cls.key}.fail" in bundle, cls.key
                assert f"engineering_brief.rules.{cls.key}.suggestion" in bundle, cls.key


# ── wiring ─────────────────────────────────────────────────────────────────


def test_migration_follows_the_previous_head() -> None:
    src = (_MODULE.parents[2] / "alembic" / "versions" / "v79_engineering_brief.py").read_text(encoding="utf-8")
    assert 'down_revision: str | Sequence[str] | None = "v78_site_logistics_ext"' in src


def test_rule_set_is_registered() -> None:
    from app.core.validation.engine import rule_registry
    from app.modules.engineering_brief import validators  # noqa: F401

    assert (
        rule_registry.list_rule_sets().get("engineering_brief") or "engineering_brief" in rule_registry.list_rule_sets()
    )


def test_manifest_depends_on_what_it_reads() -> None:
    from app.modules.engineering_brief.manifest import manifest

    assert manifest.name == "oe_engineering_brief"
    assert {"oe_project_governance", "oe_requirements", "oe_schedule"} <= set(manifest.depends)


# ── studies and the issued specification ───────────────────────────────────


def _study(code="STU-001", kind="site_analysis", conclusion="suitable", result="Done", document_id="d1"):
    return {"code": code, "kind": kind, "conclusion": conclusion, "result": result, "document_id": document_id}


def test_no_study_of_the_kind_is_not_met() -> None:
    assert rules.study_state("site_analysis", [_study(kind="suitability")]) == ("not_met", "no_study")


def test_a_concluded_documented_study_is_met_and_other_kinds_do_not_count() -> None:
    assert rules.study_state("site_analysis", [_study()]) == ("met", "")


@pytest.mark.parametrize(
    ("study", "detail"),
    [
        (_study(conclusion="open"), "study_open:STU-001"),
        (_study(result="  "), "study_open:STU-001"),
        (_study(document_id=None), "study_without_document:STU-001"),
    ],
)
def test_an_open_or_undocumented_study_blocks_its_kind(study, detail) -> None:
    assert rules.study_state("site_analysis", [_study("STU-009"), study]) == ("not_met", detail)


def test_specification_state_follows_the_requirements_hash() -> None:
    issues = [{"version_no": 1, "requirements_hash": "a"}, {"version_no": 2, "requirements_hash": "b"}]
    assert rules.specification_state([], "b") == ("not_met", "not_issued")
    assert rules.specification_state(issues, "b") == ("met", "v2")
    # An edit after the latest issue makes it stale, even though an older issue matches.
    assert rules.specification_state(issues, "a") == ("not_met", "stale_since_v2")
