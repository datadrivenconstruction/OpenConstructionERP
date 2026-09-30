# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Hungarian pack, and the three places its facts are written down twice.

A country pack states the same thing in several files by necessity: the engine
holds the chapter list because rules run on it, the manifest holds it because
the onboarding wizard renders it, and the reference document holds it because
a person reads it. Copies drift, and the drift is silent, so each pair is
compared here rather than trusted.

The one that matters most is the chapter list. A rule that accepts a chapter
the pack does not offer, or a pack that offers one the rule rejects, produces
a warning on a correctly written bill, which is the fastest way to teach a user
to ignore a rule set.

No database and no application settings: the manifest is imported directly and
everything else is filesystem and JSON.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.core.classification_registry import (
    CLASSIFICATION_STANDARD_LABELS,
    KNOWN_CLASSIFICATION_STANDARDS,
    resolve_standard,
)
from app.core.demo_packs import PACK_TEMPLATES
from app.core.demo_projects import DemoTemplate, _enrich_position_metadata
from app.core.validation.messages import is_key_present
from app.core.validation.rules import HU_BUILDING_CHAPTERS

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_DIR = REPO_ROOT / "packs" / "hungary-hu"
PACKAGE_DIR = PACK_DIR / "src" / "openconstructionerp_hungary_hu"
RULE_PACKS = PACKAGE_DIR / "rule_packs"


