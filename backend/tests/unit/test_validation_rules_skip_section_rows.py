"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Section headers must not be convicted of missing a leaf-row attribute.

A section header aggregates its children. By construction it carries no
unit, no quantity, no rate and no classification code: those live on the
leaf rows underneath it. A rule that demands a leaf-level code and then
walks every row therefore convicts every header in the tree, and on a
deep bill the false findings outnumber the real ones.

Two directions are asserted here, because only one of them is obvious.

Forwards: the rules listed in ``NARROWED`` must not fire on a section
row. That is the fix.

Backwards: the rules listed in ``STILL_JUDGE_SECTIONS`` must keep firing
on one, and each carries a payload proving it. Narrowing a rule silences
it on every header, and a rule that stopped firing looks exactly like a
rule that passed. Those eight judge something a header genuinely has -
a title, an ordinal, a sign, an arithmetic identity, a currency, or a
classification code it chose to carry - so narrowing them would trade a
false positive for a false negative.

Section detection has two branches (``_get_leaf_positions``): an
explicit ``type`` field, and the parent_id graph for the seed and import
paths that never stamp one. Both are exercised, because a hand-rolled
guard that covers only the explicit branch passes a test that only
exercises the explicit branch.

THE REGISTRY SWEEP at the bottom runs in an interpreter of its own. The
rule registry is a process-global object filled by import side effects,
so read in-process it holds whatever the session happened to load, and
the sweep's subject changed with test ordering. See the comment above it
for the measurements and for what the stated load set covers.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import sys
from typing import Any

import pytest

from app.core.validation.engine import ValidationContext, ValidationRule
from app.core.validation.rules import (
    BC3CodeRequired,
    BirimFiyatCodeRequired,
    CPWDCodeRequired,
    CurrencyConsistency,
    DIN276CostGroupRequired,
    DIN276ValidCostGroup,
    DPGFLotRequired,
    GBT50500CodeRequired,
    GESNCodeRequired,
    MasterFormatClassificationRequired,
    MasterFormatValidDivision,
    NegativeValues,
    NoDuplicateOrdinals,
    NRMClassificationRequired,
    NRMValidElement,
    PositionHasDescription,
    SekisanCodeRequired,
    SINAPICodeRequired,
    TotalMismatch,
)

SECTION_ID = "sec-1"
LEAF_OK_ID = "leaf-ok"
LEAF_BAD_ID = "leaf-bad"

# A code every one of the narrowed rules accepts, so the clean leaf in
# each payload is clean for whichever rule is under test. Verified by
# ``test_the_clean_leaf_is_clean_for_every_narrowed_rule`` rather than
# asserted by eye - a payload that quietly stopped being valid would
# turn every "no failure on the section" assertion into a coincidence.
GOOD_CLASSIFICATION: dict[str, str] = {
    "din276": "300",
    "nrm": "5.1.1",
    "masterformat": "03 30 00",
    "sinapi": "87878",
    "gesn": "08-01-001",
    "dpgf": "Lot 03",
    "gbt50500": "010101001",
    "cpwd": "2.1",
    "birimfiyat": "15.185",
    "sekisan": "1.1",
    "bc3_code": "E04AB010",
    "code": "E04AB010",
}

# The eleven ERROR-severity rules that demand a classification code the
# leaf rows carry and the headers above them do not.
NARROWED: list[type[ValidationRule]] = [
    DIN276CostGroupRequired,
    NRMClassificationRequired,
    MasterFormatClassificationRequired,
    SINAPICodeRequired,
    GESNCodeRequired,
    DPGFLotRequired,
    GBT50500CodeRequired,
    CPWDCodeRequired,
    BirimFiyatCodeRequired,
    SekisanCodeRequired,
    BC3CodeRequired,
]

_NARROWED_IDS = [cls.__name__ for cls in NARROWED]


def _ctx(positions: list[dict[str, Any]], *, region: str = "DE", standard: str = "") -> ValidationContext:
    return ValidationContext(
        data={"positions": positions},
        project_id="00000000-0000-0000-0000-000000000000",
        region=region,
        standard=standard,
        metadata={"locale": "en"},
    )


def _section(**overrides: Any) -> dict[str, Any]:
    """A section header that is correct in every way a header can be."""
    row: dict[str, Any] = {
        "id": SECTION_ID,
        "parent_id": None,
        "ordinal": "01",
        "description": "Groundworks",
        "unit": "section",
        "quantity": 0.0,
        "unit_rate": 0.0,
        "total": 0.0,
        "type": "section",
        "classification": {},
    }
    row.update(overrides)
    return row


