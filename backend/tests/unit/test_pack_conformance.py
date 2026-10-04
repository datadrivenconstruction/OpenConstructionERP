# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What every country and industry pack has to be true about, checked for all of them.

The Hungarian pack was taken apart in 18.3 and eight kinds of defect came out
of it: a rule set named by the classification instead of the engine, a locale
that was never shipped, numbers read a thousand times too small, an install
that did nothing, a cost base that silently belonged to another country, and
so on. None of them was Hungarian. Each one was a property the pack framework
promises and nothing held it to, so every other pack had the same chance of
carrying it, and most did.

So this file does not list packs. It walks ``packs/*`` and asks the same
questions of each one it finds, which means a pack added tomorrow is held to
the same answers without anybody remembering to add it here. Where a pack is
excused from a question the excuse is written down with its reason, and a
test checks that no excuse outlives the defect it covered.

The questions, by the defect class that produced them:

* C1, rules: every rule set a pack or its country selects is registered, a
  project of the country runs national rules even when it was created without
  the pack, a country row never adds another standard's "code required" rule,
  and every demo bill a pack installs clears the rules it would be validated
  with.
* C2, locale: the pack's language is shipped and offered, it is the country's
  own language when the interface has one, and the demos and onboarding speak
  it too.
* C3, formats: the country has an exchange row, and the importer reads the
  numbers the market writes (decimal comma or decimal dot, the separators
  between thousands, a currency sign in front) as the number they are.
* C4, install: every entry point resolves to a pack, and a pack switched on
  through the environment variable the READMEs document reports as applied.
* C5, market: every declared cost region loads, loads a base of the pack's own
  country and currency, and a country with a published base declares one.
* C6, classification: the classification a pack names is one the platform
  labels.
* C7, hygiene: rule documents name only rules that run, no personal e-mail
  address ships, and the tax template agrees with the rate beside it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from app.core.partner_pack.manifest import PartnerPackManifest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "backend"
PACKS_DIR = REPO_ROOT / "packs"
I18N_TS = REPO_ROOT / "frontend" / "src" / "app" / "i18n.ts"

# ── Discovery ────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _manifests() -> dict[str, PartnerPackManifest]:
    """Every manifest under ``packs/``, keyed by slug, loaded from its own file.

    An import that fails raises here instead of dropping the pack, so a broken
    manifest turns this whole file red rather than quietly shrinking it.
    """
    out: dict[str, PartnerPackManifest] = {}
    for path in sorted(PACKS_DIR.glob("*/src/*/manifest.py")):
        name = f"_conformance_manifest_{path.parts[-2]}"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader, f"{path} cannot be loaded as a module"
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        manifest = module.MANIFEST
        out[manifest.slug] = manifest
    return out


@lru_cache(maxsize=1)
def _manifests_by_path() -> dict[Path, str]:
    _manifests()
    out: dict[Path, str] = {}
    for path in sorted(PACKS_DIR.glob("*/src/*/manifest.py")):
        module = sys.modules[f"_conformance_manifest_{path.parts[-2]}"]
        out[path] = module.MANIFEST.slug
    return out


def _package_dir(slug: str) -> Path:
    for path, owner in _manifests_by_path().items():
        if owner == slug:
            return path.parent
    raise AssertionError(f"no package directory for {slug!r}")


SLUGS: list[str] = sorted(_manifests())


def _country(manifest: PartnerPackManifest) -> str | None:
    """The pack's market as an ISO code, or None for a cross-region pack."""
    return manifest.market_country_code


COUNTRY_SLUGS: list[str] = [s for s in SLUGS if _country(_manifests()[s])]


def _entry_points() -> list[tuple[str, str]]:
    """``(entry point name, pack directory)`` for every pack's pyproject."""
    out: list[tuple[str, str]] = []
    for pyproject in sorted(PACKS_DIR.glob("*/pyproject.toml")):
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        eps = data.get("project", {}).get("entry-points", {}).get("openconstructionerp.partner_packs", {})
        out.extend((name, pyproject.parent.name) for name in eps)
    return out


