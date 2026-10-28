"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Where the governance demo seed leaves each project, as data, before anything touches a database.

The module seeders tell a pre-construction or a running-site story from the
state governance left behind, so the placements and the reading of a pack's
demo file are checked here on the catalogues themselves.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.partner_pack import discovery
from app.modules.project_governance import catalogue_packs as packs
from app.modules.project_governance import seed_story as story
from app.modules.project_governance.catalogue import get_catalogue

NEUTRAL = get_catalogue("neutral")
FRAMEWORK = get_catalogue("elf_module_framework")


# ── walking the gates ──


def test_the_neutral_model_reaches_construction_through_eight_gates() -> None:
    walk = story.gates_until(NEUTRAL, "construction_start")
    assert len(walk) == 8
    assert walk[0] == "strategy_to_brief" and walk[-1] == "award_to_construction"


def test_the_gate_into_handover_is_the_one_after_construction_starts() -> None:
    assert story.gates_until(NEUTRAL, "handover")[-1] == "construction_to_handover"
    assert story.gates_until(NEUTRAL, "handover")[:-1] == story.gates_until(NEUTRAL, "construction_start")


def test_a_two_phase_model_starts_construction_at_its_only_gate() -> None:
    assert story.gates_until(FRAMEWORK, "construction_start") == ["development_to_execution"]


def test_a_capability_no_phase_enables_gives_no_walk() -> None:
    assert story.gates_until(NEUTRAL, "no_such_capability") == []


def test_the_walk_follows_the_phases_not_the_order_of_the_file() -> None:
    shuffled = SimpleNamespace(
        phases=NEUTRAL.phases, gates=tuple(reversed(NEUTRAL.gates)), phases_enabling=NEUTRAL.phases_enabling
    )
    assert story.gates_until(shuffled, "construction_start") == story.gates_until(NEUTRAL, "construction_start")


def test_the_placed_demo_projects_exist_as_templates() -> None:
    source = (Path(discovery.__file__).resolve().parents[1] / "demo_projects.py").read_text(encoding="utf-8")
    assert set(story.PLACEMENT.values()) == {"execution", "near_handover"}
    for demo_id in story.PLACEMENT:
        assert f'demo_id="{demo_id}"' in source, demo_id


def test_every_frame_document_gets_its_own_container() -> None:
    plans = [story.document_plan(d.code) for d in NEUTRAL.document_types]
    assert len({p.container_code for p in plans}) == len(plans)
    assert all(p.title and p.file_name.endswith(".pdf") and len(p.container_code) <= 255 for p in plans)
    assert story.document_plan("master_schedule").title == "Master schedule"


# ── the demo file of a pack ──


def _file() -> dict[str, Any]:
    areas = [a.code for a in FRAMEWORK.areas]
    return {
        "schema_version": 1,
        "project": {"demo_template_id": "office-frankfurt"},
        "pins": [
            {"kind": "phase_model", "source": "pack", "id": "pack_model", "version": 3},
            {"kind": "permit_type", "source": "pack", "id": "other", "version": 1},
        ],
        "governance": {
            "four_eyes": True,
            "area_owners": {code: ("cost" if i % 4 == 0 else "owner") for i, code in enumerate(areas)},
            "frame_documents": [
                {
                    "doc_type": d.code,
                    "container_code": f"GOV-{i:02d}",
                    "title": {"en": f"Frame {i}", "de": f"Rahmen {i}"},
                    "file_name": f"frame-{i}.pdf",
                    "revisions": 2,
                    "state": "draft" if i == 0 else "in_review",
                }
                for i, d in enumerate(FRAMEWORK.document_types)
            ],
            "gate": {
                "code": "development_to_execution",
                "target_in_days": 21,
                "stop_at": "in_preparation",
                "checks": [
                    {"area": code, "status": "ready", "rag": "green", "note": {"en": "Fine", "de": "In Ordnung"}}
                    for code in areas
                ],
                "decision": None,
            },
        },
    }


