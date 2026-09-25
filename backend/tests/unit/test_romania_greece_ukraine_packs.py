# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Three country packs, Romania, Greece and Ukraine, and what each one promises.

A country pack is a set of claims written in several places at once: the
manifest names a currency and a method, the methodology catalogue carries a
currency and a tax rate of its own, the tax seed says which rate is in force,
the demo templates carry their own markups and an address the installer turns
into a country code, and the rule set the pack asks for has to exist and has to
say something about the pack's own demo. Every one of those copies can drift
without anything going red, so each pair is compared here.

The test the packs were asked for is the first group: a project in the country
is priced in that country's currency and charged that country's standard VAT.
It is asserted along the paths the product really takes rather than against the
manifest alone, which would compare the manifest with itself:

* the demo installer derives ``Project.country_code`` from the template's
  address through ``_country_code_for``, and an unmapped country falls back to
  ``"DE"``, which would put a Bucharest project under German rules;
* a bill with no rate of its own is charged the rate the shipped tax seed
  resolves for the project's country, and only falls back to the region's
  markup line when the seed has no row. Greece had no row, so its bills were
  priced off the region table; the seed now carries the Greek rates.

No database: the seed file, the manifests and the templates are all read from
disk, and the engine runs in process.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.core.classification_registry import resolve_standard
from app.core.demo_packs import PACK_TEMPLATES
from app.core.demo_projects import (
    _COUNTRY_ISO2,
    _CURRENCY_SYMBOL,
    _PACK_DEMO_TYPE,
    PACK_DEMO_PROJECT,
    DemoTemplate,
    _country_code_for,
)
from app.core.partner_pack.full_install import resolve_cwicr_db_id
from app.core.validation.engine import validation_engine
from app.core.validation.messages import is_key_present
from app.core.validation.rules import register_builtin_rules
from app.modules.boq.markup_templates import region_key_for_country, resolve_region_lines
from app.modules.contracts.compliance_packs import resolve_pack, resolve_rule_sets
from app.modules.i18n_foundation.seed import load_tax_seed_rows
from app.modules.i18n_foundation.tax_rules import resolve, row_from_mapping
from app.modules.methodology.templates import TEMPLATES_BY_SLUG

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKS = REPO_ROOT / "packs"

#: A date inside every current rate's window.
TODAY = "2026-09-25"

#: slug -> what the pack has to deliver, written from the sources cited in
#: each pack's README rather than read back out of the pack.
EXPECTED: dict[str, dict[str, Any]] = {
    "romania-ro": {
        "package": "openconstructionerp_romania_ro",
        "country": "RO",
        "country_name": "Romania",
        "currency": "RON",
        "locale": "ro",
        "vat": "21",
        "methodology": "romania",
        "rule_set": "romania",
        "classification_key": "deviz",
        "compliance_pack": "ro_compliance",
        "demos": ("residential-cluj", "office-bucharest"),
    },
    "greece-gr": {
        "package": "openconstructionerp_greece_gr",
        "country": "GR",
        "country_name": "Greece",
        "currency": "EUR",
        "locale": "el",
        "vat": "24",
        "methodology": "greece",
        "rule_set": "greece",
        "classification_key": "net",
        "compliance_pack": "gr_compliance",
        "demos": ("residential-athens", "school-thessaloniki"),
    },
    "ukraine-ua": {
        "package": "openconstructionerp_ukraine_ua",
        "country": "UA",
        "country_name": "Ukraine",
        "currency": "UAH",
        "locale": "uk",
        "vat": "20",
        "methodology": "ukraine",
        "rule_set": "ukraine",
        "classification_key": "zkr",
        "compliance_pack": "ua_compliance",
        "demos": ("residential-lviv", "school-kyiv"),
    },
}

SLUGS = sorted(EXPECTED)


def _manifest(slug: str) -> Any:
    """The manifest the pack's own module builds, loaded the way the tests load the others."""
    path = PACKS / slug / "src" / EXPECTED[slug]["package"] / "manifest.py"
    spec = importlib.util.spec_from_file_location(f"_manifest_{slug.replace('-', '_')}", path)
    assert spec is not None and spec.loader is not None, f"{path} does not load"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MANIFEST


