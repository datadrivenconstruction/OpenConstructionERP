# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every onboarding Country Pack preset must name a cost base that really exists.

``countryPacks.ts`` states this as its own invariant: every ``region`` is an
existing CWICR database id. Nothing enforced it. The preset table is
TypeScript, the base registry is Python, and between them sit four
hand-maintained frontend copies of one id list, so no single file could see
both ends.

Two of the twenty-one presets broke it. The commit that wired the national cost
bases renamed ``ZH_SHANGHAI`` to ``ZH_CHINA`` and ``TR_ISTANBUL`` to
``TR_NATIONAL`` across the mirrors, as though each pair were two names for one
base, and added a store-level alias to translate the old id to the new one. The
pairs are not renames. ``ZH_SHANGHAI`` and ``TR_ISTANBUL`` are global-market
catalogues; ``ZH_CHINA`` is the Chinese Dinge base and ``TR_NATIONAL`` the
Turkish Birim Fiyat base, different norm systems in different folders, and all
four load separately. The China and Turkiye packs went on installing the
global-market ids the mirrors had just dropped, so their users got a cost
database that loaded, showed its item count, and then matched nothing in BOQ
autocomplete with no error and no empty state.

Fails in both directions, which is the point:

* a preset naming an id nothing has is red,
* a mirror dropping an id a preset needs is red,
* and all four mirrors drifting together, the case that actually happened and
  the one no frontend-only check can see, is red too, because the registry is
  asked as well as the mirrors.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.costs import base_registry


def _repo_root() -> Path:
    """Walk up until a directory holds both halves of the repository."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "backend").is_dir() and (parent / "frontend").is_dir():
            return parent
    raise RuntimeError(f"repository root not found from {__file__}")


_FRONTEND = _repo_root() / "frontend" / "src"

COUNTRY_PACKS_TS = _FRONTEND / "features" / "onboarding" / "countryPacks.ts"

# One preset object literal. Anchored on ``id`` and ``region`` together so a
# stray ``region`` in a doc comment cannot be mistaken for an entry.
_PRESET = re.compile(r"\{\s*\n\s*id:\s*'(?P<id>[a-z-]+)',.*?\n\s*region:\s*'(?P<region>[A-Z0-9_]+)',", re.S)

# An ``{ id: 'X', ... }`` row in a list-shaped mirror.
_ROW_ID = re.compile(r"\{\s*id:\s*'([A-Z0-9_]+)'")

# A ``KEY: { ... }`` entry in a record-shaped mirror.
_RECORD_KEY = re.compile(r"^\s{2}([A-Z][A-Z0-9_]*):\s*\{", re.M)

# The frontend copies of the cost-base id list, each maintained by hand.
#
# ``ADVISOR_REGION_OPTIONS`` in features/ai/AdvisorPage.tsx is deliberately NOT
# here. It looks like a fifth copy and is not one: it speaks a different
# vocabulary (UK_LONDON, CA_TORONTO, ES_BARCELONA, AE_DUBAI, SA_RIYADH), ids the
# registry has never had. Holding it to the preset list would paint nineteen
# presets red over a separate defect and drown this one. The exclusion is not
# taken on trust - ``test_the_excluded_advisor_list_is_still_a_different_vocabulary``
# below goes red if it ever starts speaking registry ids, which is the moment it
# becomes a real mirror and belongs in this table.
MIRRORS: tuple[tuple[str, Path, str, re.Pattern[str]], ...] = (
    ("REGION_MAP", _FRONTEND / "stores" / "useCostDatabaseStore.ts", "REGION_MAP", _RECORD_KEY),
    (
        "CWICR_DATABASES (onboarding)",
        _FRONTEND / "features" / "onboarding" / "OnboardingWizard.tsx",
        "CWICR_DATABASES",
        _ROW_ID,
    ),
    (
        "CWICR_DATABASES (import)",
        _FRONTEND / "features" / "costs" / "ImportDatabasePage.tsx",
        "CWICR_DATABASES",
        _ROW_ID,
    ),
    ("CWICR_REGIONS", _FRONTEND / "features" / "catalog" / "CatalogPage.tsx", "CWICR_REGIONS", _ROW_ID),
)

# Ids a mirror may carry that the registry does not load. ``CUSTOM`` is the tag
# stamped on a user's own items, not a published base.
NOT_A_LOADABLE_BASE = frozenset({"CUSTOM"})

ONBOARDING_WIZARD_TSX = _FRONTEND / "features" / "onboarding" / "OnboardingWizard.tsx"

# Languages allowed to recommend a national norm base rather than a global
# market catalogue. Empty, and adding to it is a product decision that has to be
# written down here with its reason, not made by editing the map alone.
LANGUAGES_ON_A_NATIONAL_BASE: dict[str, str] = {}

_LANG_ENTRY = re.compile(r"^\s+(?P<lang>[a-z]{2}):\s*'(?P<region>[A-Z0-9_]+)',", re.M)


def _lang_to_region() -> dict[str, str]:
    """Parse the wizard's language -> recommended base map."""
    block = _read_block(ONBOARDING_WIZARD_TSX, "LANG_TO_REGION")
    found = {m.group("lang"): m.group("region") for m in _LANG_ENTRY.finditer(block)}
    if not found:
        pytest.fail(f"parsed no entries out of LANG_TO_REGION in {ONBOARDING_WIZARD_TSX.name}; the shape changed")
    return found