def test_the_pin_is_the_phase_model_of_the_file() -> None:
    assert story.pack_pin(_file()) == ("pack_model", 3)


def test_a_valid_file_becomes_the_story_in_the_project_language() -> None:
    told = story.pack_story(_file(), FRAMEWORK, "de")
    assert told.four_eyes is True
    assert set(told.area_owners) == {a.code for a in FRAMEWORK.areas}
    assert [d.title for d in told.documents][:2] == ["Rahmen 0", "Rahmen 1"]
    assert [d.submit for d in told.documents][:2] == [False, True]
    assert told.documents[0].revisions == 2
    assert (told.gate_code, told.stop_at, told.target_in_days) == ("development_to_execution", "in_preparation", 21)
    assert told.checks[0].note == "In Ordnung"
    assert told.decision is None


def test_a_language_the_file_does_not_have_falls_back_to_english() -> None:
    assert story.pack_story(_file(), FRAMEWORK, "fr").documents[0].title == "Frame 0"


def _without_area(data: dict[str, Any]) -> None:
    data["governance"]["area_owners"].popitem()


def _unknown_login(data: dict[str, Any]) -> None:
    first = next(iter(data["governance"]["area_owners"]))
    data["governance"]["area_owners"][first] = "design manager"


def _decider_owns(data: dict[str, Any]) -> None:
    first = next(iter(data["governance"]["area_owners"]))
    data["governance"]["area_owners"][first] = "decider"


def _binding(data: dict[str, Any]) -> None:
    data["governance"]["frame_documents"][1]["state"] = "binding"


def _missing_document(data: dict[str, Any]) -> None:
    data["governance"]["frame_documents"].pop()


def _same_container(data: dict[str, Any]) -> None:
    docs = data["governance"]["frame_documents"]
    docs[1]["container_code"] = docs[0]["container_code"]


def _unknown_gate(data: dict[str, Any]) -> None:
    data["governance"]["gate"]["code"] = "no_such_gate"


def _unknown_stop(data: dict[str, Any]) -> None:
    data["governance"]["gate"]["stop_at"] = "on_hold"


def _decided_without_decision(data: dict[str, Any]) -> None:
    data["governance"]["gate"]["stop_at"] = "decided"


def _decision_without_deciding(data: dict[str, Any]) -> None:
    data["governance"]["gate"]["decision"] = {"outcome": "go", "rationale": "", "conditions": []}


def _check_status(data: dict[str, Any]) -> None:
    data["governance"]["gate"]["checks"][0]["status"] = "not_applicable"


def _check_missing(data: dict[str, Any]) -> None:
    data["governance"]["gate"]["checks"].pop()


def _four_eyes_text(data: dict[str, Any]) -> None:
    data["governance"]["four_eyes"] = "yes"


def _no_pin(data: dict[str, Any]) -> None:
    data["pins"] = [p for p in data["pins"] if p["kind"] != "phase_model"]


def _shipped_pin(data: dict[str, Any]) -> None:
    data["pins"][0]["source"] = "shipped"


@pytest.mark.parametrize(
    "fault",
    [
        _without_area,
        _unknown_login,
        _decider_owns,
        _binding,
        _missing_document,
        _same_container,
        _unknown_gate,
        _unknown_stop,
        _decided_without_decision,
        _decision_without_deciding,
        _check_status,
        _check_missing,
        _four_eyes_text,
    ],
)
def test_a_file_that_breaks_a_rule_is_refused_whole(fault) -> None:
    data = copy.deepcopy(_file())
    fault(data)
    with pytest.raises(story.DemoFileError):
        story.pack_story(data, FRAMEWORK, "en")


@pytest.mark.parametrize("fault", [_no_pin, _shipped_pin])
def test_a_file_without_a_pack_phase_model_names_no_pin(fault) -> None:
    data = copy.deepcopy(_file())
    fault(data)
    with pytest.raises(story.DemoFileError):
        story.pack_pin(data)