@pytest.fixture(scope="module")
def manifest():
    """The manifest object the pack's own module builds."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_hungary_manifest_under_test", PACKAGE_DIR / "manifest.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MANIFEST


# ── The manifest ─────────────────────────────────────────────────────────


def test_the_pack_is_a_country_pack_in_forint(manifest) -> None:
    assert manifest.slug == "hungary-hu"
    assert manifest.type == "country"
    assert manifest.metadata["country"] == "HU"
    assert manifest.default_currency == "HUF"
    assert manifest.default_methodology == "hungary"


def _offered_languages() -> set[str]:
    """The language codes the interface offers, read from its own list."""
    source = (REPO_ROOT / "frontend" / "src" / "app" / "i18n.ts").read_text(encoding="utf-8")
    offered = set(re.findall(r"\{\s*code:\s*'([A-Za-z-]+)'", source))
    assert len(offered) > 20, "the language list in i18n.ts was not found"
    return offered


def test_the_pack_switches_the_interface_to_hungarian(manifest) -> None:
    """Installing the Hungarian pack sets a Hungarian interface.

    ``normalizePackLocale`` answers a locale the application does not ship
    with English, so the value is only worth declaring while Hungarian is
    both shipped and offered; the two halves are checked separately because
    a language can have a file before it is offered. That ``hu`` answers
    with itself is asserted where the function lives, in
    ``frontend/src/app/__tests__/normalizePackLocale.test.ts``.
    """
    assert manifest.default_locale == "hu"
    assert (REPO_ROOT / "frontend" / "src" / "app" / "locales" / "hu.ts").is_file()
    assert "hu" in _offered_languages()


def test_the_apply_plan_the_dialog_reads_carries_the_hungarian_locale(manifest) -> None:
    """The install dialog switches to ``plan.default_locale`` of the pack preview."""
    from app.core.partner_pack.apply import _plan

    assert _plan(manifest)["default_locale"] == "hu"


def test_the_full_install_hands_the_hungarian_locale_to_the_interface(manifest, monkeypatch) -> None:
    """The locale step of the one-click full install reports the same locale."""
    from app.core.partner_pack import discovery, full_install

    monkeypatch.setattr(discovery, "get_pack_by_slug", lambda slug: manifest if slug == "hungary-hu" else None)
    step = full_install._step_locale("hungary-hu")
    assert step.status == "ok"
    assert step.detail == {"locale": "hu"}


def test_the_pack_merges_no_locale_file_over_the_shipped_one(manifest) -> None:
    """A file under ``additional_locales`` would override the shipped bundle for everyone."""
    assert manifest.additional_locales == {}


def test_the_declared_methodology_is_a_template_that_exists(manifest) -> None:
    from app.modules.methodology import templates

    template = templates.TEMPLATES_BY_SLUG[manifest.default_methodology]
    assert template["country_code"] == "HU"
    assert template["currency"] == "HUF"
    assert template["decimals"] == 0, "the forint is quoted in whole units"
    assert str(template["vat_rate"]) == str(manifest.metadata["vat_standard_rate"])


# ── The chapter list, in three places ────────────────────────────────────


def _manifest_chapters(manifest) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in manifest.metadata["building_chapters"]:
        code, _, name = entry.partition(" ")
        out[code] = name
    return out


def test_the_manifest_and_the_engine_agree_on_the_chapters(manifest) -> None:
    assert _manifest_chapters(manifest) == dict(HU_BUILDING_CHAPTERS)


def test_the_shipped_document_and_the_engine_agree_on_the_chapters() -> None:
    document = json.loads((RULE_PACKS / "hu_magasepitesi_tetelrend.json").read_text(encoding="utf-8"))
    from_document = {row["code"]: row["name_hu"] for row in document["chapters"]}
    assert from_document == dict(HU_BUILDING_CHAPTERS)


def test_there_are_seventeen_of_them_numbered_without_a_gap() -> None:
    assert sorted(HU_BUILDING_CHAPTERS) == [f"{n:02d}" for n in range(1, 18)]


def test_the_documents_code_pattern_is_the_one_the_engine_applies() -> None:
    """A pattern written out for a reader has to be the pattern that runs."""
    from app.core.validation.rules import _HU_BUILDING_CODE_RE

    document = json.loads((RULE_PACKS / "hu_magasepitesi_tetelrend.json").read_text(encoding="utf-8"))
    assert document["code_format"]["regex"] == _HU_BUILDING_CODE_RE.pattern
    for example in document["code_format"]["examples"]:
        assert _HU_BUILDING_CODE_RE.match(example), f"{example} is offered as an example and does not match"


# ── The rule packs on disk ───────────────────────────────────────────────


def test_every_declared_document_is_shipped_and_every_shipped_one_declared(manifest) -> None:
    declared = set(manifest.validation_rule_packs)
    on_disk = {path.stem for path in RULE_PACKS.glob("*.json")}
    assert declared == on_disk, f"declared {sorted(declared)}, on disk {sorted(on_disk)}"


def test_each_document_names_itself_by_its_own_file_stem() -> None:
    for path in sorted(RULE_PACKS.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["rule_pack_id"] == path.stem


def test_each_document_says_how_far_it_has_been_reviewed() -> None:
    """A document derived from a file and one drawn from a statute are not the
    same kind of claim, and shipping both without saying which is which is the
    part that would mislead."""
    for path in sorted(RULE_PACKS.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document.get("review_status"), f"{path.name} does not state its review status"
        assert document["jurisdiction"] == "HU"


def test_every_rule_a_document_promises_is_a_rule_the_engine_registers() -> None:
    from app.core.validation.rules import (
        HungarianChapterRecognised,
        HungarianItemCodeRequired,
        HungarianItemNumberUnique,
        HungarianMaterialFeeSplit,
    )

    implemented = {
        rule.rule_id
        for rule in (
            HungarianItemCodeRequired(),
            HungarianChapterRecognised(),
            HungarianMaterialFeeSplit(),
            HungarianItemNumberUnique(),
        )
    }
    promised: set[str] = set()
    for path in sorted(RULE_PACKS.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        promised.update(document.get("enables_rule_ids", []))
    assert promised <= implemented, f"documents promise rules that do not exist: {sorted(promised - implemented)}"
    assert promised == implemented, f"rules exist that no document mentions: {sorted(implemented - promised)}"


# ── The engine seam ──────────────────────────────────────────────────────


def test_the_declared_rule_set_is_the_one_the_rules_carry(manifest) -> None:
    from app.core.validation.rules import HungarianItemCodeRequired

    assert manifest.validation_rule_sets == [HungarianItemCodeRequired.standard]


def test_a_hungarian_project_is_classified_against_the_hungarian_item_order() -> None:
    resolved = resolve_standard(None, "HU")
    assert resolved.standard == "tetelrend"
    assert resolved.matched, "a region that matched must not report itself as a fall-through"
    assert "tetelrend" in KNOWN_CLASSIFICATION_STANDARDS, (
        "a standard absent from the known list is silently ignored when a project names it explicitly"
    )
    assert CLASSIFICATION_STANDARD_LABELS["tetelrend"]


def test_the_classification_key_the_rules_read_is_the_standard_they_classify_against() -> None:
    """The rules read ``classification['tetelrend']``, so the two have to be one name."""
    source = (REPO_ROOT / "backend" / "app" / "core" / "validation" / "rules" / "__init__.py").read_text(
        encoding="utf-8"
    )
    body = source[source.index("def _hu_code(") : source.index("class HungarianItemCodeRequired")]
    assert re.search(r'get\(\s*"tetelrend"', body), "the Hungarian rules no longer read the tetelrend key"


@pytest.mark.parametrize(
    "key",
    [
        "hungary.item_code_required.fail",
        "hungary.item_code_required.invalid",
        "hungary.item_code_required.suggestion",
        "hungary.chapter_recognised.fail",
        "hungary.material_fee_split.fail",
        "hungary.material_fee_split.suggestion",
        "hungary.item_number_unique.fail",
        "hungary.item_number_unique.suggestion",
    ],
)
@pytest.mark.parametrize("locale", ["en", "de", "es", "ru"])
def test_every_message_exists_in_every_validation_locale(key: str, locale: str) -> None:
    """A missing message is not an error anywhere: the bundle prints the key at
    the user and logs a warning nobody reads."""
    assert is_key_present(key, locale), f"{key} is missing from {locale}.json"


# ── The shipped demos ─────────────────────────────────────────────────────
#
# The pair above compares copies of a fact. This pair compares the fact
# against the data the product actually shows, which is where both Hungarian
# defects lived: the demos named a rule set that does not exist, so none of
# the rules above ran on them, and their lines carried no anyag/dij split, so
# the one rule that speaks to the thing every Hungarian bill is quoted in had
# nothing to read even once the set name was right.


def _hungarian_templates() -> list[DemoTemplate]:
    """The two shipped Hungarian demo templates."""
    return [t for t in PACK_TEMPLATES if t.demo_id in {"office-debrecen", "residential-budapest"}]


def test_both_hungarian_demos_are_present() -> None:
    """Without this the two tests below pass over an empty list."""
    assert len(_hungarian_templates()) == 2, "the Hungarian demo templates are not both loading"


@pytest.mark.parametrize("demo_id", ["office-debrecen", "residential-budapest"])
def test_the_demo_asks_for_the_rule_set_that_exists(demo_id: str) -> None:
    """``tetelrend`` is the classification standard, ``hungary`` is the rule set.

    Both templates named the standard where the rule set goes. The engine logs
    an unimplemented rule set and continues, so the only symptom was a report
    that had run fewer checks than it listed.
    """
    template = next(t for t in _hungarian_templates() if t.demo_id == demo_id)
    assert "hungary" in template.validation_rule_sets, (
        f"{demo_id} does not ask for the hungary rule set, so the item order, "
        "the seventeen chapters and the material and fee split run on nothing"
    )
    assert "tetelrend" not in template.validation_rule_sets, (
        f"{demo_id} names tetelrend as a rule set again; it is the classification standard"
    )
    assert template.classification_standard == "tetelrend", (
        f"{demo_id} should still classify to tetelrend, which is the standard's real job"
    )


@pytest.mark.parametrize("demo_id", ["office-debrecen", "residential-budapest"])
def test_every_priced_demo_line_carries_a_reconciling_split(demo_id: str) -> None:
    """anyag plus dij is the rate, on every priced line of the shipped demo.

    ``HungarianMaterialFeeSplit`` treats a line with no split as "not my row",
    which is right for the imported bills a Hungarian workspace also holds and
    wrong for the country's own demo: it made the rule silent on the one bill
    that exists to show what the pack does. The split is derived from the
    resource rollup the seeder already computes, so this asserts the derivation
    stays exact rather than merely present.
    """
    template = next(t for t in _hungarian_templates() if t.demo_id == demo_id)

    lines = 0
    for _ordinal, _title, _classification, items in template.sections:
        for item_ordinal, description, unit, _qty, rate, cls in items:
            lines += 1
            meta = _enrich_position_metadata(description=description, unit=unit, unit_rate=rate, classification=cls)
            block = meta.get("hu")
            assert block, f"{demo_id} line {item_ordinal} carries no anyag/dij split"
            split = block["material_unit_rate"] + block["fee_unit_rate"]
            # The rule's own tolerance is 1 percent; the derivation should be
            # exact, so this is tighter on purpose. A drift here means the
            # resource leaves stopped summing to the rate.
            assert abs(split - rate) <= max(0.01, rate * 1e-9), (
                f"{demo_id} line {item_ordinal}: anyag {block['material_unit_rate']} plus "
                f"dij {block['fee_unit_rate']} is {split}, and the rate is {rate}"
            )

    assert lines >= 50, f"{demo_id} priced only {lines} lines, which is too few to be the shipped demo"


def test_the_split_is_not_emitted_for_a_line_from_elsewhere() -> None:
    """A bill that is not Hungarian must not grow a Hungarian block.

    The rule reads a missing block as "not my row", and that behaviour is what
    keeps a Hungarian workspace from flagging every imported foreign bill. If
    the seeder started emitting the block for everything, the rule would begin
    judging bills it has no business judging.
    """
    foreign = _enrich_position_metadata(
        description="Cast in-situ RC slab C30/37",
        unit="m3",
        unit_rate=520.0,
        classification={"din276": "331"},
    )
    assert "hu" not in foreign, "a DIN 276 line was given an anyag/dij split"

    hungarian = _enrich_position_metadata(
        description="Monolit vasbeton fodem C30/37",
        unit="m3",
        unit_rate=38500.0,
        classification={"tetelrend": "MA-04-12-01"},
    )
    assert "hu" in hungarian, "a tetelrend line was not given an anyag/dij split"