def _read_block(path: Path, const_name: str) -> str:
    """The source of one array/record literal, from its name to its closing line."""
    source = path.read_text(encoding="utf-8")
    marker = f"const {const_name}"
    if marker not in source:
        pytest.fail(f"{path.name} no longer declares `{marker}`; this mirror was renamed or removed")
    body = source.split(marker, 1)[1]
    end = re.search(r"^\];|^\};", body, re.M)
    return body[: end.start()] if end else body


def _presets() -> list[tuple[str, str]]:
    """Parse ``(preset id, region id)`` pairs out of the shipped preset table."""
    source = COUNTRY_PACKS_TS.read_text(encoding="utf-8")
    body = source.split("export const COUNTRY_PACKS", 1)[-1]
    found = [(m.group("id"), m.group("region")) for m in _PRESET.finditer(body)]
    if not found:
        pytest.fail(f"parsed no presets out of {COUNTRY_PACKS_TS}; the table shape changed")
    return found


def _mirror_ids(name: str, path: Path, const_name: str, pattern: re.Pattern[str]) -> set[str]:
    """The region ids one mirror declares."""
    ids = set(pattern.findall(_read_block(path, const_name)))
    if not ids:
        pytest.fail(f"parsed no ids out of {name} in {path.name}; the literal shape changed")
    return ids


def _registry_regions() -> set[str]:
    """Every region id the backend can actually load a base for."""
    return {v.region for v in base_registry.iter_variants()}


def test_the_parsers_still_see_the_tables_they_are_pointed_at() -> None:
    """Guard every parser, so a silent zero can never read as a pass."""
    presets = _presets()
    assert len(presets) >= 20, f"only {len(presets)} presets parsed, the regex has stopped matching the table"
    for name, path, const_name, pattern in MIRRORS:
        ids = _mirror_ids(name, path, const_name, pattern)
        assert len(ids) >= 25, f"{name} parsed down to {len(ids)} ids, the literal shape changed"
    assert len(_registry_regions()) >= 30, "the base registry parsed to fewer regions than it has bases"


def test_every_preset_region_is_a_base_the_backend_can_load() -> None:
    """The direction no frontend check has: all four mirrors can be wrong together."""
    known = _registry_regions()
    unresolved = sorted({(pack, region) for pack, region in _presets() if region not in known})
    assert not unresolved, (
        f"{len(unresolved)} preset(s) name a region the base registry cannot load: {unresolved}. "
        f"A preset installs its region id verbatim, so an id that is not in the registry is a "
        f"one-click button that sets up an empty cost database."
    )


@pytest.mark.parametrize("name,path,const_name,pattern", MIRRORS, ids=[m[0] for m in MIRRORS])
def test_every_preset_region_resolves_in_every_mirror(
    name: str, path: Path, const_name: str, pattern: re.Pattern[str]
) -> None:
    """Red when a preset names an unknown id, and when a mirror loses one it needs."""
    ids = _mirror_ids(name, path, const_name, pattern)
    missing = sorted({(pack, region) for pack, region in _presets() if region not in ids})
    assert not missing, (
        f"{len(missing)} preset region(s) are absent from {name} in {path.name}: {missing}. "
        f"A region with no entry there has no label, no flag and no card, so the base the user "
        f"installed is unnameable in that surface - which is what made rewriting the id to a "
        f"different base look like a fix."
    )


@pytest.mark.parametrize("name,path,const_name,pattern", MIRRORS, ids=[m[0] for m in MIRRORS])
def test_no_mirror_offers_a_base_the_backend_cannot_load(
    name: str, path: Path, const_name: str, pattern: re.Pattern[str]
) -> None:
    """A card for an id the registry lacks is a button that loads nothing."""
    known = _registry_regions() | NOT_A_LOADABLE_BASE
    unknown = sorted(_mirror_ids(name, path, const_name, pattern) - known)
    assert not unknown, f"{name} in {path.name} offers {len(unknown)} id(s) the registry cannot load: {unknown}"


