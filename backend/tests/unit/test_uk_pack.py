# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The UK pack, and the ninety-seven checks it promised and did not have.

``enables_rule_ids`` reads as a promise: switching this document on turns
these checks on. The UK pack declared 97 ids across seven documents and the
engine defined none of them. That is worse than the checks being absent,
because an absent check does not tell an estimator the platform is watching
something it is not.

The gate below is stated as a property over every pack rather than over this
one, with an explicit allowlist naming the packs still carrying the defect and
the size of it. Written that way it goes red twice: when a clean pack starts
declaring a rule that does not exist, and when a listed pack is fixed and its
entry goes stale. A list that only ever gets longer is not a gate.

The end-to-end assertions matter more than the wiring ones. A rule that reads
a field nothing writes passes every test built from its own fixtures, so the
shipped UK demo project is run through the real rules here and its findings
are read.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.demo_packs import PACK_TEMPLATES
from app.core.validation.engine import ValidationContext, validation_engine
from app.core.validation.rules import register_builtin_rules

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKS = REPO_ROOT / "packs"
PACK = PACKS / "uk-jct" / "src" / "openconstructionerp_uk_jct"
RULES_SOURCE = REPO_ROOT / "backend" / "app" / "core" / "validation" / "rules" / "__init__.py"

#: Packs whose documents still name rule ids the engine does not define, with
#: the count as measured. Each entry is a debt, not a permission: fix the pack
#: and delete its line. The numbers are pinned so a pack that gets worse is
#: reported as loudly as one that starts fresh.
KNOWN_UNBACKED_RULE_IDS = {
    "aus": 92,
    "batimatech-ca": 75,
    "bimhessen-de": 138,
    "brazil-sinapi": 67,
    "doker-formwork": 87,
    "france-fr": 71,
    "germany-de": 67,
    "india-cpwd": 119,
    "italy-it": 44,
    "japan-jp": 46,
    "korea-kr": 43,
    "modular-prefab": 111,
    "netherlands-nl": 42,
    "nzs": 55,
    "poland-pl": 44,
    "renewables-epc": 173,
    "retail-grocery-dach": 69,
    "saudi-vision2030": 168,
    "south-africa": 20,
    "spain-es": 49,
    "turkey-tr": 45,
    "uae-ae": 48,
    "us-california": 54,
    "us-costdata": 97,
    "us-texas": 45,
}


