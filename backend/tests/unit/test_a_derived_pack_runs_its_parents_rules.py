# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""With the derived pack active, the parent's rules are found and they fire.

``turkey-tr-mep`` ships no ``rule_packs/`` directory and writes no rule set in
its source. Whether that costs a Turkish installation its rules depends on how
the two things are found, so this file measures both rather than reasoning
about them.

**Reference documents** (``rule_packs/*.json``) are found by pack directory,
over every discovered pack, and not by the active pack:
``app/core/validation/pack_coverage.py`` walks ``discover_packs()`` and reads
each pack's own directory. The country pack is always discovered next to the
derived one, because the derived one cannot load without it, so the five
Turkish documents are listed under ``turkey-tr`` whichever pack is active. A
derived pack does not have to expose them and must not repeat their names: the
names are file names, and it carries no such files.

**Rules** run from the engine registry by rule-set name. The name reaches a
project through the active pack's ``validation_rule_sets``, which the derived
manifest inherits as an object field.

A past defect in this area was a name that resolved nowhere while the engine
logged and carried on, with nothing red anywhere. So the measurement is not
"nothing raised". A bill built to break the Turkish rules is validated with
the rule sets a project inherits under each pack, and it has to come back with
findings from named ``birimfiyat`` rules, identical under both packs. A control
bill validated with no pack shows the findings come from the pack's rule set
and not from the baseline.

Measured in a clean interpreter: the registry is filled by imports, so an
in-process reading describes the pytest session and not the software.
"""

from __future__ import annotations

import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "backend"

COUNTRY_PACK = "turkey-tr"
DERIVED_PACK = "turkey-tr-mep"

#: Rules the bill below is built to break. Each id is one the country pack's
#: unit-price document lists under ``enables_rule_ids``.
EXPECTED_FINDINGS = frozenset({"birimfiyat.code_required", "birimfiyat.valid_poz", "birimfiyat.chapter_recognised"})

_PROBE = """
import asyncio, json, os, sys, tempfile, warnings
from pathlib import Path
warnings.filterwarnings("ignore")

# An applied pack recorded in this machine's own data directory outranks the
# environment variable, so point the state at an empty directory first.
os.environ["OE_CLI_DATA_DIR"] = tempfile.mkdtemp(prefix="oe-derived-pack-probe-")
os.environ.pop("OE_PARTNER_PACK", None)

from app.core.partner_pack import discovery
from app.core.partner_pack.apply import inherited_rule_sets, resolve_declared_rule_sets
from app.core.validation import pack_coverage
from app.core.validation.engine import rule_registry, validation_engine
from app.core.validation.rules import register_builtin_rules

register_builtin_rules()


def line(index, poz):
    return {
        "id": f"p-{index}",
        "parent_id": None,
        "ordinal": f"01.{index:02d}",
        "description": f"Line {index}",
        "unit": "m",
        "quantity": 10.0,
        "unit_rate": 50.0,
        "total": 500.0,
        "classification": {"birimfiyat": poz} if poz else {},
        "type": "position",
    }


# One line with no poz number, one that is not a poz number at all, one in a
# chapter no publisher uses, and one that is in order.
BILL = {"positions": [line(1, ""), line(2, "not a poz number"), line(3, "27.300.1406"), line(4, "25.305.1104")]}


async def findings(rule_sets):
    runnable = [name for name in rule_sets if rule_registry.has_rules(name)]
    report = await validation_engine.validate(
        data=BILL, rule_sets=runnable, target_type="boq", metadata={"locale": "en"}
    )
    failed = sorted(
        (result.rule_id, str(result.element_ref or ""))
        for result in report.results
        if not result.passed and result.rule_id.startswith("birimfiyat.")
    )
    return {
        "requested": list(rule_sets),
        "runnable": runnable,
        "unsupported": sorted(report.unsupported_rule_sets),
        "birimfiyat_rules_run": sorted({r.rule_id for r in report.results if r.rule_id.startswith("birimfiyat.")}),
        "birimfiyat_failed": failed,
    }


def documents():
    pack_coverage.reset_cache()
    return sorted(
        (c.source_pack, Path(c.file).name, list(c.implemented), list(c.declared_only))
        for c in pack_coverage.resolve_pack_coverage().packs
        if c.source_pack in sys.argv[1:]
    )


out = {"registered_sets": sorted(rule_registry.list_rule_sets()), "packs": {}}
out["no_pack"] = asyncio.run(findings(inherited_rule_sets(None, None)))
for slug in sys.argv[1:]:
    os.environ["OE_PACK"] = slug
    discovery.reset_cache()
    active = discovery.get_active_pack()
    out["packs"][slug] = {
        "active": active.slug if active else None,
        "declared_rule_sets": list(active.validation_rule_sets),
        "strictly_resolved_rule_sets": resolve_declared_rule_sets(active, strict=True),
        "documents": documents(),
        "validation": asyncio.run(findings(inherited_rule_sets(None, active))),
    }
print(json.dumps(out))
"""


@lru_cache(maxsize=1)
def _measured() -> dict:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _PROBE, COUNTRY_PACK, DERIVED_PACK],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, f"the probe would not run: {result.stderr[-3000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_probe_measured_a_loaded_registry_and_two_active_packs() -> None:
    measured = _measured()
    assert "birimfiyat" in measured["registered_sets"], (
        "the engine registers no birimfiyat rule set in a clean interpreter, so nothing below measures the packs"
    )
    for slug in (COUNTRY_PACK, DERIVED_PACK):
        assert measured["packs"][slug]["active"] == slug, (
            f"the probe asked for {slug} to be the active pack and got {measured['packs'][slug]['active']}"
        )


@pytest.mark.parametrize("slug", [COUNTRY_PACK, DERIVED_PACK])
def test_the_rule_set_is_declared_and_resolves_under_each_pack(slug: str) -> None:
    pack = _measured()["packs"][slug]
    assert pack["declared_rule_sets"] == ["birimfiyat"]
    # Strict is how apply and its preview resolve the names: a name the
    # registry does not know raises there rather than being dropped.
    assert pack["strictly_resolved_rule_sets"] == ["birimfiyat"]
    assert pack["validation"]["requested"] == ["boq_quality", "birimfiyat"]
    assert pack["validation"]["runnable"] == ["boq_quality", "birimfiyat"]
    assert pack["validation"]["unsupported"] == []


@pytest.mark.parametrize("slug", [COUNTRY_PACK, DERIVED_PACK])
def test_the_turkish_rules_fire_on_a_bill_built_to_break_them(slug: str) -> None:
    validation = _measured()["packs"][slug]["validation"]
    failed_rules = {rule_id for rule_id, _line in validation["birimfiyat_failed"]}
    assert failed_rules >= EXPECTED_FINDINGS, (
        f"with {slug} active the bill was built to break {sorted(EXPECTED_FINDINGS)} and only "
        f"{sorted(failed_rules)} reported. Rules run: {validation['birimfiyat_rules_run']}"
    )


def test_the_findings_come_from_the_pack_and_not_from_the_baseline() -> None:
    control = _measured()["no_pack"]
    assert control["requested"] == ["boq_quality"]
    assert control["birimfiyat_rules_run"] == [], (
        f"the same bill validated with no pack already ran {control['birimfiyat_rules_run']}, so the "
        f"findings above do not show that a pack switched anything on"
    )


def test_the_derived_pack_validates_exactly_as_the_country_pack_does() -> None:
    packs = _measured()["packs"]
    assert packs[DERIVED_PACK]["validation"] == packs[COUNTRY_PACK]["validation"]
    assert packs[DERIVED_PACK]["validation"]["birimfiyat_failed"], "two empty lists agree with each other"


def test_the_turkish_documents_are_found_whichever_pack_is_active() -> None:
    """Found under the country pack both times, with rule ids that resolve."""
    packs = _measured()["packs"]
    under_country, under_derived = packs[COUNTRY_PACK]["documents"], packs[DERIVED_PACK]["documents"]
    assert under_derived == under_country

    names = sorted(name for _source, name, _implemented, _declared_only in under_country)
    assert len(names) == 5, f"expected the five Turkish reference documents, found {names}"
    assert {source for source, *_rest in under_country} == {COUNTRY_PACK}, (
        "a document was listed under the derived pack, which carries none; the coverage report would count it twice"
    )
    implemented = {
        name: ids for _source, name, ids, _declared_only in under_country if name == "bayindirlik_unit_prices.json"
    }
    assert set(implemented.get("bayindirlik_unit_prices.json", [])) >= EXPECTED_FINDINGS, (
        f"the unit-price document's rule ids do not resolve to registered rules: {implemented}"
    )
