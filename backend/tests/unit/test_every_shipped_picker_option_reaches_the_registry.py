# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every option the project create page offers must reach the registry.

``frontend/src/features/projects/CreateProjectPage.tsx`` holds two hand-written
mirrors of ``app.core.classification_registry``, and both have shipped a defect
of the same shape. The region picker writes strings the registry could not read.
The standards picker writes values the registry reads and names a country beside
each one that the registry has an opinion about. This file covers both, because
they share a file, a failure mode and a parse, and splitting them would leave
the second gate as something for somebody to write later.

**The defect this file exists to prevent.**

``classification_registry.normalise_region`` reduces a region string to an
ISO 3166-1 alpha-2 code, and two separate axes hang off the answer: the
classification standard a project's section paths render against
(:func:`resolve_standard`) and the country validation rule packs a BOQ import
runs (``boq.router._build_rule_sets``). Both read the same normaliser.

The region strings it is handed come from ``project.region``, which the region
picker in ``frontend/src/features/projects/CreateProjectPage.tsx`` writes, and
so does anything else that calls the API: ``ProjectCreate.region`` is a plain
``str`` of at most 100 characters and its validator strips whitespace and
nothing else, on purpose (A-PROJ-02, so any market can be named). The picker is
therefore the population this file can enumerate, not the population that can
reach the resolver. That picker speaks
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

**The second mirror: the standards picker.**

``STANDARD_GROUPS`` in the same file names a country beside each standard, and
the wording is hand-written because the registry has no opinion about wording.
So the country beside the name can drift from the country the registry maps, and
did: VOCI was offered as "VOCI (Austria)" while ``COUNTRY_TO_STANDARD`` has only
ever resolved it for IT. An Austrian who picked the one row carrying their own
country's name wrote the Italian standard onto their project, and an Italian
scanning the list for Italy found nothing. That was fixed by hand and checked
once by hand; this half of the file is what makes the check repeat.

The country names in those labels are read against
``i18n_foundation/seed_data/countries.json``, the product's own 198-row country
registry, rather than a name-to-code table written here. A table written here
would be a third mirror of the same data, which is the defect this file exists
to catch.

Five standards carry a display label and no country:
``gaeb``, ``omniclass``, ``onorm``, ``uniclass`` and ``uniformat``. They are
outside ``KNOWN_CLASSIFICATION_STANDARDS`` and so outside the country-mapping
assertions, which is the right scope: a standard no country reads cannot be
mis-attributed to one.

``onorm`` used to be named here as the one that "reads like an omission rather
than a choice", on the grounds that OENORM is Austria's standard while Austria
resolves to ``din276``. Measured 2026-09-07, it reads like a choice:

* The OENORM rules the product ships are B 2063, the LV position-format
  standard - ordinals ``XX.XX.XXXXA`` plus a description-length floor
  (``ONORMPositionFormat`` in ``validation/rules/__init__.py``). B 2063 is a
  tender-document structure, the Austrian counterpart of GAEB, and not a
  cost-group hierarchy. B 1801-1 is the cost-group standard and it appears
  nowhere in the tree.
* Austria already runs those rules. ``boq.router._build_rule_sets`` carries
  ``COUNTRY_RULES["AT"] = ["gaeb", "onorm"]``, keyed on the country rather than
  on the classification standard, so an Austrian BOQ is validated against
  B 2063 today without any registry entry.
* Mapping ``AT`` to ``onorm`` would change no section path. The renderer walks
  ``classification_order()`` and takes the first standard the CostItem carries
  a code for, and no shipped cost row carries an ``onorm`` key, so the answer
  would still be the ``din276`` code the DACH rows do carry. The mapping alone
  would change only what the product claims.

So ``onorm`` sits with ``gaeb``: an exchange-format vocabulary living in a
cost-breakdown registry, country-less because it is not a breakdown. Whether
Austria should get B 1801-1 cost groups is a live product question, and it
needs a code table and seeded codes rather than a line in the map.

**Would anyone know if a project fell to the default?**

