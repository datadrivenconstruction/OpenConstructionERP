# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every region the product offers must name a country the registry knows.

**The defect this file exists to prevent.**

``classification_registry.normalise_region`` reduces a region string to an
ISO 3166-1 alpha-2 code, and two separate axes hang off the answer: the
classification standard a project's section paths render against
(:func:`resolve_standard`) and the country validation rule packs a BOQ import
runs (``boq.router._build_rule_sets``). Both read the same normaliser.

The region strings it is handed come from ``project.region``, which is written
by the region picker in
``frontend/src/features/projects/CreateProjectPage.tsx``. That picker speaks
neither ISO codes nor the macro names the alias table already carried. It ships
prose and glued CamelCase: ``Russia``, ``Brazil``, ``GulfStates``. Four of its
thirty shipped options resolved. The other twenty-six normalised to ``None``,
so ``resolve_standard`` returned ``DEFAULT_CLASSIFICATION_STANDARD`` with
``source="default"`` and ``_build_rule_sets`` looked up an empty country key. A
Moscow project was classified against German cost groups and ran no GESN rules,
and nothing anywhere went red, because a fall-through still returns a plausible
standard.

**Why the population is read from the picker file rather than listed here.**

``test_every_shipped_region_option_reaches_a_calendar.py`` documents the same
shape on the schedule resolver: twenty-one of the thirty options resolved to
DEFAULT while every assertion passed, because the gate walked the resolver's own
ISO-keyed tables and the picker was never in the population at all. The
instrument and the product spoke different vocabularies and agreed with
themselves. Copying the option values into this module would rebuild exactly
that: the copy and the picker would drift, and both sides would stay internally
consistent while drifting. So the parse below reads the shipped file, and is
cross-checked two independent ways, because a parse that silently matches
nothing is a green gate over an empty population - the same failure wearing a
different hat.

**What this file asserts, and what it deliberately does not.**

