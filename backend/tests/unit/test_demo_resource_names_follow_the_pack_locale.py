# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Seeded cost build-up rows are named in the demo project's own language.

A German demo bill used to break "Trennwand Trockenbau doppelt beplankt CW100"
down into "Drywall boards/profiles", "Drywall installers" and "Tools": English
row names under a German position, one lumped material line, and nothing an
estimator would recognise as a calculation. The generator now writes a stable
key per row and names it from ``demo_resource_names`` by the template's
locale, and a pack can give a position its real build-up
(``DemoTemplate.position_resources``).

The population is every priced position of every registered template, read
the way the installer reads it. A row name outside its language's table means
some branch still writes display text, and a pack language without a full
table would quietly seed English.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from app.core import demo_projects
from app.core.demo_resource_names import FALLBACK_LANGUAGE, RESOURCE_NAMES, base_language, resource_name

SOURCE = Path(demo_projects.__file__)

#: How many offenders to name before the message stops being readable.
_SHOWN = 6


def _template(demo_id: str) -> demo_projects.DemoTemplate:
    return demo_projects.DEMO_TEMPLATES[demo_id]


def _seeded(template: demo_projects.DemoTemplate, ordinal: str) -> list[dict]:
    """The leaves the installer writes for one position of a template."""
    for _sec_ordinal, _title, _cls, items in template.sections:
        for item in items:
            if item[0] == ordinal:
                meta = demo_projects._enrich_position_metadata(
                    description=item[1],
                    unit=item[2],
                    unit_rate=item[4],
                    classification=item[5],
                    locale=template.locale,
                    explicit_resources=template.position_resources.get(ordinal),
                )
                return list(meta.get("resources") or [])
    raise AssertionError(f"{template.demo_id} has no position {ordinal}")


def _rate(template: demo_projects.DemoTemplate, ordinal: str) -> Decimal:
    for _sec_ordinal, _title, _cls, items in template.sections:
        for item in items:
            if item[0] == ordinal:
                return Decimal(str(item[4]))
    raise AssertionError(f"{template.demo_id} has no position {ordinal}")


@lru_cache(maxsize=1)
def _source_keys() -> frozenset[str]:
    """Every resource key the generator writes, read off the source."""
    keys = {"generic_material", "generic_labour", "generic_equipment"}
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_make_resources":
            for element in node.args[3].elts:
                keys.add(element.elts[0].value)
    for template in demo_projects.DEMO_TEMPLATES.values():
        for rows in template.position_resources.values():
            keys.update(row[0] for row in rows)
    return frozenset(keys)


def _pack_languages() -> set[str]:
    return {base_language(t.locale) for t in demo_projects.DEMO_TEMPLATES.values()}


def test_every_pack_language_has_a_full_table() -> None:
    """A language a shipped pack uses must name every key itself, not fall back."""
    keys = _source_keys()
    assert len(keys) >= 150, f"only {len(keys)} resource keys read off the source"
    assert keys <= set(RESOURCE_NAMES[FALLBACK_LANGUAGE]), (
        f"keys with no English name: {sorted(keys - set(RESOURCE_NAMES[FALLBACK_LANGUAGE]))[:_SHOWN]}"
    )
    languages = _pack_languages()
    assert len(languages) >= 20, f"only {len(languages)} pack languages found: {sorted(languages)}"
    missing = sorted(lang for lang in languages if lang not in RESOURCE_NAMES)
    assert not missing, f"pack languages with no resource-name table: {missing}"
    gaps = [
        f"{lang}:{key}"
        for lang in sorted(languages)
        for key in sorted(keys)
        if not (RESOURCE_NAMES[lang].get(key) or "").strip()
    ]
    assert not gaps, f"{len(gaps)} names missing: " + ", ".join(gaps[:_SHOWN])


#: Names that are the same word in English and in the language, by right.
_SAME_AS_ENGLISH = frozenset(
    {
        ("es", "generic_material"),
        ("id", "generic_material"),
        ("pt", "generic_material"),
        ("ro", "generic_material"),
    }
)


def test_no_table_is_a_copy_of_the_english_one() -> None:
    """A column pasted from English passes the membership test; this catches it."""
    english = RESOURCE_NAMES[FALLBACK_LANGUAGE]
    copies = [
        f"{lang}:{key}={name!r}"
        for lang, table in RESOURCE_NAMES.items()
        if lang != FALLBACK_LANGUAGE
        for key, name in table.items()
        if name == english.get(key) and (lang, key) not in _SAME_AS_ENGLISH
    ]
    assert not copies, f"{len(copies)} names identical to English: " + ", ".join(copies[:_SHOWN])


def test_no_table_writes_a_long_dash() -> None:
    offenders = [
        f"{lang}:{key}"
        for lang, table in RESOURCE_NAMES.items()
        for key, name in table.items()
        if "—" in name or "–" in name
    ]
    assert not offenders, "names with an em or en dash: " + ", ".join(offenders[:_SHOWN])