@pytest.fixture(scope="module")
def manifest() -> Any:
    """The pack's real on-disk manifest, loaded the way the loader loads it."""
    spec = importlib.util.spec_from_file_location("_uk_manifest", PACK / "manifest.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MANIFEST


@pytest.fixture(scope="module")
def engine_rule_ids() -> set[str]:
    """Every rule id the engine defines, read from the registry it registers into."""
    register_builtin_rules()
    return {entry["rule_id"] for entry in validation_engine.registry.list_rules()}


def _documents(pack_dir: Path) -> dict[str, dict[str, Any]]:
    """The rule-pack documents a pack ships, by file stem."""
    return {p.stem: json.loads(p.read_bytes().decode("utf-8")) for p in sorted(pack_dir.glob("rule_packs/*.json"))}


def _pack_dirs() -> list[Path]:
    """Every installed pack's package directory."""
    return sorted(p.parent for p in PACKS.glob("*/src/*/manifest.py"))


# ── The promise ──────────────────────────────────────────────────────────


def test_every_rule_id_the_uk_pack_declares_exists(engine_rule_ids: set[str]) -> None:
    """The finding this file was written for, stated as the property."""
    declared: dict[str, list[str]] = {}
    for stem, document in _documents(PACK).items():
        for rule_id in document.get("enables_rule_ids") or []:
            declared.setdefault(rule_id, []).append(stem)
    assert declared, "the UK pack declares no rule ids at all, which is not the intended shape"
    missing = {rule_id: docs for rule_id, docs in declared.items() if rule_id not in engine_rule_ids}
    assert not missing, f"the UK pack promises checks the engine does not define: {missing}"


def test_the_packs_still_promising_checks_they_do_not_have_are_the_ones_listed(
    engine_rule_ids: set[str],
) -> None:
    """The same property across every pack, with the debt written down.

    Two directions matter. A pack absent from the list must be clean, which is
    what stops a new pack shipping the defect. And a pack on the list must
    still be dirty by the same amount, which is what stops the list becoming a
    permanent excuse nobody revisits.
    """
    measured: dict[str, int] = {}
    for pack_dir in _pack_dirs():
        unbacked = sum(
            1
            for document in _documents(pack_dir).values()
            for rule_id in document.get("enables_rule_ids") or []
            if rule_id not in engine_rule_ids
        )
        if unbacked:
            measured[pack_dir.parents[1].name] = unbacked
    assert measured == KNOWN_UNBACKED_RULE_IDS, (
        "the unbacked rule id debt moved. Newly dirty: "
        f"{ {k: v for k, v in measured.items() if k not in KNOWN_UNBACKED_RULE_IDS} }. "
        f"Now clean, delete their lines: {sorted(set(KNOWN_UNBACKED_RULE_IDS) - set(measured))}. "
        f"Changed count: { {k: (KNOWN_UNBACKED_RULE_IDS[k], v) for k, v in measured.items() if k in KNOWN_UNBACKED_RULE_IDS and v != KNOWN_UNBACKED_RULE_IDS[k]} }."
    )


def test_a_document_that_enables_nothing_says_why(engine_rule_ids: set[str]) -> None:
    """The honest shape for a reference document, made deliberate.

    An empty list is the right answer for a document whose subject the engine
    does not check. It is also what a document looks like when somebody
    deleted the ids without deciding anything, so the ones that ship empty
    have to explain themselves.
    """
    for stem, document in _documents(PACK).items():
        enabled = document.get("enables_rule_ids") or []
        assert set(enabled) <= engine_rule_ids, f"{stem} names ids the engine does not define"
        if enabled:
            continue
        assert "why_no_rules" in document, f"{stem} enables nothing and does not say why"
        assert len(document["why_no_rules"]) > 80, f"{stem} explains itself in a sentence fragment"


# ── Wiring ───────────────────────────────────────────────────────────────


def test_the_manifest_and_the_files_on_disk_agree(manifest: Any) -> None:
    declared = set(manifest.validation_rule_packs)
    on_disk = set(_documents(PACK))
    assert declared == on_disk, (
        f"declared but not shipped: {sorted(declared - on_disk)}; shipped but not declared: {sorted(on_disk - declared)}"
    )


def test_each_document_names_itself_the_way_its_file_is_named() -> None:
    """A document whose id and filename disagree is loadable by one and
    referenced by the other, and the mismatch surfaces as a missing pack."""
    for stem, document in _documents(PACK).items():
        assert document["rule_pack_id"] == stem, f"{stem}.json calls itself {document['rule_pack_id']}"


def test_every_document_carries_the_fields_a_reader_needs() -> None:
    """Not a schema for its own sake. ``review_status`` is the one that
    matters: it says who has read this and who has not, and a compliance
    document without it is asking to be trusted on nothing."""
    required = {"rule_pack_id", "name", "standard", "jurisdiction", "applies_to", "review_status", "description"}
    for stem, document in _documents(PACK).items():
        missing = required - set(document)
        assert not missing, f"{stem} is missing {sorted(missing)}"
        assert document["jurisdiction"] == "GB", f"{stem} claims jurisdiction {document['jurisdiction']}"
        assert len(document["description"]) > 200, f"{stem} has a description too short to be one"


def test_the_rule_sets_the_pack_switches_on_are_registered(manifest: Any) -> None:
    register_builtin_rules()
    registered = validation_engine.registry.list_rule_sets()
    for rule_set in manifest.validation_rule_sets:
        assert registered.get(rule_set), f"{rule_set} is declared by the pack and carries no rules"


def test_every_declared_rule_id_is_reachable_through_a_declared_rule_set(
    manifest: Any, engine_rule_ids: set[str]
) -> None:
    """Existing is not enough. A rule the pack names but does not switch on is
    a check nobody runs, and the pack would still read as if it did."""
    reachable = {
        rule.rule_id for rule in validation_engine.registry.get_rules_for_sets(list(manifest.validation_rule_sets))
    }
    declared = {rule_id for document in _documents(PACK).values() for rule_id in document.get("enables_rule_ids") or []}
    assert declared <= reachable, (
        f"declared but not in any rule set the pack switches on: {sorted(declared - reachable)}"
    )


def test_the_shipped_assets_the_manifest_points_at_exist(manifest: Any) -> None:
    assert (PACK / manifest.onboarding_script_path).is_file()
    assert (PACK / manifest.branding.logo_path).is_file()
    for path in manifest.additional_locales.values():
        assert (PACK / path).is_file(), f"declared locale {path} is not shipped"


def test_the_onboarding_wizard_switches_on_what_the_manifest_declares(manifest: Any) -> None:
    """The wizard writes the workspace, so a document missing from its apply
    list is a document the user never gets, however carefully it is declared."""
    script = yaml.safe_load((PACK / manifest.onboarding_script_path).read_bytes().decode("utf-8"))
    steps = {step["id"]: step for step in script["steps"]}
    apply = steps["review"]["action"]["apply"]
    enabled: set[str] = set()
    for entry in apply:
        if "enable_rule_packs" in entry:
            enabled |= set(entry["enable_rule_packs"])
        if "conditionally_enable_rule_packs" in entry:
            enabled |= set(entry["conditionally_enable_rule_packs"]["packs"])
    assert enabled == set(manifest.validation_rule_packs), (
        f"wizard enables {sorted(enabled)}; manifest declares {sorted(manifest.validation_rule_packs)}"
    )


def test_the_wizard_asks_for_what_the_statutory_rules_read_back(manifest: Any) -> None:
    """The reason the wizard is not decoration. Every statutory check is a
    question about something a person has to type in once, and a check whose
    question is never asked is a warning nobody can clear."""
    script = yaml.safe_load((PACK / manifest.onboarding_script_path).read_bytes().decode("utf-8"))
    keys = {field["key"] for step in script["steps"] for field in step.get("fields", [])}
    for expected in (
        "default_contract_form",
        "due_date_days",
        "final_date_for_payment_days",
        "retention_percentage",
        "cdm_principal_designer",
        "cdm_principal_contractor",
        "handles_hrb",
        "default_vat_treatment",
    ):
        assert expected in keys, f"the wizard never asks for {expected}, which a statutory rule reads"


# ── House style ──────────────────────────────────────────────────────────


def test_the_pack_ships_no_long_dashes() -> None:
    """House style, and it had 23 of them."""
    offenders = {}
    for path in sorted(PACK.parent.parent.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".py", ".md", ".yaml", ".toml"}:
            continue
        if "__pycache__" in path.parts:
            continue
        text = path.read_bytes().decode("utf-8")
        count = text.count("—") + text.count("–")
        if count:
            offenders[path.name] = count
    assert not offenders, f"long dashes in shipped pack files: {offenders}"


# ── The end to end reading ───────────────────────────────────────────────


def _demo_payload(demo_id: str) -> dict[str, Any]:
    """The shipped demo template, in the shape the payload builder produces.

    Assembled from the template rather than from a fixture on purpose: the
    question these tests answer is whether the estimate this pack actually
    installs passes the checks this pack actually switches on.
    """
    template = next(t for t in PACK_TEMPLATES if t.demo_id == demo_id)
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
                    "ordinal": item_ordinal,
                    "description": description,
                    "unit": unit,
                    "quantity": quantity,
                    "unit_rate": str(rate),
                    "classification": item_classification,
                    "parent_id": f"s-{ordinal}",
                }
            )
    markups = [
        {"name": name, "category": category, "percentage": str(percentage), "apply_to": apply_to, "is_active": True}
        for name, percentage, category, apply_to in template.markups
    ]
    return {
        "positions": positions,
        "boq": {"name": template.boq_name, "metadata": template.boq_metadata, "currency": template.currency},
        "markups": markups,
    }


