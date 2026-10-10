# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Guard the seam between what a partner pack declares and what the engine has.

``validation_rule_packs`` carries two kinds of name at once: identifiers of
built-in rule sets, which switch those rules on, and ids of the JSON documents
the pack ships under ``rule_packs/``, which the engine never executes. Both are
intended. The failure mode is a third thing that looks like the second: a pack
naming a standard the engine DOES implement, spelled with separators the
registry does not use, so the rules sit there unused while the installer
reports only "no built-in engine match".

The test that existed before this one asserted ``rule_registry.has_rules()``
for a handful of set names. That is a fact about the registry and it was true
the whole time; no manifest was ever read, so it could not have caught any of
this. This file reads the manifests.

What this file no longer does is allow-list. It used to hold the fifteen
pairings that were wrong on the day it was written and assert that the scan
found exactly those, which grandfathered all fifteen and could only have caught
a sixteenth. The requirement that a pack actually declare the engine identifier
now lives in ``test_partner_pack_rule_sets.py``, against the
``validation_rule_sets`` field that switches rules on. What stays here is the
detector, the probes, and the controls that stop either from going quiet.

Everything here measures in a subprocess, and that is not incidental. The
registry is not a constant: ``register_builtin_rules`` puts 29 sets in it, and
each module that owns validators adds its own on import, so the answer depends
on what the process happens to have loaded. Run in a pytest session that has
already built an app, this file saw ``boq_quality`` holding 23 rules; run
alone, 19. A guard whose subject changes with test ordering is worse than no
guard, so each helper starts a clean interpreter and loads a stated set.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.partner_pack.apply import _known_rule_sets, _near_miss_rule_set, _squash
from tests._pack_manifest_source import declared_lists

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "backend"
PACKS_DIR = REPO_ROOT / "packs"
README = REPO_ROOT / "docs" / "partner-packs" / "README.md"

_CORE_ONLY = """
import json, warnings
warnings.filterwarnings("ignore")
from app.core.validation.rules import register_builtin_rules
from app.core.validation.engine import rule_registry
register_builtin_rules()
print(json.dumps(sorted(rule_registry.list_rule_sets())))
"""

_CORE_AND_MODULES = """
import importlib, json, pathlib, warnings
warnings.filterwarnings("ignore")
from app.core.validation.rules import register_builtin_rules
from app.core.validation.engine import rule_registry
register_builtin_rules()
for p in sorted(pathlib.Path("app/modules").glob("*/validators.py")):
    try:
        importlib.import_module("app.modules." + p.parent.name + ".validators")
    except Exception:
        pass
print(json.dumps(sorted(rule_registry.list_rule_sets())))
"""

# The module-owned sets a shipped pack now names. They are listed because the
# probe below swallows a failed ``validators`` import, so the size of its answer
# depends on the environment: ten of those imports fail when ``DATABASE_URL`` is
# unset. A set that is missing from the probe is reported as unregistered, and
# every membership check that consults the probe then reads green for the wrong
# reason. Naming them turns that into a failure.
MODULE_OWNED_SETS_PACKS_RELY_ON = {"formwork"}


def _rule_sets(script: str) -> set[str]:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", script],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"the registry probe would not run: {result.stderr[-2000:]}"
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


@pytest.fixture(scope="module")
def core_rule_sets() -> set[str]:
    """What ``register_builtin_rules`` alone puts in the registry."""
    return _rule_sets(_CORE_ONLY)


@pytest.fixture(scope="module")
def shipped_rule_sets() -> set[str]:
    """The core sets plus every set a shipped module's validators register."""
    return _rule_sets(_CORE_AND_MODULES)


def declared_rule_packs() -> dict[str, list[str]]:
    """Pack slug -> the rule pack names its manifest declares.

    Read from the source by the reader ``test_partner_pack_rule_sets.py`` uses,
    which follows a derived pack to the parent it names instead of reporting
    it as declaring nothing. A pack that declares none is left out, as before.
    """
    return {slug: names for slug, names in declared_lists(PACKS_DIR, "validation_rule_packs").items() if names}


def test_the_detector_answers_without_any_manifest_in_front_of_it(shipped_rule_sets: set[str]) -> None:
    """The control. Once the pairings below are fixed the manifest scan goes
    quiet, and a quiet scan proves nothing about whether the detector still
    works, so assert the detector directly on inputs of its own."""
    known = shipped_rule_sets
    assert _near_miss_rule_set("din_276", known) == "din276"
    assert _near_miss_rule_set("masterformat_2020", known) == "masterformat"
    assert _near_miss_rule_set("sinapi_cost_db", known) == "sinapi"
    # The three shortest set names have to work too. An earlier version of this
    # helper required four characters before it would treat a name as a prefix,
    # which quietly excused every nrm_* and bc3_* slug in the tree. That miss
    # was only visible because a control like this one was run against it, and
    # fixing it turned seven pairings into fifteen.
    assert _near_miss_rule_set("nrm_1_cost_planning", known) == "nrm"
    assert _near_miss_rule_set("bc3_fiebdc", known) == "bc3"
    assert _near_miss_rule_set("pipeline_safety_2020", known) == "pipeline"
    # A name the engine has nothing for stays unmatched, or every unimplemented
    # standard would be reported as a near miss of something.
    assert _near_miss_rule_set("vob_2019", known) is None
    assert _near_miss_rule_set("iso_19650_cde", known) is None
    assert _near_miss_rule_set("aramco_standards", known) is None
    # The prefix has to end at a boundary. Both of these begin with the letters
    # of a real set name and mean something else entirely.
    assert _squash("nbr") in {_squash(k) for k in known}
    assert _near_miss_rule_set("nbrigade_scheduling", known) is None
    assert _near_miss_rule_set("gaebler_index", known) is None