def _leaf(**overrides: Any) -> dict[str, Any]:
    """A priced leaf row carrying a code every narrowed rule accepts."""
    row: dict[str, Any] = {
        "id": LEAF_OK_ID,
        "parent_id": SECTION_ID,
        "ordinal": "01.001",
        "description": "Excavation to reduce levels",
        "unit": "m3",
        "quantity": 10.0,
        "unit_rate": 25.0,
        "total": 250.0,
        "currency": "EUR",
        "type": "position",
        "classification": dict(GOOD_CLASSIFICATION),
    }
    row.update(overrides)
    return row


def _run(rule: ValidationRule, positions: list[dict[str, Any]]) -> list[Any]:
    return asyncio.run(rule.validate(_ctx(positions, standard=rule.standard)))


def _failures_against(rule: ValidationRule, positions: list[dict[str, Any]], element_ref: str) -> list[Any]:
    return [r for r in _run(rule, positions) if not r.passed and r.element_ref == element_ref]


# ── The clean payload really is clean ────────────────────────────────────


@pytest.mark.parametrize("rule_cls", NARROWED, ids=_NARROWED_IDS)
def test_the_clean_leaf_is_clean_for_every_narrowed_rule(rule_cls: type[ValidationRule]) -> None:
    """Guards the shared fixture, not the rules.

    Every assertion below reads "the section produced no failure while
    the leaf did". If the leaf's code stopped satisfying some rule, that
    rule's tests would still pass for the wrong reason.
    """
    failures = _failures_against(rule_cls(), [_section(), _leaf()], LEAF_OK_ID)
    assert failures == [], f"{rule_cls.__name__} rejects the shared good code: {[f.message for f in failures]}"


# ── Forwards: a header is not convicted ──────────────────────────────────


@pytest.mark.parametrize("rule_cls", NARROWED, ids=_NARROWED_IDS)
def test_a_section_header_is_not_convicted_of_missing_a_leaf_code(rule_cls: type[ValidationRule]) -> None:
    rule = rule_cls()
    positions = [_section(), _leaf()]
    assert _failures_against(rule, positions, SECTION_ID) == []


@pytest.mark.parametrize("rule_cls", NARROWED, ids=_NARROWED_IDS)
def test_a_header_known_only_from_the_parent_graph_is_not_convicted(rule_cls: type[ValidationRule]) -> None:
    """The implicit branch, which a hand-rolled ``type`` check misses.

    The seed and spreadsheet-import paths do not stamp a ``type`` field.
    Their headers are recognisable only because another row names them
    as its parent, so a guard that reads ``type`` alone convicts every
    one of them while passing the explicit-branch test above.
    """
    rule = rule_cls()
    section = _section()
    del section["type"]
    assert _failures_against(rule, [section, _leaf()], SECTION_ID) == []


# ── Backwards: the rule did not go silent ────────────────────────────────


@pytest.mark.parametrize("rule_cls", NARROWED, ids=_NARROWED_IDS)
def test_the_rule_still_convicts_a_leaf_row_carrying_no_code(rule_cls: type[ValidationRule]) -> None:
    """Skipping headers must not become skipping everything.

    Without this, every assertion above is satisfied by a rule that
    returns an empty list - which is the shape of the defect this whole
    file exists to fix.
    """
    rule = rule_cls()
    bad_leaf = _leaf(id=LEAF_BAD_ID, ordinal="01.002", description="Backfill", classification={})
    failures = _failures_against(rule, [_section(), _leaf(), bad_leaf], LEAF_BAD_ID)
    assert len(failures) == 1, f"{rule_cls.__name__} stopped convicting an uncoded leaf row"
    assert "01.002" in failures[0].message


# ── The eight that keep judging headers, asserted rather than noted ──────