It asserts that every shipped option is *classified*: it either reduces to a
country, or it is named below with a reason. It cannot assert the country is the
*right* one for a macro region covering several. Where the members disagree the
anchor is recorded in :data:`MACRO_OPTION_ANCHORS` with what it costs, and the
anchor is asserted, so a silent re-anchoring is red even though the option would
still "resolve".
"""

from __future__ import annotations

import re
from pathlib import Path
from types import MappingProxyType

import pytest

from app.core import classification_registry
from app.core.classification_registry import (
    COUNTRY_TO_STANDARD,
    DEFAULT_CLASSIFICATION_STANDARD,
    normalise_region,
    resolve_standard,
    standard_for_country,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PICKER = REPO_ROOT / "frontend" / "src" / "features" / "projects" / "CreateProjectPage.tsx"

#: The picker's free-text escape hatch. It is a UI mode rather than a region and
#: never reaches the backend as itself: the page substitutes the typed text
#: before submitting. Excluded from the population for that reason, not waived.
FREE_TEXT_OPTION = "__custom__"

#: Options that are meant to answer the default, named so that "we decided this
#: one has no country" is never confused with "nobody looked". An option in this
#: table still falls to DEFAULT_CLASSIFICATION_STANDARD, and its per-process
#: warning from ``_report_default`` is therefore expected rather than a signal.
PICKER_REGIONS_WITH_NO_COUNTRY: dict[str, str] = {
    "INTL": (
        "International / Multi-region names no country by construction, so there is nothing to "
        "resolve to and any anchor would be a guess dressed as an answer. DIN 276 by fall-through "
        "is as defensible as any other guess here, and a user who wants a different one names the "
        "standard explicitly, which beats the region."
    ),
}

#: The picker's macro options and the member country each is anchored on, with
#: what the anchor costs. Asserted below, so re-pointing an anchor is a
#: deliberate edit here rather than a silent change of answer for a whole region.
#:
#: Where the members agree the anchor is only a spelling. Where they disagree the
#: reason says so, because "every member reads this" and "we picked one" produce
#: the same resolver output and only a written reason tells them apart.
MACRO_OPTION_ANCHORS: dict[str, tuple[str, str]] = {
    "Nordics": (
        "SE",
        "Sweden, Norway, Denmark and Finland all read DIN 276 in COUNTRY_TO_STANDARD, so the "
        "anchor changes no answer and only decides which country the resolution reports.",
    ),
    "LatinAmerica": (
        "MX",
        "The residual 'Other' option. Every Spanish-speaking market in the table reads "
        "MasterFormat; Brazil is the one member that does not and it ships its own picker option "
        "resolving to SINAPI, so it never reaches this anchor.",
    ),
    "MiddleEast": (
        "AE",
        "Matches the MIDDLE_EAST alias the table already carried. Every Gulf and Levantine market "
        "in COUNTRY_TO_STANDARD reads MasterFormat, so the anchor changes no answer.",
    ),
    "GulfStates": (
        "AE",
        "Matches the GULF and GCC aliases. All six GCC states read MasterFormat, so the anchor changes no answer.",
    ),
    "NorthAfrica": (
        "EG",
        "Egypt, Morocco, Tunisia and Algeria all read MasterFormat, so the anchor changes no "
        "answer. Egypt is the largest construction market in the option.",
    ),
    "EastAfrica": (
        "KE",
        "Kenya, Uganda and Tanzania all read NRM, so the anchor changes no answer.",
    ),
    "WestAfrica": (
        "NG",
        "A genuine split, and the anchor is a decision. Nigeria and Ghana read NRM while Senegal, "
        "Ivory Coast and Cameroon read UNTEC on the DTU lineage. Nigeria is the larger market and "
        "the one the country programme ships. The alternative is not neutrality but DIN 276, which "
        "is wrong for every member, so anchoring is strictly better than leaving it unresolved. A "
        "Francophone project names UNTEC explicitly, which beats the region.",
    ),
    "SoutheastAsia": (
        "ID",
        "A genuine split, and the anchor is a decision. Indonesia, Thailand, Vietnam and the "
        "Philippines read MasterFormat while Malaysia and Singapore read NRM on RICS-aligned QS "
        "practice. Indonesia matches the ASIA_PAC alias the table already anchored, so the two "
        "spellings of the same region cannot answer differently.",
    ),
}


#: Quote-agnostic on purpose: the repo has no frontend autoformatter, so the file
#: may be edited into double quotes at any time, and a single-quote-only pattern
#: would then match nothing and pass over an empty population.
_OPTION_RE = re.compile(r"""\{\s*value:\s*(['"])(.*?)\1\s*,\s*label:\s*(['"])(.*?)\3\s*\}""")


def _picker_block() -> str:
    """The REGION_GROUPS literal, as text.

    Raises:
        AssertionError: The picker file or the literal is not where this gate
            expects it. Failing loudly matters more than usual: a gate that
            cannot find its population must never be allowed to pass empty.
    """
    assert PICKER.is_file(), (
        f"the project region picker is not at {PICKER}. This gate reads the shipped picker as its "
        "population and cannot fall back to a copy, because a copy is what it exists to prevent. "
        "Re-point PICKER at the file that now defines REGION_GROUPS."
    )
    source = PICKER.read_text(encoding="utf-8")
    marker = "const REGION_GROUPS"
    assert marker in source, (
        f"{PICKER.name} no longer declares {marker}. If the region options moved to a shared "
        "module, re-point this gate at it; do not copy the values here."
    )
    start = source.index(marker)
    return source[start : source.index("\n];", start)]


def _shipped_options() -> list[tuple[str, str]]:
    """Every ``{value, label}`` pair the region picker ships, in file order.

    Returns:
        Pairs of option value and human label.
    """
    return [(m.group(2), m.group(4)) for m in _OPTION_RE.finditer(_picker_block())]


def _population() -> list[tuple[str, str]]:
    """The shipped options minus the free-text UI mode."""
    return [o for o in _shipped_options() if o[0] != FREE_TEXT_OPTION]


# ── The population, cross-checked before anything is asserted over it ─────


def test_the_picker_parse_finds_every_option_the_file_declares() -> None:
    """Cross-check the population two independent ways before trusting it.

    A regex that matches nothing yields an empty population, and every
    ``for option in population`` assertion below then passes while measuring
    nothing. So the count of parsed pairs is checked against a count taken a
    different way - occurrences of the ``value:`` key - and the free-text option
    is asserted present, since it is the one value guaranteed to be in the list.
    """
    block = _picker_block()
    parsed = _shipped_options()
    declared = len(re.findall(r"\bvalue:", block))

    assert parsed, (
        "the option regex matched nothing in the REGION_GROUPS block. The picker's quoting or "
        "option shape has changed; fix the pattern, because an empty population passes every other "
        "assertion in this file."
    )
    assert len(parsed) == declared, (
        f"the option regex found {len(parsed)} options but the block declares {declared} 'value:' "
        "keys. The parse is dropping options, and a dropped option is one this gate never checks.\n"
        f"parsed: {[v for v, _ in parsed]}"
    )
    assert FREE_TEXT_OPTION in {v for v, _ in parsed}, (
        f"{FREE_TEXT_OPTION!r} is missing from the parsed options. It is the picker's free-text "
        "escape hatch and has always shipped; its absence means the parse is reading the wrong "
        "block, or the picker changed in a way this gate has not caught up with."
    )
    assert len(parsed) == len({v for v, _ in parsed}), (
        f"the picker ships a duplicate option value: {[v for v, _ in parsed]}"
    )


# ── The gate ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("value", "label"), _population())
def test_a_shipped_region_option_resolves_to_a_country_or_is_declared_countryless(value: str, label: str) -> None:
    """No option may answer the default by accident.

    Reducing to a country passes. Falling to the default passes only when
    :data:`PICKER_REGIONS_WITH_NO_COUNTRY` names the option and says why.
    Anything else is a region the product offers that reaches neither a
    classification standard nor a country rule pack, which is how twenty-six of
    the thirty options shipped classified against DIN 276.
    """
    country = normalise_region(value)
    resolved = resolve_standard(None, value)

    if country is not None:
        assert resolved.matched, (
            f"{value!r} normalises to {country!r} but resolve_standard still reports "
            f"source={resolved.source!r}; the country has no entry in COUNTRY_TO_STANDARD."
        )
        assert standard_for_country(country) == resolved.standard
        return

    assert value in PICKER_REGIONS_WITH_NO_COUNTRY, (
        f"the project region picker ships {value!r} ({label}) and normalise_region reduces it to no "
        f"country, so resolve_standard falls through to {DEFAULT_CLASSIFICATION_STANDARD!r} with "
        "source='default' and boq.router._build_rule_sets looks up an empty country key.\n"
        "Nothing decided that this region reads German cost groups; it is simply absent from every "
        "keyspace the normaliser reads, and an absent region is indistinguishable from one that "
        "was considered.\n"
        "Close it one of two ways:\n"
        "  - add it to classification_registry.REGION_ALIAS_TO_COUNTRY, pointing at the country it "
        "stands for, or at a member country if it is a macro region, and record the anchor in "
        "MACRO_OPTION_ANCHORS here;\n"
        "  - add it to PICKER_REGIONS_WITH_NO_COUNTRY with the reason it genuinely names no "
        "country.\n"
        "Do not delete this assertion: it is the only thing connecting the picker's vocabulary to "
        "the resolver's."
    )


@pytest.mark.parametrize(("value", "expected"), sorted((v, a) for v, (a, _) in MACRO_OPTION_ANCHORS.items()))
def test_a_macro_option_resolves_to_the_anchor_this_file_names(value: str, expected: str) -> None:
    """The anchor is asserted, not merely described.

    The test above would stay green if a macro option were re-pointed at another
    member, because it would still resolve. For a region covering countries that
    read different standards that is a change of answer for every project in it,
    so it has to be a deliberate edit here.
    """
    actual = normalise_region(value)
    assert actual == expected, (
        f"the picker option {value!r} now resolves to {actual!r}, not the {expected!r} this file "
        f"records for it ({standard_for_country(expected)} rather than {standard_for_country(actual)}). "
        "Re-anchoring a macro region changes the standard for every project stored under it; update "
        "MACRO_OPTION_ANCHORS with the new reason if that is intended."
    )


def test_no_declaration_names_an_option_the_picker_no_longer_ships() -> None:
    """A stale waiver is a waiver nobody reads.

    An entry naming a value the picker has dropped, or one that now resolves on
    its own, is dead text that makes the tables look more considered than they
    are.
    """
    shipped = {v for v, _ in _shipped_options()}
    problems: list[str] = []

    for value in sorted(PICKER_REGIONS_WITH_NO_COUNTRY):
        if value not in shipped:
            problems.append(f"  PICKER_REGIONS_WITH_NO_COUNTRY[{value!r}]: the picker no longer ships this option")
        elif normalise_region(value) is not None:
            problems.append(
                f"  PICKER_REGIONS_WITH_NO_COUNTRY[{value!r}]: now resolves to "
                f"{normalise_region(value)!r}, so the entry is stale and should be deleted"
            )
    for value in sorted(MACRO_OPTION_ANCHORS):
        if value not in shipped:
            problems.append(f"  MACRO_OPTION_ANCHORS[{value!r}]: the picker no longer ships this option")

    assert problems == [], "these declarations no longer describe anything:\n" + "\n".join(problems)


def test_no_option_is_both_anchored_and_declared_countryless() -> None:
    """The two tables mean opposite things, so an option in both is unreadable."""
    both = sorted(set(MACRO_OPTION_ANCHORS) & set(PICKER_REGIONS_WITH_NO_COUNTRY))
    assert both == [], f"{both} are declared both anchored on a country and countryless; pick one"


def test_every_declaration_carries_a_reason() -> None:
    """An empty reason is a waiver with the justification left out."""
    thin = sorted(
        f"  {value}: {reason!r}"
        for value, reason in (
            *PICKER_REGIONS_WITH_NO_COUNTRY.items(),
            *((v, r) for v, (_, r) in MACRO_OPTION_ANCHORS.items()),
        )
        if len(reason.strip()) < 20
    )
    assert thin == [], (
        "these declarations carry no usable reason:\n"
        + "\n".join(thin)
        + "\nThe reason is the whole value of the table; without it the entry is a silenced "
        "assertion."
    )


def test_every_anchor_names_a_country_the_registry_knows() -> None:
    """An anchor pointing at a country with no standard resolves to a fall-through."""
    dangling = sorted(f"{v} -> {a}" for v, (a, _) in MACRO_OPTION_ANCHORS.items() if a not in COUNTRY_TO_STANDARD)
    assert dangling == [], f"these anchors point at countries COUNTRY_TO_STANDARD does not name: {dangling}"


# ── The specific defect, pinned ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("region", "standard"),
    [
        ("Russia", "gesn"),
        ("China", "gb50500"),
        ("Brazil", "sinapi"),
        ("Spain", "bc3"),
        ("Italy", "voci"),
        ("Turkey", "birimfiyat"),
        ("Japan", "sekisan"),
        ("Korea", "kbim"),
        ("India", "nrm"),
    ],
)
def test_a_country_with_a_native_standard_is_not_given_the_german_one(region: str, standard: str) -> None:
    """Pin the countries where the fall-through was most obviously wrong.

    The parametrized gate above would go green again if one of these were added
    to ``PICKER_REGIONS_WITH_NO_COUNTRY``, which is a legitimate way to close it
    for a genuinely countryless option and never for these. Every one of them
    names exactly one country, and that country has a native cost system the
    product already renders; DIN 276 is not a defensible answer for any of them.
    """
    resolved = resolve_standard(None, region)
    assert resolved.standard == standard, (
        f"the picker option {region!r} resolves to {resolved.standard!r} (source={resolved.source!r}); "
        f"a {region} project reads {standard}."
    )
    assert resolved.source == "region"


def test_a_resolved_region_also_reaches_its_country_validation_rule_pack() -> None:
    """The second axis the same normaliser feeds, asserted on the same options.

    ``boq.router._build_rule_sets`` keys its country table off
    ``normalise_region`` too, so an unresolvable region lost the country rule
    pack as well as the standard. Testing only the standard would leave half the
    defect uncovered and the half that a validation run actually reports on.
    """
    from app.modules.boq.router import _build_rule_sets

    expected = {"Russia": "gesn", "China": "gbt50500", "India": "cpwd", "Brazil": "sinapi", "France": "dpgf"}
    missing = {
        region: pack for region, pack in expected.items() if pack not in _build_rule_sets(["boq_quality"], "", region)
    }
    assert missing == {}, (
        f"these picker regions reach no country rule pack: {missing}. A BOQ imported into such a "
        "project is validated against the generic rules only, and the country rules the market "
        "requires never run."
    )


# ── Negative control ──────────────────────────────────────────────────────


def test_the_gate_is_actually_watching_the_alias_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """Break the mechanism at the one point unique to it, expect red.

    The fix is "the alias table speaks the picker's vocabulary". Emptying the
    table is a break nothing else in this module could produce. If the
    parametrized gate above can still pass with no aliases at all, it is passing
    for some other reason and proves nothing about the fix.

    ``normalise_region`` reads the mapping from its own module namespace at call
    time, so replacing the attribute is enough. The catalogue mapping is built
    from the alias table and memoised, so its cache is cleared on both sides.
    """
    monkeypatch.setattr(classification_registry, "REGION_ALIAS_TO_COUNTRY", MappingProxyType({}))
    classification_registry._catalogue_region_to_country.cache_clear()
    classification_registry._reported_defaults.clear()
    try:
        unresolved = [
            value
            for value, _ in _population()
            if classification_registry.normalise_region(value) is None and value not in PICKER_REGIONS_WITH_NO_COUNTRY
        ]
    finally:
        monkeypatch.undo()
        classification_registry._catalogue_region_to_country.cache_clear()
        classification_registry._reported_defaults.clear()

    assert unresolved, (
        "emptying REGION_ALIAS_TO_COUNTRY left every picker option resolving, so this gate is not "
        "reading the alias table and would stay green through the original defect"
    )