def test_the_suite_found_every_pack() -> None:
    """The control: a file that iterates nothing passes everything."""
    assert len(SLUGS) >= 47, f"only {len(SLUGS)} pack manifests were found under {PACKS_DIR}"
    assert len(COUNTRY_SLUGS) >= 40, f"only {len(COUNTRY_SLUGS)} of them are country packs"
    directories = {p.parent.name for p in PACKS_DIR.glob("*/pyproject.toml")}
    with_manifest = {p.parts[-4] for p in PACKS_DIR.glob("*/src/*/manifest.py")}
    shims = directories - with_manifest
    names = dict(_entry_points())
    # A directory without a manifest is only allowed as a declared alias.
    from app.core.partner_pack.discovery import PACK_SLUG_ALIASES

    unexplained = sorted(
        d for d in shims if not any(n in PACK_SLUG_ALIASES for n, owner in names.items() if owner == d)
    )
    assert unexplained == [], f"pack directories with neither a manifest nor a declared alias: {unexplained}"


@pytest.mark.parametrize(("name", "directory"), _entry_points())
def test_every_entry_point_name_reaches_a_pack(name: str, directory: str) -> None:
    """``OE_PACK=<entry point name>`` must activate something.

    The deprecated ``aus-nzs`` shim promised that its old name keeps
    resolving, while activation matched on manifest slugs only and there is
    no manifest with that slug, so the promised compatibility activated
    nothing and logged that no such pack was installed.
    """
    from app.core.partner_pack.discovery import resolve_pack_slug

    assert resolve_pack_slug(name) in _manifests(), (
        f"the entry point {name!r} in packs/{directory} resolves to no pack manifest"
    )


# ── C1: rule sets ────────────────────────────────────────────────────────────

_REGISTRY_PROBE = """
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
print(json.dumps({"sets": sorted(rule_registry.list_rule_sets()), "ids": sorted(r["rule_id"] for r in rule_registry.list_rules())}))
"""


@lru_cache(maxsize=1)
def _registry() -> dict[str, list[str]]:
    """Rule sets and rule ids a clean interpreter registers, module-owned ones included.

    Measured in a subprocess because the registry is filled by imports, and an
    in-process reading describes whatever this pytest session loaded.
    """
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _REGISTRY_PROBE],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"the registry probe failed: {result.stderr[-2000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def _selected(country: str, standard: str = "", project_sets: list[str] | None = None, region: str = "") -> list[str]:
    from app.modules.boq.router import _build_rule_sets

    return _build_rule_sets(list(project_sets or ["boq_quality"]), standard, region, country_code=country)


#: Countries whose projects run no national rule set, each with the reason.
#: Every entry is a gap listed as open, not a design; the test below fails when
#: an entry is no longer needed so the list cannot outlive the gap.
COUNTRIES_WITHOUT_NATIONAL_RULES: dict[str, str] = {
    "KR": "KBIM has no rule set in the platform; the Korean pack says so in its description.",
    "DK": "SfB/CCS is not a classification the platform can check yet.",
    "NO": "NS 3451 is not a classification the platform can check yet.",
    "SE": "BSAB is not a classification the platform can check yet.",
    "NL": "NL/SfB has a label but no rule set yet.",
    "IT": "The voci of a regional prezzario have no rule set yet.",
    "PT": (
        "ProNIC is not in the platform, and MasterFormat, which the registry uses as Portugal's "
        "fallback, is not what a Portuguese bill is coded in, so it is not run on every Portuguese project."
    ),
}


def test_the_rule_selection_answers_through_the_real_registry() -> None:
    """The control on the C1 tests: the registry probe saw the national sets."""
    sets = set(_registry()["sets"])
    for name in ("boq_quality", "din276", "nrm", "masterformat", "hungary", "gesn", "formwork"):
        assert name in sets, f"the registry probe did not see {name!r}"


@pytest.mark.parametrize("slug", SLUGS)
def test_every_rule_set_a_pack_declares_is_registered(slug: str) -> None:
    manifest = _manifests()[slug]
    missing = sorted(set(manifest.validation_rule_sets) - set(_registry()["sets"]))
    assert missing == [], f"{slug} switches on rule sets the engine does not register: {missing}"


