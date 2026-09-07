"""Every rule set a module asks the engine for must resolve to real rules.

A rule set is a name, and nothing checks that the name means anything. Rules
register into the set named by their ``standard`` unless the registration
passes an explicit list, so renaming a constant, or writing a rule whose
``standard`` does not match the set its module requests, leaves the module
calling ``validate(rule_sets=["something"])`` against an empty set. The call
succeeds. The report comes back clean. Nothing ran.

That is not hypothetical: three ``ai_takeoff`` rules shipped with full i18n
messages in three languages and never executed once, because no caller ever
passed that set name. The rules were eventually deleted, but the shape that
hid them is still here, and it is invisible to every other kind of test. A
behaviour test for a dormant rule passes by asserting the absence of a
finding, which is exactly what a dormant rule produces.

Registration happens along two routes and the check has to know both, or it
reports its own blind spot as a defect. Core rules land in the registry when
``register_builtin_rules`` runs. Module rules land when a module's
``validators`` module is imported, or when the module loader awaits that
package's ``on_startup`` hook, and no in-process test does either. So the first
route is checked by asking the live registry and the second by reading the
source: a set counts as reachable if some module registers into it and the
package exposes the startup hook that performs the registration. The subprocess
sweep at the end of this file does walk both module routes for real, in its own
interpreter, and is what the demo allowlist is re-asked against.

These tests live in the PG lane because that lane is a merge gate and the
default unit lane is not. The check itself needs no database.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.validation.engine import rule_registry
from app.core.validation.rules import register_builtin_rules

MODULES_DIR = Path(__file__).resolve().parents[2] / "app" / "modules"

#: Suffix that marks a module-level constant as a rule set name.
RULE_SET_SUFFIX = "_RULE_SET"


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Map module-level ``NAME = "value"`` string constants by name."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                out[target.id] = node.value.value
    return out


def _parsed_modules() -> dict[Path, ast.Module]:
    """Parse every module source once.

    Parsing rather than importing keeps a module that fails to import for an
    unrelated reason from quietly dropping its rule sets out of the check.
    """
    trees: dict[Path, ast.Module] = {}
    for path in sorted(MODULES_DIR.rglob("*.py")):
        try:
            trees[path] = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
            continue
    return trees


def _declared_rule_sets(trees: dict[Path, ast.Module]) -> dict[str, list[str]]:
    """Collect ``*_RULE_SET`` string constants declared by backend modules.

    Returns:
        Rule set name mapped to the module-relative paths declaring it.
    """
    found: dict[str, set[str]] = {}
    for path, tree in trees.items():
        for name, value in _string_constants(tree).items():
            if name.endswith(RULE_SET_SUFFIX):
                found.setdefault(value, set()).add(path.relative_to(MODULES_DIR).as_posix())
    return {name: sorted(paths) for name, paths in sorted(found.items())}


def _statically_registered(trees: dict[Path, ast.Module]) -> set[str]:
    """Rule set names some module passes to ``rule_registry.register``.

    The argument is read in both the forms the call is written in. This used to
    read ``node.args[1]`` alone, on the stated grounds that the positional form
    was "the whole signature", and that sentence was the defect. Five of the
    forty seven registrations in the tree pass ``rule_sets`` by keyword, so the
    check could not see them, and it accused the variations module of shipping
    a rule set nothing registers into while ``variations/validators.py``
    registers two rules into it on the line above. A reader defined by the
    shape of a call is blind to the same call written the other way.

    Both a literal and a reference to a constant declared in the same file are
    resolved; anything else is left out rather than guessed at, so this set is
    still a lower bound, which is why it is only ever used to explain a
    failure and never to claim coverage.
    """
    registered: set[str] = set()
    for path, tree in trees.items():
        consts = _string_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "register":
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "rule_registry":
                continue
            sets_arg: ast.expr | None = node.args[1] if len(node.args) >= 2 else None
            if sets_arg is None:
                sets_arg = next((kw.value for kw in node.keywords if kw.arg == "rule_sets"), None)
            if not isinstance(sets_arg, (ast.List, ast.Tuple)):
                continue
            for element in sets_arg.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    registered.add(element.value)
                elif isinstance(element, ast.Name) and element.id in consts:
                    registered.add(consts[element.id])
        del path
    return registered


def _packages_with_startup_hook(trees: dict[Path, ast.Module]) -> set[str]:
    """Module package names whose ``__init__.py`` defines ``on_startup``."""
    out: set[str] = set()
    for path, tree in trees.items():
        if path.name != "__init__.py":
            continue
        for node in tree.body:
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and (node.name == "on_startup"):
                out.add(path.parent.name)
    return out


@pytest.fixture(scope="module")
def trees() -> dict[Path, ast.Module]:
    """Parse the module sources once for the whole file."""
    return _parsed_modules()


@pytest.fixture(scope="module", autouse=True)
def _builtin_rules() -> None:
    """Register the built-in rules once for the whole module."""
    register_builtin_rules()


def test_modules_declare_rule_sets(trees: dict[Path, ast.Module]) -> None:
    """The discovery itself must find something.

    Without this, a refactor that renames the constant convention would turn
    every assertion below into a vacuous pass over an empty list.
    """
    declared = _declared_rule_sets(trees)
    assert len(declared) >= 4, (
        "no module rule set constants were discovered, so the reachability "
        f"check below would assert nothing. Found: {declared}"
    )


def test_every_declared_rule_set_has_rules(trees: dict[Path, ast.Module]) -> None:
    """No module may request a rule set that nothing registers into."""
    declared = _declared_rule_sets(trees)
    by_module = _statically_registered(trees)
    hooked = _packages_with_startup_hook(trees)

    dormant: dict[str, str] = {}
    for name, paths in declared.items():
        if rule_registry.has_rules(name):
            continue
        if name not in by_module:
            dormant[name] = f"declared in {', '.join(paths)}, nothing registers into it"
            continue
        owners = {p.split("/")[0] for p in paths}
        if not owners & hooked:
            dormant[name] = f"declared in {', '.join(paths)}, registered but no on_startup hook runs the registration"

    assert not dormant, (
        "these rule sets are requested by a module but resolve to no rules, so "
        "validation runs and finds nothing: " + "; ".join(f"{name} ({why})" for name, why in dormant.items())
    )


@pytest.mark.parametrize(
    "rule_set",
    ["procurement", "subcontract", "submittal", "rfq_issue", "rfq_award", "boq_quality"],
)
def test_known_rule_set_is_reachable(rule_set: str) -> None:
    """Pin the core sets whose reachability has been questioned before.

    These four modules were listed in an audit as having no validation
    coverage. They do. Naming them here means the next person gets the answer
    from a test rather than from another read of the registry, and a rename
    that breaks one says which module lost its validation.
    """
    assert rule_registry.has_rules(rule_set), (
        f"rule set {rule_set!r} resolves to no rules, so every validation "
        "request for it reports a clean pass without running anything"
    )


def test_resolve_reports_an_unknown_set_as_unsupported() -> None:
    """The engine must not silently treat an unknown set as having passed.

    This is the guard that makes the tests above meaningful: they rely on
    ``has_rules`` telling the truth about an empty set.
    """
    supported, unsupported = rule_registry.resolve_rule_sets(["boq_quality", "a_rule_set_nobody_registered"])
    assert supported == ["boq_quality"]
    assert unsupported == ["a_rule_set_nobody_registered"]


def test_the_reader_sees_both_call_shapes() -> None:
    """A registration passed by keyword counts as a registration.

    This exists because the check once read only the second positional
    argument and therefore reported a module that registers two rules as
    registering none. The failure looked exactly like a real dormant rule set,
    which is the worst kind of false alarm: it accuses the code of the very
    thing the test was written to catch, and the obvious repair is to delete
    working rules.

    Asserting on the live tree would not hold this down, because the tree can
    stop using the keyword form without anybody noticing. So both shapes are
    written out here and the reader has to agree about them.
    """
    source = (
        'SET_A = "positional_set"\n'
        'SET_B = "keyword_set"\n'
        "rule_registry.register(RuleOne(), [SET_A])\n"
        "rule_registry.register(RuleTwo(), rule_sets=[SET_B])\n"
        'rule_registry.register(RuleThree(), rule_sets=["literal_set"])\n'
    )
    seen = _statically_registered({Path("synthetic.py"): ast.parse(source)})
    assert seen == {"positional_set", "keyword_set", "literal_set"}


def test_the_reader_still_refuses_to_guess() -> None:
    """A set name the reader cannot resolve must not be counted as registered.

    The lower bound is deliberate. Widening the reader to the keyword form
    must not turn it into something that assumes a registration it cannot
    actually see, because every name it wrongly counts is a dormant rule set
    it would let through.
    """
    source = (
        "rule_registry.register(RuleOne(), rule_sets=some_variable)\n"
        "rule_registry.register(RuleTwo(), rule_sets=[computed()])\n"
        "rule_registry.register(RuleThree(), rule_sets=[UNDECLARED_NAME])\n"
        'other_registry.register(RuleFour(), rule_sets=["not_ours"])\n'
    )
    assert _statically_registered({Path("synthetic.py"): ast.parse(source)}) == set()


# ── Demo templates ────────────────────────────────────────────────────────
#
# The tests above take their population from ``app/modules``: a rule set
# counts as declared when some module assigns it to a ``*_RULE_SET`` constant.
# That population is green and it excludes the place this defect actually
# shipped from. A demo template declares its rule sets as a plain list literal
# in ``app/core``, never touches the constant convention, and is what the
# product reads when it seeds a project: ``demo_projects.py`` writes
# ``template.validation_rule_sets`` onto the project row and seeds the first
# validation report from the same list. So the name a demo carries is the name
# a user's dashboard runs, and nothing checked it.
#
# It was wrong. Both Hungarian demos asked for ``tetelrend``, which is the
# classification standard, not a rule set; the Hungarian rules register under
# ``hungary``. The engine logs an unimplemented rule set and continues, so two
# country demos ran the generic quality rules and none of their country's own,
# including the material and fee split that is the one thing every Hungarian
# bill is quoted in. Nothing was red anywhere.
#
# The reader below takes both syntactic forms on purpose. Eight of the forty
# nine declaration sites write the dict form, ``"validation_rule_sets": [...]``,
# rather than the keyword form, and a reader shaped like one of them is blind
# to the other. That is the same mistake this file already records against
# itself higher up, and repeating it here would have hidden the seed scripts.

CORE_DIR = Path(__file__).resolve().parents[2] / "app" / "core"
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "app" / "scripts"

#: Rule sets a demo asks for that the engine does not register.
#:
#: ``project_completeness`` is declared by twenty two demo templates and no rule
#: registers into it. Requesting it prints "Validation requested unimplemented
#: rule set(s): project_completeness (no rules registered)" and the run
#: continues, so twenty two dashboards promise a completeness check and show
#: nothing. Whether that set gets written or the declarations get
#: dropped is a product decision and not this test's to make, so it is named
#: here rather than hidden by a wildcard: a new pack cannot quietly join it,
#: and ``test_the_allowlist_still_describes_the_tree`` fails the day it is
#: implemented, which is the day this entry has to go.
_UNREGISTERED_DEMO_RULE_SETS = {"project_completeness"}


def _demo_sources() -> list[Path]:
    """Every file that spells out a demo's rule sets.

    The pack templates, the built-in templates that live in
    ``demo_projects.py``, and the seed scripts, which carry their own copies.
    """
    return (
        sorted(CORE_DIR.glob("demo_packs/*.py"))
        + [CORE_DIR / "demo_projects.py"]
        + sorted(SCRIPTS_DIR.glob("seed_*.py"))
    )


def _rule_set_lists(tree: ast.Module) -> list[ast.expr]:
    """Every ``validation_rule_sets`` value in a file, both forms.

    Keyword: ``DemoTemplate(..., validation_rule_sets=["nrm"], ...)``.
    Dict: ``{"validation_rule_sets": ["nrm"]}``, which the seed scripts use.
    """
    out: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "validation_rule_sets":
            out.append(node.value)
        elif isinstance(node, ast.Dict):
            # strict: ast keeps the two lists in step, and a dict written with **
            # unpacking puts None in keys, which the isinstance guard drops.
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "validation_rule_sets":
                    out.append(value)
    return out


def _demo_declared_rule_sets() -> dict[str, list[str]]:
    """Rule set name mapped to the demo files declaring it.

    Only list and tuple literals of plain strings are read. A value built at
    runtime (``template.validation_rule_sets``, ``l10n["validation_rule_sets"]``)
    is skipped rather than guessed at, which keeps this a lower bound on the
    declarations and never an overstatement of coverage.
    """
    found: dict[str, set[str]] = {}
    for path in _demo_sources():
        for value in _rule_set_lists(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(value, (ast.List, ast.Tuple)):
                continue
            for element in value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    found.setdefault(element.value, set()).add(path.name)
    return {name: sorted(files) for name, files in sorted(found.items())}


def test_the_demo_sweep_reaches_the_demos() -> None:
    """The population is asserted next to the verdict, not assumed.

    A glob that stops matching, or a reader that loses one of the two forms,
    would turn the check below into a pass over nothing. All three are floors:
    a new demo must not fail an unrelated test.
    """
    sources = _demo_sources()
    assert len(sources) >= 40, f"only {len(sources)} demo sources found under {CORE_DIR} and {SCRIPTS_DIR}"

    declared = _demo_declared_rule_sets()
    assert len(declared) >= 10, f"only {len(declared)} rule sets discovered across the demos: {sorted(declared)}"

    # boq_quality is the one set nearly every demo carries, so it stands in for
    # "the reader is actually reading". A count near one means a broken reader.
    assert len(declared.get("boq_quality", [])) >= 25, (
        "the reader found boq_quality in only "
        f"{len(declared.get('boq_quality', []))} demo files, which is too few to be the truth"
    )


def test_the_reader_sees_both_declaration_forms() -> None:
    """A rule set declared in the dict form counts as declared.

    Written against a synthetic source rather than the live tree, because the
    tree can stop using one form without anybody noticing and the point is
    that the reader handles both. Eight real declaration sites use the dict
    form, and a keyword-only reader would drop every one of them.
    """
    source = (
        'DemoTemplate(demo_id="a", validation_rule_sets=["kw_set"])\n'
        'TEMPLATE = {"demo_id": "b", "validation_rule_sets": ["dict_set"]}\n'
        'OTHER = {"demo_id": "c", "validation_rule_sets": some_variable}\n'
        'DemoTemplate(demo_id="d", validation_rule_sets=template.validation_rule_sets)\n'
    )
    values = _rule_set_lists(ast.parse(source))
    names = {
        element.value
        for value in values
        if isinstance(value, (ast.List, ast.Tuple))
        for element in value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }
    assert names == {"kw_set", "dict_set"}, f"the reader saw {names}"


def test_every_demo_rule_set_has_rules() -> None:
    """A demo may not ask for a rule set the engine does not have.

    This is the check that would have caught ``tetelrend``. A demo that names
    a set with no rules seeds a report that ran fewer checks than it claims,
    and the only trace is one log line at seed time that nobody reads.
    """
    declared = _demo_declared_rule_sets()
    dormant = {
        name: files
        for name, files in declared.items()
        if not rule_registry.has_rules(name) and name not in _UNREGISTERED_DEMO_RULE_SETS
    }
    assert not dormant, (
        "these rule sets are named by a demo template and resolve to no rules, "
        "so the seeded dashboard silently runs fewer checks than it lists: "
        + "; ".join(f"{name} (in {', '.join(files)})" for name, files in dormant.items())
    )


def test_the_allowlist_still_describes_the_tree() -> None:
    """An allowlist that outlives its reason is a label nobody rechecks.

    Both directions matter. An entry that is now registered has to leave, or
    the next reader believes a check is missing when it is running. An entry
    no demo declares any more has to leave too, or the list grows into a place
    where names go to be forgotten.
    """
    declared = _demo_declared_rule_sets()
    now_registered = {name for name in _UNREGISTERED_DEMO_RULE_SETS if rule_registry.has_rules(name)}
    assert not now_registered, (
        f"{sorted(now_registered)} now resolves to real rules. Remove it from "
        "_UNREGISTERED_DEMO_RULE_SETS so the gate starts guarding it."
    )
    unused = {name for name in _UNREGISTERED_DEMO_RULE_SETS if name not in declared}
    assert not unused, f"{sorted(unused)} is on the allowlist and no demo declares it any more. Remove it."


def test_the_hungarian_demos_ask_for_the_rule_set_that_exists() -> None:
    """Pin the specific case, so a revert says what broke rather than which name changed.

    ``tetelrend`` is the classification standard these two templates correctly
    set on ``classification_standard``; it is not a rule set. The generic test
    above catches a reintroduction, but only this one names the country whose
    rules would go dark, which is the sentence the next reader needs.
    """
    declared = _demo_declared_rule_sets()
    hungarian_demos = {"office-debrecen.py", "residential-budapest.py"}

    assert hungarian_demos <= set(declared.get("hungary", [])), (
        "the Hungarian demos no longer ask for the hungary rule set, so the "
        "item order, the seventeen chapters and the material and fee split "
        f"run on nothing. hungary is declared by: {declared.get('hungary', [])}"
    )
    assert not (hungarian_demos & set(declared.get("tetelrend", []))), (
        "a Hungarian demo names tetelrend as a rule set again. That is the "
        "classification standard; the rules register under hungary."
    )


# ── The registry a dashboard actually runs against ─────────────────────────
#
# Everything above asks a registry that only ``register_builtin_rules`` has
# filled. That is not the registry the product runs. The module loader imports
# every module's ``validators.py`` at boot, and those imports register rules of
# their own, some of them into sets they do not own. So the allowlist above can
# be green while the shipped software disagrees with it, and the population is
# the reason: the check never loaded the half of the tree where the
# disagreement lives.
#
# It was not hypothetical. The carbon module registered its 6D coverage rule
# into ``project_completeness`` as a second set alongside ``carbon_6d``. At
# runtime that made the set resolve to a rule, so ``resolve_rule_sets`` put it
# in the supported bucket, the report stopped listing it as unimplemented, and
# the twenty two demo dashboards that ask for it showed completeness as a check
# that ran and found nothing. The rule itself returns no results unless the
# data carries BIM element counts, which a BOQ demo never does, so there was
# nothing on screen to contradict the clean bill either.
#
# Both module routes are walked, and the difference between them is not small:
# importing the validator modules alone reaches 36 rule sets, running the
# startup hooks as well reaches 62. A sweep that stopped at the imports would
# have been a corrected population that is still half the registry, and the
# module that registers from its hook is the one it would miss.
#
# The sweep runs in a subprocess on purpose. Importing forty two validator
# modules and awaiting a hundred and sixty two startup hooks mutates the
# process-global registry for every test that follows, and a registry that
# grows on import answers differently depending on the order tests run in.

_SWEEP_SOURCE = """
import asyncio
import importlib
import json
import pathlib
import sys

