# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The synthetic fixture course is a valid input for every later wave.

``tests/fixtures/trainer/course_fixture_v1.json`` is what the spec loader, the
checker and the seeder will all be tested against before any real course file
is loaded. It is invented end to end: no name, figure or rule comes from a real
course. These tests pin the properties the later waves rely on, so a careless
edit to the fixture fails here rather than as a confusing failure three modules
away:

* it uses the union of the course-file keys from the backend design, plus the
  new machine fields (``readback[].probe``, ``answer_key[].graded_by``, seed
  ``stage``, rate ``unit``, ``vat_rate_percent``, SOV ``unit`` and
  ``metadata.classification``, ``probe.gate``);
* every task opens a registered lock and grades at least one item through a
  probe that reads the ERP (decision 6), so "right numbers in the panel, ERP
  untouched" can fail;
* the diagnoses of one field cannot be confused with each other or with the
  right answer, within that field's tolerance;
* every figure the fixture states adds up.

It reads the raw file with ``parse_float=Decimal``, as the loader does, so no
comparison here goes through a float. Being raw, it still sees the root
``authoring`` object and the ``_``-prefixed keys the loader strips; the spec
tests pin the stripping.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.trainer.locks import is_known_lock_id
from app.modules.trainer.probe_types import ERP_PROBE_TYPE_NAMES, PROBE_TYPE_NAMES

COURSE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "trainer" / "course_fixture_v1.json"

ROOT_KEYS = {
    "id", "version", "status", "title", "summary", "country", "region", "currency", "as_of",
    "story_period", "rules_checked_on", "contract", "fictional_case", "language",
    "erp_walked_version", "sources", "derivation_language", "constants", "conventions", "rules",
    "status_vocabulary", "seed", "tasks", "badge",
    "contract_choice_reason", "diagnosis_semantics", "jurisdiction", "schema_additions_vs_uk",
    "locale", "date_style", "legal_review", "authoring",
}  # fmt: skip
TASK_KEYS_SHARED = {
    "id", "n", "title", "role", "module", "opens", "opens_label", "estimated_minutes", "brief",
    "steps", "answer_key", "readback", "checks", "trace_question", "explain_question",
    "diagnoses", "hints", "given",
}  # fmt: skip
TASK_KEYS_COURSE_ONLY = {"dc4_step", "erp_fit", "optional_answer_key", "panel_notes", "seeder", "video"}
SEED_BLOCKS_WITH_STAGE = {"project", "boq", "surety_bond_row", "bid_package", "contract"}
#: Canonical per-period and per-change lists (coordinator freeze (a)); every entry is staged.
SEED_LISTS_WITH_STAGE = {"progress_readings", "variations"}
_STAGE_RE = re.compile(r"^(on_enrol|on_unlock\(([1-9]\d*)\))$")
_GRADED_BY_RE = re.compile(r"^(panel|both|probe:(\d+))$")


@pytest.fixture(scope="module")
def course() -> dict:
    return json.loads(COURSE_PATH.read_text(encoding="utf-8"), parse_float=Decimal)


@pytest.fixture(scope="module")
def tasks(course: dict) -> list[dict]:
    return course["tasks"]


def test_the_root_carries_the_union_of_keys(course: dict) -> None:
    assert set(course) == ROOT_KEYS


def test_the_tasks_cover_the_shared_and_course_only_keys(tasks: list[dict]) -> None:
    seen = set().union(*(set(t) for t in tasks))
    assert seen == TASK_KEYS_SHARED | TASK_KEYS_COURSE_ONLY
    for task in tasks:
        assert set(task) >= TASK_KEYS_SHARED, task["id"]


def test_no_figure_was_read_as_a_float(course: dict) -> None:
    def walk(node: object) -> None:
        assert not isinstance(node, float), node
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(course)


def test_tasks_are_numbered_one_to_five_with_short_unique_ids(tasks: list[dict]) -> None:
    assert [t["n"] for t in tasks] == [1, 2, 3, 4, 5]
    ids = [t["id"] for t in tasks]
    assert len(set(ids)) == len(ids)
    # oe_trainer_task_state.task_id is String(16); PostgreSQL enforces it.
    assert all(len(i) <= 16 for i in ids), ids


def test_every_task_opens_a_registered_lock(course: dict, tasks: list[dict]) -> None:
    for task in tasks:
        assert is_known_lock_id(task["opens"]), task["opens"]
    assert tasks[-1]["opens"] == f"badge:{course['badge']['id']}"