@pytest.mark.parametrize("slug", COUNTRY_SLUGS)
def test_a_project_of_the_country_runs_national_rules_without_the_pack(slug: str) -> None:
    """The Hungarian C1: rules ran only if the pack was active at creation.

    A project created before the pack was switched on, or on an install that
    never switched it on, is validated through the country row alone.
    """
    country = _country(_manifests()[slug])
    national = [s for s in _selected(country) if s != "boq_quality"]
    registered = set(_registry()["sets"])
    unknown = [s for s in national if s not in registered]
    assert unknown == [], f"{country} selects rule sets the engine does not register: {unknown}"
    if country in COUNTRIES_WITHOUT_NATIONAL_RULES:
        assert not national, f"{country} now selects {national}; delete its entry from COUNTRIES_WITHOUT_NATIONAL_RULES"
        return
    assert national, f"a {country} project created without the {slug} pack runs no national rule at all"


#: ``(country, rule set)`` pairs a pack switches on that deliberately do not run
#: on every project of the country, with the reason.
PACK_ONLY_RULE_SETS: dict[tuple[str, str], str] = {
    ("PT", "masterformat"): COUNTRIES_WITHOUT_NATIONAL_RULES["PT"],
    ("GB", "uk_statutory"): (
        "the statutory checks read contract and CDM declarations a UK project gains from the pack's "
        "onboarding; on a project without them every one would warn"
    ),
    ("BR", "nbr"): "NBR 12721 is a second, optional cost-group coding the Brazilian pack adds beside SINAPI",
}


def test_no_pack_only_exception_outlives_its_reason() -> None:
    stale = []
    for country, rule_set in PACK_ONLY_RULE_SETS:
        declaring = [m for m in _manifests().values() if _country(m) == country and rule_set in m.validation_rule_sets]
        if not declaring or rule_set in _selected(country):
            stale.append((country, rule_set))
    assert stale == [], f"these PACK_ONLY_RULE_SETS entries are no longer needed: {stale}"


@pytest.mark.parametrize("slug", COUNTRY_SLUGS)
def test_the_rule_sets_a_pack_declares_also_run_without_it(slug: str) -> None:
    manifest = _manifests()[slug]
    country = _country(manifest)
    selected = set(_selected(country))
    missing = sorted(
        s for s in manifest.validation_rule_sets if s not in selected and (country, s) not in PACK_ONLY_RULE_SETS
    )
    assert missing == [], f"{slug} switches on {missing}, which a {country} project created without the pack never runs"


def _code_sets() -> dict[str, str]:
    """Rule set -> the classification standard whose code it requires on every line."""
    from app.modules.boq.router import _CLASSIFICATION_CODE_SETS

    return dict(_CLASSIFICATION_CODE_SETS)


@pytest.mark.parametrize("slug", COUNTRY_SLUGS)
def test_the_country_row_adds_no_other_standards_code_rule(slug: str) -> None:
    """The UAE C1: the country row said NRM while the country and pack read MasterFormat.

    A "code required" rule for a standard the bill is not written in fails
    every line with an error, and the country row is added to every project of
    the country whatever it declares.
    """
    from app.core.classification_registry import standard_for_country
    from app.modules.boq.router import _COUNTRY_RULE_SETS, _STANDARD_RULE_SETS

    manifest = _manifests()[slug]
    country = _country(manifest)
    allowed = set(manifest.validation_rule_sets)
    for standard in (standard_for_country(country), manifest.metadata.get("classification_standard")):
        if standard and _STANDARD_RULE_SETS.get(standard):
            allowed.add(_STANDARD_RULE_SETS[standard])
    foreign = sorted(s for s in _COUNTRY_RULE_SETS.get(country, []) if s in _code_sets() and s not in allowed)
    assert foreign == [], (
        f"the {country} row adds {foreign}, a code rule for a standard neither {country} nor {slug} reads"
    )


