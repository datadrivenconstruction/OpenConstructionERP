"""Five tax tables, hand-maintained, that can silently disagree.

The platform carries VAT rates in five unrelated places:

* ``app/core/tax.py`` - a Python dict, 22 countries, read by the country packs.
* ``app/modules/property_dev/data/tax_rates.yaml`` - 12 jurisdictions, and the
  one that actually feeds the property development tax quote panel. Its rate
  classes live under ``vat`` and, for SG, AU and IN, under ``gst``; both are
  read here, because a rate is a rate whatever the block it sits in is called.
* ``app/modules/i18n_foundation/seed_data/tax_configurations.json`` - 40
  countries, effective-dated, and the only one with any history.
* ``app/modules/methodology/templates.py`` - the methodology catalogue's
  ``vat_rate``, 53 countries, and the figure a project's cascade actually
  charges VAT at once a country template is installed.
* ``app/modules/boq/markup_templates.py`` - the regional markup stacks, 42
  regions covering 50 countries. This is the one the money goes through:
  the ``tax`` line of a region's stack is the percentage a newly seeded
  bill of quantities charges VAT at.

Why the fourth table was added, which is the whole argument for it
------------------------------------------------------------------
It was measured, on 2026-09-02. Israel raised standard VAT from 17 % to 18 % on
2025-01-01. The methodology catalogue was updated and said 18. The seed file
was not: it went on carrying 17 with no ``effective_to``, so it read as the
rate in force, and the platform stated two different rates for one country on
one date. Nothing was red, because the three tables above happen not to carry
Israel at all - neither ``core/tax.py`` nor the yaml has an IL row - so the
seed's stale figure had no counterpart to disagree with, and the one table that
held the right answer was not in the comparison.

That is the failure this file was written against, arriving through a table
nobody had added rather than through a rate nobody had updated. The catalogue
is the platform's most-maintained rate list, because it is the one somebody
edits when they add a country, and leaving it out meant the check was blind
wherever the other three were silent.

``core/tax.py`` says so in its own docstring: "Nothing currently checks that
the two agree ... so the two can drift apart silently. Treat that as a known
gap, not as a guarantee." This is that check. It does not unify them - which
is the source of truth is a design decision nobody has taken - it only makes a
disagreement impossible to ship without somebody seeing it.

Two things this deliberately does NOT do.

It does not convict on absence. Most countries appear in one table and not
another, by design: the yaml carries stamp duty for jurisdictions with no VAT
block at all, and ``core/tax.py`` leaves out Brazil and the United States on
purpose. A gate that fired on absence would be red from birth, and a gate that
is always red teaches everyone to ignore it.

It does not compare sub-national rates. The other tables are keyed by country
and cannot express a province, so only rows marked ``national`` are comparable
at all. Canada's federal GST is not "Canada's VAT rate" in the sense the other
tables mean, and comparing them would be a category error.

And it does not assert blanket equality across the catalogue, because that
would be false. See :data:`_CONSTRUCTION_TIER_DIVERGES`.

Why the fifth table was added, which is a second version of the same story
-------------------------------------------------------------------------
Measured on 2026-09-02, right after the Israeli seed row was corrected. The
bill table went on pricing Israel at 17, and it carried a comment saying so:
the rate had been noticed, written down as superseded, and shipped anyway.
The four tables above were green while the number a customer is invoiced at
was stale, because none of the four was the bill table. A gate whose
population does not include the place the defect lives is green about
something else.

This table does not compare the way the other four do, and the difference is
the point. The other four are country-keyed. This one is REGION-keyed, and a
region can serve several countries: one DACH stack serves Austria, Germany
and Switzerland. So its number is a claim about a country only where a
region serves exactly one. That split is what
:data:`_SERVED_BY_A_SHARED_REGION` records, and it is why this file asks two
different questions of the fifth table rather than one.

Read the ``xfailed`` count before reading the passes. Seven countries carry a
neighbour's rate on this table and
``test_no_country_is_priced_at_another_country_s_rate`` fails because of it.
Since the bill resolves a country's own rate from the tax seed, that table is
a fallback rather than the invoice, so the xfail records a latent wrong number
rather than a live one. What a bill actually charges is measured in
``tests/pg/test_a_bill_is_priced_at_its_own_countrys_vat.py``.
None of them is corrected here: no source settles which of the three tables
is right for them, and a majority vote would replace a visible inconsistency
with a confident wrong number that this very gate would then hold in place.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.core.tax import VATNotApplicable, get_vat_rate, list_covered_countries
from app.modules.boq.markup_templates import (
    DEFAULT_MARKUP_TEMPLATES,
    NON_SINGLE_TAX_REGIONS,
    REGION_BY_COUNTRY,
)
from app.modules.methodology.templates import TEMPLATES

_BACKEND = Path(__file__).resolve().parents[2]
_SEED = _BACKEND / "app" / "modules" / "i18n_foundation" / "seed_data" / "tax_configurations.json"
_YAML = _BACKEND / "app" / "modules" / "property_dev" / "data" / "tax_rates.yaml"
_CORE = _BACKEND / "app" / "core" / "tax.py"
_CATALOGUE = _BACKEND / "app" / "modules" / "methodology" / "templates.py"
_MARKUP = _BACKEND / "app" / "modules" / "boq" / "markup_templates.py"

# Seed ``tax_code`` values that name one of the three rate classes the other
# two tables also carry. This mapping is the soft spot in the whole check: get
# it wrong and the comparison silently shrinks rather than failing, which is
# the vacuous pass this file exists to avoid. ``test_every_seed_tax_code_is_
# classified`` is what keeps it honest.
_CLASS_OF: dict[str, str] = {
    # Headline rate, under each country's own name for it.
    "AFA": "standard",
    "ALV": "standard",
    "BTW": "standard",
    "CT": "standard",
    "DDS": "standard",
    "DPH": "standard",
    "GST": "standard",
    "IVA": "standard",
    "KDV": "standard",
    "MOMS": "standard",
    "MVA": "standard",
    "NDS": "standard",
    "PDV": "standard",
    "TVA": "standard",
    "VAT": "standard",
    # India has four GST bands and no single headline rate. ``core/tax.py``
    # declares the standard one to be 18 %, so that is the band compared;
    # the other three have nothing to compare against.
    "GST_18": "standard",
    # Reduced rate.
    "ALV_RED": "reduced",
    "BTW_RED": "reduced",
    "CT_RED": "reduced",
    "DPH_RED": "reduced",
    "IVA_RED": "reduced",
    "KDV_RED": "reduced",
    "MOMS_RED": "reduced",
    "MVA_RED": "reduced",
    "NDS_RED": "reduced",
    "PDV_RED": "reduced",
    "TVA_RED": "reduced",
    "VAT_RED": "reduced",
    "VAT_REDUCED": "reduced",
    "VAT_ZERO": "zero",
}

# Codes with no counterpart in a country-keyed table, and why. Listed rather
# than skipped by a wildcard so that a new code has to be thought about.
_NOT_COMPARABLE: dict[str, str] = {
    "GST_5": "one of India's four GST bands; no single-rate counterpart",
    "GST_12": "one of India's four GST bands; no single-rate counterpart",
    "GST_28": "one of India's four GST bands; no single-rate counterpart",
    "TVA_INT": "France's intermediate 10 % tier; neither standard nor reduced",
    "VAT_SPECIAL": "Swiss accommodation rate; no counterpart class",
    "ICMS_SP": "Brazilian state ICMS; sub-national, and no federal row exists",
    "ISS": "Brazilian municipal service tax; sub-national",
    "NONE": "sentinel meaning the country levies no such tax",
    "HST_ON": "Canadian provincial",
    "HST_NS": "Canadian provincial",
    "HST_NB": "Canadian provincial",
    "HST_NL": "Canadian provincial",
    "HST_PE": "Canadian provincial",
    "QST_QC": "Canadian provincial",
    "PST_BC": "Canadian provincial",
    "PST_SK": "Canadian provincial",
    "RST_MB": "Canadian provincial",
    "CA_SALES": "United States state sales tax; sub-national",
}


def _seed_rows() -> list[dict]:
    return json.loads(_SEED.read_text(encoding="utf-8"))


def _seed_rates() -> dict[tuple[str, str], Decimal]:
    """Currently active, country-wide seed rates, as fractions."""
    out: dict[tuple[str, str], Decimal] = {}
    for row in _seed_rows():
        if row["effective_to"] is not None:
            continue
        if row["combination"] != "national":
            continue
        cls = _CLASS_OF.get(row["tax_code"] or "")
        if cls is None:
            continue
        out[(row["country_code"], cls)] = Decimal(row["rate_pct"]) / Decimal("100")
    return out


def _seed_history() -> dict[tuple[str, str], list[tuple[Decimal, str]]]:
    """Closed seed periods, so a stale value can be named as stale."""
    out: dict[tuple[str, str], list[tuple[Decimal, str]]] = {}
    for row in _seed_rows():
        if row["effective_to"] is None or row["combination"] != "national":
            continue
        cls = _CLASS_OF.get(row["tax_code"] or "")
        if cls is None:
            continue
        rate = Decimal(row["rate_pct"]) / Decimal("100")
        out.setdefault((row["country_code"], cls), []).append((rate, row["effective_to"]))
    return out


#: Countries where the catalogue and the seed carry different figures on
#: purpose, each with the reason it is not drift.
#:
#: This is an exception list rather than an allowlist, and the difference is
#: enforced: ``test_every_named_catalogue_exception_still_diverges`` fails when
#: an entry here stops disagreeing, so a country cannot be left excused after
#: the reason for excusing it has gone. That is the failure mode of every
#: "known exceptions" list - it silently grows into a list of things nobody
#: checks - and it is the one thing that would make this file worse than not
#: having the fourth table at all.
#:
#: The two sources are answering different questions, which is why a blanket
#: equality assertion across the construction-priced tables would be false
#: rather than merely strict. The seed's ``is_default`` row is documented as a
#: country's STANDARD rate: the headline figure, the one a general supply is
#: charged at. The catalogue's ``vat_rate`` and the bill table's ``tax`` line
#: are both the rate a bill of quantities is priced at, which is the standard
#: rate in almost every country and is not in a country that puts construction
#: on a tier of its own. Where the two coincide - which is everywhere but here
#: - a disagreement is drift and this file says so.
#:
#: This excuses a country on BOTH construction-priced tables, because the
#: reason is a fact about the country's tax law rather than about either
#: file. It was named ``_CATALOGUE_DIVERGES`` while the catalogue was the
#: only such table; the bill table is the second, and a name that says
#: which file rather than which reason would have had to be read as
#: covering a file it does not mention.
_CONSTRUCTION_TIER_DIVERGES: dict[str, str] = {
    "CN": (
        "China's headline VAT rate is 13 %, which is what the seed row flagged is_default carries "
        "and what the seed's VAT_RED row at 9 % is reduced from. Construction and building "
        "services are charged at that 9 % tier, so 9 is the rate a bill of quantities is priced "
        "at and the rate the methodology template quotes. Both figures are right about different "
        "questions, and the platform needs both."
    ),
}


def _catalogue_rates_raw(templates: list[dict] | None = None) -> dict[tuple[str, str], Decimal]:
    """Every standard rate the methodology catalogue carries, exceptions included.

    Only ``(country, "standard")`` keys exist here: a methodology carries one
    VAT percentage and no reduced tier, so there is nothing else to compare.

    ``vat_rate`` is tested against ``None`` rather than for truthiness. Qatar,
    Bahrain's neighbours and the other zero-VAT templates carry the string
    "0", which is a rate this platform quotes and not an absence; ``if not
    rate`` would drop precisely those and the comparison would go quiet on the
    countries where a wrong rate is most obvious.

    ``templates`` defaults to the shipped catalogue and exists so the
    disagreement guard below can be reached by a control. Every template that
    ships today agrees with its own country's other templates, so the guard is
    unreachable on real data, and a guard nobody can reach is a guard nobody
    has seen work.
    """
    out: dict[tuple[str, str], Decimal] = {}
    for template in TEMPLATES if templates is None else templates:
        country = template.get("country_code")
        rate = template.get("vat_rate")
        if not country or rate is None:
            continue
        key = (str(country).upper(), "standard")
        value = Decimal(str(rate)) / Decimal("100")
        if key in out and out[key] != value:
            raise AssertionError(
                f"{key[0]} has two methodology templates quoting different VAT rates "
                f"({out[key] * 100} and {value * 100}). A country can hold two templates - Chile "
                f"and Colombia each ship a flat one and an APU one - but not two opinions about "
                f"its VAT rate, and which one this comparison saw would depend on catalogue order."
            )
        out[key] = value
    return out


def _catalogue_rates() -> dict[tuple[str, str], Decimal]:
    """The catalogue's rates, less the countries excused in :data:`_CONSTRUCTION_TIER_DIVERGES`."""
    return {key: value for key, value in _catalogue_rates_raw().items() if key[0] not in _CONSTRUCTION_TIER_DIVERGES}


