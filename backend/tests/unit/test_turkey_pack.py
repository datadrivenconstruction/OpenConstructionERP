# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Turkish pack: every name it declares resolves, and it is written in Turkish.

Two things went wrong in this pack before, and both were silent.

It was written in ASCII transliteration from end to end ("Hosgeldiniz",
"Bayindirlik Bakanligi"), which a Turkish reader takes for a broken product,
and nothing checked the spelling because no test knew what Turkish looks like.

And it named things by slug that nobody resolved: a cost base that turned out
to be the general market catalogue with no poz numbers in it, and eleven
planned rule ids of which the engine had two. A slug that reads right is not
a thing that exists, so each one is resolved here through the code that
resolves it in the product, in a clean interpreter where the answer depends
on what this test session imported.

The copies of one fact (the chapters of the unit-price book, the rule ids, the
KDV rates, the code pattern) are compared with each other rather than trusted.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

from app.core.classification_registry import (
    CLASSIFICATION_STANDARD_LABELS,
    KNOWN_CLASSIFICATION_STANDARDS,
    resolve_standard,
)
from app.core.validation import rules
from app.core.validation.messages import is_key_present

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "backend"
PACK_DIR = REPO_ROOT / "packs" / "turkey-tr"
PACKAGE_DIR = PACK_DIR / "src" / "openconstructionerp_turkey_tr"
RULE_PACKS = PACKAGE_DIR / "rule_packs"
TAX_SEED = BACKEND / "app" / "modules" / "i18n_foundation" / "seed_data" / "tax_configurations.json"

#: Every text file the pack ships. The spelling and encoding checks walk this
#: list, so a file added to the pack is covered without anyone remembering to.
PACK_TEXT_FILES = sorted(
    path
    for path in PACK_DIR.rglob("*")
    if path.is_file()
    and path.suffix in {".py", ".json", ".yaml", ".yml", ".md", ".toml"}
    and "__pycache__" not in path.parts
    and ".egg-info" not in str(path)
)

BIRIMFIYAT_RULES = (
    rules.BirimFiyatCodeRequired,
    rules.BirimFiyatValidPoz,
    rules.BirimFiyatChapterRecognised,
    rules.BirimFiyatUnitRecognised,
    rules.BirimFiyatPozUnitConsistent,
    rules.BirimFiyatPozRateConsistent,
    rules.BirimFiyatOwnItemAnalysed,
    rules.BirimFiyatProfitOverheadOnce,
    rules.BirimFiyatUnitMatchesPoz,
    rules.BirimFiyatRateAgainstPublished,
)

#: What the unit-price document still lists as planned. Pinned by name, so an
#: id cannot leave or join the list without this file being read.
STILL_PLANNED = {
    "birimfiyat.profit_included_in_book_rate",
    "birimfiyat.edition_year_current",
    "birimfiyat.price_difference_documented",
}