def _demo_ids(slug: str) -> list[str]:
    from app.core.demo_projects import PACK_DEMO_PROJECT

    manifest = _manifests()[slug]
    ids = [PACK_DEMO_PROJECT.get(slug), *manifest.demo_template_ids]
    return [d for d in dict.fromkeys(ids) if d]


def _demo_cases() -> list[tuple[str, str]]:
    return [(slug, demo) for slug in SLUGS for demo in _demo_ids(slug)]


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


@pytest.mark.parametrize(("slug", "demo_id"), _demo_cases())
def test_every_demo_a_pack_installs_clears_the_rules_it_is_validated_with(slug: str, demo_id: str) -> None:
    """The one behavioural C1 test, and the one that finds what a table cannot.

    The demo is validated the way the Validate button does it: its own rule
    sets, the classification standard the installer stores it under (which
    is the registry's answer, not always the one the template declares), its
    region and the country the installer stamps from its address. Swiss BKP bills failed DIN 276 on every
    line, the Vienna ÖNORM bill failed it because ``DACH`` beat Austria, the
    UAE flagship failed NRM, and the Mexican one failed BC3.
    """
    from app.core.classification_registry import resolve_standard
    from app.core.demo_projects import DEMO_TEMPLATES, _country_code_for
    from app.core.validation.engine import validation_engine
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    template = DEMO_TEMPLATES.get(demo_id)
    assert template is not None, f"{slug} names the demo {demo_id!r}, which is not registered"
    rule_sets = _selected(
        _country_code_for(template) or "",
        resolve_standard(template.classification_standard or None, region=template.region).standard or "",
        list(template.validation_rule_sets or ["boq_quality"]),
        template.region or "",
    )
    runnable = [s for s in rule_sets if validation_engine.registry.has_rules(s)]
    report = asyncio.run(
        validation_engine.validate(
            data=_demo_payload(template), rule_sets=runnable, target_type="boq", metadata={"locale": "en"}
        )
    )
    errors: dict[str, int] = {}
    for result in report.results:
        if not result.passed and result.severity.value == "error":
            errors[result.rule_id] = errors.get(result.rule_id, 0) + 1
    assert errors == {}, f"the {demo_id} demo of {slug}, validated with {runnable}, fails {errors}"


@pytest.mark.parametrize(("slug", "demo_id"), [c for c in _demo_cases() if _country(_manifests()[c[0]])])
def test_a_country_pack_installs_only_demos_of_its_own_country(slug: str, demo_id: str) -> None:
    """Installing the Polish pack seeded a Hungarian forint project."""
    from app.core.demo_projects import DEMO_TEMPLATES, _country_code_for

    manifest = _manifests()[slug]
    template = DEMO_TEMPLATES[demo_id]
    assert _country_code_for(template) == _country(manifest), (
        f"{slug} installs {demo_id}, a project in {_country_code_for(template) or template.region}"
    )
    assert template.currency == manifest.default_currency, (
        f"{slug} installs {demo_id} priced in {template.currency}, not {manifest.default_currency}"
    )


# ── C2: locale ───────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _offered() -> dict[str, str]:
    """Offered interface language code -> the country its entry names."""
    source = I18N_TS.read_text(encoding="utf-8")
    entries = re.findall(r"\{\s*code:\s*'([A-Za-z-]+)'[^}]*?country:\s*'([a-z]+)'", source)
    assert len(entries) > 20, "the language list in i18n.ts was not found"
    return dict(entries)


@lru_cache(maxsize=1)
def _english_day_first_regions() -> frozenset[str]:
    source = I18N_TS.read_text(encoding="utf-8")
    match = re.search(r"ENGLISH_DAY_FIRST_REGIONS[^=]*=\s*new Set\(\[([^\]]*)\]", source)
    assert match, "ENGLISH_DAY_FIRST_REGIONS was not found in i18n.ts"
    return frozenset(re.findall(r"'([A-Z]{2})'", match.group(1)))