#: Countries whose bill is priced by a region that serves several countries, and
#: whose own national rate is therefore NOT the number the region carries.
#:
#: How this arises, because it is a design and not a typo. The bill table is
#: keyed by REGION. ``REGION_BY_COUNTRY`` maps Austria, Germany and Switzerland
#: onto one DACH stack, Ireland onto the UK stack, four Gulf states onto GULF
#: and four Nordics onto NORDIC. One stack carries one ``tax`` line, so at most
#: one of the countries it serves can see its own rate in it. The mechanism
#: meant to correct this is the per-project ``default_vat_rate`` override, which
#: ``resolve_region_lines`` swaps into the tax line of any single-levy region.
#:
#: The exposure, stated plainly because naming these as "deliberate" without it
#: would be the comfortable half of the truth: ``default_vat_rate`` is nullable,
#: has no server default, and is populated only from what a user types when
#: creating a project. ``ProjectService.create`` passes ``data.default_vat_rate``
#: straight through. So a project created in one of these countries without
#: somebody typing a rate is seeded at the number below, and for Saudi Arabia
#: that is 5 against a real 15. These entries record a known gap, not a
#: harmless one, and the fix for it is a decision about regions and defaults
#: that is bigger than this file.
#:
#: What this list is NOT allowed to hide is a region whose rate is nobody's:
#: see :func:`test_every_shared_region_prices_at_least_one_country_it_serves`.
_SERVED_BY_A_SHARED_REGION: dict[str, str] = {
    "AT": (
        "the DACH stack carries 19, which is Germany's rate. Austria's standard rate is 20 "
        "under the Umsatzsteuergesetz 1994, and the DACH block's own comment names 20 as "
        "Austria's number while the shipped line stays German"
    ),
    "CH": (
        "the DACH stack carries 19, which is Germany's rate. Switzerland's standard rate is "
        "8.1 since 2024-01-01, the largest proportional gap in this table: a Swiss bill "
        "seeded with no override is charged more than twice the tax it owes"
    ),
    "FI": (
        "the NORDIC stack carries 25, which is Denmark's, Norway's and Sweden's rate. "
        "Finland raised its standard rate to 25.5 on 2024-09-01 and is now the one Nordic "
        "the shared number does not fit"
    ),
    "IE": (
        "the UK stack carries 20, which is Great Britain's rate. Ireland's standard rate is "
        "23. The REGION_BY_COUNTRY comment putting Ireland on the UK stack argues the two "
        "share a measurement tradition and names the per-project override as the answer to "
        "the rate, and it quotes 13.5, the Irish reduced rate for construction services, "
        "which is a third number again and matches neither table"
    ),
    "KW": (
        "the GULF stack carries 5, which is the rate in the UAE and Saudi Arabia's former "
        "rate. Kuwait has not implemented VAT: the methodology catalogue carries 0 for it, "
        "so a Kuwaiti bill seeded with no override is charged a tax that does not exist"
    ),
    "QA": (
        "the GULF stack carries 5, which is the rate in the UAE. Qatar has not implemented "
        "VAT either and the catalogue carries 0 for it, so the same overcharge applies"
    ),
    "SA": (
        "the GULF stack carries 5, which was Saudi Arabia's rate until 2020-06-30. It rose "
        "to 15 on 2020-07-01 and both the seed and the catalogue say 15. This is the "
        "largest absolute gap in the table and the one closest to being simply stale rather "
        "than shared"
    ),
}