def _seed_rows() -> list:
    return [row_from_mapping(r) for r in load_tax_seed_rows()]


def _template(demo_id: str) -> DemoTemplate:
    found = [t for t in PACK_TEMPLATES if t.demo_id == demo_id]
    assert found, f"demo template {demo_id} is not loaded by app.core.demo_packs"
    return found[0]


def _positions(template: DemoTemplate) -> list[dict[str, Any]]:
    """The template's bill as the engine receives it: sections as parents, lines as leaves."""
    positions: list[dict[str, Any]] = []
    for ordinal, title, classification, items in template.sections:
        section_id = str(uuid.uuid4())
        positions.append(
            {
                "id": section_id,
                "ordinal": ordinal,
                "description": title,
                "type": "section",
                "classification": dict(classification),
            }
        )
        for item_ordinal, description, unit, quantity, rate, cls in items:
            positions.append(
                {
                    "id": str(uuid.uuid4()),
                    "parent_id": section_id,
                    "ordinal": item_ordinal,
                    "description": description,
                    "unit": unit,
                    "quantity": quantity,
                    "unit_rate": rate,
                    "total": quantity * rate,
                    "classification": dict(cls),
                }
            )
    return positions


def _failures(rule_set: str, positions: list[dict[str, Any]], *, errors_only: bool = False) -> list[tuple[str, str]]:
    """``(rule_id, message)`` for every result of one rule set that did not pass."""
    register_builtin_rules()

    async def _run() -> Any:
        return await validation_engine.validate(
            data={"positions": positions},
            rule_sets=[rule_set],
            target_type="boq",
            target_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            metadata={"locale": "en"},
        )

    report = asyncio.run(_run())
    assert not report.unsupported_rule_sets, f"the engine does not know {report.unsupported_rule_sets}"
    return sorted(
        (r.rule_id, r.message) for r in report.results if not r.passed and (not errors_only or r.severity == "error")
    )


# ── A project in the country: currency and VAT ───────────────────────────


@pytest.mark.parametrize("slug", SLUGS)
def test_the_pack_names_its_countrys_currency_locale_and_method(slug: str) -> None:
    want = EXPECTED[slug]
    manifest = _manifest(slug)
    assert manifest.slug == slug
    assert manifest.pack_type == "country"
    assert manifest.metadata["country"] == want["country"]
    assert manifest.default_currency == want["currency"]
    assert manifest.default_locale == want["locale"]
    assert manifest.default_methodology == want["methodology"]
    assert want["rule_set"] in manifest.validation_rule_sets
    assert manifest.metadata["vat_standard_rate"] == int(want["vat"])
    assert tuple(manifest.demo_template_ids) == want["demos"]


@pytest.mark.parametrize("slug", SLUGS)
def test_the_methodology_the_pack_names_prices_in_the_same_currency_and_rate(slug: str) -> None:
    """The methodology carries its own currency and VAT, and drives the cascade."""
    want = EXPECTED[slug]
    template = TEMPLATES_BY_SLUG.get(want["methodology"])
    assert template is not None, f"methodology {want['methodology']!r} is not in the catalogue"
    assert template["country_code"] == want["country"]
    assert template["currency"] == want["currency"]
    assert str(template["vat_rate"]) == want["vat"]


@pytest.mark.parametrize("slug", SLUGS)
def test_the_tax_seed_resolves_the_countrys_standard_rate(slug: str) -> None:
    """What a bill with no rate of its own is charged, straight from the shipped seed."""
    want = EXPECTED[slug]
    resolution = resolve(_seed_rows(), want["country"], None, TODAY)
    assert resolution.resolved, f"{want['country']}: {resolution.status} - {resolution.reason}"
    assert resolution.combined_rate_pct == want["vat"]


@pytest.mark.parametrize("slug", SLUGS)
def test_a_new_bill_in_the_country_is_charged_the_seeded_rate(slug: str) -> None:
    """The bill path: the country's region stack with the seeded rate swapped in."""
    want = EXPECTED[slug]
    seeded = resolve(_seed_rows(), want["country"], None, TODAY).combined_rate_pct
    lines = resolve_region_lines(region_key_for_country(want["country"]), vat_rate=seeded)
    tax = [line for line in lines if line["category"] == "tax"]
    assert len(tax) == 1, f"{want['country']} bill carries {len(tax)} tax lines"
    assert tax[0]["percentage"] == want["vat"]
    assert tax[0]["vat_override"] is True, "the rate came from the region table, not from the seed"