def _match_supported(tag: str) -> str | None:
    """``matchSupportedLanguage`` in i18n.ts, read rule for rule."""
    offered = _offered()
    parts = tag.strip().split("-")
    if len(parts) >= 2 and parts[1]:
        regional = f"{parts[0].lower()}-{parts[1].upper()}"
        if regional in offered:
            return regional
        if parts[0].lower() == "en" and parts[1].upper() in _english_day_first_regions() and "en-GB" in offered:
            return "en-GB"
    base = parts[0].lower()
    return base if base in offered else None


#: Countries whose pack speaks English although the interface offers a language
#: of the country, with the reason.
ENGLISH_BY_CHOICE: dict[str, str] = {
    "IN": "Indian contracts, the CPWD schedules and the DSR are written in English; Hindi is offered beside it.",
}


@pytest.mark.parametrize("slug", SLUGS)
def test_the_pack_language_is_shipped_and_offered(slug: str) -> None:
    manifest = _manifests()[slug]
    assert _match_supported(manifest.default_locale) is not None, (
        f"{slug} asks for {manifest.default_locale!r}, which the interface neither ships nor falls back from"
    )


@pytest.mark.parametrize("slug", COUNTRY_SLUGS)
def test_the_pack_speaks_the_countrys_own_language_when_the_interface_has_it(slug: str) -> None:
    """The Hungarian C2: installing the pack kept a Hungarian user in English."""
    manifest = _manifests()[slug]
    country = _country(manifest).lower()
    own = {code for code, flag in _offered().items() if flag == country}
    resolved = _match_supported(manifest.default_locale)
    if not own or manifest.market_country_code in ENGLISH_BY_CHOICE:
        return
    assert resolved in own, f"{slug} opens in {resolved!r} while the interface ships {sorted(own)} for its country"


@pytest.mark.parametrize("slug", COUNTRY_SLUGS)
def test_an_english_pack_outside_the_us_reads_dates_day_first(slug: str) -> None:
    """Unqualified ``en`` prints ``3/14/2026``: a US date in Dublin, Lagos or Sydney."""
    manifest = _manifests()[slug]
    country = _country(manifest)
    resolved = _match_supported(manifest.default_locale)
    if not resolved or not resolved.startswith("en") or country in ("US", "CA"):
        return
    assert resolved == "en-GB", f"{slug} ({country}) resolves to {resolved!r}, which prints month-first dates"


#: Demos that open in another of the country's languages on purpose, with the reason.
DEMOS_IN_ANOTHER_LANGUAGE_BY_CHOICE: dict[str, str] = {
    "tower-abudhabi": (
        "The UAE pack works in English, the working language of its contracts, and ships one "
        "demo in Arabic, the official language, so the right-to-left interface is exercised."
    ),
    "residential-lausanne": (
        "Switzerland has more than one official language and the Swiss pack defaults to German. "
        "This demo is a project in Vaud, which is French-speaking, and its bill is written in French, "
        "so its documents, PDF and invitation emails are French too."
    ),
}


@pytest.mark.parametrize(("slug", "demo_id"), [c for c in _demo_cases() if _country(_manifests()[c[0]])])
def test_a_demo_speaks_its_packs_language(slug: str, demo_id: str) -> None:
    """The Budapest flagship printed its PDF in English after the pack went Hungarian."""
    from app.core.demo_projects import DEMO_TEMPLATES

    manifest = _manifests()[slug]
    template = DEMO_TEMPLATES[demo_id]
    pack_language = (_match_supported(manifest.default_locale) or "").split("-")[0]
    demo_language = (_match_supported(template.locale) or template.locale or "").split("-")[0]
    assert _match_supported(template.locale) is not None, f"{demo_id} carries {template.locale!r}, which is not offered"
    if demo_id in DEMOS_IN_ANOTHER_LANGUAGE_BY_CHOICE:
        return
    assert demo_language == pack_language, (
        f"{demo_id} speaks {template.locale!r} while {slug} speaks {manifest.default_locale!r}"
    )