@pytest.mark.asyncio
async def test_the_shipped_uk_demo_passes_the_checks_the_pack_switches_on(manifest: Any) -> None:
    """The assertion the wiring tests cannot make.

    A rule reading a field nothing writes passes every test built from its own
    fixtures. This runs the real rule sets over the estimate a UK user is
    handed on first boot, and any warning it raises is one that user would see
    with nothing they could do about it.
    """
    register_builtin_rules()
    report = await validation_engine.validate(
        data=_demo_payload("commercial-london"),
        rule_sets=list(manifest.validation_rule_sets),
        target_type="boq",
        target_id="commercial-london",
        metadata={"locale": "en"},
    )
    assert report.results, "the UK rule sets produced no findings at all on the UK demo"
    failed = sorted({result.rule_id for result in report.results if not result.passed})
    assert not failed, f"the shipped UK demo cannot clear its own pack's checks: {failed}"


@pytest.mark.asyncio
async def test_the_uk_demo_is_read_by_both_rule_sets_not_just_one(manifest: Any) -> None:
    """Both sets have to have run. A report that is green because half of it
    never fired is the failure this whole file is about."""
    register_builtin_rules()
    report = await validation_engine.validate(
        data=_demo_payload("commercial-london"),
        rule_sets=list(manifest.validation_rule_sets),
        target_type="boq",
        target_id="commercial-london",
        metadata={"locale": "en"},
    )
    fired = {result.rule_id.split(".")[0] for result in report.results}
    assert "nrm" in fired, "no NRM rule ran on the UK demo"
    assert "uk" in fired, "no UK statutory rule ran on the UK demo"


@pytest.mark.asyncio
async def test_the_demo_declares_it_is_not_a_higher_risk_building_and_is_right() -> None:
    """A ten-storey speculative office with no dwellings. The rule reads the
    three numbers the estimate gives and agrees with the answer it declared,
    which is the whole point of encoding the threshold rather than describing
    it."""
    from app.core.validation.rules import UKHigherRiskBuildingRegime

    payload = _demo_payload("commercial-london")
    results = await UKHigherRiskBuildingRegime().validate(ValidationContext(data=payload, metadata={"locale": "en"}))
    assert results[0].passed
    assert results[0].details["higher_risk_building"] is False
    assert results[0].details["derived"] is False
    assert results[0].details["residential_units"] == 0


def test_the_demo_no_longer_claims_a_gateway_regime_it_is_outside_of() -> None:
    """It did. The template described a commercial office as delivered under
    the higher-risk building regime, which needs two dwellings it does not
    have, and the number carried a gateway programme with it."""
    source = (
        (REPO_ROOT / "backend" / "app" / "core" / "demo_packs" / "commercial-london.py").read_bytes().decode("utf-8")
    )
    claims = re.findall(r"[^.]*higher-risk building regime[^.]*\.", source)
    for claim in claims:
        assert "does not" in claim or "outside" in claim, f"the demo still claims the regime applies: {claim.strip()}"