def test_every_seeded_row_is_named_in_its_pack_language() -> None:
    """Every leaf of every position carries a name from its own language's table."""
    offenders: list[str] = []
    checked = 0
    for demo_id, template in demo_projects.DEMO_TEMPLATES.items():
        allowed = set(RESOURCE_NAMES.get(base_language(template.locale), RESOURCE_NAMES[FALLBACK_LANGUAGE]).values())
        for _sec_ordinal, _title, _cls, items in template.sections:
            for item in items:
                if Decimal(str(item[4])) <= 0:
                    continue
                for leaf in _seeded(template, item[0]):
                    checked += 1
                    if leaf.get("name") not in allowed:
                        offenders.append(f"{demo_id} ({template.locale}) {item[0]}: {leaf.get('name')!r}")
    assert checked >= 12000, f"only {checked} leaves checked"
    assert not offenders, f"{len(offenders)} rows not named in their pack language: " + "; ".join(offenders[:_SHOWN])


def test_a_german_pack_no_longer_reads_english() -> None:
    """The discriminating case: the same keys read differently by locale."""
    german = {leaf["name"] for leaf in _seeded(_template("office-frankfurt"), "340.2")}
    english = set(RESOURCE_NAMES[FALLBACK_LANGUAGE].values())
    assert german, "office-frankfurt 340.2 seeded no rows"
    assert not (german & english), f"English names on a German position: {sorted(german & english)}"


def test_the_frankfurt_partition_is_a_real_calculation() -> None:
    """340.4 carries per-m2 norms at a wage, in German, summing to its unit rate."""
    template = _template("office-frankfurt")
    leaves = _seeded(template, "340.4")
    assert [(leaf["name"], leaf["type"], leaf["unit"], leaf["quantity"], leaf["unit_rate"]) for leaf in leaves] == [
        ("CW-Ständerprofile CW 100", "material", "m", 2.0, 2.3),
        ("UW-Anschlussprofile UW 100, Boden und Decke", "material", "m", 0.8, 2.1),
        ("Gipskartonplatten GKB 12,5 mm", "material", "m2", 4.2, 3.2),
        ("Mineralwolle-Trennwandplatte", "material", "m2", 1.05, 4.0),
        ("Schnellbauschrauben", "material", "pcs", 40.0, 0.012),
        ("Fugenspachtel mit Fugenband", "material", "kg", 0.6, 1.2),
        ("Anschlussdichtungsband", "material", "m", 1.2, 0.375),
        ("Nageldübel", "material", "pcs", 1.6, 0.15),
        ("Trockenbaumonteure, Mittellohn", "labor", "hr", 0.58, 54.0),
        ("Kleingerät und Werkzeug", "equipment", "hr", 0.58, 1.5),
    ]
    grid = sum((Decimal(str(leaf["quantity"])) * Decimal(str(leaf["unit_rate"])) for leaf in leaves), Decimal("0"))
    stored = sum((Decimal(str(leaf["total"])) for leaf in leaves), Decimal("0"))
    assert grid == stored == _rate(template, "340.4") == Decimal("58.0")


def test_the_warsaw_partition_is_the_same_trade_in_polish() -> None:
    """The same build-up shape in another country, language and currency."""
    template = _template("residential-warsaw")
    assert template.currency == "PLN"
    leaves = _seeded(template, "4.3")
    names = [leaf["name"] for leaf in leaves]
    assert names[0] == "Profile pionowe CW 75"
    assert "Monterzy suchej zabudowy, średnia stawka roboczogodziny" in names
    grid = sum((Decimal(str(leaf["quantity"])) * Decimal(str(leaf["unit_rate"])) for leaf in leaves), Decimal("0"))
    assert grid == _rate(template, "4.3")


def test_every_hand_written_build_up_is_applied_not_refused() -> None:
    """A list that misses its rate falls back to the generated split with only a log line.

    The census of sums stays green in that case, so this asserts that each
    declared list really reaches the seeded position.
    """
    offenders: list[str] = []
    declared = 0
    for demo_id, template in demo_projects.DEMO_TEMPLATES.items():
        for ordinal, rows in template.position_resources.items():
            declared += 1
            leaves = _seeded(template, ordinal)
            expected = [resource_name(row[0], template.locale) for row in rows]
            if [leaf["name"] for leaf in leaves] != expected:
                offenders.append(f"{demo_id} {ordinal}")
    assert declared >= 5, f"only {declared} hand-written build-ups found"
    assert not offenders, "build-ups refused (rows do not add up to the unit rate): " + ", ".join(offenders)


def test_the_budget_split_labels_follow_the_locale() -> None:
    leaves = demo_projects._resources_for_position("Rohbau", "LS", 1.0, 1000.0, locale="de")
    assert [leaf["name"] for leaf in leaves] == ["Baumaterial - Rohbau", "Lohn - Rohbau", "Gerät - Rohbau"]
    english = demo_projects._resources_for_position("Shell", "LS", 1.0, 1000.0)
    assert [leaf["name"] for leaf in english] == ["Material - Shell", "Labour - Shell", "Equipment - Shell"]


def test_lookup_reads_the_base_language_and_falls_back_to_english() -> None:
    assert resource_name("drywall_installers", "pt-BR") == RESOURCE_NAMES["pt"]["drywall_installers"]
    assert resource_name("drywall_installers", "en-CA") == "Drywall installers"
    assert resource_name("drywall_installers", "xx") == "Drywall installers"
    assert resource_name("drywall_installers", None) == "Drywall installers"