@pytest.mark.parametrize("slug", SLUGS)
def test_the_onboarding_script_speaks_the_packs_language(slug: str) -> None:
    manifest = _manifests()[slug]
    if not manifest.onboarding_script_path:
        return
    script = _package_dir(slug) / manifest.onboarding_script_path
    assert script.is_file(), f"{slug} names {manifest.onboarding_script_path}, which it does not ship"
    match = re.search(r"^locale:\s*[\"']?([A-Za-z-]+)", script.read_text(encoding="utf-8"), re.M)
    if match is None:
        return
    assert _match_supported(match.group(1)) == _match_supported(manifest.default_locale), (
        f"{slug}'s onboarding says locale {match.group(1)!r} and its manifest {manifest.default_locale!r}"
    )


# ── C3: exchange formats and numbers ─────────────────────────────────────────


@pytest.mark.parametrize("slug", COUNTRY_SLUGS)
def test_the_country_has_an_exchange_format(slug: str) -> None:
    """The Croatian pack is built around the troškovnik and the catalogue had no row for Croatia."""
    from app.modules.boq.exchange_formats import default_format_for_country

    country = _country(_manifests()[slug])
    assert default_format_for_country(country) is not None, f"no exchange format row lists {country}"


def _workbook_languages() -> list[str]:
    from app.modules.boq.exchange_formats import EXCHANGE_FORMATS

    return sorted({f.header_language for f in EXCHANGE_FORMATS if f.header_language and f.reader == "excel"})


def _csv_for(language: str, quantity: str, rate: str) -> bytes:
    from app.modules.boq.importers.excel import _HEADERS_BY_LANGUAGE

    table = {**_HEADERS_BY_LANGUAGE["en"], **_HEADERS_BY_LANGUAGE[language]}
    header = [table["description"][0], table["unit"][0], table["quantity"][0], table["unit_rate"][0]]
    rows = [header, ["Line one", "m3", quantity, rate]]
    body = "\n".join(";".join(f'"{cell}"' for cell in row) for row in rows)
    return ("﻿" + body + "\n").encode("utf-8")


def _import(content: bytes) -> Any:
    from app.modules.boq.importers.excel import ExcelImporter

    return asyncio.run(ExcelImporter.parse(content, locale="en"))


def _decimal_comma(language: str) -> bool:
    from app.modules.boq.importers.excel import DECIMAL_COMMA_LANGUAGES

    return language in DECIMAL_COMMA_LANGUAGES


@pytest.mark.parametrize("language", _workbook_languages())
def test_a_national_workbook_reads_a_grouped_number_as_the_number_it_is(language: str) -> None:
    """The Hungarian C3 on every market: 1,250 and 12.500 imported a thousandth.

    A decimal-comma market writes twelve thousand five hundred as ``12.500``
    and a decimal-dot market writes one thousand two hundred and fifty as
    ``1,250``. Read the other way both are a thousandth of the number, and
    nothing on the import said so.
    """
    grouped = "12.500" if _decimal_comma(language) else "12,500"
    decimal = "1.250,5" if _decimal_comma(language) else "1,250.5"
    result = _import(_csv_for(language, grouped, decimal))
    assert result.positions, f"a {language} CSV imported nothing: {result.errors}"
    position = result.positions[0]
    assert position.quantity == 12500, f"{language}: {grouped!r} was read as {position.quantity}"
    assert position.unit_rate == 1250.5, f"{language}: {decimal!r} was read as {position.unit_rate}"


@pytest.mark.parametrize(
    ("language", "text", "expected"),
    [
        ("de", "1'250.50", 1250.5),
        ("de", "1’250.50", 1250.5),
        ("en", "$1,234.56", 1234.56),
        ("en", "₹ 25,000", 25000),
        ("en", "AED 1,250", 1250),
        ("id", "Rp 1.250.000", 1250000),
        ("pt", "R$ 1.234,56", 1234.56),
        ("zh", "¥12,500", 12500),
    ],
)
def test_a_currency_sign_or_a_swiss_apostrophe_does_not_lose_the_number(
    language: str, text: str, expected: float
) -> None:
    result = _import(_csv_for(language, "1", text))
    assert result.positions, f"{text!r} imported nothing: {result.errors}"
    assert result.positions[0].unit_rate == expected, f"{text!r} was read as {result.positions[0].unit_rate}"