def _region_tax_lines(region: str) -> list[dict[str, object]]:
    """The ``tax`` lines of a region's stack, selected structurally.

    On ``category`` rather than on ``name``, because the names are the local
    ones and are not Latin: the Israeli line is written in Hebrew, the Chinese
    and Korean lines in their own scripts, and matching "VAT" as a substring
    would quietly read a different set of countries than it appears to.
    """
    return [line for line in DEFAULT_MARKUP_TEMPLATES[region] if line.get("category") == "tax"]


def _countries_by_region() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for country, region in REGION_BY_COUNTRY.items():
        out.setdefault(region, []).append(country.upper())
    return {region: sorted(countries) for region, countries in out.items()}


def _table_rates_raw() -> dict[tuple[str, str], Decimal]:
    """The VAT percentage the region-keyed fallback table holds, per country.

    Reads ``DEFAULT_MARKUP_TEMPLATES`` and nothing else. That used to be the
    same thing as what a bill charges, and since the bill began resolving a
    country's own rate from the effective-dated tax seed it is not: this table
    is now the LAST resort, reached by a country with no seed row and by a
    database with no seed at all. So what follows measures the fallback, and
    ``tests/pg/test_a_bill_is_priced_at_its_own_countrys_vat.py`` measures the
    bill. Neither substitutes for the other, and a green run here says nothing
    about what a customer is invoiced.

    Regions named in ``NON_SINGLE_TAX_REGIONS`` are skipped, because there the
    stack carries two levies or none and no single number is the country's VAT
    rate. A region NOT named there and carrying a count other than one raises,
    rather than being skipped or having its first line taken: skipping would
    shrink this population silently, and taking the first line is the exact
    defect ``resolve_region_lines`` was changed to stop, where an override
    applied to both Brazilian levies doubled the tax on a bill.
    """
    out: dict[tuple[str, str], Decimal] = {}
    for country, region in REGION_BY_COUNTRY.items():
        if region in NON_SINGLE_TAX_REGIONS:
            continue
        lines = _region_tax_lines(region)
        if len(lines) != 1:
            raise AssertionError(
                f"region {region} carries {len(lines)} tax lines and is not named in "
                f"NON_SINGLE_TAX_REGIONS, so there is no single rate to compare and this "
                f"check cannot say which line prices {country}. Name the region there with "
                f"its reason, the way CA, MY, CO, US and BR are."
            )
        out[(country.upper(), "standard")] = Decimal(str(lines[0]["percentage"])) / Decimal("100")
    return out


