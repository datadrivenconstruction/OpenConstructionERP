# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every ``trainer_spec`` rule, both polarities.

Green: the synthetic fixture course passes every rule, one test per rule id.
Red: one targeted edit of the fixture per rule, and that very rule id fails
with a translated message. A rule that passes both the fixture and its
mutation would be a rule that checks nothing, so a red case without its rule
failing is the test failure here, not a pass.
"""

from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationReport, rule_registry, validation_engine
from app.core.validation.messages import is_key_present
from app.modules.trainer.spec import normalise_course_dict
from app.modules.trainer.validators import (
    TRAINER_RULES,
    TRAINER_SPEC_RULE_SET,
    discriminating_items,
    register_trainer_rules,
)

BACKEND_DIR = Path(__file__).resolve().parents[3]
COURSE_PATH = BACKEND_DIR / "tests" / "fixtures" / "trainer" / "course_fixture_v1.json"
RULE_IDS = sorted(rule.rule_id for rule in TRAINER_RULES)


def _course() -> dict[str, Any]:
    raw = json.loads(COURSE_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    data, problems = normalise_course_dict(raw)
    assert problems == []
    return data


def _run(data: dict[str, Any], metadata: dict[str, Any] | None = None) -> ValidationReport:
    register_trainer_rules()
    return asyncio.run(validation_engine.validate(data=data, rule_sets=[TRAINER_SPEC_RULE_SET], metadata=metadata))


@pytest.fixture(scope="module")
def fixture_report() -> ValidationReport:
    return _run(_course(), {"sha256": "a" * 64, "previous_sha256": "a" * 64})


def test_the_rule_set_holds_every_rule_once() -> None:
    register_trainer_rules()
    register_trainer_rules()
    assert len(RULE_IDS) == len(set(RULE_IDS)) == 29
    assert rule_registry.list_rule_sets()[TRAINER_SPEC_RULE_SET] == len(RULE_IDS)


def test_the_rule_set_is_registered_from_a_clean_interpreter() -> None:
    code = (
        "from app.modules.trainer.validators import register_trainer_rules\n"
        "from app.core.validation.engine import rule_registry\n"
        "register_trainer_rules()\n"
        "print(rule_registry.list_rule_sets().get('trainer_spec'))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=300, check=True
    )
    assert out.stdout.strip().splitlines()[-1] == str(len(RULE_IDS))


def test_the_fixture_raises_no_engine_error(fixture_report: ValidationReport) -> None:
    assert fixture_report.engine_errors == []
    assert {r.rule_id for r in fixture_report.results} == set(RULE_IDS)


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_the_fixture_passes(fixture_report: ValidationReport, rule_id: str) -> None:
    failed = [r for r in fixture_report.results if r.rule_id == rule_id and not r.passed]
    assert failed == [], [(r.element_ref, r.message) for r in failed]


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_every_message_and_suggestion_is_translated(rule_id: str) -> None:
    short = rule_id.split(".", 1)[1]
    for locale in ("en", "de", "es", "ru"):
        assert is_key_present(f"trainer.{short}.suggestion", locale), (rule_id, locale)


# ── Red: one mutation per rule ───────────────────────────────────────────────


def _set(path: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(data: dict[str, Any]) -> None:
        node: Any = data
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        last = parts[-1]
        if value is _DELETE:
            del node[last]
        elif isinstance(node, list):
            node[int(last)] = value
        else:
            node[last] = value

    return mutate


_DELETE = object()


def _all_panel(data: dict[str, Any]) -> None:
    for answer in data["tasks"][0]["answer_key"]:
        answer["graded_by"] = "panel"


def _all_correct(data: dict[str, Any]) -> None:
    for option in data["tasks"][0]["trace_question"]["options"]:
        option["correct"] = True


def _nothing_graded(data: dict[str, Any]) -> None:
    task = data["tasks"][0]
    task["answer_key"], task["readback"], task["diagnoses"] = [], [], []
    task["trace_question"], task["explain_question"] = {}, {}


def _seed_already_right(data: dict[str, Any]) -> None:
    """Task 5 grades only the contract sum, and the seed already holds it."""
    task = data["tasks"][4]
    task["answer_key"][0]["graded_by"] = "panel"
    task["answer_key"][1]["value"] = data["seed"]["contract"]["value"]["value"]


def _ungraded_probe_lost(data: dict[str, Any]) -> None:
    del data["tasks"][0]["readback"][1]["probe"]


MUTATIONS: dict[str, Callable[[dict[str, Any]], None]] = {
    "trainer.task_order_contiguous": _set("tasks.1.n", 3),
    "trainer.task_id_fits_storage": _set("tasks.0.id", "t1-" + "x" * 20),
    "trainer.opens_known_lock": _set("tasks.0.opens", "boq.nothing"),
    "trainer.answer_tolerance_positive": _set("tasks.0.answer_key.1.tolerance", "0"),
    "trainer.answer_names_unique": _set("tasks.1.answer_key.1.name", "overheads_amount"),
    "trainer.every_answer_graded": _set("tasks.0.answer_key.0.graded_by", "probe:9"),
    "trainer.numbers_check_subset_of_answer_key": _set("tasks.0.checks.0.expects", ["no_such_answer"]),
    "trainer.numbers_check_lists_only_panel_answers": _set("tasks.0.checks.0.expects", ["blockwork_rate"]),
    "trainer.readback_resolves_in_file": _set("tasks.0.readback.0.expects", ["fx_not_in_file"]),
    "trainer.readback_has_probe": _ungraded_probe_lost,
    "trainer.probe_args_frozen": _set("tasks.0.readback.0.probe.args.ref", "boq.main"),
    "trainer.task_has_probe_graded_item": _all_panel,
    "trainer.task_discriminates_seed_state": _seed_already_right,
    "trainer.diagnosis_applies_to_resolves": _set("tasks.0.diagnoses.0.applies_to", "no_such_field"),
    "trainer.diagnosis_unique_per_field": _set("tasks.0.diagnoses.0.wrong_value", Decimal("30414.00")),
    "trainer.diagnosis_wrong_value_numeric": _set("tasks.0.diagnoses.0.wrong_value", "lots"),
    "trainer.related_value_unlabelled": _set("tasks.0.diagnoses.0.related.0.label", _DELETE),
    "trainer.single_correct_option": _all_correct,
    "trainer.check_id_prefix_matches_task": _set("tasks.0.checks.1.id", "x-trace"),
    "trainer.seed_stage_resolvable": _set("seed.contract.stage", "on_unlock(9)"),
    "trainer.rate_unit_explicit": _set("rules.0.unit", _DELETE),
    "trainer.percent_not_written_as_fraction": _set("seed.contract.vat_rate_percent", Decimal("0.2")),
    "trainer.einvoice_vat_resolvable": _set("seed.contract.vat_rate_percent", _DELETE),
    "trainer.sov_signable": _set("seed.contract.schedule_of_values.0.metadata.classification", {}),
    "trainer.project_rule_sets_known": _set("seed.project.validation_rule_sets", ["nrm", "nmr"]),
    "trainer.graded_items_nonzero": _nothing_graded,
    "trainer.variation_under_approval_threshold": _set("tasks.4.answer_key.0.value", Decimal("150000.00")),
    "trainer.money_scale": _set("seed.contract.schedule_of_values.0.amount", Decimal("4977.001")),
    # version_not_bumped is driven by metadata, below.
}


def test_every_rule_has_a_mutation() -> None:
    assert set(MUTATIONS) | {"trainer.version_not_bumped"} == set(RULE_IDS)


def _assert_fails(report: ValidationReport, rule_id: str) -> None:
    assert report.engine_errors == [], [r.message for r in report.engine_errors]
    failed = [r for r in report.results if r.rule_id == rule_id and not r.passed]
    assert failed, f"{rule_id} did not fail on its mutation"
    for result in failed:
        assert not result.message.startswith("trainer."), result.message
        assert result.suggestion and not result.suggestion.startswith("trainer."), result.suggestion


@pytest.mark.parametrize("rule_id", sorted(MUTATIONS))
def test_the_mutation_fails_its_rule(rule_id: str) -> None:
    data = copy.deepcopy(_course())
    MUTATIONS[rule_id](data)
    _assert_fails(_run(data), rule_id)


def test_new_content_under_a_stored_version_fails() -> None:
    report = _run(_course(), {"sha256": "b" * 64, "previous_sha256": "a" * 64})
    _assert_fails(report, "trainer.version_not_bumped")


def test_a_platform_classification_code_is_checked_not_only_present() -> None:
    data = _course()
    data["seed"]["contract"]["schedule_of_values"][0]["metadata"]["classification"]["nrm"] = "not-a-code"
    report = _run(data)
    failed = [r for r in report.results if r.rule_id == "trainer.sov_signable" and not r.passed]
    assert any(r.details.get("reason") == "platform_rule" for r in failed), [r.details for r in failed]


def test_a_flat_sov_classification_fails_the_rule_as_well_as_the_model() -> None:
    data = _course()
    line = data["seed"]["contract"]["schedule_of_values"][0]
    line["classification"] = line.pop("metadata")["classification"]
    report = _run(data)
    failed = [r for r in report.results if r.rule_id == "trainer.sov_signable" and not r.passed]
    assert any(r.details.get("reason") == "flat_classification" for r in failed)


def test_warning_rules_never_block() -> None:
    data = _course()
    MUTATIONS["trainer.project_rule_sets_known"](data)
    report = _run(data)
    failed = [r for r in report.results if not r.passed]
    assert failed
    assert all(r.severity == Severity.WARNING for r in failed)


# ── Decision 19: gate ────────────────────────────────────────────────────────


def test_an_ungated_probe_no_answer_grades_is_informational() -> None:
    data = _course()
    gated = data["tasks"][2]["readback"][2]["probe"]
    assert gated["gate"] is True
    # The fixture's retention percent readback in task 4 carries no gate and
    # no answer, and it equals the seed: it must not make task 4 look static.
    assert "gate" not in data["tasks"][3]["readback"][3]["probe"]
    items = discriminating_items(data)
    assert 3 not in {r for r, _ in items[3]}
    assert 2 in {r for r, _ in items[2]}


def test_a_gate_makes_the_probe_count_as_the_tasks_probe_graded_item() -> None:
    data = _course()
    task = data["tasks"][2]
    for answer in task["answer_key"]:
        answer["graded_by"] = "panel"
    for check in task["checks"]:
        if check["kind"] == "numbers":
            check["expects"] = [a["name"] for a in task["answer_key"]]
    report = _run(data)
    assert not [r for r in report.results if r.rule_id == "trainer.task_has_probe_graded_item" and not r.passed]
    del task["readback"][2]["probe"]["gate"]
    _assert_fails(_run(data), "trainer.task_has_probe_graded_item")