# (rule, positions, id of the row whose conviction is expected or None
# for a whole-bill finding). Each defect is something a header genuinely
# has and can get wrong, which is why narrowing these would replace a
# false positive with a false negative.
STILL_JUDGE_SECTIONS: list[tuple[type[ValidationRule], list[dict[str, Any]], str | None]] = [
    # A header with no title is unreadable in every export and outline.
    (PositionHasDescription, [_section(description=""), _leaf()], SECTION_ID),
    # Two headers sharing an ordinal collide exactly as two leaves do.
    (NoDuplicateOrdinals, [_section(), _section(id="sec-2"), _leaf()], SECTION_ID),
    # A header that chose to carry a cost group must carry a real one.
    (DIN276ValidCostGroup, [_section(classification={"din276": "999"}), _leaf()], SECTION_ID),
    (NRMValidElement, [_section(classification={"nrm": "77"}), _leaf()], SECTION_ID),
    (MasterFormatValidDivision, [_section(classification={"masterformat": "77 00 00"}), _leaf()], SECTION_ID),
    # A negative figure is wrong on any row, header included.
    (NegativeValues, [_section(quantity=-1.0), _leaf()], SECTION_ID),
    # A header whose stored total contradicts its own zeroes is corrupt.
    (TotalMismatch, [_section(total=5000.0), _leaf()], SECTION_ID),
    # A stray currency on a header still splits the bill in two.
    (CurrencyConsistency, [_section(currency="USD"), _leaf()], None),
]

_STILL_IDS = [f"{cls.__name__}" for cls, _, _ in STILL_JUDGE_SECTIONS]


@pytest.mark.parametrize(("rule_cls", "positions", "element_ref"), STILL_JUDGE_SECTIONS, ids=_STILL_IDS)
def test_these_rules_deliberately_still_judge_a_section_row(
    rule_cls: type[ValidationRule],
    positions: list[dict[str, Any]],
    element_ref: str | None,
) -> None:
    failures = [r for r in _run(rule_cls(), positions) if not r.passed]
    assert failures, f"{rule_cls.__name__} no longer judges section rows"
    if element_ref is not None:
        assert any(f.element_ref == element_ref for f in failures)


@pytest.mark.parametrize(("rule_cls", "positions", "element_ref"), STILL_JUDGE_SECTIONS, ids=_STILL_IDS)
def test_the_same_rules_pass_a_well_formed_section_row(
    rule_cls: type[ValidationRule],
    positions: list[dict[str, Any]],
    element_ref: str | None,
) -> None:
    """Still judging headers is only defensible if the judgement is fair.

    The payloads above are deliberately defective. The same rule against
    a correct header must say nothing, or "keeps judging sections" would
    just mean "convicts every section".
    """
    assert [r for r in _run(rule_cls(), [_section(), _leaf()]) if not r.passed] == []


# ── Registry-wide, so a rule added later cannot reintroduce this ─────────
#
# WHY THIS RUNS IN AN INTERPRETER OF ITS OWN. ``rule_registry`` is a single
# process-global object filled by import side effects: ``register_builtin_rules``
# puts the built-ins in it, and every ``app/modules/*/validators.py`` adds its
# own rules the moment anything imports that module. Read in-process, it holds
# whatever the session happened to load, and nothing here decides that. Measured
# on this tree, this file alone saw 125 rules; with the module validators
# imported, 165; and in two sessions where an earlier test had already built a
# FastAPI app, 251 and 297. The sweep used to read that global directly, so its
# subject was up to 172 rules wider or narrower depending on what ran before it,
# and two sessions of the same kind did not even agree with each other. A rule
# that convicts a header would then be caught in one order and missed in another
# on the same tree, and the green run and the red run would be equally honest,
# which is the same as saying neither measured anything.
#
# Pinning the order or resetting the registry between tests would only hold until
# somebody adds a test, so the process history is removed instead: the sweep
# starts a clean interpreter, loads a stated set, and answers from that. Its
# verdict is a property of the tree and of nothing else.
#
# WHAT THE STATED SET COVERS, written down because an unstated boundary gets
# exceeded by the next reader: the built-in rules, every ``validators.py`` under
# ``app/modules``, and every ``register_*_rules`` hook those modules expose. The
# hooks are not optional decoration. A module registers its rules one of two
# ways, at import or from its ``on_startup`` hook, and importing alone reaches
# only the first kind - it leaves ``design_options`` and thirty-three others
# with no rule in the registry at all. Loading both ways is what makes this
# sweep's subject the same size as the one a booted application has. What is
# still outside it is a rule set installed at runtime from a partner pack, and
# a rule registered from a router or a service rather than from ``validators``.

_BACKEND = pathlib.Path(__file__).resolve().parents[2]

# Nine of the module validators refuse to import unless DATABASE_URL names a
# PostgreSQL database, and none of them connects at import time. So the child is
# given a well-formed address that leads nowhere rather than the session's
# cluster: inheriting the live one would hand the sweep back a piece of session
# state, and a cluster a later fixture tears down is the same bug in a new place.
_INERT_DATABASE_URL = "postgresql+asyncpg://gate:gate@127.0.0.1:1/section_header_gate"
_INERT_DATABASE_SYNC_URL = "postgresql+psycopg://gate:gate@127.0.0.1:1/section_header_gate"