def _table_rates() -> dict[tuple[str, str], Decimal]:
    """The bill rates that are a claim about their own country, and so comparable.

    Two subtractions, both accounted for by a test of their own rather than
    left as a quiet filter: countries on a construction tier
    (:data:`_CONSTRUCTION_TIER_DIVERGES`) and countries served by a region
    built for somebody else (:data:`_SERVED_BY_A_SHARED_REGION`).
    """
    return {
        key: value
        for key, value in _table_rates_raw().items()
        if key[0] not in _CONSTRUCTION_TIER_DIVERGES and key[0] not in _SERVED_BY_A_SHARED_REGION
    }


def _national_rate(country: str) -> Decimal | None:
    """A country's own standard rate, seed first and catalogue second.

    The seed is preferred because it is the effective-dated table and the one
    a repair maintains. The catalogue is the fallback rather than nothing,
    because Kuwait and Qatar have no seed row at all and their rate of 0 is a
    real statement that the comparison would otherwise never hear.
    """
    key = (country.upper(), "standard")
    seeded = _seed_rates().get(key)
    return seeded if seeded is not None else _catalogue_rates_raw().get(key)


def _shared_region_mismatches() -> dict[str, tuple[Decimal, Decimal]]:
    """Countries a multi-country region prices at somebody else's rate.

    The two exception lists own two different axes and a country can sit on
    both, so this states which one wins. A country in
    :data:`_CONSTRUCTION_TIER_DIVERGES` is skipped here, exactly as
    :func:`test_a_region_serving_one_country_prices_that_country_s_own_rate`
    skips it: its bill rate differs from the seed because construction is
    charged on a different tier, and that is true whether or not it also shares
    a region. Measuring it here as well would demand a
    :data:`_SERVED_BY_A_SHARED_REGION` entry whose reason - that the number
    belongs to a neighbour - would be the wrong explanation for a real
    divergence, which is the failure the reason strings exist to prevent.

    Not a live case: China is the only tier country and the CN region serves
    only China. It is written down because the two arms disagreed about it
    silently until they were compared, and the next tier country is the one
    that would find out.
    """
    out: dict[str, tuple[Decimal, Decimal]] = {}
    for region, countries in _countries_by_region().items():
        if len(countries) < 2 or region in NON_SINGLE_TAX_REGIONS:
            continue
        rate = Decimal(str(_region_tax_lines(region)[0]["percentage"])) / Decimal("100")
        for country in countries:
            if country in _CONSTRUCTION_TIER_DIVERGES:
                continue
            own = _national_rate(country)
            if own is not None and own != rate:
                out[country] = (rate, own)
    return out


def _core_rates() -> dict[tuple[str, str], Decimal]:
    out: dict[tuple[str, str], Decimal] = {}
    for country in list_covered_countries():
        for cls in ("standard", "reduced", "zero"):
            try:
                out[(country, cls)] = Decimal(get_vat_rate(country, cls))
            except VATNotApplicable:
                continue
    return out


def _declares_a_rate(entry: object) -> bool:
    """Whether a yaml rate class states a rate at all, in any shape it may be written in."""
    if isinstance(entry, list):
        return any(isinstance(period, dict) and "rate" in period for period in entry)
    if isinstance(entry, dict):
        return "rate" in entry
    return entry is not None


def _current_yaml_rate(entry: object) -> Decimal | None:
    """The rate a yaml class charges today, from either of the two shapes it uses.

    A class is either a single mapping or a list of dated periods written
    oldest first. The newest period is the comparable one, because the other
    two tables carry current rates and nothing else: ``core/tax.py`` has no
    dates at all and only the seed's open rows are read.

    Returns None for a class that states no rate anywhere, such as the UAE and
    Russian ``exempt`` entries, which name what they apply to and have nothing
    to compare against.
    """
    if isinstance(entry, list):
        periods = [period for period in entry if isinstance(period, dict) and "rate" in period]
        if not periods:
            return None
        newest = max(periods, key=lambda period: str(period.get("effective_from") or ""))
        return Decimal(str(newest["rate"]))
    if isinstance(entry, dict) and "rate" in entry:
        return Decimal(str(entry["rate"]))
    return None


#: The yaml keys that hold rate classes. ``gst`` is here because leaving it
#: out was a real hole rather than a hypothetical one: SG and AU carry their
#: standard rate under ``gst``, the other two tables carry the same rate for
#: the same country, and this comparison never put the pairs together. A scope
#: written as a key name is blind to the sibling key holding the same thing,
#: which is the defect this whole file exists to catch, one layer up.
_RATE_BLOCKS = ("vat", "gst")


def _yaml_rates() -> dict[tuple[str, str], Decimal]:
    doc = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], Decimal] = {}
    for country, block in (doc.get("jurisdictions") or {}).items():
        for block_key in _RATE_BLOCKS:
            for cls, entry in ((block or {}).get(block_key) or {}).items():
                rate = _current_yaml_rate(entry)
                if rate is None:
                    continue
                assert (country, cls) not in out, (
                    f"{country}.{cls} is declared under more than one of {_RATE_BLOCKS}, so one "
                    f"of them would silently win here. Decide which block owns it."
                )
                out[(country, cls)] = rate
    return out