def test_a_gate_the_seed_cannot_reach_is_refused() -> None:
    data = _file()
    areas = [a.code for a in NEUTRAL.areas]
    data["governance"]["area_owners"] = dict.fromkeys(areas, "owner")
    data["governance"]["frame_documents"] = [
        {
            "doc_type": d.code,
            "container_code": f"G-{i}",
            "title": "T",
            "file_name": "t.pdf",
            "revisions": 1,
            "state": "draft",
        }
        for i, d in enumerate(NEUTRAL.document_types)
    ]
    data["governance"]["gate"]["checks"] = [{"area": a, "status": "ready", "rag": "green", "note": ""} for a in areas]
    data["governance"]["gate"]["code"] = "strategy_to_brief"
    assert story.pack_story(data, NEUTRAL, "en").gate_code == "strategy_to_brief"
    data["governance"]["gate"]["code"] = "brief_to_concept"
    with pytest.raises(story.DemoFileError, match="first gate"):
        story.pack_story(data, NEUTRAL, "en")


def test_a_decided_gate_carries_its_decision() -> None:
    data = _file()
    area = FRAMEWORK.areas[0].code
    data["governance"]["gate"]["stop_at"] = "decided"
    data["governance"]["gate"]["decision"] = {
        "outcome": "go_with_conditions",
        "rationale": {"en": "Go ahead", "de": "Freigabe"},
        "conditions": [{"area": area, "text": {"en": "Close it"}, "owner": "cost", "due_in_days": 14}],
    }
    decision = story.pack_story(data, FRAMEWORK, "en").decision
    assert decision is not None
    assert (decision.outcome, decision.rationale) == ("go_with_conditions", "Go ahead")
    assert [(c.area, c.text, c.owner, c.due_in_days, c.severity) for c in decision.conditions] == [
        (area, "Close it", "cost", 14, "essential")
    ]


# ── finding the file ──