_SWEEP = """
import asyncio, importlib, inspect, json, pathlib, re, sys, warnings
warnings.filterwarnings("ignore")

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.rules import register_builtin_rules

payload = json.loads(sys.stdin.read())
section_id = payload["section_id"]

register_builtin_rules()
core_rules = len(rule_registry._rules)

on_disk = sorted(p.parent.name for p in pathlib.Path("app/modules").glob("*/validators.py"))
imported, failed, hooks, hook_failures = [], {}, [], {}
for name in on_disk:
    try:
        module = importlib.import_module("app.modules." + name + ".validators")
    except Exception as exc:
        failed[name] = type(exc).__name__ + ": " + str(exc)
        continue
    imported.append(name)
    for attr in sorted(vars(module)):
        if not re.fullmatch(r"register_\\w*rules", attr):
            continue
        hook = getattr(module, attr)
        if not callable(hook) or getattr(hook, "__module__", None) != module.__name__:
            continue
        label = name + "." + attr
        required = [
            p
            for p in inspect.signature(hook).parameters.values()
            if p.default is inspect.Parameter.empty and p.kind is not p.VAR_POSITIONAL and p.kind is not p.VAR_KEYWORD
        ]
        if required:
            hook_failures[label] = "takes arguments, so this sweep cannot call it"
            continue
        try:
            hook()
            hooks.append(label)
        except Exception as exc:
            hook_failures[label] = type(exc).__name__ + ": " + str(exc)


def convictions(positions):
    # Convictions that name the section row. A rule reading this payload as a
    # purchase order or a submittal reports against no row at all, and that is a
    # different defect.
    found = {}
    for rule in list(rule_registry._rules.values()):
        context = ValidationContext(
            data={"positions": positions},
            project_id="00000000-0000-0000-0000-000000000000",
            region="DE",
            standard=rule.standard,
            metadata={"locale": "en"},
        )
        try:
            results = asyncio.run(rule.validate(context))
        except Exception:
            continue
        for res in results:
            if not res.passed and res.severity == Severity.ERROR and res.element_ref == section_id:
                found[rule.rule_id] = res.message
    return found


print(json.dumps({
    "core_rules": core_rules,
    "rules": len(rule_registry._rules),
    "providers_on_disk": on_disk,
    "providers_imported": imported,
    "providers_failed": failed,
    "hooks_called": hooks,
    "hook_failures": hook_failures,
    "registered_rule_ids": sorted(rule_registry._rules),
    "clean": convictions(payload["clean"]),
    "broken": convictions(payload["broken"]),
}))
"""


@pytest.fixture(scope="module")
def sweep() -> dict[str, Any]:
    """One child run, read by all three assertions below."""
    broken_section = _section(description="", quantity=-1.0, total=5000.0)
    request = json.dumps(
        {
            "section_id": SECTION_ID,
            "clean": [_section(), _leaf()],
            "broken": [broken_section, _leaf()],
        }
    )
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _SWEEP],
        cwd=_BACKEND,
        env={
            **os.environ,
            "DATABASE_URL": _INERT_DATABASE_URL,
            "DATABASE_SYNC_URL": _INERT_DATABASE_SYNC_URL,
            "PYTHONWARNINGS": "ignore",
        },
        input=request,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, f"the registry sweep would not run: {result.stderr[-2000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_sweep_measured_the_population_it_claims_to_have_swept(sweep: dict[str, Any]) -> None:
    """The load control, and it has to name a rule only a module registers.

    What this replaces asked for more than a hundred rules in the registry and
    for three rule ids - sinapi, nrm, din276. All three are built-ins, put there
    by the very ``register_builtin_rules`` call the control made, and the
    built-ins alone clear a hundred. So the same call that satisfied the floor
    satisfied every named id, and the control stayed green with every module
    rule absent, which is precisely the population it existed to guard. A gate
    that can sweep almost nothing and report a pass is worse than the defect it
    looks for.

    So: every provider the tree holds must have imported, every registration
    hook must have run, and a rule that only a module registers must be present.
    """
    failed = sweep["providers_failed"]
    assert failed == {}, f"the sweep could not import {sorted(failed)}, so it swept less than the tree holds: {failed}"
    assert sweep["providers_on_disk"], "no app/modules/*/validators.py was found, so the sweep loaded nothing"
    assert sweep["providers_imported"] == sweep["providers_on_disk"]
    hook_failures = sweep["hook_failures"]
    assert hook_failures == {}, f"a rule registration hook did not run, so its rules were never swept: {hook_failures}"
    assert sweep["hooks_called"], "no register_*_rules hook was found, so every startup-registered rule is missing"

    registered = set(sweep["registered_rule_ids"])
    for expected in ("sinapi.code_required", "nrm.classification_required", "din276.cost_group_required"):
        assert expected in registered, f"{expected} is not registered, so this test did not measure it"
    # Registered by app/modules/design_options/validators.py and by nothing
    # else, and only from its ``on_startup`` hook, so it is absent both when no
    # module loaded and when the hooks were skipped. That is what separates
    # "the sweep saw nothing" from "nothing convicts a header".
    assert "design_options.gfa_present" in registered, (
        "no rule from a module validator reached the registry, so the sweep saw the built-ins and nothing else"
    )
    assert sweep["rules"] > sweep["core_rules"], "the module validators added no rule at all"