@pytest.mark.parametrize(
    ("language", "codec"),
    [("ru", "cp1251"), ("uk", "cp1251"), ("el", "cp1253"), ("tr", "cp1254"), ("hu", "cp1250"), ("pl", "cp1250")],
)
def test_a_csv_saved_by_excel_in_the_markets_code_page_keeps_its_letters(language: str, codec: str) -> None:
    """Excel saves a CSV in the Windows code page of the market, not in UTF-8."""
    from app.modules.boq.importers.excel import _HEADERS_BY_LANGUAGE

    table = _HEADERS_BY_LANGUAGE[language]
    header = [table["description"][0], table["unit"][0], table["quantity"][0], table["unit_rate"][0]]
    description = {
        "ru": "Бетон",
        "uk": "Бетон",
        "el": "Σκυρόδεμα",
        "tr": "Beton dökümü şantiye",
        "hu": "Beton ő",
        "pl": "Beton żelbet",
    }[language]
    body = ";".join(header) + "\n" + ";".join([description, "m3", "1", "2"]) + "\n"
    result = _import(body.encode(codec))
    assert result.positions, f"a {codec} CSV imported nothing: {result.errors}"
    assert result.positions[0].description == description


# ── C4: install ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("variable", ["OE_PACK", "OE_PARTNER_PACK"])
def test_a_pack_switched_on_by_the_environment_reports_as_applied(
    variable: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seven READMEs say ``OE_PACK=<slug>``; the Modules page asked only about the old name."""
    from app.core.partner_pack import apply

    monkeypatch.delenv("OE_PACK", raising=False)
    monkeypatch.delenv("OE_PARTNER_PACK", raising=False)
    monkeypatch.setenv(variable, "germany-de")
    monkeypatch.setattr(apply, "load_applied_state", lambda: None)
    info = apply.get_applied_info()
    assert info["applied"] is True and info["slug"] == "germany-de"


# ── C5: cost bases ───────────────────────────────────────────────────────────


def _base_country(db_id: str) -> str | None:
    from app.core.classification_registry import normalise_region
    from app.modules.costs import base_registry

    variant = base_registry.variant_by_region(db_id)
    if variant is not None and variant.flag:
        return variant.flag.upper()
    return normalise_region(db_id)


@pytest.mark.parametrize("slug", SLUGS)
def test_every_declared_cost_region_loads_a_base_of_the_packs_market(slug: str) -> None:
    """Four of five Australian regions loaded nothing, and the Brazilian ``national`` loaded Turkey."""
    from app.core.partner_pack.full_install import describe_cost_bases

    manifest = _manifests()[slug]
    country = _country(manifest)
    for entry in describe_cost_bases(list(manifest.cwicr_regions)):
        assert entry["db_id"], f"{slug} declares {entry['slug']!r}, which loads no published base"
        if country:
            assert _base_country(entry["db_id"]) == country, (
                f"{slug} ({country}) declares {entry['slug']!r}, which loads {entry['db_id']} from "
                f"{_base_country(entry['db_id'])}"
            )
        if entry["currency"]:
            assert entry["currency"] == manifest.default_currency, (
                f"{slug} prices in {manifest.default_currency} and loads {entry['db_id']} in {entry['currency']}"
            )


@pytest.mark.parametrize("slug", COUNTRY_SLUGS)
def test_a_country_with_a_published_base_declares_one(slug: str) -> None:
    from app.core.partner_pack.full_install import resolve_cwicr_db_id
    from app.modules.costs.router import _GITHUB_CWICR_FILES

    manifest = _manifests()[slug]
    country = _country(manifest)
    published = sorted(db for db in _GITHUB_CWICR_FILES if _base_country(db) == country)
    if not published:
        return
    declared = {resolve_cwicr_db_id(s) for s in manifest.cwicr_regions}
    assert declared & set(published), f"{slug} declares no cost region although {published} are published for {country}"


@pytest.mark.parametrize("db_id", ["BR_NATIONAL", "GR_NATIONAL", "TR_NATIONAL", "ID_NATIONAL"])
def test_every_national_base_is_reachable_by_its_own_countrys_slug(db_id: str) -> None:
    from app.core.partner_pack.full_install import resolve_cwicr_db_id

    country = db_id.split("_")[0].lower()
    assert resolve_cwicr_db_id(f"cwicr-{country}-national") == db_id


def test_a_shared_token_never_answers_for_another_country() -> None:
    """``national`` names a base in several countries, and it used to answer Turkey for all of them."""
    from app.core.partner_pack.full_install import resolve_cwicr_db_id

    assert resolve_cwicr_db_id("cwicr-pt-national") is None
    assert resolve_cwicr_db_id("cwicr-xx-national") is None


# ── C6: classification ───────────────────────────────────────────────────────


@pytest.mark.parametrize("slug", SLUGS)
def test_the_classification_a_pack_names_is_one_the_platform_labels(slug: str) -> None:
    from app.core.classification_registry import CLASSIFICATION_STANDARD_LABELS

    standard = _manifests()[slug].metadata.get("classification_standard")
    if not standard:
        return
    assert standard in CLASSIFICATION_STANDARD_LABELS, (
        f"{slug} names the classification {standard!r}, which has no label"
    )


# ── C7: hygiene ──────────────────────────────────────────────────────────────


# Rule documents (``rule_packs/*.json``) may list rule ids no engine rule
# carries yet. That is by design, not a defect: the ids are the pack's
# intended checks, and app/core/validation/pack_coverage.py reports each one
# that does not run as "declared only" rather than as a pass. Nothing in the
# product echoes the raw declared count, so this suite does not pin it.


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_ALLOWED_EMAILS = {"info@datadrivenconstruction.io"}


@pytest.mark.parametrize("slug", SLUGS)
def test_no_personal_email_address_ships_in_a_pack(slug: str) -> None:
    folder = _package_dir(slug)
    texts = [folder / "manifest.py", folder.parents[1] / "README.md", folder.parents[1] / "pyproject.toml"]
    found = sorted(
        {m for p in texts if p.is_file() for m in _EMAIL.findall(p.read_text(encoding="utf-8"))} - _ALLOWED_EMAILS
    )
    assert found == [], f"{slug} ships the address(es) {found}"


#: Commercial cost-data publishers, which the product describes by category.
_COST_DATA_BRANDS = re.compile(r"\b(BCIS|BIMSA|PINI)\b")


@pytest.mark.parametrize("slug", SLUGS)
def test_a_pack_describes_cost_data_by_category_not_by_publisher(slug: str) -> None:
    folder = _package_dir(slug)
    files = [folder / "manifest.py", folder.parents[1] / "pyproject.toml", *sorted((folder / "locales").glob("*.json"))]
    hits = sorted({p.name for p in files if p.is_file() and _COST_DATA_BRANDS.search(p.read_text(encoding="utf-8"))})
    assert hits == [], f"{slug} names a commercial cost-data publisher in {hits}"


@pytest.mark.parametrize("slug", SLUGS)
def test_the_tax_template_agrees_with_the_rate_beside_it(slug: str) -> None:
    """The Russian pack said ``ru_nds_20`` next to a 22% rate."""
    manifest = _manifests()[slug]
    template = manifest.default_tax_template or ""
    digits = re.findall(r"_(\d+(?:_\d+)?)$", template)
    rates = {
        manifest.metadata.get(k)
        for k in ("vat_standard_rate", "vat_standard_rate_pct", "vat_construction_rate", "vat_reduced_rate")
    } - {None}
    if not digits or not rates:
        return
    value = float(digits[0].replace("_", "."))
    assert value in {float(r) for r in rates}, f"{slug} names {template!r} beside the rates {sorted(rates)}"


@pytest.mark.parametrize("slug", SLUGS)
def test_the_description_is_written_in_english(slug: str) -> None:
    """The schema says English; German text with transliterated umlauts reached every UI language."""
    text = _manifests()[slug].description
    german = re.findall(r"\b(fuer|für|und|mit|oeffentliche|vollstaendig|Vorkonfiguriert)\b", text)
    assert german == [], f"{slug}'s description is not English: {german}"
