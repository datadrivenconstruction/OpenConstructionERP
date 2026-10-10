# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integrity tests for the partner-pack flagship country projects.

Each active partner pack ships one fully worked-out demo project authored as
a standalone ``DemoTemplate`` under ``app/core/demo_packs/``. These templates
are merged into ``DEMO_TEMPLATES``, surfaced in ``DEMO_CATALOG``, and mapped
to their pack via ``PACK_DEMO_PROJECT`` so an active pack auto-installs its
country project on first boot.

This module asserts the wiring stays consistent:
1. Every discovered partner pack slug has a demo-project mapping.
2. Every mapped demo_id resolves to a loaded ``DemoTemplate``.
3. Every pack demo project appears in the marketplace catalog with the
   required keys and a derived ISO-2 country.
4. Each pack template is substantial and structurally valid (sections with
   items, allowed units, positive quantities/rates).
"""

from __future__ import annotations

import pytest

from app.core.classification_registry import (
    CLASSIFICATION_STANDARD_LABELS,
    KNOWN_CLASSIFICATION_STANDARDS,
    resolve_standard,
)
from app.core.demo_packs import PACK_TEMPLATES
from app.core.demo_projects import (
    DEMO_CATALOG,
    DEMO_TEMPLATES,
    PACK_DEMO_PROJECT,
)

# Units accepted by the BOQ position model / demo installer.
# Includes locale-authentic codes the flagship country demos use on purpose:
# Brazil "vb" (verba / lump sum), "un" (unidade), "mes" (month); India "MT"
# (metric tonne), "rm" (running metre); Canada "suite". The China GB/T
# 50500-2013 demo uses the standard Chinese measurement words: "项" (xiang,
# lump-sum work item, like "lsum"), "台" (tai, a machine/equipment set), "樘"
# (tang, a door/window leaf), "组" (zu, a group/set), "套" (tao, a set/system),
# "根" (gen, a long single piece such as a pile or rod). Hungary uses the
# tetelrend words "db" (darab, piece), "klt" (keszlet, set), "ho" (month) and
# "nap" (day), plus "kWp" for photovoltaic capacity. Russia uses GESN measurers,
# which carry the norm multiplier in the unit itself: "100 m2" means the rate is
# per hundred square metres, which is how the resource-index method prices a
# norm, so the scaled forms are units in their own right and not a formatting
# accident. Cyrillic month and Latin "mes" look near-identical and are two
# separate tokens on purpose. The Latin one is a single token serving both
# Portuguese and Spanish, which is why the Spanish block below does not repeat
# it. Six more markets joined with their own
# measurers rather than translated ones, which is the whole reason this
# allowlist grows by market instead of being replaced with a generic set: the
# Spanish, Dutch, Polish, Turkish, Japanese and Korean blocks below each carry
# the word a local estimator would actually read on the line.
_ALLOWED_UNITS = {
    "m2",
    "m3",
    "m",
    "t",
    "kg",
    "pcs",
    "lsum",
    "hour",
    "day",
    "month",
    "each",
    "ha",
    "l",
    "MT",
    "rm",
    "un",
    "vb",
    "mes",
    "suite",
    "项",
    "台",
    "樘",
    "组",
    "套",
    "根",
    "个",  # ge, generic counter word for individual items
    "株",  # zhu, a single plant or tree
    # Hungary (tetelrend)
    "db",
    "klt",
    "hó",
    "nap",
    "kWp",
    # Russia (GESN measurers)
    "шт",
    "компл",
    "м3",
    "мес",
    "т",
    "100 м",
    "100 м2",
    "100 м3",
    "100 шт",
    "100 компл",
    "1000 м2",
    "1000 м3",
    # Italy (computo metrico estimativo)
    "cad",  # cadauno
    "a corpo",  # a lump sum, the Italian "lsum"; the space is part of the token
    "mese",
    # Spain (mediciones y presupuesto)
    "u",  # unidad
    "pa",  # partida alzada, a lump-sum item
    # Spanish "mes" is the same Latin token as the Brazilian one above and is
    # already allowed; it is listed once because it is one token, unlike the
    # Cyrillic "мес" which only looks the same.
    # Netherlands (RAW / STABU)
    "st",  # stuks
    "post",  # a lump-sum post
    "mnd",  # maand
    "ton",  # also used by the Istanbul pack
    # Poland (KNR kosztorys)
    "szt",  # sztuka
    "kpl",  # komplet
    "mies",  # miesiąc
    # Türkiye (birim fiyat)
    "adet",
    "takım",  # a set
    # Japan (sekisan). "台" is already allowed above, from the Chinese set.
    "式",  # shiki, a lump-sum item
    "基",  # ki, a founded or standing installation
    "本",  # hon, a long slender object
    "箇所",  # kasho, a location
    "面",  # men, a flat face or panel
    # South Korea (pumsem)
    "EA",
    "식",  # sik, a lump-sum item
    "개소",  # gaeso, a location
    "대",  # dae, a machine or vehicle
    "대·월",  # unit-months, how plant hire is measured rather than a typo
    "세대",  # sedae, a dwelling unit
    # Korean "본" (U+BCF8) is the hangul spelling of the same word the Japanese
    # block writes as "本" (U+672C). Two codepoints, one meaning, and the pair
    # is as easy to mistake for one token as the Cyrillic and Latin months
    # above. Listing only one of them silently rejects the other market.
    "본",
    # Nordics (SfB/CCS, NS 3451, BSAB)
    "mdr",  # Danish/Norwegian "måned" abbreviated, month
    "maan",  # Swedish "månad" abbreviated, month
    "tonn",  # Norwegian tonne (distinct from English "ton")
    "stk",  # stykk/styck, a piece in Nordic languages
    "bolig",  # Danish dwelling unit
    "leilighet",  # Norwegian apartment/dwelling
    "laaegenhet",  # Swedish "lägenhet" (apartment), ASCII-folded
    "sett",  # Norwegian set
    # Generic English
    "unit",  # used by residential demos in various markets
    # Portugal
    "cj",  # conjunto (set)
    "gl",  # global / lump sum (Portuguese)
}

_CATALOG_BY_ID = {c["demo_id"]: c for c in DEMO_CATALOG}
_TEMPLATE_IDS = {t.demo_id for t in PACK_TEMPLATES}


def test_all_pack_slugs_have_a_demo_project() -> None:
    """Every installed partner pack maps to a flagship demo project."""
    from app.core.partner_pack.discovery import discover_packs

    slugs = {p.slug for p in discover_packs()}
    missing = sorted(slugs - set(PACK_DEMO_PROJECT))
    assert not missing, f"partner packs without a demo project mapping: {missing}"


def test_mapped_demo_ids_resolve_to_templates() -> None:
    """Each PACK_DEMO_PROJECT target is a real, loaded DemoTemplate."""
    for slug, demo_id in PACK_DEMO_PROJECT.items():
        assert demo_id in DEMO_TEMPLATES, f"{slug} -> {demo_id} not in DEMO_TEMPLATES"


#: Country packs whose market has one demo so far. They install that one: the
#: second slot used to be filled with a neighbour's bill (a Tokyo office in the
#: Korean pack, a Budapest block in the Polish one, a Rome block in the Spanish
#: one, a Jeddah hospital in the Turkish one), in another currency and
#: validated as another country, which is the opposite of the in-market
#: guarantee this test exists for.
PACKS_WITH_ONE_IN_MARKET_DEMO = frozenset({"japan-jp", "korea-kr", "poland-pl", "spain-es", "turkey-tr"})


def test_every_pack_resolves_to_exactly_two_demos() -> None:
    """Every discovered pack installs two distinct, real, in-market demo projects.

    Some packs (the cross-region modular / renewables packs, and the small
    single-country ones) have no second demo that shares the flagship's country,
    so they pin an explicit ``demo_template_ids`` pair on the manifest. Whether a
    pack relies on the flagship + country-fill default or on an explicit list,
    the one-click installer must land two in-market projects, or the one its
    market has. This guards against the regression where ``aus`` /
    ``modular-prefab`` / ``renewables-epc`` seeded only a single demo.
    """
    from app.core.partner_pack.discovery import discover_packs
    from app.core.partner_pack.full_install import _demo_install_list

    for pack in discover_packs():
        install_ids = _demo_install_list(pack.slug, 2)
        expected = 1 if pack.slug in PACKS_WITH_ONE_IN_MARKET_DEMO else 2
        assert len(install_ids) == expected, f"{pack.slug} resolved {len(install_ids)} demo(s): {install_ids}"
        assert len(set(install_ids)) == len(install_ids), f"{pack.slug} resolved duplicate demos: {install_ids}"
        for demo_id in install_ids:
            assert demo_id in DEMO_TEMPLATES, f"{pack.slug} -> {demo_id} not in DEMO_TEMPLATES"


def test_explicit_demo_template_ids_resolve_to_templates() -> None:
    """Any pack that pins ``demo_template_ids`` references real templates."""
    from app.core.partner_pack.discovery import discover_packs

    for pack in discover_packs():
        for demo_id in pack.demo_template_ids:
            assert demo_id in DEMO_TEMPLATES, f"{pack.slug} demo_template_ids -> {demo_id} not in DEMO_TEMPLATES"


def test_pack_demos_present_in_catalog() -> None:
    """Each pack demo project has a marketplace catalog row with ISO-2 country."""
    required = {"demo_id", "name", "description", "country", "currency", "type", "sections", "positions"}
    for demo_id in PACK_DEMO_PROJECT.values():
        assert demo_id in _CATALOG_BY_ID, f"{demo_id} missing from DEMO_CATALOG"
        row = _CATALOG_BY_ID[demo_id]
        assert required <= set(row), f"{demo_id} catalog row missing keys: {required - set(row)}"
        assert len(row["country"]) == 2, f"{demo_id} country is not ISO-2: {row['country']!r}"
        assert row["positions"] > 0 and row["sections"] > 0


def test_pack_demos_have_a_populated_budget() -> None:
    """Each pack catalog row shows a real budget figure, not an empty cell.

    Pack templates carry no pre-formatted ``budget`` string in
    ``project_metadata`` (unlike the hand-authored built-in rows), so the
    catalog derives it from the priced section items. Regression guard for the
    bug where all pack rows rendered an empty budget on the dashboard demo card.
    """
    for demo_id in PACK_DEMO_PROJECT.values():
        row = _CATALOG_BY_ID[demo_id]
        budget = str(row.get("budget", ""))
        assert budget.strip(), f"{demo_id} catalog budget is empty"
        # Derived labels carry the currency code or a known symbol plus a
        # magnitude suffix (K/M) or a plain figure.
        assert any(ch.isdigit() for ch in budget), f"{demo_id} budget has no figure: {budget!r}"


@pytest.mark.parametrize("template", PACK_TEMPLATES, ids=lambda t: t.demo_id)
def test_pack_template_is_substantial_and_valid(template) -> None:  # noqa: ANN001
    """A flagship country project is large and structurally sound."""
    assert template.sections, f"{template.demo_id} has no sections"
    positions = sum(len(section[3]) for section in template.sections)
    assert positions >= 55, f"{template.demo_id} only has {positions} positions (expected >= 55)"
    assert template.currency and len(template.currency) == 3, f"{template.demo_id} bad currency"

    for section in template.sections:
        _ordinal, _title, _classification, items = section
        assert items, f"{template.demo_id} section {_ordinal} has no items"
        for item in items:
            ordinal, desc, unit, qty, rate, _cls = item
            assert unit in _ALLOWED_UNITS, f"{template.demo_id} {ordinal}: bad unit {unit!r}"
            assert qty > 0, f"{template.demo_id} {ordinal}: non-positive qty {qty}"
            assert rate >= 0, f"{template.demo_id} {ordinal}: negative rate {rate}"
            assert desc.strip(), f"{template.demo_id} {ordinal}: empty description"


# ── The classification standard a demo declares ───────────────────────────
#
# ``resolve_standard`` returns the requested standard when the registry knows
# it and otherwise falls back, first to whatever the region maps to and then
# to the global default, saying nothing either way. So a template can declare
# one standard, be stored under another, and look correct from every angle
# except a direct comparison.

#: Demos whose declared standard the registry does not know.
#:
#: ``hospital-lyon`` used to sit here, declaring ``dpgf`` while FR mapped to
#: ``untec``. The registry learned dpgf in 2026-10 and the entry left.
#:
#: Named rather than skipped by a wildcard, so a second demo cannot join the
#: same silence, and ``test_the_standard_allowlist_still_describes_the_tree``
#: fails the day the registry learns one of these.
_DEMOS_WHOSE_STANDARD_DOES_NOT_RESOLVE = {
    # Nordics and Alpine demos declare native classification standards that
    # the product does not yet register in COUNTRY_TO_STANDARD. The resolver
    # falls back to the nearest common standard (din276 for all of these via
    # their country mapping). The standards are real national systems but have
    # no rules, renderers or section-path logic in the engine yet.
    "office-copenhagen",
    "residential-aarhus",
    "office-oslo",
    "residential-bergen",
    "office-stockholm",
    "residential-gothenburg",
    "office-vienna",
    "residential-salzburg",
    "office-zurich",
    "residential-lausanne",
}


def test_every_demo_standard_resolves_to_itself() -> None:
    """A demo must be stored under the standard it declares.

    Not cosmetic: the standard drives which classification the project page
    labels, which codes the pickers offer, and what a reader believes the bill
    is written to.
    """
    drifted: dict[str, str] = {}
    for template in PACK_TEMPLATES:
        declared = template.classification_standard
        if template.demo_id in _DEMOS_WHOSE_STANDARD_DOES_NOT_RESOLVE:
            continue
        resolved = resolve_standard(declared, region=template.region)
        if resolved.standard != declared:
            drifted[template.demo_id] = f"declares {declared!r}, stored as {resolved.standard!r} via {resolved.source}"

    assert not drifted, (
        "these demos are stored under a classification standard they do not declare, "
        "silently, because the registry does not know the name they asked for: "
        + "; ".join(f"{demo} ({why})" for demo, why in sorted(drifted.items()))
    )


def test_the_standard_allowlist_still_describes_the_tree() -> None:
    """The allowlist must not outlive the thing it describes.

    Both directions: an entry the registry has since learned has to leave, and
    an entry naming a demo that no longer exists has to leave too.
    """
    demo_ids = {t.demo_id for t in PACK_TEMPLATES}
    gone = _DEMOS_WHOSE_STANDARD_DOES_NOT_RESOLVE - demo_ids
    assert not gone, f"{sorted(gone)} is allowlisted and is not a shipped demo any more. Remove it."

    still_drifting = set()
    for template in PACK_TEMPLATES:
        if template.demo_id not in _DEMOS_WHOSE_STANDARD_DOES_NOT_RESOLVE:
            continue
        resolved = resolve_standard(template.classification_standard, region=template.region)
        if resolved.standard != template.classification_standard:
            still_drifting.add(template.demo_id)

    settled = _DEMOS_WHOSE_STANDARD_DOES_NOT_RESOLVE - still_drifting
    assert not settled, (
        f"{sorted(settled)} now resolves to the standard it declares. Remove it from "
        "_DEMOS_WHOSE_STANDARD_DOES_NOT_RESOLVE so the check starts guarding it."
    )


def test_the_registry_and_its_labels_are_two_different_lists() -> None:
    """Pin the gap, because reading either one alone gives a wrong answer.

    ``KNOWN_CLASSIFICATION_STANDARDS`` is what a project can be stored under.
    ``CLASSIFICATION_STANDARD_LABELS`` is what the UI can name. The second is
    the larger, and the difference is legacy names plus two, gaeb and onorm,
    that have rule sets in the engine while no project can be classified to
    them. A reader who measures "how many standards do we support" against
    the wrong list is out by five.
    """
    known = set(KNOWN_CLASSIFICATION_STANDARDS)
    labelled = set(CLASSIFICATION_STANDARD_LABELS)
    assert known < labelled, "the labels no longer cover every storable standard, which is the wrong direction"
    assert labelled - known == {
        "bkp",
        "bsab",
        "gaeb",
        "knr",
        "ns3451",
        "omniclass",
        "onorm",
        "sfb_ccs",
        "uniclass",
        "uniformat",
    }, (
        "the set of labelled-but-unstorable standards changed: "
        f"{sorted(labelled - known)}. If one became storable, the picker should offer it."
    )