def _tables() -> list[tuple[str, dict[tuple[str, str], Decimal]]]:
    return [
        (str(_CORE.relative_to(_BACKEND)), _core_rates()),
        (str(_YAML.relative_to(_BACKEND)), _yaml_rates()),
        (str(_SEED.relative_to(_BACKEND)), _seed_rates()),
        (str(_CATALOGUE.relative_to(_BACKEND)), _catalogue_rates()),
        (str(_MARKUP.relative_to(_BACKEND)), _table_rates()),
    ]


def test_every_seed_tax_code_is_classified() -> None:
    """A new tax code must be classified or excluded, never silently dropped.

    Without this, adding a code the mapping does not know shrinks the compared
    population and the drift check keeps passing on less and less.
    """
    codes = {row["tax_code"] for row in _seed_rows() if row["tax_code"]}

    unaccounted = sorted(codes - set(_CLASS_OF) - set(_NOT_COMPARABLE))

    assert unaccounted == [], (
        f"{len(unaccounted)} tax codes are neither classified nor excluded: {unaccounted}. "
        f"Add each to _CLASS_OF (it names a standard/reduced/zero rate) or to "
        f"_NOT_COMPARABLE (with the reason it has no counterpart)."
    )


def _disagreements(
    tables: list[tuple[str, dict[tuple[str, str], Decimal]]],
    history: dict[tuple[str, str], list[tuple[Decimal, str]]],
) -> tuple[list[str], list[str]]:
    """Compare every key two or more tables carry.

    Returns ``(population, disagreements)`` - the keys actually compared and
    the ones that differ. This is the whole gate, and it is a plain function
    precisely so the controls below can call it on perturbed input rather
    than re-implementing the comparison and proving only that ``!=`` works.
    """
    population: list[str] = []
    disagreements: list[str] = []

    for key in sorted(set().union(*[set(t) for _, t in tables])):
        present = [(name, table[key]) for name, table in tables if key in table]
        if len(present) < 2:
            continue  # Absence is not disagreement.
        population.append(f"  {key[0]} {key[1]:<9} " + "  ".join(f"{n.split('/')[-1]}={v}" for n, v in present))
        for i, (name_a, value_a) in enumerate(present):
            for name_b, value_b in present[i + 1 :]:
                if value_a == value_b:
                    continue
                note = ""
                for old_rate, ended in history.get(key, []):
                    if value_a == old_rate:
                        note = f" - {name_a} looks stale: that was the rate until {ended}"
                    elif value_b == old_rate:
                        note = f" - {name_b} looks stale: that was the rate until {ended}"
                disagreements.append(f"  {key[0]} {key[1]}: {name_a} says {value_a}, {name_b} says {value_b}{note}")

    return population, disagreements


def census() -> str:
    """Every count this check has, in one printable line.

    Runnable rather than described, because the counts are what a reader
    needs and a paragraph telling somebody how to rebuild them is what goes
    stale. "0 disagreements" says nothing until it is read beside how many
    keys were compared and how many each table holds.
    """
    tables = _tables()
    population, disagreements = _disagreements(tables, _seed_history())
    sizes = ", ".join(f"{name} {len(rates)}" for name, rates in tables)
    return f"compared {len(population)} keys, {len(disagreements)} disagreements; tables hold: {sizes}"


def test_the_compared_population_is_not_empty() -> None:
    """Guards the vacuous pass: zero disagreements over zero pairs proves nothing."""
    population, _ = _disagreements(_tables(), _seed_history())
    print(census())

    assert len(population) >= 15, (
        f"{census()}. "
        f"Only {len(population)} comparable (country, rate class) keys - the drift check has "
        f"gone vacuous. Either a table stopped parsing, _CLASS_OF stopped matching, or the "
        f"comparison stopped comparing."
    )


def test_every_yaml_rate_class_is_either_compared_or_states_no_rate() -> None:
    """A class this reader cannot parse must fail here rather than drop out quietly.

    The reader used to accept a single mapping only. When GB and DE standard
    VAT were rewritten as dated histories they stopped being mappings, left the
    comparison, and this file went on passing over a population two keys
    smaller - the two headline rates the platform quotes most. That is the
    vacuous pass the module docstring is about, arriving through the shape of
    the data rather than through the tax-code mapping, and nothing here noticed.

    The rule: every rate class in the yaml is either compared or states no rate
    at all, which is the only honest reason to have nothing to compare. Both
    blocks are walked. Reading ``vat`` alone was the same defect in a second
    form - it did not lose a class to a shape it could not parse, it never
    looked at six of them, and a population that is never looked at cannot
    report that it is missing.
    """
    doc = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    compared = set(_yaml_rates())

    unread = sorted(
        f"{country}.{cls}"
        for country, block in (doc.get("jurisdictions") or {}).items()
        for block_key in _RATE_BLOCKS
        for cls, entry in ((block or {}).get(block_key) or {}).items()
        if (country, cls) not in compared and _declares_a_rate(entry)
    )

    assert unread == [], (
        f"{unread} state a rate the yaml reader did not return, so they have dropped out of the "
        f"drift comparison rather than failing it. Teach _current_yaml_rate the shape they use."
    )
    # Named as well as covered by the rule above: these are the classes the
    # rule was written for, and a reader that lost them again would otherwise
    # only be caught by a count. SG and AU are here because they are what the
    # ``vat``-only reader could not see, and a rule stated in the abstract is
    # worth less than one instance of it that used to be missing.
    assert {("GB", "standard"), ("DE", "standard"), ("SG", "standard"), ("AU", "standard")} <= compared


def test_every_seed_country_still_has_an_open_period() -> None:
    """A country whose periods have all closed leaves the comparison silently.

    ``_seed_rates`` only reads open rows, so a country whose last period was
    given an end date drops out of the population entirely - and because
    absence never convicts, genuine staleness would then look like agreement.
    """
    rows = _seed_rows()

    stranded = sorted(
        {r["country_code"] for r in rows} - {r["country_code"] for r in rows if r["effective_to"] is None}
    )

    assert stranded == [], (
        f"{stranded} have no open tax period, so they have dropped out of the drift comparison rather than failing it"
    )