import app
from app.core.validation.engine import rule_registry
from app.core.validation.rules import register_builtin_rules

register_builtin_rules()
modules_dir = pathlib.Path(app.__file__).resolve().parent / "modules"

paths = sorted(modules_dir.glob("*/validators.py"))
failures = {}
imported = 0
for path in paths:
    name = "app.modules." + path.parent.name + ".validators"
    try:
        importlib.import_module(name)
        imported += 1
    except Exception as exc:
        failures[name] = type(exc).__name__ + ": " + str(exc)

hooks_found = 0
hooks_run = 0
for package in sorted(p.parent.name for p in modules_dir.glob("*/__init__.py")):
    try:
        module = importlib.import_module("app.modules." + package)
    except Exception as exc:
        failures[package] = "import " + type(exc).__name__ + ": " + str(exc)
        continue
    hook = getattr(module, "on_startup", None)
    if hook is None:
        continue
    hooks_found += 1
    try:
        result = hook()
        if asyncio.iscoroutine(result):
            asyncio.run(result)
        hooks_run += 1
    except Exception as exc:
        failures[package + ".on_startup"] = type(exc).__name__ + ": " + str(exc)

print(
    json.dumps(
        {
            "app_file": app.__file__,
            "on_disk": len(paths),
            "imported": imported,
            "hooks_found": hooks_found,
            "hooks_run": hooks_run,
            "failures": failures,
            "sets": sorted(rule_registry.list_rule_sets()),
            "members": {
                wanted: [rule.rule_id for rule in rule_registry.get_rules_for_sets([wanted])]
                for wanted in sys.argv[1:]
            },
        }
    )
)
"""


@pytest.fixture(scope="module")
def boot_registry() -> dict:
    """Registry contents after the built-in rules and both module routes.

    Answers in a fresh interpreter, and reports what it managed to load so the
    caller can refuse a verdict taken over a collapsed population.
    """
    env = dict(os.environ)
    backend_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = os.pathsep.join([backend_root, env["PYTHONPATH"]]) if env.get("PYTHONPATH") else backend_root
    # Settings refuse to construct without a PostgreSQL URL and nine validator
    # modules import them, so one is needed. It points at a port nothing
    # listens on, deliberately: the startup hooks below are the real product's
    # and some of them reach for a database, which this sweep has no business
    # writing to. They log the refusal and carry on, which is all the sweep
    # needs, and the lane's own database is left alone.
    env["DATABASE_URL"] = "postgresql+asyncpg://gate:gate@127.0.0.1:1/oe_rule_set_sweep"

    proc = subprocess.run(
        [sys.executable, "-c", _SWEEP_SOURCE, *sorted(_UNREGISTERED_DEMO_RULE_SETS)],
        capture_output=True,
        text=True,
        env=env,
        cwd=backend_root,
        check=False,
        timeout=600,
    )
    assert proc.returncode == 0, f"the sweep subprocess failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_sweep_loaded_the_tree_and_both_registration_routes(boot_registry: dict) -> None:
    """The population is asserted next to the verdict below, not assumed.

    Three ways this sweep can lie and all of them are silent. It can import
    ``app`` from an installed copy rather than from the tree, it can lose a
    validator module to an unrelated import error, and it can lose a startup
    hook the same way. Each one takes some module's registrations out of the
    check without taking anything red with it.
    """
    print(f"\nPOPULATION: app imported from {boot_registry['app_file']}")
    assert str(Path(__file__).resolve().parents[2]) in boot_registry["app_file"], (
        "the sweep imported app from outside this tree, so it measured some "
        f"other copy of the software: {boot_registry['app_file']}"
    )

    on_disk, imported = boot_registry["on_disk"], boot_registry["imported"]
    hooks_found, hooks_run = boot_registry["hooks_found"], boot_registry["hooks_run"]
    print(
        f"POPULATION: {imported} of {on_disk} module validators imported, "
        f"{hooks_run} of {hooks_found} on_startup hooks run, "
        f"{len(boot_registry['sets'])} rule sets in the registry"
    )
    assert on_disk >= 40, f"only {on_disk} validator modules found, so this sweep checks almost nothing"
    assert hooks_found >= 100, f"only {hooks_found} startup hooks found, so half the registrations are missing"
    assert imported == on_disk and hooks_run == hooks_found, (
        f"{on_disk - imported} validator modules and {hooks_found - hooks_run} startup hooks did not "
        f"run, so their registrations are missing from the verdict below: {boot_registry['failures']}"
    )


def test_the_allowlist_still_describes_the_running_software(boot_registry: dict) -> None:
    """The allowlist above, re-asked of the registry the product boots with.

    Same assertion as ``test_the_allowlist_still_describes_the_tree``, over the
    population that test cannot see. A module that tags a demo-declared set as
    a second home for one of its own rules turns "not implemented" into "ran
    and found nothing" on every dashboard that asks for the set, and until this
    ran there was nowhere that could go red.
    """
    print(f"\nPOPULATION: {len(boot_registry['sets'])} rule sets registered, {len(boot_registry['members'])} asked")
    members = {name: rules for name, rules in boot_registry["members"].items() if rules}
    assert not members, (
        "these rule sets are on _UNREGISTERED_DEMO_RULE_SETS, and with the module "
        "validators loaded they resolve to rules, so the engine reports them as "
        "supported and every dashboard that asks for one shows a check that ran "
        "and found nothing: "
        + "; ".join(f"{name} <- {', '.join(rules)}" for name, rules in sorted(members.items()))
        + ". Either the set is implemented, in which case it leaves the allowlist, "
        "or the rule belongs to its own set and should not be registered into this one."
    )