def test_no_registered_rule_convicts_a_well_formed_section_row(sweep: dict[str, Any]) -> None:
    """The property, stated over the registry rather than over a list.

    A list of the rules that had this defect can only ever catch the
    next one after somebody adds it to the list. This asks the question
    of every rule in the stated set, so a new standard's ``code_required``
    fails here on the day it is written.
    """
    convicted = sweep["clean"]
    assert convicted == {}, f"{len(convicted)} rule(s) convict a well-formed section header: {sorted(convicted)}"


def test_the_registry_sweep_can_see_a_conviction_at_all(sweep: dict[str, Any]) -> None:
    """Negative control for the sweep above.

    Same walk, same scoping, against a header stripped of the things a
    header legitimately has. If this finds nothing, the sweep is not
    capable of finding anything and its silence means nothing.
    """
    convicted = set(sweep["broken"])
    assert "boq_quality.position_has_description" in convicted
    assert "boq_quality.negative_values" in convicted
    assert "boq_quality.total_mismatch" in convicted


# ── Where the detector draws the line, pinned from both sides ────────────

# A header is not detected by having children. ``boq/router.py::_row_type``
# builds the real payload and calls a row a section when it has no unit,
# no quantity and no rate, and the spreadsheet importer says the same
# thing in the same words before it ever reaches the engine. So a row of
# that shape is skipped whether or not anything names it as a parent.
#
# That is a real consequence and it cuts both ways, which is why the
# neighbours are here too: change any one of the three and the row is a
# leaf again and must still be convicted. Without the second half of this
# table, "the eleven skip headers" could quietly have become "the eleven
# skip anything cheap to skip". The thirteen rules that were already on
# this helper have always drawn the line here; the eleven now agree with
# them rather than disagreeing.
DETECTOR_BOUNDARY: list[tuple[str, str, float, float, bool]] = [
    ("no unit, no quantity, no rate", "", 0.0, 0.0, False),
    ("carries a unit", "m3", 0.0, 0.0, True),
    ("carries a quantity", "", 5.0, 0.0, True),
    ("carries a rate", "", 0.0, 12.5, True),
    ("fully priced", "m3", 5.0, 12.5, True),
]


def _row_type(unit: str, quantity: float, unit_rate: float) -> str:
    """Mirrors ``boq/router.py::_row_type``, which stamps the real payload."""
    normalised = (unit or "").strip().lower()
    if normalised in ("", "section") and quantity == 0.0 and unit_rate == 0.0:
        return "section"
    return "position"


@pytest.mark.parametrize(
    ("label", "unit", "quantity", "unit_rate", "expect_convicted"),
    DETECTOR_BOUNDARY,
    ids=[case[0] for case in DETECTOR_BOUNDARY],
)
def test_only_the_unpriced_unitless_row_is_read_as_a_header(
    label: str,
    unit: str,
    quantity: float,
    unit_rate: float,
    expect_convicted: bool,
) -> None:
    row = {
        "id": "orphan",
        "parent_id": None,
        "ordinal": "07",
        "description": "Sundries",
        "unit": unit,
        "quantity": quantity,
        "unit_rate": unit_rate,
        "total": quantity * unit_rate,
        "type": _row_type(unit, quantity, unit_rate),
        "classification": {},
    }
    failures = _failures_against(SINAPICodeRequired(), [row], "orphan")
    assert bool(failures) is expect_convicted, label