def test_the_two_conflated_pairs_are_four_separate_bases() -> None:
    """Pin the fact the alias got wrong, so it cannot be re-asserted quietly.

    Asking the registry rather than restating the claim. If these four ever
    collapse into two, the alias was right after all and this whole file is
    wrong, which is a conversation worth forcing rather than a silent merge.
    """
    pairs = (("ZH_SHANGHAI", "ZH_CHINA"), ("TR_ISTANBUL", "TR_NATIONAL"))
    for market_id, national_id in pairs:
        market = base_registry.variant_by_region(market_id)
        national = base_registry.variant_by_region(national_id)
        assert market is not None, f"{market_id} is no longer a loadable base"
        assert national is not None, f"{national_id} is no longer a loadable base"
        assert not base_registry.is_national_region(market_id), f"{market_id} became a national base"
        assert base_registry.is_national_region(national_id), f"{national_id} stopped being a national base"
        assert market.workitems_path != national.workitems_path, (
            f"{market_id} and {national_id} now read the same work items, so they are one base "
            f"after all and the aliasing this file forbids would be correct"
        )


def test_the_language_map_recommends_bases_that_exist() -> None:
    """The wizard's other route into a cost base, held to the same registry."""
    known = _registry_regions()
    unresolved = sorted((lang, region) for lang, region in _lang_to_region().items() if region not in known)
    assert not unresolved, f"LANG_TO_REGION recommends {len(unresolved)} base(s) the registry cannot load: {unresolved}"


def test_no_language_recommends_a_national_norm_base() -> None:
    """The split this file exists to stop, in its second and quieter form.

    A user reaches a cost base two ways: the country pack, and the language
    step. Both used to name China and Turkiye, and after ``cdf7391c1`` they
    named different bases for the same market, so which catalogue a user got
    depended on which step they came through.

    Deliberately NOT asserting that the language map equals the country map. A
    language is not a country: ``es`` serves both the Spain and Mexico packs,
    and ``sv`` also answers for Norwegian, Danish and Finnish, so equality would
    be the wrong rule and would go red on entries that are correct. What is
    asserted is the rule the map actually follows for all of its entries - a
    language names a global-market catalogue, never one country's own norm
    system, because recommending the Chinese Dinge base to every zh speaker is
    a different claim from repricing the global base into China. Pointing a
    language at a national base stays possible; it just has to be written into
    ``LANGUAGES_ON_A_NATIONAL_BASE`` with a reason first.
    """
    offenders = {
        lang: region
        for lang, region in _lang_to_region().items()
        if base_registry.is_national_region(region) and lang not in LANGUAGES_ON_A_NATIONAL_BASE
    }
    assert not offenders, (
        f"{sorted(offenders.items())} recommend a national norm base. Either point the language at that "
        f"market's global catalogue, or record the decision in LANGUAGES_ON_A_NATIONAL_BASE with its reason."
    )


def test_a_recorded_language_exception_is_a_real_one() -> None:
    """Keep the exception list honest: no stale entries, no empty reasons."""
    langs = _lang_to_region()
    for lang, reason in LANGUAGES_ON_A_NATIONAL_BASE.items():
        assert lang in langs, f"LANGUAGES_ON_A_NATIONAL_BASE names '{lang}', which LANG_TO_REGION no longer has"
        assert base_registry.is_national_region(langs[lang]), (
            f"'{lang}' now points at {langs[lang]}, which is not a national base, so its exception is stale"
        )
        assert reason.strip(), f"the exception for '{lang}' carries no reason"


def test_the_excluded_advisor_list_is_still_a_different_vocabulary() -> None:
    """The named exception, checked rather than trusted.

    ``ADVISOR_REGION_OPTIONS`` is left out of ``MIRRORS`` because its ids are
    not registry ids. That is a statement about today's code, so it is measured
    here: the moment the list is cleaned up to speak registry ids it becomes a
    real fifth mirror and has to join the table above, and this test is what
    says so.
    """
    advisor = _mirror_ids(
        "ADVISOR_REGION_OPTIONS",
        _FRONTEND / "features" / "ai" / "AdvisorPage.tsx",
        "ADVISOR_REGION_OPTIONS",
        re.compile(r"'([A-Z0-9_]+)'"),
    )
    foreign = sorted(advisor - _registry_regions())
    assert foreign, (
        "ADVISOR_REGION_OPTIONS now names only ids the registry loads, so it is a real mirror "
        "of this id list. Add it to MIRRORS above and delete this test."
    )