@pytest.fixture(scope="module")
def manifest():
    """The manifest object the pack's own module builds."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_turkey_manifest_under_test", PACKAGE_DIR / "manifest.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MANIFEST


@pytest.fixture(scope="module")
def onboarding() -> dict:
    return yaml.safe_load((PACKAGE_DIR / "onboarding.yaml").read_text(encoding="utf-8"))


def _documents() -> dict[str, dict]:
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(RULE_PACKS.glob("*.json"))}


# ── The manifest ─────────────────────────────────────────────────────────────


def test_the_manifest_loads_and_describes_a_turkish_country_pack(manifest) -> None:
    assert manifest.slug == "turkey-tr"
    assert manifest.type == "country"
    assert manifest.metadata["country"] == "TR"
    assert manifest.metadata["country_name_tr"] == "Türkiye"
    assert manifest.default_currency == "TRY"
    assert manifest.default_locale == "tr"
    assert manifest.default_methodology == "turkey"


def test_the_pack_hides_and_preselects_no_module(manifest) -> None:
    """A country pack shows everything; a module preset belongs to an industry pack."""
    assert manifest.default_modules == []
    assert manifest.hidden_modules == []


def test_the_review_status_names_both_reviewers_it_is_waiting_for(manifest) -> None:
    status = manifest.metadata["review_status"]
    assert "ending review" in status
    assert "quantity surveyor" in status
    assert "accountant" in status


def test_the_three_copies_of_the_version_agree(manifest) -> None:
    pyproject = (PACK_DIR / "pyproject.toml").read_text(encoding="utf-8")
    package = (PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1) == manifest.pack_version
    assert re.search(r'^__version__ = "([^"]+)"', package, re.M).group(1) == manifest.pack_version
    assert tuple(int(part) for part in manifest.pack_version.split(".")) >= (0, 2, 0)


def test_the_pack_merges_no_locale_file_over_the_shipped_one(manifest) -> None:
    assert manifest.additional_locales == {}
    assert (REPO_ROOT / "frontend" / "src" / "app" / "locales" / "tr.ts").is_file()


def test_the_declared_methodology_is_a_template_that_exists(manifest) -> None:
    from app.modules.methodology import templates

    template = templates.TEMPLATES_BY_SLUG[manifest.default_methodology]
    assert template["country_code"] == "TR"
    assert template["currency"] == "TRY"
    assert template["decimals"] == manifest.metadata["currency_decimals"] == 2
    assert str(template["vat_rate"]) == str(manifest.metadata["vat_standard_rate"])


def test_the_method_a_turkish_bill_gets_is_the_25_percent_then_kdv(manifest) -> None:
    """The template's own 12 and 8 are a fallback the regional stack replaces."""
    from app.modules.methodology import templates

    steps = templates.TEMPLATES_BY_SLUG["turkey"]["cascade_steps"]
    assert [Decimal(str(step.get("rate") or step.get("percentage"))) for step in steps] == [
        Decimal(manifest.metadata["contractor_profit_and_overhead_percent"]),
        Decimal(manifest.metadata["vat_standard_rate"]),
    ]


def test_the_demo_the_pack_installs_is_registered_and_turkish(manifest) -> None:
    from app.core.demo_projects import DEMO_TEMPLATES, PACK_DEMO_PROJECT

    assert manifest.demo_template_ids == ["mixed-use-istanbul"]
    assert PACK_DEMO_PROJECT["turkey-tr"] == "mixed-use-istanbul"
    template = DEMO_TEMPLATES["mixed-use-istanbul"]
    assert template.currency == "TRY"
    assert template.classification_standard == "birimfiyat"


# ── The cost base ────────────────────────────────────────────────────────────


def test_the_declared_cost_base_is_the_one_whose_items_carry_poz_numbers(manifest) -> None:
    """Asserted on what the slug resolves to, not on how the slug is spelled.

    ``cwicr-tr-istanbul`` reads like a Turkish base and resolves to
    ``TR_ISTANBUL``, a general market catalogue with codes of its own. A pack
    whose every rule reads a poz number has to load the base built from the
    official unit-price lists, which is ``TR_NATIONAL``.
    """
    from app.core.partner_pack.full_install import resolve_cwicr_db_id
    from app.modules.costs import base_registry

    resolved = [resolve_cwicr_db_id(slug) for slug in manifest.cwicr_regions]
    assert resolved == ["TR_NATIONAL"]
    family = base_registry.family_by_region("TR_NATIONAL")
    assert family is not None
    assert "birim fiyat" in f"{family.name} {family.description}".casefold()
    variant = base_registry.variant_by_region("TR_NATIONAL")
    assert variant is not None
    assert variant.currency == manifest.default_currency
    assert variant.lang_code == manifest.default_locale


def test_the_slug_the_pack_used_to_declare_is_a_different_base() -> None:
    """The control for the test above: the two slugs do not name one base."""
    from app.core.partner_pack.full_install import resolve_cwicr_db_id

    assert resolve_cwicr_db_id("cwicr-tr-istanbul") == "TR_ISTANBUL"
    assert resolve_cwicr_db_id("cwicr-tr-national") == "TR_NATIONAL"


