# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A country pack names the rule sets its country runs, and the engine resolves each name.

Ten packs shipped with ``validation_rule_packs`` filled and no
``validation_rule_sets`` at all: aus, nzs, saudi-vision2030, turkey-tr,
batimatech-ca, austria-at, switzerland-ch, south-africa, us-california and
us-texas. The first list is reference documents the engine never executes, so
those packs switched on nothing of their own. Their countries were not left
unchecked, because the BOQ router's country row adds the national sets to any
project filed under the country, but the pack's own preview said it switched
on no rule set, and a project whose region names no country got nothing.
All ten now name their sets. South Africa was briefly left empty, because its
nrm would have reached its MasterFormat-coded Johannesburg demo unfiltered;
the record of what a pack added closed that, see
:func:`test_the_record_is_what_keeps_a_pack_code_set_off_a_demo_coded_otherwise`.

A named set is copied onto every project created under the pack, and project
creation records which sets the pack added. The BOQ router drops such a set,
when it demands a code of another standard than the project names, exactly as
it drops the country row's; a set the creator asked for is kept. So the demos
each pack installs are validated here with exactly what a project created
under the pack would carry, record included, and must clear it.

``test_pack_conformance`` already holds one direction: every set a pack names
also runs without it. Nothing held the other one, so a pack could name
nothing and every check stayed green. This file holds it.

Two further things are measured here rather than assumed:

* that the engine actually resolves every declared name, read in a clean
  interpreter, because the registry is filled by imports and an in-process
  reading describes the pytest session rather than the software;
* that no producer of rule-set names writes a classification key in place of
  a rule set. ``tetelrend`` is the Hungarian classification and ``hungary`` its
  rule set; written the wrong way round the engine logs one line and carries
  on, and the bill validates against nothing national.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from app.core.partner_pack.manifest import PartnerPackManifest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "backend"
PACKS_DIR = REPO_ROOT / "packs"

#: The packs this repair was about, with the set each must run. Listed rather
#: than derived so one cannot quietly drop out while another is being fixed.
#: doker-formwork already declared ``formwork`` before the repair and is kept
#: here so the claim that it does stays checked.
EXPECTED: dict[str, list[str]] = {
    "aus": ["nrm"],
    "nzs": ["nrm"],
    "saudi-vision2030": ["masterformat"],
    "turkey-tr": ["birimfiyat"],
    "batimatech-ca": ["masterformat"],
    "doker-formwork": ["formwork"],
    "austria-at": ["gaeb", "onorm"],
    "switzerland-ch": ["gaeb"],
    "us-california": ["masterformat"],
    "us-texas": ["masterformat"],
    "south-africa": ["nrm"],
}

#: Country packs that deliberately name none of their country row's sets, with
#: the reason. Self-cancelling: see
#: :func:`test_a_pack_left_to_the_country_row_still_has_its_reason`. Empty since
#: South Africa names nrm again.
LEFT_TO_THE_COUNTRY_ROW: dict[str, str] = {}

_PROBE = """
import importlib, importlib.util, json, pathlib, sys, warnings
warnings.filterwarnings("ignore")
from app.core.validation.rules import register_builtin_rules
from app.core.validation.engine import rule_registry
register_builtin_rules()
for p in sorted(pathlib.Path("app/modules").glob("*/validators.py")):
    try:
        importlib.import_module("app.modules." + p.parent.name + ".validators")
    except Exception:
        pass
from app.core.partner_pack.apply import UnknownRuleSetError, resolve_declared_rule_sets
from app.core.partner_pack.manifest import PartnerPackManifest

packs = {}
for path in sorted(pathlib.Path("../packs").glob("*/src/*/manifest.py")):
    name = "_rule_set_probe_" + path.parts[-2]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    manifest = module.MANIFEST
    entry = {"declared": list(manifest.validation_rule_sets), "resolved": None, "error": None}
    try:
        entry["resolved"] = resolve_declared_rule_sets(manifest, strict=True)
    except UnknownRuleSetError as exc:
        entry["error"] = str(exc)
    packs[manifest.slug] = entry

refusals = {}
for name in ("tetelrend", "gb50500", "knr", "spurious_ruleset_for_this_test"):
    probe = PartnerPackManifest(
        slug="probe-pack",
        partner_name="Probe Partner",
        pack_version="1.0.0",
        description="A manifest built for a test.",
        validation_rule_sets=[name],
    )
    try:
        resolve_declared_rule_sets(probe, strict=True)
        refusals[name] = None
    except UnknownRuleSetError as exc:
        refusals[name] = str(exc)

print(json.dumps({"sets": sorted(rule_registry.list_rule_sets()), "packs": packs, "refusals": refusals}))
"""