def test_the_methodology_catalogue_is_actually_being_read() -> None:
    """A reader returning nothing would empty the fourth table without failing anything.

    Absence never convicts in this file, so a catalogue that stopped parsing
    would remove itself from every comparison and leave the whole gate greener
    than it was before it existed. Named instances as well as a count, because
    a count survives losing exactly the rows that matter.
    """
    rates = _catalogue_rates()

    assert len(rates) >= 30, f"the catalogue returned only {len(rates)} rates; it has stopped being read"

    assert rates[("IL", "standard")] == Decimal("0.18"), (
        "Israel is the case this table was added for. The seed carried 17 % with no end date for "
        "months after the rise to 18 % and the catalogue said 18 the whole time, with nothing "
        "comparing the two. If Israel ever leaves this table, the same gap is open again."
    )
    assert rates[("QA", "standard")] == Decimal("0"), (
        "Qatar's 0 % is a rate the platform quotes, not an absence. A reader testing vat_rate for "
        "truthiness rather than against None drops it, and every other zero-rated template with it."
    )


def test_every_named_tier_exception_still_diverges() -> None:
    """An exception that has stopped being needed must fail rather than sit there.

    Without this, ``_CONSTRUCTION_TIER_DIVERGES`` is an allowlist: a country put on it
    for a real reason stays excused forever, including after somebody aligns
    the two figures, and the next genuine divergence in that country is
    excused by an entry whose reason no longer applies. The list has to be
    checkable, so it is checked.

    It excuses a country on both construction-priced tables, so both are
    checked. An entry that still diverges on the catalogue but has quietly come
    into line on the bill is excusing nothing there, and the bill is the table
    a customer is invoiced from.
    """
    seed = _seed_rates()
    priced = {"the methodology catalogue": _catalogue_rates_raw(), "the bill table": _table_rates_raw()}

    for country, reason in _CONSTRUCTION_TIER_DIVERGES.items():
        key = (country, "standard")
        assert key in seed, (
            f"{country} is excused from the construction-tier comparison, but the seed no longer "
            f"carries an open standard rate for it, so the entry is excusing nothing. Remove it."
        )
        seen_anywhere = False
        for label, table in priced.items():
            if key not in table:
                continue
            seen_anywhere = True
            assert table[key] != seed[key], (
                f"{country} is on the exception list, which says: {reason} But the seed and "
                f"{label} now both say {seed[key]}, so the exception is excusing an agreement "
                f"and would go on excusing a real disagreement later. Remove {country} and let "
                f"it be compared like the rest."
            )
        assert seen_anywhere, (
            f"{country} is excused from the construction-tier comparison, but neither the "
            f"methodology catalogue nor the bill table carries a rate for it any more, so the "
            f"entry is excusing nothing. Remove it."
        )


def test_the_bill_table_is_actually_being_read() -> None:
    """A reader returning nothing would remove the priced table without failing anything.

    Same argument as for the catalogue, and more load-bearing here: this is the
    table a customer is invoiced from, so a silent emptying of it would leave
    the check green about every table except the one that matters.
    """
    rates = _table_rates_raw()

    assert len(rates) >= 40, f"the bill table returned only {len(rates)} rates; it has stopped being read"

    assert rates[("IL", "standard")] == Decimal("0.18"), (
        "Israel is the case this table was added for. The bill priced it at 17 for months "
        "after the rise to 18, carrying a comment that said so, while every gate stayed green "
        "because none of them read this file."
    )
    assert rates[("DE", "standard")] == Decimal("0.19"), (
        "Germany is the country the DACH stack's number belongs to. If it moves, the reason "
        "the other DACH members are excused moves with it."
    )


def test_a_region_serving_one_country_prices_that_country_s_own_rate() -> None:
    """The check that would have caught Israel, stated as its own question.

    Where a region serves exactly one country there is no shared-stack argument
    available: the number is that country's rate or it is wrong. Israel had its
    own region, its own stack and its own tax line, and still priced at 17 for
    months after the rise, because nothing compared this file against anything.
    """
    bill = _table_rates_raw()
    by_region = _countries_by_region()
    wrong: list[str] = []
    checked = 0

    for region, countries in sorted(by_region.items()):
        if len(countries) != 1 or region in NON_SINGLE_TAX_REGIONS:
            continue
        country = countries[0]
        if country in _CONSTRUCTION_TIER_DIVERGES:
            continue
        own = _national_rate(country)
        if own is None or (country, "standard") not in bill:
            continue
        checked += 1
        priced = bill[(country, "standard")]
        if priced != own:
            wrong.append(f"  {country} (region {region}): bill prices {priced}, the country's own rate is {own}")

    print(f"\nsole-country regions compared: {checked}")

    assert wrong == [], (
        f"{len(wrong)} of {checked} countries with a region of their own are priced at a rate "
        f"that is not theirs:\n" + "\n".join(wrong) + "\nThe region serves one country, so no "
        "shared-stack argument applies and the number is simply wrong."
    )


def test_every_shared_region_prices_at_least_one_country_it_serves() -> None:
    """A shared region's rate must be somebody's, or it is a typo with an alibi.

    :data:`_SERVED_BY_A_SHARED_REGION` excuses the members a region does not
    fit. That excuse is only honest while the region fits somebody: a DACH rate
    of 17 would fit none of Austria, Germany or Switzerland, and every member
    would be excused by an entry written for a rate that no longer exists.
    """
    orphans: list[str] = []

    for region, countries in sorted(_countries_by_region().items()):
        if len(countries) < 2 or region in NON_SINGLE_TAX_REGIONS:
            continue
        rate = Decimal(str(_region_tax_lines(region)[0]["percentage"])) / Decimal("100")
        owners = [c for c in countries if _national_rate(c) == rate]
        print(f"  {region}: {rate} is the rate of {owners or 'NOBODY'} out of {countries}")
        if not owners:
            stated = {c: str(_national_rate(c)) for c in countries}
            orphans.append(f"  {region} prices {rate}, which is no member's rate: {stated}")

    assert orphans == [], (
        "a shared region carries a rate belonging to none of the countries it serves:\n"
        + "\n".join(orphans)
        + "\nEvery member is then excused by _SERVED_BY_A_SHARED_REGION for a reason that "
        "names a rate the region no longer carries."
    )