def test_the_probes_measured_a_registry_that_is_actually_loaded(
    core_rule_sets: set[str],
    shipped_rule_sets: set[str],
) -> None:
    """The control on both fixtures, and the second hole this file used to have.

    ``_CORE_AND_MODULES`` wraps each module import in ``except Exception:
    pass``. Ten of those imports raise when ``DATABASE_URL`` is unset, so the
    "shipped" answer shrinks silently with the environment. When ``formwork``
    is missing from it, ``formwork_cycle_quality`` stops looking like a near
    miss at all and a guard that scans for near misses goes quiet - green,
    measuring nothing. Assert the subject before asserting anything about it.
    """
    assert core_rule_sets, "the core probe came back empty"
    assert shipped_rule_sets, "the shipped probe came back empty"
    assert shipped_rule_sets > core_rule_sets, (
        "loading the module validators added no rule set at all, so the shipped probe is "
        f"measuring the core and nothing else: {sorted(shipped_rule_sets)}"
    )
    missing = MODULE_OWNED_SETS_PACKS_RELY_ON - shipped_rule_sets
    assert not missing, (
        f"the shipped probe did not see {sorted(missing)}, which a shipped pack declares. "
        "Something the probe imports is failing quietly; fix that before trusting any "
        "membership answer this file gives."
    )


def test_the_near_miss_scan_over_the_shipped_manifests_still_has_a_subject(
    shipped_rule_sets: set[str],
) -> None:
    """The pairings this file used to allow-list are the ones that must stay
    findable.

    Whether each pack has since declared the engine identifier that runs them
    is asserted in ``test_partner_pack_rule_sets.py``; the requirement lives
    there because it is a statement about ``validation_rule_sets``, which is
    the field that switches rules on. What belongs here is the detector's
    reach over the real manifests: if that scan ever comes back empty it is the
    scan that broke, not the tree that healed, because the document ids cannot
    be renamed - each one has to keep matching its JSON file stem.

    Deliberately no assertion on how many it finds. The allow-list this file
    used to carry failed exactly that way: it pinned an exact set, so a new
    pack that ships a standard-named document *and* declares the engine
    identifier correctly would still red the test, and the fix would be to bump
    a number. Non-empty is the part that has safety value.
    """
    found: dict[tuple[str, str], str] = {}
    for pack, declared in declared_rule_packs().items():
        for name in declared:
            if name in shipped_rule_sets:
                continue
            neighbour = _near_miss_rule_set(name, shipped_rule_sets)
            if neighbour:
                found[(pack, name)] = neighbour

    assert found, "the near-miss scan found nothing across every shipped manifest, which it cannot have"


def test_the_installer_reads_the_registry_and_not_the_standard_attribute(shipped_rule_sets: set[str]) -> None:
    """``_known_rule_sets`` must ask the registry. Scraping ``standard = "..."``
    out of the rules module was the obvious alternative and it is wrong by five
    names in both directions, which is how a doc came to teach identifiers that
    were never rule sets."""
    scraped = set(
        re.findall(
            r'standard\s*=\s*"([a-z0-9_]+)"',
            (BACKEND / "app/core/validation/rules/__init__.py").read_text(encoding="utf-8"),
        )
    )
    assert scraped - shipped_rule_sets, "the two lists agree today, so this test no longer discriminates"
    in_process = _known_rule_sets()
    assert in_process, "the registry came back empty, so nothing here measured what it claims to"
    assert in_process >= shipped_rule_sets or shipped_rule_sets >= in_process, (
        "the registry the installer sees is neither a subset nor a superset of the shipped sets, "
        "which means something registers under a name no shipped module owns"
    )


def _readme_slug_table() -> set[str]:
    text = README.read_text(encoding="utf-8")
    start = text.find("The rule sets the core registers on its own are these.")
    assert start != -1, "the README section that lists the rule sets has been renamed or removed"
    end = text.find("Modules add more.", start)
    assert end != -1, "the end of the rule set table is no longer where this test looks for it"
    return set(re.findall(r"^\|\s*`([a-z0-9_]+)`", text[start:end], re.M))


def test_the_readme_lists_the_rule_sets_the_core_actually_registers(core_rule_sets: set[str]) -> None:
    """The section this checks used to name 36 identifiers of which 3 existed,
    and it introduced itself as the list the core ships. Every wrong slug in the
    shipped manifests can be traced back to it."""
    listed = _readme_slug_table()
    assert listed, "no slugs were read out of the README table at all"
    assert listed == core_rule_sets, (
        "the README's rule set table and the core registry disagree. Missing from the README: "
        f"{sorted(core_rule_sets - listed)}. Named by the README but never registered: "
        f"{sorted(listed - core_rule_sets)}."
    )


def test_the_readme_table_does_not_publish_rule_counts(core_rule_sets: set[str]) -> None:
    """A count is not a stable property of a rule set. ``boq_quality`` holds 19
    rules in a bare interpreter, 24 once the module validators are loaded and 23
    in one particular pytest session, because modules register into existing
    sets as well as their own. Publishing any one of those numbers documents the
    reader's process rather than the software."""
    text = README.read_text(encoding="utf-8")
    start = text.find("The rule sets the core registers on its own are these.")
    end = text.find("Modules add more.", start)
    rows = re.findall(r"^\|\s*`[a-z0-9_]+`\s*\|([^|]*)\|", text[start:end], re.M)
    assert len(rows) >= len(core_rule_sets) - 1, "the table stopped covering the rule sets a row each"
    numeric = [r.strip() for r in rows if re.fullmatch(r"\s*\d+\s*", r)]
    assert not numeric, f"the table has gone back to publishing rule counts: {numeric}"