# ── The rule set, in a clean interpreter ─────────────────────────────────────

_REGISTRY_PROBE = """
import json, warnings
warnings.filterwarnings("ignore")
from app.core.validation.rules import register_builtin_rules
from app.core.validation.engine import rule_registry
register_builtin_rules()
print(json.dumps({
    "sets": sorted(rule_registry.list_rule_sets()),
    "ids": sorted(r["rule_id"] for r in rule_registry.list_rules() if r["rule_id"].startswith("birimfiyat.")),
}))
"""


@lru_cache(maxsize=1)
def _registry() -> dict[str, list[str]]:
    """What a fresh interpreter registers, not what this session happened to import."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _REGISTRY_PROBE],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"the registry probe failed: {result.stderr[-2000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_declared_rule_set_is_one_the_engine_registers(manifest) -> None:
    """A classification name standing where a rule-set name belongs is logged and skipped."""
    assert manifest.validation_rule_sets == ["birimfiyat"]
    assert set(manifest.validation_rule_sets) <= set(_registry()["sets"])


def test_the_declared_rule_set_is_the_one_the_rules_carry(manifest) -> None:
    assert {rule.standard for rule in BIRIMFIYAT_RULES} == set(manifest.validation_rule_sets)


def test_the_engine_registers_exactly_the_rules_this_file_knows() -> None:
    assert _registry()["ids"] == sorted(rule.rule_id for rule in BIRIMFIYAT_RULES)


def test_a_turkish_project_is_classified_by_poz_number(manifest) -> None:
    resolved = resolve_standard(None, "TR")
    assert resolved.standard == manifest.metadata["classification_standard"] == "birimfiyat"
    assert resolved.matched, "a region that matched must not report itself as a fall-through"
    assert "birimfiyat" in KNOWN_CLASSIFICATION_STANDARDS
    assert CLASSIFICATION_STANDARD_LABELS["birimfiyat"]


def test_the_classification_key_the_rules_read_is_the_standard_they_classify_against() -> None:
    source = (BACKEND / "app" / "core" / "validation" / "rules" / "__init__.py").read_text(encoding="utf-8")
    body = source[source.index("def _tr_poz(") : source.index("class BirimFiyatChapterRecognised")]
    assert '_national_code(pos, "birimfiyat")' in body


# ── The reference documents ──────────────────────────────────────────────────


def test_every_declared_document_is_shipped_and_every_shipped_one_declared(manifest) -> None:
    assert set(manifest.validation_rule_packs) == set(_documents())
    assert len(manifest.validation_rule_packs) == len(set(manifest.validation_rule_packs))


def test_each_document_names_itself_states_its_review_and_its_jurisdiction() -> None:
    for stem, document in _documents().items():
        assert document["rule_pack_id"] == stem
        assert document["jurisdiction"] == "TR", stem
        assert document.get("review_status"), f"{stem} does not state its review status"
        assert document.get("name_tr"), f"{stem} has no Turkish name"


def test_every_rule_a_document_promises_is_a_rule_the_engine_registers() -> None:
    promised: set[str] = set()
    for document in _documents().values():
        promised.update(document.get("enables_rule_ids", []))
    implemented = set(_registry()["ids"])
    assert promised <= implemented, f"documents promise rules that do not exist: {sorted(promised - implemented)}"
    assert promised == implemented, f"rules exist that no document mentions: {sorted(implemented - promised)}"


def test_no_planned_rule_id_is_one_the_engine_already_has() -> None:
    implemented = set(_registry()["ids"])
    for stem, document in _documents().items():
        planned = set(document.get("planned_not_built_rule_ids", []))
        assert not planned & implemented, f"{stem} lists as planned what is built: {sorted(planned & implemented)}"
        assert not planned & set(document.get("enables_rule_ids", [])), stem
        if planned:
            assert "planned, not built" in document.get("planned_not_built_note", "").lower(), stem


def test_the_unit_price_document_plans_exactly_the_three_checks_nothing_can_make_yet() -> None:
    document = _documents()["bayindirlik_unit_prices"]
    assert set(document["planned_not_built_rule_ids"]) == STILL_PLANNED
    assert len(document["planned_not_built_rule_ids"]) == len(STILL_PLANNED)


def test_the_two_price_book_checks_are_promised_because_they_are_built() -> None:
    from app.core.validation.poz_catalogue import POZ_CATALOGUE_RULE_IDS

    document = _documents()["bayindirlik_unit_prices"]
    assert set(document["enables_rule_ids"]) >= POZ_CATALOGUE_RULE_IDS
    assert set(_registry()["ids"]) >= POZ_CATALOGUE_RULE_IDS
    assert {rules.BirimFiyatUnitMatchesPoz.rule_id, rules.BirimFiyatRateAgainstPublished.rule_id} == set(
        POZ_CATALOGUE_RULE_IDS
    )


def test_the_published_price_thresholds_ship_unset_and_unconfirmed() -> None:
    """No tolerance is known, so none is shipped: the document states null, not a number."""
    from app.core.validation.poz_catalogue import PRICE_COMPARISON_BLOCK, tolerance_from_document

    document = _documents()["bayindirlik_unit_prices"]
    block = document[PRICE_COMPARISON_BLOCK]
    assert block["applies_to_rule_id"] == rules.BirimFiyatRateAgainstPublished.rule_id
    assert block["review_status"] == "unconfirmed"
    assert "warn_above_percent" in block
    assert "warn_below_percent" in block
    assert block["warn_above_percent"] is None
    assert block["warn_below_percent"] is None
    tolerance = tolerance_from_document(document)
    assert tolerance.warn_above_percent is None
    assert tolerance.warn_below_percent is None
    assert tolerance.review_status == "unconfirmed"


def test_the_engine_reads_the_thresholds_from_the_document_the_pack_ships() -> None:
    """The path the product takes to the file, not a second copy of its contents."""
    from app.core.validation.pack_coverage import _discover_pack_files
    from app.core.validation.poz_catalogue import TR_POZ_RULE_PACK

    found = [file.path for file in _discover_pack_files() if file.path.stem == TR_POZ_RULE_PACK]
    assert found, "the pack's unit-price document is not discoverable, so a threshold set in it would be ignored"
    assert found[0].resolve() == (RULE_PACKS / f"{TR_POZ_RULE_PACK}.json").resolve()


def test_only_the_unit_price_document_runs_rules() -> None:
    """The other four are reference documents and say so by enabling nothing."""
    enabling = {stem for stem, document in _documents().items() if document.get("enables_rule_ids")}
    assert enabling == {"bayindirlik_unit_prices"}


def test_the_manifest_the_document_and_the_engine_agree_on_the_chapters(manifest) -> None:
    from_manifest = dict(entry.split(" ", 1) for entry in manifest.metadata["poz_chapters"])
    document = _documents()["bayindirlik_unit_prices"]
    from_document = {row["code"]: row["name_tr"] for row in document["chapters"]}
    assert from_manifest == dict(rules._TR_MINISTRY_CHAPTERS)
    assert from_document == dict(rules._TR_MINISTRY_CHAPTERS)


def test_the_mechanical_and_electrical_chapters_are_25_and_35() -> None:
    assert rules._TR_MINISTRY_CHAPTERS["25"] == "Mekanik tesisat"
    assert rules._TR_MINISTRY_CHAPTERS["35"] == "Elektrik tesisatı"
    assert not set(rules._TR_MINISTRY_CHAPTERS) & set(rules._TR_OTHER_PUBLISHER_CHAPTERS)


def test_the_documents_code_pattern_is_the_one_the_engine_applies() -> None:
    document = _documents()["bayindirlik_unit_prices"]
    assert document["code_format"]["regex"] == rules.BirimFiyatValidPoz._CURRENT_PATTERN.pattern
    for example in document["code_format"]["examples"]:
        assert rules.BirimFiyatValidPoz.poz_is_well_formed(example), example
        assert rules.BirimFiyatChapterRecognised.chapter_of(example) in rules._TR_MINISTRY_CHAPTERS, example


def test_every_unit_the_document_lists_is_one_the_engine_accepts() -> None:
    for unit in _documents()["bayindirlik_unit_prices"]["units"]["accepted"]:
        assert rules._tr_unit(unit)[1], unit


def test_the_25_percent_is_one_number_in_four_places(manifest) -> None:
    from app.modules.boq.markup_templates import DEFAULT_MARKUP_TEMPLATES

    document = _documents()["bayindirlik_unit_prices"]
    stack = DEFAULT_MARKUP_TEMPLATES["TR"]
    combined = [line for line in stack if line["category"] in {"overhead", "profit"}]
    assert len(combined) == 1, "the Turkish stack carries the 25 percent on one line"
    assert (
        Decimal(str(combined[0]["percentage"]))
        == Decimal(document["profit_and_general_expenses"]["percent"])
        == Decimal(manifest.metadata["contractor_profit_and_overhead_percent"])
        == rules._TR_PROFIT_AND_GENERAL_EXPENSES_PERCENT
    )


@pytest.mark.parametrize("locale", ["en", "tr"])
@pytest.mark.parametrize("rule", BIRIMFIYAT_RULES, ids=lambda r: r.rule_id)
def test_every_message_exists_in_english_and_in_turkish(rule, locale: str) -> None:
    for suffix in ("fail", "suggestion"):
        assert is_key_present(f"{rule.rule_id}.{suffix}", locale), f"{rule.rule_id}.{suffix} missing from {locale}"


# ── KDV ──────────────────────────────────────────────────────────────────────

#: Every tier the pack offers is in the tax seed since the list (I) row
#: shipped on 2026-10-10. Kept as an empty set rather than deleted, so a tier
#: offered without a seeded row has to be written down here to pass.
_KDV_TIERS_NOT_YET_SEEDED: set[Decimal] = set()


def _seeded_kdv_rates() -> set[Decimal]:
    rows = json.loads(TAX_SEED.read_text(encoding="utf-8"))
    return {
        Decimal(row["rate_pct"])
        for row in rows
        if row["country_code"] == "TR" and row["tax_type"] == "vat" and row["effective_to"] is None
    }


def _offered_kdv_rates(onboarding: dict) -> set[Decimal]:
    field = next(
        field for step in onboarding["steps"] for field in step.get("fields", []) if field["key"] == "default_kdv_rate"
    )
    rates = set()
    for option in field["options"]:
        match = re.match(r"^(\d+(?:\.\d+)?)%", option)
        assert match, f"the KDV option {option!r} does not start with its rate"
        rates.add(Decimal(match.group(1)))
    assert field["default"] in field["options"]
    return rates


def test_the_kdv_rates_offered_are_the_three_the_law_has(manifest, onboarding: dict) -> None:
    assert _offered_kdv_rates(onboarding) == {Decimal(rate) for rate in manifest.metadata["vat_rates"]}
    assert _offered_kdv_rates(onboarding) == {Decimal("20"), Decimal("10"), Decimal("1")}


def test_the_kdv_rates_offered_are_the_seeded_ones_plus_the_recorded_gap(onboarding: dict) -> None:
    seeded = _seeded_kdv_rates()
    assert seeded, "the tax seed carries no open Turkish VAT row"
    assert _offered_kdv_rates(onboarding) - seeded == _KDV_TIERS_NOT_YET_SEEDED
    assert seeded <= _offered_kdv_rates(onboarding)


def test_the_standard_rate_is_one_number_everywhere(manifest, onboarding: dict) -> None:
    from app.core.tax import get_vat_rate
    from app.modules.boq.markup_templates import DEFAULT_MARKUP_TEMPLATES

    standard = Decimal(manifest.metadata["vat_standard_rate"])
    rows = json.loads(TAX_SEED.read_text(encoding="utf-8"))
    default_rows = [r for r in rows if r["country_code"] == "TR" and r["is_default"] and r["effective_to"] is None]
    assert [Decimal(r["rate_pct"]) for r in default_rows] == [standard]
    tax_lines = [line for line in DEFAULT_MARKUP_TEMPLATES["TR"] if line["category"] == "tax"]
    assert [Decimal(str(line["percentage"])) for line in tax_lines] == [standard]
    assert get_vat_rate("TR") * 100 == standard
    assert get_vat_rate("TR", "reduced") * 100 == Decimal(manifest.metadata["vat_reduced_rate"])
    field = next(f for s in onboarding["steps"] for f in s.get("fields", []) if f["key"] == "default_kdv_rate")
    assert field["default"].startswith(f"{standard}%")
    assert manifest.default_tax_template.endswith(f"_{standard}")


# ── The onboarding script ────────────────────────────────────────────────────


def test_the_onboarding_script_parses_and_speaks_turkish(manifest, onboarding: dict) -> None:
    assert manifest.onboarding_script_path == "onboarding.yaml"
    assert onboarding["locale"] == manifest.default_locale
    assert "hoş geldiniz" in onboarding["title_tr"]
    ids = [step["id"] for step in onboarding["steps"]]
    assert len(ids) == len(set(ids))
    assert ids[-1] == "review"
    keys = [field["key"] for step in onboarding["steps"] for field in step.get("fields", [])]
    assert len(keys) == len(set(keys)), "a field key is used twice"


def _apply(onboarding: dict) -> list[dict]:
    return onboarding["steps"][-1]["action"]["apply"]


def test_every_apply_action_names_something_that_exists(manifest, onboarding: dict) -> None:
    known_verbs = {
        "set_default_currency",
        "set_tax_template",
        "preload_cwicr_regions",
        "enable_rule_packs",
        "conditionally_enable_rule_pack",
    }
    field_keys = {field["key"] for step in onboarding["steps"] for field in step.get("fields", [])}
    enabled: list[str] = []
    for action in _apply(onboarding):
        ((verb, value),) = action.items()
        assert verb in known_verbs, verb
        if verb == "set_default_currency":
            assert value == manifest.default_currency
        elif verb == "set_tax_template":
            assert value == manifest.default_tax_template
        elif verb == "preload_cwicr_regions":
            assert value == list(manifest.cwicr_regions)
        elif verb == "enable_rule_packs":
            enabled.extend(value)
        else:
            enabled.append(value["rule_pack"])
            condition_field = value["when"].split(" ", 1)[0]
            assert condition_field in field_keys, f"{value['when']!r} reads a field the script does not ask for"
    assert sorted(enabled) == sorted(manifest.validation_rule_packs), "every document is switched on exactly once"


def test_the_public_and_structural_documents_are_switched_on_only_on_request(onboarding: dict) -> None:
    """A private installation contractor does not get procurement or seismic references by default."""
    conditional = {
        action["conditionally_enable_rule_pack"]["rule_pack"]
        for action in _apply(onboarding)
        if "conditionally_enable_rule_pack" in action
    }
    assert conditional == {"kamu_ihale", "tbdy_2018"}
    defaults = {field["key"]: field.get("default") for step in onboarding["steps"] for field in step.get("fields", [])}
    assert defaults["works_in_public_procurement"] is False
    assert defaults["structural_scope"] is False


# ── Written in Turkish ───────────────────────────────────────────────────────

#: Turkish words written without their letters, as the pack carried them. Each
#: is a spelling that cannot occur in English prose or in an identifier of this
#: pack, so a hit is a transliteration and not a coincidence. Rule ids keep
#: their ASCII form on purpose (``tbdy.zemin_sinifi_classified``) and are
#: matched as whole words here, which an id joined by underscores never is.
_TRANSLITERATIONS = [
    "Hosgeldiniz",
    "Hos geldiniz",
    "Turkiye",
    "Bayindirlik",
    "Bakanligi",
    "Sehircilik",
    "Iklim Degisikligi",
    "Yapi Denetim",
    "Yonetmeligi",
    "Yonetmelik",
    "Insaat",
    "Elektrik Tesisati",
    "Sartname",
    "Kamu Ihale",
    "Sozlesme",
    "Yuklenici",
    "Muteahhit",
    "Katma Deger",
    "Calisma",
    "Gozden gecir",
    "Iller Bankasi",
    "Istanbul",
    "Izmir",
    "Standartlari",
    "Enstitusu",
    "Turkce",
    "sinifi",
    "bolgesi",
    "yaklasik",
    "olustur",
]

_WORD = r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])"

#: Lines that carry an ASCII spelling on purpose: a slug, a package keyword or
#: an identifier, none of which a reader sees as prose.
_ASCII_BY_DESIGN = re.compile(r"mixed-use-istanbul|cwicr-tr-istanbul|TR_ISTANBUL|^\s*\"[a-z0-9-]+\",\s*$")


def test_the_deny_list_itself_is_ascii_and_the_right_spellings_are_not() -> None:
    """A deny-list holding a correctly spelled word would forbid Turkish."""
    assert all(word.isascii() for word in _TRANSLITERATIONS)
    for right in ("Türkiye", "Bayındırlık", "Şehircilik", "İnşaat", "Yüklenici", "İstanbul"):
        assert not any(re.search(_WORD.format(re.escape(word)), right) for word in _TRANSLITERATIONS), right


@pytest.mark.parametrize("path", PACK_TEXT_FILES, ids=lambda p: p.relative_to(PACK_DIR).as_posix())
def test_no_turkish_word_is_written_without_its_letters(path: Path) -> None:
    hits: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if _ASCII_BY_DESIGN.search(line):
            continue
        for word in _TRANSLITERATIONS:
            if re.search(_WORD.format(re.escape(word)), line):
                hits.append(f"{path.name}:{number}: {word}")
    assert hits == [], "Turkish written in ASCII transliteration: " + "; ".join(hits)


def test_the_spelling_check_reaches_every_kind_of_file_the_pack_ships() -> None:
    names = {path.name for path in PACK_TEXT_FILES}
    assert {"manifest.py", "onboarding.yaml", "README.md", "pyproject.toml"} <= names
    assert {f"{stem}.json" for stem in _documents()} <= names
    assert len(PACK_TEXT_FILES) >= 10


@pytest.mark.parametrize("path", PACK_TEXT_FILES, ids=lambda p: p.relative_to(PACK_DIR).as_posix())
def test_every_file_is_utf8_without_a_byte_order_mark_or_a_long_dash(path: Path) -> None:
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "byte order mark"
    text = raw.decode("utf-8")
    assert chr(0x2014) not in text, "em dash"
    assert chr(0x2013) not in text, "en dash"
    assert chr(0xFFFD) not in text, "a replacement character: the file was decoded wrongly once"


def test_the_files_a_turkish_reader_sees_actually_contain_turkish_letters() -> None:
    """The control for the deny-list: a pack with every Turkish word removed would pass it."""
    turkish = set("çğıöşüÇĞİÖŞÜ")
    for name in ("manifest.py", "onboarding.yaml", "README.md"):
        path = next(p for p in PACK_TEXT_FILES if p.name == name)
        assert turkish & set(path.read_text(encoding="utf-8")), f"{name} has no Turkish letter in it"
    for stem, document in _documents().items():
        assert turkish & set(document["name_tr"] + document["description"]), stem


def test_the_readme_names_the_ministry_and_the_board_that_publish_the_book() -> None:
    readme = (PACK_DIR / "README.md").read_text(encoding="utf-8")
    flat = " ".join(readme.split())
    assert "Çevre, Şehircilik ve İklim Değişikliği Bakanlığı" in flat
    assert "Yüksek Fen Kurulu Başkanlığı" in flat
    assert "No engine rule set is active" not in flat
    assert "pending review by a Turkish quantity surveyor and a Turkish accountant" in flat
    assert "TR_NATIONAL" in flat