def test_the_countries_a_shared_region_misprices_are_exactly_the_named_set() -> None:
    """The excused set is pinned, so it cannot grow or shrink without being read.

    Fails in both directions on purpose. A new country mapped onto an existing
    region, or a region whose rate moves, adds a mispriced country and this
    goes red with its name. Somebody splitting a region or correcting a rate
    removes one, and it goes red too, because an entry excusing a country that
    is now priced correctly would excuse the next real defect there in silence.

    Countries on a construction tier are not measured here; see
    :func:`_shared_region_mismatches` for which list owns which axis.
    """
    measured = _shared_region_mismatches()

    for country, (region_rate, own) in sorted(measured.items()):
        print(f"  {country}: region prices {region_rate}, own rate {own}")

    assert set(measured) == set(_SERVED_BY_A_SHARED_REGION), (
        f"the countries a shared region misprices have changed.\n"
        f"  measured: {sorted(measured)}\n"
        f"  named:    {sorted(_SERVED_BY_A_SHARED_REGION)}\n"
        f"  newly mispriced and unnamed: {sorted(set(measured) - set(_SERVED_BY_A_SHARED_REGION))}\n"
        f"  named but priced correctly now: {sorted(set(_SERVED_BY_A_SHARED_REGION) - set(measured))}\n"
        f"Add the new ones with the reason and the source, or remove the ones that have been "
        f"fixed so they are compared like everybody else."
    )

    for country, reason in _SERVED_BY_A_SHARED_REGION.items():
        assert reason.strip(), f"{country} is excused with an empty reason, which excuses nothing"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Seven countries have a neighbour's VAT rate on the region-keyed fallback table. "
        "Nothing here is a guess and nothing is corrected: no rate in any of the three tables "
        "can be shown right from a source for these, and resolving a three-way disagreement by "
        "majority vote would put a confident wrong number where a visible inconsistency is. "
        "The exposure is now latent rather than live: a bill resolves the country's own rate "
        "from the tax seed, so this table is reached only by a country with no seed row or a "
        "database with no seed at all. It is still worth stating as unsatisfied, because those "
        "two cases are real and the number would be wrong in both. strict=True, so the day the "
        "last one is fixed this XPASSes and forces _SERVED_BY_A_SHARED_REGION to be deleted "
        "rather than left behind excusing nothing."
    ),
)
def test_no_country_is_priced_at_another_country_s_rate() -> None:
    """The invariant the bill table does not satisfy, written down as a failure.

    :data:`_SERVED_BY_A_SHARED_REGION` keeps the rest of this file green while
    seven countries are mispriced, and a list of excuses is exactly where a
    real defect goes to be forgotten. So the thing the platform ought to
    satisfy is also stated as a test, and it fails.

    ``xfail`` rather than a hard failure, and the difference is deliberate.
    This file's own header argues that a gate which is always red teaches
    everyone to ignore it, and the only gate that catches anything in this
    project is the one somebody runs locally before pushing. An ``xfail``
    reports as ``xfailed`` in the summary rather than as a pass, so the count
    is visible on every run and cannot be mistaken for health, while a suite
    somebody is willing to keep running stays runnable. It is one decorator
    away from being a hard failure if that is the call.

    What this does NOT do is decide who is right. Saudi Arabia is 5 here, 15
    in the seed and 15 in the catalogue; two against one is not evidence, it
    is a tally.
    """
    mispriced = _shared_region_mismatches()

    listing = [
        f"  {country}: the bill charges {region_rate}, the country's own rate is {own} "
        f"({_SERVED_BY_A_SHARED_REGION.get(country, 'no reason recorded')})"
        for country, (region_rate, own) in sorted(mispriced.items())
    ]

    assert mispriced == {}, (
        f"{len(mispriced)} countries are priced at a rate that is not theirs:\n"
        + "\n".join(listing)
        + "\nEach is a fallback line carrying another country's rate. It reaches a bill only "
        "where the tax seed cannot answer, which today means a country with no seed row or an "
        "unseeded database; a seeded country is invoiced its own rate before this table is "
        "consulted. Fixing this is a decision about splitting regions, not about which table "
        "to copy."
    )


def test_reintroducing_the_israeli_bill_defect_is_caught() -> None:
    """The bill table put back to 17, against the real comparison.

    The other direction from the seed control above: there the seed went stale
    and the bill was right, here the bill goes stale and everything else is
    right. This is the shape the defect actually had.
    """
    perturbed = []
    for name, table in _tables():
        table = dict(table)
        if name.endswith("markup_templates.py"):
            table[("IL", "standard")] = Decimal("0.17")
        perturbed.append((name, table))

    _, disagreements = _disagreements(perturbed, _seed_history())

    assert any("markup_templates.py" in line and "IL standard" in line.strip() for line in disagreements), (
        f"a stale rate in the bill table was not reported: {disagreements}"
    )


def test_the_tax_tables_agree_where_they_overlap() -> None:
    """Fail when two tables carry a rate for the same country and disagree."""
    population, disagreements = _disagreements(_tables(), _seed_history())

    print(f"\nCompared {len(population)} (country, rate class) keys carried by two or more tables:")
    print("\n".join(population))

    assert disagreements == [], "tax tables disagree:\n" + "\n".join(disagreements)