def test_every_probe_type_is_on_the_closed_list(tasks: list[dict]) -> None:
    for task in tasks:
        for readback in task["readback"]:
            assert "probe" in readback, f"{task['id']}: readback without a probe"
            assert readback["probe"]["type"] in PROBE_TYPE_NAMES, readback["probe"]["type"]


def test_graded_by_names_a_readback_that_reads_the_same_ledger_key(tasks: list[dict]) -> None:
    for task in tasks:
        for answer in task["answer_key"]:
            match = _GRADED_BY_RE.match(answer["graded_by"])
            assert match, f"{task['id']}.{answer['name']}: graded_by {answer['graded_by']!r}"
            if match.group(2) is not None:
                index = int(match.group(2))
                assert index < len(task["readback"]), f"{task['id']}.{answer['name']}: no readback {index}"
                assert answer["ledger_key"] in task["readback"][index]["expects"]
            if answer["graded_by"] == "both":
                readers = [r for r in task["readback"] if answer["ledger_key"] in r["expects"]]
                assert len(readers) == 1, f"{task['id']}.{answer['name']}: 'both' needs exactly one readback"


def test_every_task_grades_an_item_through_an_erp_probe(tasks: list[dict]) -> None:
    """Decision 6: right numbers in the panel with the ERP untouched must fail."""
    for task in tasks:
        erp_readbacks = {i for i, r in enumerate(task["readback"]) if r["probe"]["type"] in ERP_PROBE_TYPE_NAMES}
        probe_only = [
            a["name"]
            for a in task["answer_key"]
            if a["graded_by"].startswith("probe:") and int(a["graded_by"].split(":")[1]) in erp_readbacks
        ]
        assert probe_only, f"{task['id']}: no answer is graded through the ERP alone"


def test_every_readback_expectation_resolves_in_this_file(course: dict, tasks: list[dict]) -> None:
    rule_keys = {r["key"] for r in course["rules"]}
    for task in tasks:
        keys = {a["ledger_key"] for a in task["answer_key"]} | rule_keys
        for readback in task["readback"]:
            if not readback["expects"]:
                assert "expect" in readback["probe"], f"{task['id']}: {readback['what']} expects nothing"
            for key in readback["expects"]:
                assert key in keys, f"{task['id']}: {key} does not resolve in this file"


def test_numbers_checks_list_only_answers_the_panel_grades(tasks: list[dict]) -> None:
    for task in tasks:
        panel = {a["name"] for a in task["answer_key"] if a["graded_by"] in ("panel", "both")}
        numbers = [c for c in task["checks"] if c["kind"] == "numbers"]
        assert len(numbers) == 1, task["id"]
        assert numbers[0]["expects"], task["id"]
        assert set(numbers[0]["expects"]) <= panel, task["id"]
        assert {c["kind"] for c in task["checks"]} == {"numbers", "trace", "explain"}


def test_answer_names_are_unique_within_a_task(tasks: list[dict]) -> None:
    for task in tasks:
        names = [a["name"] for a in task["answer_key"]]
        assert len(names) == len(set(names)), task["id"]


def test_every_question_has_exactly_one_correct_option_and_full_feedback(tasks: list[dict]) -> None:
    for task in tasks:
        for key in ("trace_question", "explain_question"):
            options = task[key]["options"]
            assert sum(1 for o in options if o["correct"]) == 1, f"{task['id']}.{key}"
            assert all(o["feedback"] for o in options), f"{task['id']}.{key}"


def test_diagnoses_cannot_collide_within_their_own_field(tasks: list[dict]) -> None:
    for task in tasks:
        answers = {a["name"]: a for a in task["answer_key"]}
        by_field: dict[str, list[Decimal]] = {}
        for diag in task["diagnoses"]:
            assert diag["applies_to"] in answers, f"{task['id']}: {diag['id']} applies to an unknown field"
            if diag["kind"] == "convention" and "wrong_value" not in diag:
                assert diag["when"], diag["id"]
                continue
            by_field.setdefault(diag["applies_to"], []).append(Decimal(str(diag["wrong_value"])))
        for field, wrong_values in by_field.items():
            tolerance = Decimal(answers[field]["tolerance"])
            correct = Decimal(str(answers[field]["value"]))
            for i, wrong in enumerate(wrong_values):
                assert abs(wrong - correct) > tolerance, f"{task['id']}.{field}: {wrong} is the right answer"
                for other in wrong_values[i + 1 :]:
                    assert abs(wrong - other) > tolerance, f"{task['id']}.{field}: {wrong} and {other} collide"


