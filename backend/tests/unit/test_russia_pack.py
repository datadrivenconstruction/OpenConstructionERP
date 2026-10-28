# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The Russian pack, and the seams it has to hold together.

A country pack states the same fact in several files by necessity: the engine
holds the code pattern because a rule compiles it, the manifest holds it
because the onboarding wizard renders it, and the reference document holds it
because a person reads it. Copies drift silently, so each pair is compared here
rather than trusted.

Two of these cases are not about this pack at all and are here because this
pack is what exposed them. One walks the project screens' copies of the
classification registry: a standard the backend resolves and no screen offers
is unreachable, and a value a screen writes that the backend cannot resolve
falls into the default without saying so. Both happened. The other asserts that
the Russian markup stack is reachable, which lives with its own suite.

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
from app.core.validation.messages import is_key_present

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_DIR = REPO_ROOT / "packs" / "russia-gesn"
PACKAGE_DIR = PACK_DIR / "src" / "openconstructionerp_russia_gesn"
RULE_PACKS = PACKAGE_DIR / "rule_packs"
FRONTEND = REPO_ROOT / "frontend" / "src" / "features" / "projects"


@pytest.fixture(scope="module")
def manifest():
    """The manifest object the pack's own module builds."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_russia_manifest_under_test", PACKAGE_DIR / "manifest.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MANIFEST


# ── The manifest ─────────────────────────────────────────────────────────


def test_the_pack_is_a_country_pack_in_roubles(manifest) -> None:
    assert manifest.slug == "russia-gesn"
    assert manifest.type == "country"
    assert manifest.metadata["country"] == "RU"
    assert manifest.default_currency == "RUB"
    assert manifest.default_methodology == "russia"


def test_the_pack_promises_a_russian_interface_and_the_bundle_is_there(manifest) -> None:
    """The opposite of the Hungarian pack, and for a measured reason.

    A pack can only select a locale the application already ships. One that
    declares a language with no bundle behind it promises an interface it
    cannot deliver: ``matchSupportedLanguage`` answers with English and nothing
    tells the user their choice was dropped. Hungarian has no bundle, so that
    pack declares English. Russian has one, so this pack declares Russian, and
    the file it depends on is checked here rather than assumed.
    """
    assert manifest.default_locale == "ru"
    assert (REPO_ROOT / "frontend" / "src" / "app" / "locales" / "ru.ts").is_file(), (
        "the pack selects ru, so the application has to ship a ru bundle"
    )
    assert manifest.additional_locales == {}


def test_the_declared_methodology_carries_the_national_stack(manifest) -> None:
    """Russia had a markup stack and no methodology to attach it to.

    ``_reconcile_with_region_table`` rewrites a flat country template from the
    regional table when the table covers its country. With no Russian template
    there was nothing to rewrite, so the stack sat in the source unused. The
    assertion that matters is ``derived_from_region``: without it this template
    would be the neutral international method wearing a Russian name.
    """
    from app.modules.methodology import templates

    template = templates.TEMPLATES_BY_SLUG[manifest.default_methodology]
    assert template["country_code"] == "RU"
    assert template["currency"] == "RUB"
    assert template["decimals"] == 2, "the rouble is quoted with kopecks"
    assert str(template["vat_rate"]) == str(manifest.metadata["vat_standard_rate"])
    assert template["derived_from_region"] == "RU", "the template is not carrying the national stack"

    categories = [str(step["category"]) for step in template["cascade_steps"]]
    assert categories == ["overhead", "profit", "contingency", "tax"]


def test_the_declared_cost_database_is_one_the_marketplace_offers(manifest) -> None:
    """A region id nothing serves is a promise the install cannot keep."""
    from app.core.marketplace import MARKETPLACE_MODULES

    offered = {module.id for module in MARKETPLACE_MODULES}
    for region in manifest.cwicr_regions:
        assert region in offered, f"{region} is declared by the pack and not offered by the marketplace"


# ── The summary-estimate chapters, in three places ───────────────────────


def _manifest_chapters(manifest) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in manifest.metadata["summary_estimate_chapters"]:
        code, _, name = entry.partition(" ")
        out[code] = name
    return out


def test_the_manifest_and_the_platform_agree_on_the_chapters(manifest) -> None:
    from app.modules.methodology.templates import _CBS_CHAPTERS

    from_platform = {row["code"]: row["label"] for row in _CBS_CHAPTERS}
    assert _manifest_chapters(manifest) == from_platform


def test_the_shipped_document_and_the_platform_agree_on_the_chapters() -> None:
    from app.modules.methodology.templates import _CBS_CHAPTERS

    document = json.loads((RULE_PACKS / "ru_svodnyy_smetnyy_raschet.json").read_text(encoding="utf-8"))
    from_document = {row["code"]: row["name_en"] for row in document["chapters"]}
    assert from_document == {row["code"]: row["label"] for row in _CBS_CHAPTERS}


def test_there_are_twelve_of_them_numbered_without_a_gap() -> None:
    from app.modules.methodology.templates import _CBS_CHAPTERS

    assert [row["code"] for row in _CBS_CHAPTERS] == [str(n) for n in range(1, 13)]


def test_every_chapter_is_named_in_russian_as_well() -> None:
    """The English label is what the platform seeds; a Russian estimator reads
    the Russian one, and a chapter with only half of the pair is a chapter one
    of the two readers cannot find."""
    document = json.loads((RULE_PACKS / "ru_svodnyy_smetnyy_raschet.json").read_text(encoding="utf-8"))
    for row in document["chapters"]:
        assert row["name_ru"].strip(), f"chapter {row['code']} has no Russian name"
        assert row["name_en"].strip(), f"chapter {row['code']} has no English name"


# ── The norm code, published and compiled ────────────────────────────────


def test_the_documents_code_pattern_is_the_one_the_engine_applies() -> None:
    """A pattern written out for a reader has to be the pattern that runs."""
    from app.core.validation.rules import GESNValidCode

    document = json.loads((RULE_PACKS / "ru_gesn_fer_kody.json").read_text(encoding="utf-8"))
    assert document["code_format"]["regex"] == GESNValidCode._PATTERN.pattern
    for example in document["code_format"]["examples"]:
        assert GESNValidCode._PATTERN.match(example), f"{example} is offered as an example and does not match"


def test_the_manifest_code_example_is_one_the_engine_accepts(manifest) -> None:
    from app.core.validation.rules import GESNValidCode

    assert GESNValidCode._PATTERN.match(manifest.metadata["code_example"])


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
    """A document derived from a norm base and one drawn from a statute are not
    the same kind of claim, and shipping both without saying which is which is
    the part that would mislead."""
    for path in sorted(RULE_PACKS.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document.get("review_status"), f"{path.name} does not state its review status"
        assert document["jurisdiction"] == "RU"
        assert document["standard"] == "gesn"


def test_every_rule_a_document_promises_is_a_rule_the_engine_registers() -> None:
    from app.core.validation.rules import (
        GESNCodeRequired,
        GESNLabourHoursPresent,
        GESNPriceLevelDeclared,
        GESNResourceBreakdown,
        GESNValidCode,
    )

    implemented = {
        rule.rule_id
        for rule in (
            GESNCodeRequired(),
            GESNValidCode(),
            GESNResourceBreakdown(),
            GESNLabourHoursPresent(),
            GESNPriceLevelDeclared(),
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
    from app.core.validation.rules import GESNCodeRequired

    assert manifest.validation_rule_sets == [GESNCodeRequired.standard]


def test_a_russian_project_is_classified_against_the_norm_base() -> None:
    resolved = resolve_standard(None, "RU")
    assert resolved.standard == "gesn"
    assert resolved.matched, "a region that matched must not report itself as a fall-through"
    assert "gesn" in KNOWN_CLASSIFICATION_STANDARDS, (
        "a standard absent from the known list is silently ignored when a project names it explicitly"
    )
    assert CLASSIFICATION_STANDARD_LABELS["gesn"]


def test_the_classification_key_the_rules_read_is_the_standard_they_classify_against() -> None:
    """The rules read ``classification['gesn']``, so the two have to be one name."""
    source = (REPO_ROOT / "backend" / "app" / "core" / "validation" / "rules" / "__init__.py").read_text(
        encoding="utf-8"
    )
    body = source[source.index("def _gesn_code(") : source.index("def _gesn_resources(")]
    assert re.search(r'get\(\s*"gesn"', body), "the Russian rules no longer read the gesn key"


@pytest.mark.parametrize(
    "key",
    [
        "gesn.code_required.fail",
        "gesn.code_required.suggestion",
        "gesn.valid_code.fail",
        "gesn.valid_code.suggestion",
        "gesn.resource_breakdown.fail",
        "gesn.resource_breakdown.suggestion",
        "gesn.labour_hours_present.fail",
        "gesn.labour_hours_present.suggestion",
        "gesn.price_level_declared.fail",
        "gesn.price_level_declared.suggestion",
    ],
)
@pytest.mark.parametrize("locale", ["en", "de", "es", "ru"])
def test_every_message_exists_in_every_validation_locale(key: str, locale: str) -> None:
    """A missing message is not an error anywhere: the bundle prints the key at
    the user and logs a warning nobody reads."""
    assert is_key_present(key, locale), f"{key} is missing from {locale}.json"


# ── The project screens' copies of the registry ──────────────────────────
#
# Four hand-written mirrors of ``CLASSIFICATION_STANDARD_LABELS`` live in the
# frontend: the picker that writes a project's standard, and three separate
# ``standardLabels`` maps that read it back on the project page, in the project
# list and on the dashboard card. None was checked against the registry and all
# four had drifted.
#
# Counting them was the part that went wrong. Fixing the one map this test
# first knew about would have left a project showing its standard by name on
# one screen and by raw identifier on the two beside it, and the test would
# have been green, because a test that knows about one mirror cannot report
# the existence of a second.

LABEL_MIRRORS = (
    FRONTEND / "ProjectDetailPage.tsx",
    FRONTEND / "ProjectsPage.tsx",
    REPO_ROOT / "frontend" / "src" / "features" / "dashboard" / "components" / "CompactProjectCard.tsx",
)


def _picker_values() -> set[str]:
    source = (FRONTEND / "CreateProjectPage.tsx").read_text(encoding="utf-8")
    block = re.search(r"const STANDARD_GROUPS: OptionGroup\[\] = \[(.*?)\n\];", source, re.S)
    assert block is not None, "STANDARD_GROUPS is no longer where this test looks for it"
    return set(re.findall(r"value: '([a-z0-9_]+)'", block.group(1))) - {"__custom__"}


def _label_keys(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    block = re.search(r"const standardLabels: Record<string, string> = \{(.*?)\n\s*\};", source, re.S)
    assert block is not None, f"standardLabels is no longer where this test looks for it in {path.name}"
    return set(re.findall(r"^\s*([a-z0-9_]+):", block.group(1), re.M))


def test_every_standard_the_picker_writes_is_one_the_backend_can_resolve() -> None:
    """The direction that was broken, and broken silently.

    The picker offered ``gbt`` for China. The registry calls that standard
    ``gb50500`` and has no entry under the shorter name, so every Chinese
    project created through this screen stored a value ``resolve_standard``
    could not match and fell through to the default. Nothing errored, nothing
    was logged, and the project simply carried the wrong standard.

    The set to compare against is ``KNOWN_CLASSIFICATION_STANDARDS`` and not
    ``CLASSIFICATION_STANDARD_LABELS``, which is where this test was first
    pointed and where it went green while five options were still broken. The
    two differ on purpose: a standard earns a label so a CostItem encoded
    against it can be named, and it joins the known set only when the product
    renders a section path for it. ``resolve_standard`` consults the second.
    Checking the first is checking a superset, which is to say checking
    nothing about the five that are only in it.
    """
    unknown = _picker_values() - set(KNOWN_CLASSIFICATION_STANDARDS)
    assert not unknown, (
        f"the project picker offers standards resolve_standard does not accept: {sorted(unknown)}. "
        f"A stored value the registry cannot resolve falls into the default without telling anybody."
    )


def test_a_labelled_standard_is_not_thereby_a_resolvable_one() -> None:
    """Pins the distinction the test above depends on.

    If the two sets are ever made equal, the assertion above stops being able
    to fail and nobody would notice, because the failure it guards against is
    invisible at runtime by construction. Should the sets genuinely be merged
    one day, this test is the place that has to be argued with first.
    """
    labelled_only = set(CLASSIFICATION_STANDARD_LABELS) - set(KNOWN_CLASSIFICATION_STANDARDS)
    assert labelled_only, (
        "every labelled standard is now resolvable, so the picker check above compares against a set "
        "that can no longer be wrong. Either that merge was deliberate and this test should go, or a "
        "standard was added to the country table that does not render."
    )


@pytest.mark.parametrize("mirror", LABEL_MIRRORS, ids=lambda p: p.stem)
def test_every_standard_the_picker_writes_can_be_read_back_with_a_name(mirror: Path) -> None:
    """The picker and each label map are two halves of one round trip.

    Every one of these maps falls back to printing the stored identifier, so a
    standard it has never heard of costs no exception and leaves no blank: the
    user is simply shown ``gesn`` where the screen next to it says GESN / FER.
    That is why three copies could sit at three entries each while the picker
    grew to eighteen.
    """
    missing = _picker_values() - _label_keys(mirror)
    assert not missing, (
        f"the project picker can write {sorted(missing)} and {mirror.name} has no label for them, "
        f"so those projects show a raw identifier on that screen and a name on the others."
    )


def test_the_label_mirrors_agree_with_each_other() -> None:
    """Three copies of one map is a drift problem, and the drift that matters
    is between the copies rather than against the picker: two screens naming
    the same standard differently is the version a user actually notices."""
    keys = {path.name: _label_keys(path) for path in LABEL_MIRRORS}
    reference = keys[LABEL_MIRRORS[0].name]
    disagree = {name: sorted(k ^ reference) for name, k in keys.items() if k != reference}
    assert not disagree, f"the label maps have drifted apart: {disagree}"


def test_the_standards_a_pack_ships_are_offered_to_the_user() -> None:
    """A country pack that classifies against a standard nobody can select is
    a resolver behind a gate that never opens. Russia and Hungary are checked
    by name because their packs are the two that put them there."""
    offered = _picker_values()
    for standard in ("gesn", "tetelrend"):
        assert standard in offered, f"{standard} is shipped by a country pack and cannot be picked on a project"