No, unless they are reading logs. ``_report_default`` emits one WARNING naming
the region, deduplicated per process and capped at 512 distinct strings, and
nothing in ``app`` reads ``StandardResolution.matched`` or ``.source``. There is
no API field, no operator view and nothing a user sees, so the only signal that
a project is being classified against a fallback is a log line nobody has a
reason to open. That is why the check has to happen here: afterwards there is
nothing to notice.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import MappingProxyType

import pytest

import app
from app.core import classification_registry
from app.core.classification_registry import (
    CLASSIFICATION_STANDARD_LABELS,
    COUNTRY_TO_STANDARD,
    DEFAULT_CLASSIFICATION_STANDARD,
    KNOWN_CLASSIFICATION_STANDARDS,
    normalise_region,
    resolve_standard,
    standard_for_country,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PICKER = REPO_ROOT / "frontend" / "src" / "features" / "projects" / "CreateProjectPage.tsx"

#: The product's own country registry, 198 rows, resolved from the imported
#: package rather than a path guess. Read for ``name_en`` so the standards
#: labels are checked against a country list the product ships rather than one
#: written in this file.
COUNTRIES_JSON = Path(app.__file__).resolve().parent / "modules" / "i18n_foundation" / "seed_data" / "countries.json"

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


def _picker_block(declaration: str) -> str:
    """One option-group literal from the create page, as text.

    Args:
        declaration: The ``const`` name to read, ``REGION_GROUPS`` or
            ``STANDARD_GROUPS``.

    Raises:
        AssertionError: The picker file or the literal is not where this gate
            expects it. Failing loudly matters more than usual: a gate that
            cannot find its population must never be allowed to pass empty.
    """
    assert PICKER.is_file(), (
        f"the project create page is not at {PICKER}. This gate reads the shipped page as its "
        "population and cannot fall back to a copy, because a copy is what it exists to prevent. "
        f"Re-point PICKER at the file that now defines {declaration}."
    )
    source = PICKER.read_text(encoding="utf-8")
    marker = f"const {declaration}"
    assert marker in source, (
        f"{PICKER.name} no longer declares {marker}. If the options moved to a shared module, "
        "re-point this gate at it; do not copy the values here."
    )
    start = source.index(marker)
    return source[start : source.index("\n];", start)]


def _options_in(declaration: str) -> list[tuple[str, str]]:
    """Every ``{value, label}`` pair in one option-group literal, in file order.

    Args:
        declaration: The ``const`` name to read.

    Returns:
        Pairs of option value and human label.
    """
    return [(m.group(2), m.group(4)) for m in _OPTION_RE.finditer(_picker_block(declaration))]


def _assert_parse_is_complete(declaration: str) -> list[tuple[str, str]]:
    """Cross-check one literal's parse two independent ways, and return it.

    A regex that matches nothing yields an empty population, and every
    ``for option in population`` assertion over it then passes while measuring
    nothing. So the count of parsed pairs is checked against a count taken a
    different way - occurrences of the ``value:`` key - and the free-text option
    is asserted present, since it is the one value both literals are guaranteed
    to carry.

    Args:
        declaration: The ``const`` name to read.

    Returns:
        The parsed pairs.
    """
    block = _picker_block(declaration)
    parsed = _options_in(declaration)
    declared = len(re.findall(r"\bvalue:", block))

    assert parsed, (
        f"the option regex matched nothing in the {declaration} block. The picker's quoting or "
        "option shape has changed; fix the pattern, because an empty population passes every other "
        "assertion in this file."
    )
    assert len(parsed) == declared, (
        f"the option regex found {len(parsed)} options in {declaration} but the block declares "
        f"{declared} 'value:' keys. The parse is dropping options, and a dropped option is one this "
        f"gate never checks.\nparsed: {[v for v, _ in parsed]}"
    )
    assert FREE_TEXT_OPTION in {v for v, _ in parsed}, (
        f"{FREE_TEXT_OPTION!r} is missing from the parsed {declaration} options. It is the picker's "
        "free-text escape hatch and has always shipped; its absence means the parse is reading the "
        "wrong block, or the picker changed in a way this gate has not caught up with."
    )
    assert len(parsed) == len({v for v, _ in parsed}), (
        f"{declaration} ships a duplicate option value: {[v for v, _ in parsed]}"
    )
    return parsed


def _shipped_options() -> list[tuple[str, str]]:
    """Every ``{value, label}`` pair the region picker ships, in file order."""
    return _options_in("REGION_GROUPS")


def _population() -> list[tuple[str, str]]:
    """The shipped options minus the free-text UI mode."""
    return [o for o in _shipped_options() if o[0] != FREE_TEXT_OPTION]


# ── The population, cross-checked before anything is asserted over it ─────


@pytest.mark.parametrize("declaration", ["REGION_GROUPS", "STANDARD_GROUPS"])
def test_the_picker_parse_finds_every_option_the_file_declares(declaration: str) -> None:
    """Cross-check both populations two independent ways before trusting them."""
    _assert_parse_is_complete(declaration)


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


# ── The second mirror: the standards picker ───────────────────────────────

#: Tokens that appear in a standards label beside the country names and name no
#: single country. Named rather than skipped, because a token the resolver
#: cannot read is exactly the shape that let "Austria" sit beside VOCI: silence
#: from an instrument is indistinguishable from agreement.
STANDARD_LABEL_TOKENS_THAT_NAME_NO_COUNTRY: dict[str, str] = {
    "CIS": (
        "A bloc rather than a country, and the registry maps all five of its construction markets "
        "to GESN individually (RU, UA, BY, KZ, MN). The label says CIS because a Kazakh estimator "
        "would not otherwise recognise the row as theirs, and there is nothing for it to resolve "
        "to that would say more than the countries already do."
    ),
}

_PARENTHESISED = re.compile(r"\(([^)]*)\)")


def _country_tokens(label: str) -> list[str]:
    """The country names a standards label claims, in order.

    The convention in the shipped labels is a parenthesised tail listing the
    countries the standard is read in, separated by a slash or a comma:
    ``"MasterFormat (US / Canada)"``, ``"GESN / FER (Russia, CIS)"``. Text
    before the parenthesis is the standard's own name and never a country, which
    matters because ``"NRM 1/2"`` and ``"GESN / FER"`` both carry the separator.

    Args:
        label: The option label as shipped.

    Returns:
        The trimmed tokens, empty when the label names no country.
    """
    return [
        piece.strip() for group in _PARENTHESISED.findall(label) for piece in re.split(r"[/,]", group) if piece.strip()
    ]


def _country_name_to_iso() -> dict[str, str]:
    """English country name to alpha-2, from the product's shipped registry.

    Raises:
        AssertionError: The registry is missing or implausibly small. An empty
            mapping would make every label token unresolvable and the whole
            standards half of this file would then measure nothing.
    """
    assert COUNTRIES_JSON.is_file(), (
        f"the shipped country registry is not at {COUNTRIES_JSON}. This gate reads it so the "
        "standards labels are checked against a country list the product ships; do not replace it "
        "with a name-to-code table written in this file, which would be a third mirror of the same "
        "data."
    )
    rows = json.loads(COUNTRIES_JSON.read_text(encoding="utf-8"))
    mapping = {row["name_en"].upper(): row["iso_code"].upper() for row in rows if row.get("name_en")}
    assert len(mapping) > 150, (
        f"the shipped country registry resolved {len(mapping)} names, which is too few to be the "
        "real list. Every label token would fall through as unresolvable and this half of the file "
        "would pass over an empty population."
    )
    return mapping


def _iso_for_label_token(token: str) -> str | None:
    """The country a standards-label token names, or ``None``.

    Tried through the product's own resolvers in order: ``normalise_region``,
    which knows the aliases and macro names, then the shipped country registry's
    English names, which knows the spellings the resolver deliberately does not
    chase.
    """
    return normalise_region(token) or _country_name_to_iso().get(token.upper())


def test_every_shipped_standard_option_is_one_the_registry_can_resolve() -> None:
    """A value outside the known set is written and then dropped on the floor.

    ``resolve_standard`` accepts an explicit standard only when it is in
    ``KNOWN_CLASSIFICATION_STANDARDS``. An option carrying a value that is
    merely labelled writes it onto the project and then falls through to the
    region and to DIN 276, with no error and nothing a user could see. Three
    options - UniFormat, Uniclass and OmniClass - and a short ``gbt`` for China
    once did exactly that.
    """
    offenders = sorted(
        f"{value!r} ({label})"
        for value, label in _options_in("STANDARD_GROUPS")
        if value != FREE_TEXT_OPTION and value not in KNOWN_CLASSIFICATION_STANDARDS
    )
    assert offenders == [], (
        f"the standards picker offers {offenders}, which resolve_standard does not accept. Writing "
        "one onto a project stores a standard the product then ignores, falling through to the "
        f"region and to {DEFAULT_CLASSIFICATION_STANDARD!r}. Being in "
        "CLASSIFICATION_STANDARD_LABELS is not enough: a standard has a label so a CostItem encoded "
        "against it can be named, and it is known only if the product renders a section path for it."
    )


@pytest.mark.parametrize(
    ("value", "label"),
    [o for o in _options_in("STANDARD_GROUPS") if o[0] != FREE_TEXT_OPTION and _country_tokens(o[1])],
)
def test_a_standards_label_names_the_country_the_registry_maps(value: str, label: str) -> None:
    """The country beside the name must be one that reads that standard.

    The label is hand-written and the registry has no opinion about wording, so
    the two can drift, and did: "VOCI (Austria)" while ``COUNTRY_TO_STANDARD``
    resolves VOCI only for IT. An Austrian picking the one row carrying their
    country's name wrote the Italian standard onto their project, and neither
    side was internally inconsistent, so nothing anywhere went red.
    """
    problems: list[str] = []
    for token in _country_tokens(label):
        iso = _iso_for_label_token(token)
        if iso is None:
            if token in STANDARD_LABEL_TOKENS_THAT_NAME_NO_COUNTRY:
                continue
            problems.append(
                f"  {token!r} names no country the product knows. Neither normalise_region nor the "
                "shipped country registry resolves it, so nobody can check what it claims. Spell it "
                "the way the country registry does, or name it in "
                "STANDARD_LABEL_TOKENS_THAT_NAME_NO_COUNTRY with the reason it is not a country."
            )
            continue
        actual = standard_for_country(iso)
        if actual != value:
            problems.append(
                f"  {token!r} resolves to {iso}, and the registry maps {iso} to {actual!r}, not "
                f"{value!r}. An estimator in {token} who picks the row carrying their own country's "
                f"name writes {value!r} onto their project while their real standard is {actual!r}."
            )

    assert problems == [], (
        f"the standards option {value!r} ({label}) names a country the registry disagrees with:\n" + "\n".join(problems)
    )


def test_every_standard_a_country_reads_is_offered_by_the_picker() -> None:
    """The other direction: a standard nobody can select from the page.

    The picker's own comment records this half of the defect. GESN, BC3, UNTEC,
    VOCI, SINAPI, Sekisan, KBIM and Birim Fiyat were all resolvable server-side
    and absent from the page, so an estimator in any of those countries could
    not name their own standard on a project. A standard added to
    ``COUNTRY_TO_STANDARD`` tomorrow is unreachable the same way until someone
    adds the row, and nothing but this would say so.

    The five standards that carry a label and no country - gaeb, omniclass,
    onorm, uniclass, uniformat - are outside ``KNOWN_CLASSIFICATION_STANDARDS``
    and so outside this assertion by construction, not by waiver.
    """
    offered = {value for value, _ in _options_in("STANDARD_GROUPS")}
    missing = sorted(s for s in KNOWN_CLASSIFICATION_STANDARDS if s not in offered)
    assert missing == [], (
        f"the registry resolves {missing} for at least one country and the standards picker offers "
        "no row for them, so an estimator in that country cannot name their own standard. Add the "
        "option with the country beside it, the way the rest of the group is written."
    )


def test_no_declared_label_token_has_quietly_become_resolvable() -> None:
    """A stale waiver is a waiver nobody reads."""
    stale = sorted(
        f"{token!r} now resolves to {_iso_for_label_token(token)!r}"
        for token in STANDARD_LABEL_TOKENS_THAT_NAME_NO_COUNTRY
        if _iso_for_label_token(token) is not None
    )
    assert stale == [], f"these declarations are dead text and should be deleted: {stale}"
    thin = sorted(
        token for token, reason in STANDARD_LABEL_TOKENS_THAT_NAME_NO_COUNTRY.items() if len(reason.strip()) < 20
    )
    assert thin == [], f"these declarations carry no usable reason: {thin}"


def test_the_five_unmapped_standards_are_labelled_and_unreachable_on_purpose() -> None:
    """Pin the scope decision so it is a decision and not an omission.

    Five standards carry a display label so a CostItem encoded against them can
    be named, and no country resolves to them, so the picker does not offer them
    and the assertions above do not reach them. If a country is ever mapped to
    one, it enters ``KNOWN_CLASSIFICATION_STANDARDS`` and the completeness test
    above starts requiring a picker row for it, which is the intended behaviour
    and the reason this is asserted rather than described in a comment.
    """
    unmapped = sorted(set(CLASSIFICATION_STANDARD_LABELS) - set(KNOWN_CLASSIFICATION_STANDARDS))
    assert unmapped == ["gaeb", "omniclass", "onorm", "uniclass", "uniformat"], (
        f"the set of labelled-but-countryless standards is now {unmapped}. If one gained a country "
        "it must also gain a picker row; if one was added, decide deliberately whether any country "
        "reads it.\n"
        "onorm and gaeb are not omissions. Both name tender-document formats rather than cost-group "
        "hierarchies - OENORM B 2063 is the Austrian counterpart of GAEB - and both are already "
        "reachable as validation rule packs through boq.router._build_rule_sets, which keys "
        "COUNTRY_RULES['AT'] = ['gaeb', 'onorm'] off the country. Mapping AT to onorm here would "
        "change no section path, because no shipped cost row carries an onorm code and the renderer "
        "would fall through to the din276 code the DACH rows do carry; it would change only what the "
        "product claims. Austria reading OENORM B 1801-1 cost groups needs that code table shipped "
        "first."
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


# ── Every standards picker the app ships, not only the project one ────────
#
# ``test_every_shipped_standard_option_is_one_the_registry_can_resolve`` above
# reads ``STANDARD_GROUPS`` and nothing else, so its population is one file.
# That is how the defect survived being fixed. When UniFormat, Uniclass and
# OmniClass were removed from the project picker for writing values
# ``resolve_standard`` drops, nobody looked at the other surfaces that offer a
# classification standard, and two of them went on shipping UniFormat and
# Uniclass. A gate scoped to one mirror is silent about the others by
# construction, and the repair is to widen this population rather than to add a
# second gate that would drift from this one.
#
# Swept 2026-09-07 across ``frontend/src`` for any option list offering
# ``masterformat`` as a value. Exactly three files carry one and all three are
# named below. A fourth picker added tomorrow is invisible here until somebody
# adds the row, which is the same shape of gap, so the sweep is recorded:
#
#     git grep -ln "value: 'masterformat'" -- frontend/src
STANDARD_PICKERS: dict[str, tuple[Path, str]] = {
    "CreateProjectPage.STANDARD_GROUPS": (PICKER, "const STANDARD_GROUPS"),
    "QuickEstimatePage.STANDARDS": (
        REPO_ROOT / "frontend" / "src" / "features" / "ai" / "QuickEstimatePage.tsx",
        "const STANDARDS",
    ),
    "CreateAssemblyPage.STANDARDS": (
        REPO_ROOT / "frontend" / "src" / "features" / "assemblies" / "CreateAssemblyPage.tsx",
        "const STANDARDS",
    ),
}

#: How many real options each picker ships, so a parse that quietly stops
#: matching cannot pass over a shrunken population. Pinned rather than derived:
#: the cross-check below catches a regex that drops *some* options, and this
#: catches one that reads the wrong literal entirely and still finds a coherent
#: handful. Changing a picker means changing the number here, deliberately.
STANDARD_PICKER_OPTION_COUNTS: dict[str, int] = {
    "CreateProjectPage.STANDARD_GROUPS": 13,
    "QuickEstimatePage.STANDARDS": 4,
    "CreateAssemblyPage.STANDARDS": 3,
}

#: Options a picker ships that ``resolve_standard`` does not honour, each named
#: with why that is right for its surface. Keyed by (picker, value) rather than
#: by picker, so waiving one option never blinds the gate to the next one added
#: to the same file.
STANDARD_PICKER_OPTIONS_NOT_HONOURED: dict[tuple[str, str], str] = {
    ("QuickEstimatePage.STANDARDS", "uniformat"): (
        "This picker does not write project.classification_standard and never reaches "
        "resolve_standard. Its value is posted as the free-text 'standard' field on the quick / "
        "photo / file estimate endpoints, sanitised to 64 characters and interpolated into the LLM "
        "prompt ('Classification standard: {standard}' in app.modules.ai.prompts), so it steers "
        "what the model returns rather than selecting a renderer. The codes that come back are "
        "displayed without a whitelist - QuickEstimatePage.tsx renders "
        "Object.entries(item.classification) - so a UniFormat answer is readable end to end on this "
        "surface. It is the one classification-standard option in the app that is honest while "
        "sitting outside KNOWN_CLASSIFICATION_STANDARDS, and it stays in the population so a value "
        "added beside it later still has to be justified."
    ),
}

#: Value-only, because the three pickers disagree about the rest of the option
#: shape: the project page ships ``{value, label}``, the quick-estimate page
#: ``{value, labelKey, fallback}`` and the assembly form ``{value, key,
#: defaultLabel}``. ``_OPTION_RE`` above requires ``label:`` and so matches
#: nothing in two of the three, which is exactly the empty population this file
#: warns about; the wider gate reads values and leaves labels to the narrower
#: test that genuinely needs them.
_VALUE_RE = re.compile(r"""value:\s*(['"])(.*?)\1""")


def _block_from_source(source: str, marker: str, where: str) -> str:
    """Slice one option-group literal out of already-read source text.

    Takes text rather than a path so the negative controls below can feed it a
    synthetic literal. A gate whose red state can only be produced by editing a
    shipped file is one nobody dares prove, and this checkout is shared.

    The slice starts at the array literal rather than at the ``const``, because
    a TypeScript annotation can itself declare a ``value:`` key:
    ``QuickEstimatePage`` types its list as
    ``Array<{ value: string; label?: string; ... }>``. Slicing from the ``const``
    put that annotation in the block, and the cross-check in
    :func:`_assert_value_parse_is_complete` then reported the parse as dropping
    an option it had never been offered. The annotation is not an option.

    Args:
        source: The file contents.
        marker: The ``const`` declaration to slice from.
        where: Human name of the picker, used in the failure messages.

    Returns:
        The array literal's text, from its opening bracket to its closing one.
    """
    assert marker in source, (
        f"{where} no longer declares {marker!r}. If the options moved to a shared module, re-point "
        "STANDARD_PICKERS at it; do not copy the values into this file."
    )
    declaration = source.index(marker)
    opening = source.find("= [", declaration)
    assert opening != -1, (
        f"{where}: found {marker!r} but no '= [' after it, so the option array cannot be located and "
        "the population would be whatever the rest of the file happens to contain."
    )
    end = source.find("\n];", opening)
    assert end != -1, (
        f"{where}: found {marker!r} but no closing bracket after it, so the literal cannot be "
        "sliced and the population would run on into the next declaration."
    )
    return source[opening:end]


def _values_in_source(block: str) -> list[str]:
    """Every option value in one picker literal, in file order."""
    return [m.group(2) for m in _VALUE_RE.finditer(block)]


def _real_values(block: str) -> list[str]:
    """Option values that name a standard.

    Drops the free-text escape hatch and the empty value the quick-estimate
    page ships for its "Auto-detect" row, neither of which is a standard.
    """
    return [v for v in _values_in_source(block) if v and v != FREE_TEXT_OPTION]


def _assert_value_parse_is_complete(where: str, block: str) -> list[str]:
    """Cross-check a value parse against the block's own ``value:`` count.

    Args:
        where: Human name of the picker, used in the failure messages.
        block: The literal's text.

    Returns:
        Every parsed value, including the free-text and empty ones.
    """
    parsed = _values_in_source(block)
    declared = len(re.findall(r"\bvalue:", block))

    assert declared, (
        f"{where}: the sliced block contains no 'value:' key at all, so the population is empty and "
        "every assertion over it would pass while measuring nothing."
    )
    assert len(parsed) == declared, (
        f"{where}: the value regex found {len(parsed)} options but the block declares {declared} "
        f"'value:' keys, so the parse is dropping options and a dropped option is never checked.\n"
        f"parsed: {parsed}"
    )
    return parsed


def _picker_values(name: str) -> list[str]:
    """Real option values one named picker ships."""
    path, marker = STANDARD_PICKERS[name]
    assert path.is_file(), (
        f"{name} is not at {path}. This gate reads the shipped pages as its population and cannot "
        "fall back to a copy, because a copy is what it exists to prevent."
    )
    block = _block_from_source(path.read_text(encoding="utf-8"), marker, name)
    _assert_value_parse_is_complete(name, block)
    return _real_values(block)


def _standards_inventory() -> dict[str, list[str]]:
    """Every standards picker in the app and the values it offers."""
    return {name: _picker_values(name) for name in STANDARD_PICKERS}


@pytest.mark.parametrize("name", sorted(STANDARD_PICKERS))
def test_a_standards_picker_ships_the_population_this_gate_expects(name: str) -> None:
    """The denominator is asserted before anything is asserted over it.

    A narrowed population cannot fake the denominator: if a picker loses
    options, or the parse starts reading a different literal, this goes red
    naming both numbers instead of passing over the smaller set.
    """
    values = _picker_values(name)
    expected = STANDARD_PICKER_OPTION_COUNTS[name]
    assert len(values) == expected, (
        f"{name} ships {len(values)} real standard options, not the {expected} this gate records.\n"
        f"  offered: {values}\n"
        "If the picker legitimately gained or lost a row, update STANDARD_PICKER_OPTION_COUNTS. Do "
        "not delete the assertion: it is what stops a silently shrinking population from passing."
    )


def test_every_standards_picker_in_the_app_offers_only_values_the_product_honours() -> None:
    """The mirrors must agree with the registry, and there are three of them.

    ``resolve_standard`` accepts an explicit standard only when it is in
    ``KNOWN_CLASSIFICATION_STANDARDS``, which is 13 of the 18 slugs carrying a
    display label. An option outside that set writes a value the product then
    ignores, falling through to the region and to DIN 276 with no error and
    nothing a user could see.

    Measured 2026-09-07, before the fix this test ships with:
    ``CreateAssemblyPage`` offered UniFormat and Uniclass, and the value it
    writes becomes a *key* in the template's ``classification`` dict, where no
    reader could reach it. The library page badged only ``din276`` and
    ``masterformat``, and the BOQ section-path renderer only ever looks up keys
    that ``classification_order()`` returns. An estimator classified a template
    against UniFormat and the code disappeared with no error anywhere.
    """
    inventory = _standards_inventory()
    population = sum(len(v) for v in inventory.values())

    offenders: list[str] = []
    for name, values in sorted(inventory.items()):
        for value in values:
            if value in KNOWN_CLASSIFICATION_STANDARDS:
                continue
            if (name, value) in STANDARD_PICKER_OPTIONS_NOT_HONOURED:
                continue
            labelled = (
                " (carries a display label, which is not enough)" if value in CLASSIFICATION_STANDARD_LABELS else ""
            )
            offenders.append(f"  {name}: {value!r}{labelled}")

    assert offenders == [], (
        f"population: {population} options across {len(inventory)} pickers "
        + ", ".join(f"{n}={len(v)}" for n, v in sorted(inventory.items()))
        + f"; honoured set {len(KNOWN_CLASSIFICATION_STANDARDS)} of "
        f"{len(CLASSIFICATION_STANDARD_LABELS)} labelled.\n"
        "these options are offered and not honoured:\n" + "\n".join(offenders) + "\n"
        f"Writing one stores a standard the product ignores, falling through to "
        f"{DEFAULT_CLASSIFICATION_STANDARD!r}, or - where the value becomes a classification dict "
        "key - stores a code no reader can name. Close it by removing the option, by mapping a "
        "country to the standard so it enters KNOWN_CLASSIFICATION_STANDARDS, or by naming the "
        "(picker, value) pair in STANDARD_PICKER_OPTIONS_NOT_HONOURED with the reason its surface "
        "is different."
    )


def test_no_picker_waiver_names_an_option_that_is_no_longer_offered() -> None:
    """A stale waiver is a waiver nobody reads."""
    inventory = _standards_inventory()
    problems: list[str] = []
    for (name, value), reason in sorted(STANDARD_PICKER_OPTIONS_NOT_HONOURED.items()):
        if name not in inventory:
            problems.append(f"  ({name}, {value}): no such picker in STANDARD_PICKERS")
        elif value not in inventory[name]:
            problems.append(f"  ({name}, {value}): the picker no longer offers this option")
        elif value in KNOWN_CLASSIFICATION_STANDARDS:
            problems.append(f"  ({name}, {value}): now honoured by resolve_standard, so the waiver is dead text")
        if len(reason.strip()) < 20:
            problems.append(f"  ({name}, {value}): carries no usable reason")
    assert problems == [], "these picker waivers no longer describe anything:\n" + "\n".join(problems)


# ── Negative controls for the widened gate ────────────────────────────────
#
# Both directions, and neither touches a shipped file: 28 agents share this
# checkout, and a control that has to edit a real page to go red is one nobody
# runs.


def test_the_widened_gate_goes_red_when_a_mirror_drifts() -> None:
    """A picker offering a labelled-but-unhonoured value must be caught.

    The defect itself, reconstructed: OmniClass carries a display label and no
    country, so it reads as selectable and resolves to nothing.
    """
    drifted = (
        "const STANDARDS = [\n"
        "  { value: 'din276', label: 'DIN 276' },\n"
        "  { value: 'omniclass', label: 'OmniClass' },\n"
        "];"
    )
    values = _real_values(_block_from_source(drifted, "const STANDARDS", "synthetic"))

    assert values == ["din276", "omniclass"], f"the control's own parse is broken: {values}"
    assert "omniclass" in CLASSIFICATION_STANDARD_LABELS, (
        "omniclass no longer carries a display label, so this control no longer reconstructs the "
        "defect; pick another labelled-but-unhonoured slug"
    )
    unhonoured = [v for v in values if v not in KNOWN_CLASSIFICATION_STANDARDS]
    assert unhonoured == ["omniclass"], (
        "a picker offering OmniClass was not flagged as unhonoured, so the gate above would stay "
        f"green through the exact defect it exists to catch: {unhonoured}"
    )


def test_the_widened_gate_goes_red_when_its_own_parse_finds_nothing() -> None:
    """An empty parse must fail loudly rather than pass over no options.

    The failure this file was built around is a green gate with an empty
    population, so the parse has to be hostile to its own silence.
    """
    empty = "const STANDARDS = [\n  { name: 'din276', label: 'DIN 276' },\n];"
    block = _block_from_source(empty, "const STANDARDS", "synthetic")

    assert _values_in_source(block) == [], "the control block was supposed to carry no 'value:' key"
    with pytest.raises(AssertionError, match="no 'value:' key at all"):
        _assert_value_parse_is_complete("synthetic", block)


def test_the_widened_gate_goes_red_when_the_parse_drops_options() -> None:
    """A parse that reads some options and misses others must also fail.

    Distinct from the empty case: a regex matching most of a list while
    skipping the one option that is wrong leaves a plausible non-empty
    population and still misses the defect.
    """
    partial = "const STANDARDS = [\n  { value: 'din276' },\n  { value: `omniclass` },\n];"
    block = _block_from_source(partial, "const STANDARDS", "synthetic")

    assert _values_in_source(block) == ["din276"], "the backtick option was supposed to escape the value regex"
    with pytest.raises(AssertionError, match="dropping options"):
        _assert_value_parse_is_complete("synthetic", block)