def test_a_planted_disagreement_is_caught() -> None:
    """The control: prove the gate can fail, not only that it passes.

    Note that this calls ``_disagreements`` - the same function the real test
    calls - on a perturbed copy of the tables. A control that re-implemented
    the comparison here would stay green if the real loop were broken, which
    is the failure this whole file exists to make impossible.
    """
    tables = _tables()
    # Found by name rather than by position. This used to take the last entry,
    # which was the seed until a fourth table was appended after it - at which
    # point the control was perturbing the methodology catalogue while claiming
    # to perturb the seed. A control that quietly measures something else is
    # worse than no control.
    seed_index = next(i for i, (name, _) in enumerate(tables) if name.endswith("tax_configurations.json"))
    seed_name, seed = tables[seed_index]

    others = [key for key in seed if sum(key in t for _, t in tables) >= 2]
    assert others, "no seed key is carried by a second table"
    key = sorted(others)[0]
    carriers = sum(key in t for _, t in tables)

    perturbed = [(name, dict(table)) for name, table in tables]
    perturbed[seed_index][1][key] = seed[key] + Decimal("0.01")

    population, disagreements = _disagreements(perturbed, _seed_history())

    # Every other table carrying that key now disagrees with the seed.
    assert len(disagreements) == carriers - 1, disagreements
    assert all(f"{key[0]} {key[1]}:" in line for line in disagreements)
    assert all(seed_name in line for line in disagreements)
    # Perturbing a value must not change which keys are comparable.
    assert len(population) == len(_disagreements(tables, _seed_history())[0])


def test_a_stale_value_is_named_as_stale() -> None:
    """The second control: the staleness message must actually be reachable.

    The lead asked for two failures, disagreement and staleness, and the
    staleness branch only runs inside a disagreement. No live country has
    both a closed period and a counterpart elsewhere, so on today's data
    that branch never executes and would rot untested. This plants the case:
    a second table still carrying a rate the seed closed on a known date.
    """
    history = _seed_history()
    active = _seed_rates()
    candidates = sorted(key for key in history if key in active)
    assert candidates, "no seed key has both a closed period and a current rate"

    key = candidates[0]
    old_rate, ended = history[key][0]
    assert old_rate != active[key]

    stale_table = ("app/core/some_other_table.py", {key: old_rate})
    seed_table = (str(_SEED.relative_to(_BACKEND)), active)

    _, disagreements = _disagreements([stale_table, seed_table], history)

    assert len(disagreements) == 1, disagreements
    line = disagreements[0]
    assert "looks stale" in line
    assert ended in line, f"the message does not name the date the period closed: {line}"
    assert stale_table[0] in line
    assert seed_table[0] in line


def test_reintroducing_the_israeli_defect_is_caught() -> None:
    """The control for the fourth table: put the real defect back and require a red.

    Everything above is measured on a file that has been fixed, and a check
    that has only ever seen the fixed state is not evidence it would have
    caught the broken one. So this rebuilds it exactly: the seed carrying
    Israel's superseded 17 % as the rate in force, the catalogue carrying 18,
    and nothing else changed.

    Two claims, and the second is the one that makes the failure useful rather
    than merely present. The comparison has to notice, and it has to say the
    seed is the stale side, which it can because the seed's own closed window
    names the date the 17 % rate ended.
    """
    perturbed = []
    for name, table in _tables():
        table = dict(table)
        if name.endswith("tax_configurations.json"):
            table[("IL", "standard")] = Decimal("0.17")
        perturbed.append((name, table))

    _, disagreements = _disagreements(perturbed, _seed_history())

    israeli = [line for line in disagreements if line.strip().startswith("IL standard")]
    assert israeli, (
        "the seed was put back to Israel's superseded 17 % and nothing was reported, so the "
        f"methodology catalogue is not being compared against it. Disagreements found: {disagreements}"
    )
    assert any("looks stale" in line and "2024-12-31" in line for line in israeli), (
        f"the disagreement was reported without naming the seed as the stale side: {israeli}"
    )


def test_the_catalogue_side_can_fail_too() -> None:
    """And in the other direction: a catalogue rate that drifts off the seed's.

    The test above moves the seed. If the comparison were somehow keyed to the
    seed alone, it would pass while a wrong figure in the catalogue - the table
    that decides what a project actually charges - went unreported.
    """
    perturbed = []
    for name, table in _tables():
        table = dict(table)
        if name.endswith("templates.py"):
            table[("IL", "standard")] = Decimal("0.17")
        perturbed.append((name, table))

    _, disagreements = _disagreements(perturbed, _seed_history())

    assert any("templates.py" in line and "IL standard" in line.strip() for line in disagreements), (
        f"a wrong rate in the methodology catalogue was not reported: {disagreements}"
    )


def test_two_templates_disagreeing_about_one_country_are_refused() -> None:
    """The catalogue reader's own guard, exercised on data that reaches it.

    A country may hold more than one methodology - Brazil, Chile and Colombia
    each ship a flat template and an APU one - and today every such pair quotes
    the same VAT rate, so this guard never fires on the shipped catalogue. That
    makes it the one line in this file no measurement has ever seen do
    anything. If it were broken, the reader would keep whichever template the
    catalogue happened to list last and the comparison would silently depend on
    file order rather than on agreement.
    """
    with pytest.raises(AssertionError, match="two methodology templates"):
        _catalogue_rates_raw(
            [
                {"slug": "xx-flat", "country_code": "XX", "vat_rate": "19"},
                {"slug": "xx-apu", "country_code": "XX", "vat_rate": "21"},
            ]
        )

    agreeing = _catalogue_rates_raw(
        [
            {"slug": "xx-flat", "country_code": "XX", "vat_rate": "19"},
            {"slug": "xx-apu", "country_code": "XX", "vat_rate": "19"},
        ]
    )
    assert agreeing[("XX", "standard")] == Decimal("0.19"), (
        "two templates that agree must be accepted, or the guard would be refusing the shape "
        "Brazil, Chile and Colombia actually ship rather than the disagreement it is aimed at"
    )


@pytest.mark.parametrize("path", [_SEED, _YAML, _CORE, _CATALOGUE, _MARKUP])
def test_every_table_this_check_reads_still_exists(path: Path) -> None:
    """A moved or renamed table must break the check rather than empty it."""
    assert path.is_file(), f"{path} is gone; the drift check is reading nothing"