def test_every_seed_block_carries_a_machine_stage(course: dict) -> None:
    seed = course["seed"]
    for block in SEED_BLOCKS_WITH_STAGE:
        assert _STAGE_RE.match(seed[block]["stage"]), f"seed.{block}.stage = {seed[block]['stage']!r}"
    for name in SEED_LISTS_WITH_STAGE:
        assert seed[name], f"seed.{name} is empty"
        for entry in seed[name]:
            assert _STAGE_RE.match(entry["stage"]), f"seed.{name}[].stage = {entry['stage']!r}"
    stages = {block: seed[block]["stage"] for block in SEED_BLOCKS_WITH_STAGE}
    assert stages["contract"] == "on_unlock(4)"
    assert stages["project"] == "on_enrol"


def test_every_rate_states_its_unit(course: dict) -> None:
    """A unit is required where a value is a rate (coordinator freeze (c)), optional elsewhere."""
    unitless = [r for r in course["rules"] if "unit" not in r]
    assert unitless, "a rule that is not a rate must appear, to pin that it may omit its unit"
    for rule in unitless:
        assert not 0 < Decimal(str(rule["value"])) <= 1, f"{rule['key']} looks like a fraction and needs a unit"
    rates = [r for r in course["rules"] if "unit" in r]
    rates.append(course["seed"]["contract"]["retention_percent"])
    rates.append(course["seed"]["surety_bond_row"])
    rates += [a for t in course["tasks"] for a in t["answer_key"] if "unit" in a]
    assert {r["unit"] for r in rates} == {"percent", "fraction"}, "both rate shapes must appear"
    for rate in rates:
        assert rate["unit"] in ("percent", "fraction")
        if rate["unit"] == "fraction" and "value" in rate:
            assert Decimal(str(rate["value"])) <= 1, rate


def test_the_contract_states_vat_and_signable_sov_lines(course: dict) -> None:
    contract = course["seed"]["contract"]
    assert Decimal(str(contract["vat_rate_percent"])) == Decimal("20")
    lines = contract["schedule_of_values"]
    assert lines
    for line in lines:
        assert "classification" not in line, f"{line['code']}: flat classification (decision 18)"
        assert line["unit"], line["code"]
        assert line["metadata"]["classification"].get("nrm"), line["code"]
        assert re.match(r"^(csa|none|boq:[\d.]+)$", line["progress_link"]), line["progress_link"]


def test_the_figures_add_up(course: dict) -> None:
    """Every total the fixture states is the sum it claims, in Decimal."""
    seed = course["seed"]
    positions = seed["boq"]["positions"]
    rates = {"01.002": Decimal("46.20")}
    direct = sum(Decimal(p["qty"]) * (rates.get(p["code"]) or Decimal(str(p["rate"]))) for p in positions)
    assert direct == Decimal(str(seed["boq"]["direct_cost_after_t1"]["value"]))

    overheads = direct * Decimal("0.08")
    profit = direct * Decimal("0.05")
    t2 = {a["name"]: Decimal(str(a["value"])) for a in course["tasks"][1]["answer_key"]}
    assert overheads == t2["overheads_amount"]
    assert direct + overheads + profit == t2["grand_total"]

    for bid in seed["bid_package"]["bids"]:
        priced = [Decimal(str(line["amount"])) for line in bid["lines"] if line["amount"] is not None]
        assert sum(priced) == Decimal(str(bid["total"])), bid["bidder"]

    sov = seed["contract"]["schedule_of_values"]
    total = sum(Decimal(str(line["amount"])) for line in sov)
    assert total == Decimal(str(seed["contract"]["value"]["value"]))
    assert total == Decimal(str(seed["contract"]["schedule_total"]["value"]))

    t4 = {a["name"]: Decimal(str(a["value"])) for a in course["tasks"][3]["answer_key"]}
    gross = sum(Decimal(str(r["value"])) for r in seed["progress_readings"][0]["readings"])
    assert gross == t4["gross_valuation"]
    assert gross * Decimal("0.05") == t4["retention_amount"]
    assert gross - t4["retention_amount"] == t4["net_due"]

    t5 = {a["name"]: Decimal(str(a["value"])) for a in course["tasks"][4]["answer_key"]}
    vr = sum(Decimal(s["qty"]) * Decimal(str(s["rate"])) for s in seed["variations"][0]["scope"])
    assert vr == t5["vr_net"]
    assert total + vr == t5["new_contract_sum"]