def test_romania_before_the_august_2025_reform_still_resolves_to_19() -> None:
    """Negative control: the dated window is intact, the pack did not rewrite history."""
    assert resolve(_seed_rows(), "RO", None, "2025-07-31").combined_rate_pct == "19"


def test_greece_carries_its_reduced_rates_without_answering_with_them() -> None:
    rows = [r for r in _seed_rows() if r.country_code == "GR"]
    rates = sorted((r.tax_code, r.rate_pct, r.is_default) for r in rows)
    assert rates == [("FPA", "24.0", True), ("FPA_RED", "13.0", False), ("FPA_SRED", "6.0", False)]


@pytest.mark.parametrize("slug", SLUGS)
@pytest.mark.parametrize("index", [0, 1])
def test_the_demo_project_lands_in_the_country_in_its_currency_at_its_rate(slug: str, index: int) -> None:
    """The demo installer's own derivation, not the manifest's word for it."""
    want = EXPECTED[slug]
    template = _template(want["demos"][index])
    assert _COUNTRY_ISO2.get(want["country_name"]) == want["country"]
    assert _country_code_for(template) == want["country"], (
        f"{template.demo_id} would be installed with country_code "
        f"{_country_code_for(template) or 'DE (fallback)'}, not {want['country']}"
    )
    assert template.currency == want["currency"]
    taxes = [m for m in template.markups if m[2] == "tax"]
    assert len(taxes) == 1 and taxes[0][1] == float(want["vat"]), f"{template.demo_id} taxes {taxes}"
    assert template.classification_standard == "din276"
    assert want["rule_set"] in template.validation_rule_sets
    assert template.demo_id in _PACK_DEMO_TYPE
    assert want["currency"] in _CURRENCY_SYMBOL


@pytest.mark.parametrize("slug", SLUGS)
def test_the_pack_installs_its_flagship_demo(slug: str) -> None:
    assert PACK_DEMO_PROJECT.get(slug) == EXPECTED[slug]["demos"][0]


@pytest.mark.parametrize("slug", SLUGS)
def test_a_project_in_the_country_is_classified_against_din276(slug: str) -> None:
    """The region alone, with no standard named, lands on the hierarchy the pack maps onto.

    Ukraine read ``gesn`` here, the Russian norm lineage its 2021 cost rules
    replaced, and Greece had no entry and fell through to the default with a
    warning, so both are asserted as a match from the region and not as a
    fallback that happens to spell the same word.
    """
    resolution = resolve_standard(explicit=None, region=EXPECTED[slug]["country"])
    assert resolution.source == "region", f"{slug}: {resolution}"
    assert resolution.standard == "din276"


# ── Validation ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("slug", SLUGS)
@pytest.mark.parametrize("index", [0, 1])
def test_the_shipped_demo_is_clean_under_its_own_national_rules(slug: str, index: int) -> None:
    """The demo exists to show what the pack checks, so it has to pass those checks.

    Run on the shipped template, not on a fixture: a rule that reads a key the
    demo never writes passes every fixture test and says nothing on the bill a
    user actually opens.
    """
    want = EXPECTED[slug]
    template = _template(want["demos"][index])
    positions = _positions(template)
    leaves = [p for p in positions if p.get("type") != "section"]
    assert len(leaves) >= 30, f"{template.demo_id} prices only {len(leaves)} lines"
    assert all(p["classification"].get(want["classification_key"]) for p in leaves), (
        f"{template.demo_id} has lines without a {want['classification_key']!r} code"
    )
    assert all(p["classification"].get("din276") for p in leaves), f"{template.demo_id} has lines without DIN 276"
    assert _failures(want["rule_set"], positions) == []
    # The DIN 276 view the pack maps onto has to hold as well: a cost group
    # the standard does not define would be an error on the same bill.
    assert _failures("din276", positions, errors_only=True) == []