@pytest.fixture
def pack(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {
        "active": SimpleNamespace(slug="p", metadata={"demo": {"path": "demo/d.json"}}),
        "files": {},
    }
    monkeypatch.setattr(discovery, "get_active_pack", lambda: state["active"])
    monkeypatch.setattr(discovery, "read_pack_file", lambda slug, rel: state["files"].get((slug, rel)))
    return state


def test_the_demo_file_of_the_active_pack_is_read(pack: dict[str, Any]) -> None:
    pack["files"][("p", "demo/d.json")] = json.dumps(_file()).encode()
    assert packs.active_pack_demo() == _file()


def test_no_pack_no_path_or_no_file_is_no_demo(pack: dict[str, Any]) -> None:
    assert packs.active_pack_demo() is None  # the file is missing
    pack["active"] = SimpleNamespace(slug="p", metadata={})
    assert packs.active_pack_demo() is None
    pack["active"] = None
    assert packs.active_pack_demo() is None


@pytest.mark.parametrize("raw", [b"{not json", b"[]", json.dumps({"schema_version": 2}).encode()])
def test_a_file_the_seed_cannot_read_is_no_demo(pack: dict[str, Any], raw: bytes) -> None:
    pack["files"][("p", "demo/d.json")] = raw
    assert packs.active_pack_demo() is None
    # Not the same as a pack that ships no demo: the seed reports this one.
    assert packs.active_pack_demo_reading() == ("unreadable", None)


def test_the_reading_tells_a_pack_without_a_demo_from_one_whose_file_is_lost(pack: dict[str, Any]) -> None:
    assert packs.active_pack_demo_reading() == ("unreadable", None)  # named, not carried
    pack["files"][("p", "demo/d.json")] = json.dumps(_file()).encode()
    assert packs.active_pack_demo_reading() == ("read", _file())
    pack["active"] = SimpleNamespace(slug="p", metadata={})
    assert packs.active_pack_demo_reading() == ("absent", None)
    pack["active"] = None
    assert packs.active_pack_demo_reading() == ("absent", None)


# ── what the seed reports ──

PID = "00000000-0000-0000-0000-000000000001"


def test_the_planned_moment_is_known_before_any_story_is_read() -> None:
    assert story.planned_moment("residential-berlin", None) == "execution"
    assert story.planned_moment("medical-us", None) == "near_handover"
    assert story.planned_moment("office-london", None) == "first_gate"
    assert story.planned_moment(None, None) == "first_gate"
    # The project the pack names is planned as the pack story even when its file later fails the rules.
    assert story.planned_moment("office-frankfurt", "office-frankfurt") == "pack"
    assert story.planned_moment("medical-us", "medical-us") == "pack"
    assert story.planned_moment(None, None) == "first_gate"


def test_the_project_a_demo_file_names() -> None:
    assert story.pack_demo_id({"project": {"demo_template_id": "office-frankfurt"}}) == "office-frankfurt"
    for data in (None, [], {}, {"project": "x"}, {"project": {}}, {"project": {"demo_template_id": 7}}):
        assert story.pack_demo_id(data) is None


def test_a_project_left_at_its_planned_moment_is_no_fallback() -> None:
    row = story.placement(PID, "medical-us", "near_handover", "near_handover")
    assert row == {
        "project_id": PID,
        "demo_id": "medical-us",
        "planned": "near_handover",
        "reached": "near_handover",
        "fallback_reason": None,
        "skipped": False,
        "named": True,
        "loud": False,
    }
    assert story.seed_result([row]) == {
        "projects": 1,
        "placements": [row],
        "fallbacks": [],
        "pack_demo_file": "absent",
        "ok": True,
    }


def test_a_named_project_left_with_the_first_gate_story_is_a_fallback() -> None:
    row = story.placement(PID, "residential-berlin", "execution", "first_gate", "gate_blocked")
    assert (row["fallback_reason"], row["named"], row["loud"]) == ("gate_blocked", True, True)
    result = story.seed_result([row])
    # The project did get a model, so it counts; the miss is what the caller has to see.
    assert (result["projects"], result["fallbacks"], result["ok"]) == (1, [row], False)


def test_a_pack_project_whose_file_broke_a_rule_is_a_fallback_although_a_story_was_told() -> None:
    row = story.placement(PID, "office-frankfurt", "pack", "first_gate", "demo_file_invalid")
    assert row["fallback_reason"] == "demo_file_invalid"
    assert story.seed_result([row], "read")["ok"] is False


def test_a_project_that_got_nothing_is_loud_and_one_seeded_earlier_is_not() -> None:
    nothing = story.placement(PID, "office-london", "first_gate", None, "story_error")
    earlier = story.placement(PID, "medical-us", "near_handover", None, skipped=True)
    # Nobody placed this project, and still: a demo project without a model is a fault.
    assert (nothing["fallback_reason"], nothing["named"], nothing["loud"]) == ("story_error", False, True)
    assert (earlier["fallback_reason"], earlier["skipped"], earlier["loud"]) == (None, True, False)
    result = story.seed_result([nothing, earlier])
    assert (result["projects"], result["fallbacks"], result["ok"]) == (0, [nothing], False)


def test_a_project_told_by_its_owner_alone_is_reported_and_does_not_fail_the_run() -> None:
    """An installation without the demo logins is a legal state, for a placed project too."""
    rows = [
        story.placement(PID, demo_id, planned, story.OWNER_ONLY, reason)
        for demo_id, planned in (("office-london", "first_gate"), ("residential-berlin", "execution"))
        for reason in sorted(story.ONE_PERSON_REASONS)
    ]
    assert [(r["fallback_reason"], r["loud"]) for r in rows] == [
        ("no_decider", False),
        ("owner_is_decider", False),
    ] * 2
    result = story.seed_result(rows)
    assert (result["projects"], result["fallbacks"], result["ok"]) == (4, rows, True)


def test_the_project_the_pack_names_waits_quietly_for_the_demo_logins() -> None:
    """Without the demo logins the filmed project is left alone at info; any other miss of it stays loud."""
    for reached in (None, story.OWNER_ONLY):
        row = story.placement(PID, "office-frankfurt", "pack", reached, "no_decider")
        assert (row["fallback_reason"], row["loud"]) == ("no_decider", False)
        assert story.seed_result([row], "read")["ok"] is True
    for reason in ("owner_is_decider", "gate_blocked"):
        row = story.placement(PID, "office-frankfurt", "pack", None, reason)
        assert row["loud"] is True


def test_a_placed_project_that_missed_for_another_reason_stays_loud() -> None:
    blocked = story.placement(PID, "residential-berlin", "execution", story.OWNER_ONLY, "gate_blocked")
    with_people = story.placement(PID, "residential-berlin", "execution", "first_gate", "no_decider")
    assert (blocked["loud"], with_people["loud"]) == (True, True)
    assert story.seed_result([blocked])["ok"] is False


def test_a_miss_without_a_known_reason_still_carries_one() -> None:
    assert story.placement(PID, None, "first_gate", None)["fallback_reason"] == "story_error"
    assert story.placement(PID, None, "first_gate", None, "made up")["fallback_reason"] == "story_error"


def test_a_demo_file_nobody_could_read_fails_the_result_without_any_project() -> None:
    assert story.seed_result([], "unreadable")["ok"] is False
    assert story.seed_result([], "absent")["ok"] is True


def test_every_stop_of_the_seed_names_a_reason_the_result_knows() -> None:
    import ast

    source = Path(story.__file__).with_name("seed.py").read_text(encoding="utf-8")
    codes = [
        node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "SeedStop"
    ]
    assert codes, "the seed raises SeedStop nowhere; this test reads nothing"
    assert set(codes) <= story.FALLBACK_REASONS, codes


# ── a file that tells more than one project ──


def _two_projects() -> dict[str, Any]:
    first, second = _file(), _file()
    second["project"] = {"demo_template_id": "school-ludwigsburg"}
    second["module_files"] = {"permits": "demo/permits.json", "staffing": 3, "empty": ""}
    return {"schema_version": 1, "projects": [first, second]}


def test_a_file_lists_its_projects_and_the_old_single_shape_is_a_list_of_one() -> None:
    assert story.pack_demo_ids(_two_projects()) == ["office-frankfurt", "school-ludwigsburg"]
    assert story.pack_demo_ids(_file()) == ["office-frankfurt"]
    assert story.pack_demo_id(_two_projects()) == "office-frankfurt"
    assert story.pack_demo_ids(None) == [] and story.pack_demo_ids({"projects": "x"}) == []


def test_the_entry_of_a_project_is_found_by_its_demo_id_only() -> None:
    data = _two_projects()
    assert story.entry_for(data, "school-ludwigsburg") is data["projects"][1]
    assert story.entry_for(data, "office-london") is None
    assert story.entry_for(data, None) is None
    assert story.entry_for(_file(), "office-frankfurt") is not None


def test_every_project_the_file_names_is_planned_as_the_pack_story() -> None:
    named = story.pack_demo_ids(_two_projects())
    assert story.planned_moment("school-ludwigsburg", named) == "pack"
    assert story.planned_moment("office-frankfurt", named) == "pack"
    assert story.planned_moment("office-frankfurt", "office-frankfurt") == "pack"
    assert story.planned_moment("office-london", named) == "first_gate"


def test_each_entry_is_checked_on_its_own() -> None:
    data = _two_projects()
    data["projects"][1]["governance"]["gate"]["stop_at"] = "later"
    assert story.pack_story(story.entry_for(data, "office-frankfurt"), FRAMEWORK, "en").stop_at == "in_preparation"
    with pytest.raises(story.DemoFileError):
        story.pack_story(story.entry_for(data, "school-ludwigsburg"), FRAMEWORK, "en")


def test_a_module_story_is_the_json_object_the_project_names(pack: dict[str, Any]) -> None:
    pack["files"][("p", "demo/d.json")] = json.dumps(_two_projects()).encode()
    pack["files"][("p", "demo/permits.json")] = json.dumps({"authority_name": "Baurechtsamt"}).encode()
    assert packs.demo_module_story("school-ludwigsburg", "permits") == {"authority_name": "Baurechtsamt"}
    # Not named by the project, a project the file does not tell, no id at all: the seeder keeps its default.
    assert packs.demo_module_story("school-ludwigsburg", "stakeholders") == {}
    assert packs.demo_module_story("office-frankfurt", "permits") == {}
    assert packs.demo_module_story("office-london", "permits") == {}
    assert packs.demo_module_story(None, "permits") == {}


def test_a_module_story_that_cannot_be_read_is_an_error_and_the_default(
    pack: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    pack["files"][("p", "demo/d.json")] = json.dumps(_two_projects()).encode()
    assert packs.demo_module_story("school-ludwigsburg", "permits") == {}  # named, not carried
    pack["files"][("p", "demo/permits.json")] = b"[1]"
    assert packs.demo_module_story("school-ludwigsburg", "permits") == {}
    assert packs.demo_module_story("school-ludwigsburg", "staffing") == {}  # a path that is no string
    assert packs.demo_module_story("school-ludwigsburg", "empty") == {}
    assert len([r for r in caplog.records if r.levelno >= 40]) == 2


# ── the shipped file of the eleven areas pack ──

_PACK = Path(__file__).resolve().parents[3] / "packs" / "eleven-areas-framework" / "src"
_PACK = _PACK / "openconstructionerp_eleven_areas_framework"


def test_every_project_of_the_shipped_pack_file_is_a_valid_story_on_the_pack_model() -> None:
    from app.modules.project_governance.catalogue import catalogue_from_body

    data = json.loads((_PACK / "demo" / "demo_project.json").read_text(encoding="utf-8"))
    ids = story.pack_demo_ids(data)
    assert ids == ["residential-regensburg", "school-ludwigsburg"]
    for demo_id in ids:
        entry = story.entry_for(data, demo_id)
        _, version = story.pack_pin(entry)
        path = _PACK / "catalogues" / "phase_model" / "eleven_areas_framework.json"
        model = catalogue_from_body(json.loads(path.read_text(encoding="utf-8")), source="pack", origin=str(path))
        assert version == model.version
        for locale in ("en", "de"):
            told = story.pack_story(entry, model, locale)
            # Regensburg is told after its gate, the school with its gate submitted and in review.
            assert told.stop_at == {"residential-regensburg": "decided", "school-ludwigsburg": "in_review"}[demo_id]
            assert (told.decision is not None) == (told.stop_at == "decided")
            assert all(c.status != "not_assessed" for c in told.checks), demo_id
            assert all(d.title for d in told.documents), (demo_id, locale)
            assert all(c.note for c in told.checks if c.status != "not_assessed"), (demo_id, locale)


def test_the_two_shipped_projects_tell_different_stories() -> None:
    data = json.loads((_PACK / "demo" / "demo_project.json").read_text(encoding="utf-8"))
    first, second = (story.entry_for(data, d) for d in story.pack_demo_ids(data))
    assert first["governance"]["gate"]["checks"] != second["governance"]["gate"]["checks"]
    assert {d["container_code"] for d in first["governance"]["frame_documents"]}.isdisjoint(
        {d["container_code"] for d in second["governance"]["frame_documents"]}
    )
    assert second["pins"] != first["pins"], "the school resolves the Baden-Wuerttemberg permit catalogue"