@lru_cache(maxsize=1)
def _measured() -> dict[str, Any]:
    """What a clean interpreter registers and resolves, read once per session."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _PROBE],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"the clean-interpreter probe would not run: {result.stderr[-2000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


@lru_cache(maxsize=1)
def _manifests() -> dict[str, PartnerPackManifest]:
    """Every pack manifest, loaded from its own file. A broken one raises."""
    out: dict[str, PartnerPackManifest] = {}
    for path in sorted(PACKS_DIR.glob("*/src/*/manifest.py")):
        name = f"_rule_set_manifest_{path.parts[-2]}"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader, f"{path} cannot be loaded as a module"
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        out[module.MANIFEST.slug] = module.MANIFEST
    return out


def _country_slugs() -> list[str]:
    return sorted(slug for slug, m in _manifests().items() if m.market_country_code)


def _sets_the_country_row_requires(manifest: PartnerPackManifest) -> list[str]:
    """The national sets a project of the pack's country runs without the pack.

    Read off the same table and the same filter ``_build_rule_sets`` applies: a
    country row's "code required" set for a standard other than the one the
    pack classifies against is dropped there, because it would fail every
    correctly coded line, so it is not required here either.
    """
    from app.core.classification_registry import standard_for_country
    from app.modules.boq.router import _CLASSIFICATION_CODE_SETS, _COUNTRY_RULE_SETS, _STANDARD_RULE_SETS

    country = manifest.market_country_code or ""
    standard = (manifest.metadata or {}).get("classification_standard") or standard_for_country(country)
    standard_rule = _STANDARD_RULE_SETS.get(str(standard or ""))
    return [
        name
        for name in _COUNTRY_RULE_SETS.get(country, [])
        if not (name in _CLASSIFICATION_CODE_SETS and standard_rule and name != standard_rule)
    ]


def _unnamed(manifest: PartnerPackManifest) -> list[str]:
    return [name for name in _sets_the_country_row_requires(manifest) if name not in manifest.validation_rule_sets]


# ── Controls ─────────────────────────────────────────────────────────────────


def test_the_probe_saw_the_registry_and_the_packs() -> None:
    """A probe that loaded nothing would make every assertion below vacuous."""
    measured = _measured()
    sets = set(measured["sets"])
    for name in ("boq_quality", "nrm", "masterformat", "birimfiyat", "formwork", "gaeb", "onorm", "hungary"):
        assert name in sets, f"the clean interpreter did not register {name!r}"
    assert len(measured["packs"]) >= 47, f"only {len(measured['packs'])} pack manifests were probed"
    assert set(measured["packs"]) == set(_manifests()), "the probe and this process found different packs"
    assert len(_country_slugs()) >= 40, "the country-pack population shrank below what this file was written for"


def test_the_reverse_check_reports_a_pack_that_names_nothing() -> None:
    """Negative control: the same aus manifest with its declaration removed must be caught."""
    stripped = _manifests()["aus"].model_copy(update={"validation_rule_sets": []})
    assert _unnamed(stripped) == ["nrm"], (
        "a country pack declaring nothing passed the reverse check, so a green run below would mean nothing"
    )


# ── The packs name what they run ─────────────────────────────────────────────


@pytest.mark.parametrize(("slug", "expected"), sorted(EXPECTED.items()))
def test_the_repaired_pack_names_its_rule_set_and_the_engine_resolves_it(slug: str, expected: list[str]) -> None:
    entry = _measured()["packs"].get(slug)
    assert entry is not None, f"{slug} was not found under packs/"
    assert entry["declared"] == expected, f"{slug} declares {entry['declared']}, expected {expected}"
    assert entry["error"] is None, f"{slug} is refused at apply time: {entry['error']}"
    assert entry["resolved"] == expected, (
        f"{slug} declares {expected} and the engine resolved {entry['resolved']}: a name was dropped"
    )


def test_every_pack_resolves_every_name_it_declares_in_a_clean_interpreter() -> None:
    """Strict resolution is what apply runs. A refusal or a dropped entry is a dead pack."""
    broken = {
        slug: entry["error"] or f"declared {entry['declared']}, resolved {entry['resolved']}"
        for slug, entry in _measured()["packs"].items()
        if entry["error"] is not None or entry["resolved"] != entry["declared"]
    }
    assert broken == {}, f"packs whose declared rule sets do not all resolve: {broken}"


@pytest.mark.parametrize("slug", _country_slugs())
def test_a_country_pack_names_the_national_sets_its_country_row_runs(slug: str) -> None:
    """The direction ``test_pack_conformance`` does not hold.

    A pack that names nothing reads in its own preview as a pack that switches
    nothing on, and a project created under it with a region that names no
    country inherits nothing national.
    """
    if slug in LEFT_TO_THE_COUNTRY_ROW:
        pytest.skip(LEFT_TO_THE_COUNTRY_ROW[slug])
    manifest = _manifests()[slug]
    missing = _unnamed(manifest)
    assert missing == [], (
        f"{slug} is the {manifest.market_country_code} pack and does not name {missing}, which every "
        f"{manifest.market_country_code} project runs through the country row. Add them to "
        "validation_rule_sets."
    )


# ── A classification key is not a rule set ───────────────────────────────────


def _classification_only_keys() -> set[str]:
    """Classification keys that are not also the name of a registered rule set."""
    from app.core.classification_registry import CLASSIFICATION_STANDARD_LABELS
    from app.modules.boq.router import _STANDARD_RULE_SETS

    registered = set(_measured()["sets"])
    keys = set(CLASSIFICATION_STANDARD_LABELS) | set(_STANDARD_RULE_SETS)
    return {key for key in keys if key not in registered}


def _rule_set_producers() -> dict[str, list[str]]:
    """Every shipped place that writes a rule-set name, by where it lives."""
    from app.config import Settings
    from app.core.demo_projects import DEMO_TEMPLATES
    from app.modules.boq.exchange_formats import EXCHANGE_FORMATS
    from app.modules.boq.router import _COUNTRY_RULE_SETS, _STANDARD_RULE_SETS

    out: dict[str, list[str]] = {}
    for slug, manifest in _manifests().items():
        out[f"pack {slug}"] = list(manifest.validation_rule_sets)
    for demo_id, template in DEMO_TEMPLATES.items():
        out[f"demo {demo_id}"] = list(template.validation_rule_sets or [])
    for country, names in _COUNTRY_RULE_SETS.items():
        out[f"country row {country}"] = list(names)
    for standard, name in _STANDARD_RULE_SETS.items():
        out[f"standard row {standard}"] = [name]
    for fmt in EXCHANGE_FORMATS:
        out[f"exchange format {fmt.format_id}"] = list(fmt.rule_packs)
    out["settings default"] = list(Settings.model_fields["default_validation_rule_sets"].default)
    return out


def test_the_classification_population_holds_the_known_two_name_pairs() -> None:
    """Control: if these were missing, the next test would pass by looking at nothing."""
    only = _classification_only_keys()
    for key in ("tetelrend", "gb50500", "knr"):
        assert key in only, f"{key!r} is no longer a classification-only key; the guard below lost its reason"


def test_no_producer_writes_a_classification_key_where_a_rule_set_belongs() -> None:
    only = _classification_only_keys()
    producers = _rule_set_producers()
    assert len(producers) >= 100, f"only {len(producers)} producers were read; the walk lost a population"
    wrong = {where: sorted(set(names) & only) for where, names in producers.items() if set(names) & only}
    assert wrong == {}, (
        f"these write a classification key into a rule-set list: {wrong}. The engine registers no set "
        "of that name, logs one line and validates against nothing national."
    )


def test_every_producer_names_only_registered_rule_sets() -> None:
    registered = set(_measured()["sets"])
    unknown = {
        where: sorted(set(names) - registered)
        for where, names in _rule_set_producers().items()
        if set(names) - registered
    }
    assert unknown == {}, f"these name rule sets a clean interpreter does not register: {unknown}"


@pytest.mark.parametrize(
    ("classification", "rule_set"),
    [("tetelrend", "hungary"), ("gb50500", "gbt50500"), ("knr", "poland")],
)
def test_apply_refuses_a_classification_key_and_names_the_rule_set_that_checks_it(
    classification: str, rule_set: str
) -> None:
    message = _measured()["refusals"][classification]
    assert message is not None, f"a pack naming {classification!r} as a rule set was applied without a refusal"
    assert f"{classification!r}" in message
    assert f"{rule_set!r}" in message, (
        f"the refusal of {classification!r} does not name {rule_set!r}, so the admin is left to guess "
        f"which rule set checks the classification: {message}"
    )
    assert "classification" in message


def test_an_invented_name_is_refused_without_a_classification_hint() -> None:
    """Negative control for the hint: it must not fire on a name that is no classification."""
    message = _measured()["refusals"]["spurious_ruleset_for_this_test"]
    assert message is not None
    assert "classification standard, not a rule set" not in message


def test_a_pack_left_to_the_country_row_still_has_its_reason() -> None:
    """The exemption holds only while the two standards still disagree and the pack still names nothing."""
    from app.core.classification_registry import resolve_standard, standard_for_country
    from app.core.demo_projects import DEMO_TEMPLATES, PACK_DEMO_PROJECT

    for slug in LEFT_TO_THE_COUNTRY_ROW:
        manifest = _manifests()[slug]
        assert _unnamed(manifest), f"{slug} names its country row's sets now; remove it from LEFT_TO_THE_COUNTRY_ROW"
        demo = DEMO_TEMPLATES[PACK_DEMO_PROJECT[slug]]
        demo_standard = resolve_standard(demo.classification_standard or None, region=demo.region).standard
        assert demo_standard != standard_for_country(manifest.market_country_code), (
            f"{slug}: the demo and the registry agree on {demo_standard!r} now, so the reason is gone"
        )


def _demo_payload(template: Any) -> dict[str, Any]:
    positions: list[dict[str, Any]] = []
    for ordinal, title, classification, items in template.sections:
        positions.append(
            {
                "id": f"s-{ordinal}",
                "ordinal": ordinal,
                "description": title,
                "classification": classification,
                "type": "section",
            }
        )
        for item_ordinal, description, unit, quantity, rate, item_classification in items:
            positions.append(
                {
                    "id": f"p-{item_ordinal}",
                    "parent_id": f"s-{ordinal}",
                    "ordinal": item_ordinal,
                    "description": description,
                    "unit": unit,
                    "quantity": float(quantity),
                    "unit_rate": float(rate),
                    "total": float(quantity) * float(rate),
                    "classification": item_classification,
                    "type": "position",
                }
            )
    return {"positions": positions}


def _demo_cases_with_code_sets() -> list[tuple[str, str]]:
    """``(pack, demo)`` for every demo of a pack that names a "code required" set."""
    from app.core.demo_projects import PACK_DEMO_PROJECT
    from app.modules.boq.router import _CLASSIFICATION_CODE_SETS

    cases: list[tuple[str, str]] = []
    for slug, manifest in _manifests().items():
        if not any(name in _CLASSIFICATION_CODE_SETS for name in manifest.validation_rule_sets):
            continue
        demos = [PACK_DEMO_PROJECT.get(slug), *manifest.demo_template_ids]
        cases.extend((slug, demo) for demo in dict.fromkeys(demos) if demo)
    return cases


def test_the_inherited_demo_population_covers_the_repaired_code_set_packs() -> None:
    """Control: the test below must actually reach the packs that now name a code set."""
    packs = {slug for slug, _demo in _demo_cases_with_code_sets()}
    for slug in (
        "aus",
        "nzs",
        "saudi-vision2030",
        "turkey-tr",
        "batimatech-ca",
        "us-california",
        "us-texas",
        "south-africa",
    ):
        assert slug in packs, f"{slug} has no demo the inherited-set check can validate"


def _inherited_errors(
    manifest: PartnerPackManifest, demo_id: str, *, recorded: bool = True
) -> tuple[list[str], dict[str, int]]:
    """Validate ``demo_id`` with the sets a project created under ``manifest`` carries; count errors per rule.

    ``recorded`` is whether the router is told which sets the pack added, as
    project creation records them. Off, it reads every carried set as asked
    for, which is what it did before the record existed.
    """
    import asyncio

    from app.core.classification_registry import resolve_standard
    from app.core.demo_projects import DEMO_TEMPLATES, _country_code_for
    from app.core.partner_pack.apply import split_inherited_rule_sets
    from app.core.validation.engine import validation_engine
    from app.core.validation.rules import register_builtin_rules
    from app.modules.boq.router import _build_rule_sets

    register_builtin_rules()
    template = DEMO_TEMPLATES[demo_id]
    standard = resolve_standard(template.classification_standard or None, region=template.region).standard or ""
    inherited, pack_added = split_inherited_rule_sets(list(template.validation_rule_sets or []), manifest)
    rule_sets = _build_rule_sets(
        inherited,
        standard,
        template.region or "",
        _country_code_for(template) or "",
        pack_rule_sets=pack_added if recorded else (),
    )
    runnable = [name for name in rule_sets if validation_engine.registry.has_rules(name)]
    for name in manifest.validation_rule_sets:
        if name in pack_added and recorded and name not in rule_sets:
            continue  # dropped on purpose: a code set of a standard the demo does not use
        assert name in runnable, f"{manifest.slug} names {name!r} and the in-process registry does not run it"
    report = asyncio.run(
        validation_engine.validate(
            data=_demo_payload(template), rule_sets=runnable, target_type="boq", metadata={"locale": "en"}
        )
    )
    errors: dict[str, int] = {}
    for result in report.results:
        if not result.passed and result.severity.value == "error":
            errors[result.rule_id] = errors.get(result.rule_id, 0) + 1
    return runnable, errors


@pytest.mark.parametrize(("slug", "demo_id"), _demo_cases_with_code_sets())
def test_a_demo_validated_with_what_a_pack_project_inherits_raises_no_error(slug: str, demo_id: str) -> None:
    """The rule sets a project created under the pack carries, run on the pack's own demo bill.

    ``test_pack_conformance`` validates a demo with the demo's own sets, which
    is how the installed demo is validated. A project the user creates under
    the pack inherits the pack's sets as well, with the record of which ones
    the pack added, and that is the population a pack-declared "code required"
    set reaches.
    """
    runnable, errors = _inherited_errors(_manifests()[slug], demo_id)
    assert errors == {}, (
        f"a project created under {slug} carries {runnable}, and the pack's own {demo_id} bill fails {errors}"
    )


def test_the_record_is_what_keeps_a_pack_code_set_off_a_demo_coded_otherwise() -> None:
    """Negative control: South Africa naming nrm, on its Johannesburg demo coded in MasterFormat.

    Without the record of what the pack added, the router reads nrm as a set
    the project asked for and the bill fails on every line, which is what
    happened before the record existed. With it, nrm is dropped for a
    MasterFormat project exactly as the ZA country row's nrm is.
    """
    from app.core.demo_projects import PACK_DEMO_PROJECT

    named = _manifests()["south-africa"]
    assert named.validation_rule_sets == ["nrm"]
    demo = PACK_DEMO_PROJECT["south-africa"]
    _runnable, unrecorded = _inherited_errors(named, demo, recorded=False)
    assert unrecorded.get("nrm.classification_required", 0) > 0, unrecorded
    runnable, recorded = _inherited_errors(named, demo)
    assert "nrm" not in runnable
    assert recorded == {}, recorded