#: One compliant and one malformed line per national rule set, written against
#: the structure each README cites.
_LINES: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "romania": ({"deviz": "4.1"}, {"deviz": "7.2"}),
    "greece": ({"net": "ΟΙΚ 32.01.06"}, {"net": "ΟΙΚ 99.01.01"}),
    "ukraine": ({"zkr": "2"}, {"zkr": "13"}),
}


def _line(classification: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(uuid.uuid4()),
            "ordinal": "1.1",
            "description": "Excavation",
            "unit": "m3",
            "quantity": 10,
            "unit_rate": 100,
            "total": 1000,
            "classification": classification,
        }
    ]


@pytest.mark.parametrize("rule_set", sorted(_LINES))
def test_the_national_rule_set_tells_a_compliant_line_from_the_others(rule_set: str) -> None:
    compliant, malformed = _LINES[rule_set]
    assert _failures(rule_set, _line({})), f"{rule_set} finds nothing on a line with no national code"
    assert _failures(rule_set, _line(compliant)) == []
    assert _failures(rule_set, _line(malformed)), f"{rule_set} accepts {malformed}"


def test_greek_codes_typed_with_latin_lookalike_letters_are_read_as_greek() -> None:
    """``OIK`` in Latin letters is what a keyboard left in English produces."""
    assert _failures("greece", _line({"net": "OIK 32.01.06"})) == []
    assert _failures("greece", _line({"net": "ΑΤΗΕ 8151.1"})) == []
    assert _failures("greece", _line({"net": "ΝΑΟΙΚ 38.20.02"})) == []


def test_romanian_deviz_codes_below_a_recognised_subchapter_are_accepted() -> None:
    assert _failures("romania", _line({"deviz": "3.8.2"})) == []
    assert _failures("romania", _line({"deviz": "4.9"}))


_MESSAGE_KEYS = [
    "romania.deviz_chapter_required.fail",
    "romania.deviz_chapter_required.suggestion",
    "romania.deviz_chapter_recognised.fail",
    "romania.deviz_chapter_recognised.suggestion",
    "greece.net_article_required.fail",
    "greece.net_article_required.suggestion",
    "greece.net_article_valid.invalid",
    "greece.net_article_valid.chapter",
    "greece.net_article_valid.suggestion",
    "ukraine.zkr_chapter_required.fail",
    "ukraine.zkr_chapter_required.suggestion",
    "ukraine.zkr_chapter_recognised.fail",
    "ukraine.zkr_chapter_recognised.suggestion",
]


@pytest.mark.parametrize("key", _MESSAGE_KEYS)
@pytest.mark.parametrize("locale", ["en", "de", "es", "ru"])
def test_every_message_exists_in_every_validation_locale(key: str, locale: str) -> None:
    assert is_key_present(key, locale), f"{key} is missing from {locale}.json"


@pytest.mark.parametrize("slug", SLUGS)
def test_the_rule_pack_documents_name_only_rules_the_engine_defines(slug: str) -> None:
    from app.core.validation.engine import rule_registry

    register_builtin_rules()
    known = {entry["rule_id"] for entry in rule_registry.list_rules()}
    manifest = _manifest(slug)
    docs = PACKS / slug / "src" / EXPECTED[slug]["package"] / "rule_packs"
    stems = sorted(p.stem for p in docs.glob("*.json"))
    assert stems == sorted(manifest.validation_rule_packs), "manifest and rule_packs/ disagree"
    for path in docs.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["rule_pack_id"] == path.stem
        assert document["jurisdiction"] == EXPECTED[slug]["country"]
        assert document.get("references"), f"{path.name} cites nothing"
        missing = [rid for rid in document.get("enables_rule_ids") or [] if rid not in known]
        assert not missing, f"{path.name} promises checks the engine does not define: {missing}"


@pytest.mark.parametrize("slug", SLUGS)
def test_a_contract_in_the_country_is_signed_against_its_own_rules(slug: str) -> None:
    want = EXPECTED[slug]
    pack = resolve_pack(want["country"], None)
    assert pack == want["compliance_pack"]
    assert want["rule_set"] in resolve_rule_sets([pack])


def test_the_romanian_pack_cost_database_resolves() -> None:
    manifest = _manifest("romania-ro")
    assert [resolve_cwicr_db_id(r) for r in manifest.cwicr_regions] == ["RO_BUCHAREST"]
