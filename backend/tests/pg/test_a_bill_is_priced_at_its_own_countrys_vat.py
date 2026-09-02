# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: a seeded bill charges its own country's VAT, not its region's.

The defect
----------
``DEFAULT_MARKUP_TEMPLATES`` is keyed by region and fifty countries map onto
forty-two regions, so a region that serves several markets carries one VAT
number and it is one member's. A bill on a project that set no rate of its own
took that number: Austria was invoiced at Germany's 19 against its own 20,
Switzerland at 19 against its own 8.1, Saudi Arabia at the Gulf's 5 against its
own 15, Ireland at Britain's 20 against its own 23. The methodology engine has
read the country's own rate from the catalogue all along, so the two engines
priced the same project differently.

What this gate asserts is the end of that: for every country the bill prices
with a single tax line, the line on a freshly seeded bill equals the rate the
shipped tax seed states as in force, or the country is named below with a
reason. The list is hand-written and checked in both directions, so a country
mapped onto a shared region tomorrow lands red here instead of being absorbed
by a rule that grows on its own.

Three populations, counted apart
-------------------------------
"No disagreements" over the whole set would read as forty-five countries
verified when it is thirty-four verified, ten unmeasured and one asserted
against a different number. A country with no row in the seed cannot be
checked against the seed, so it is reported as unmeasured rather than as
agreement, and every denominator is printed beside the verdict.

The third population is one country and it is the interesting one. China's
seed row carries the headline 13 and its bill is priced at the 9 tier
construction is charged at, so the rule the other thirty-four obey would move
a Chinese bill to a number that is right about the wrong question. It is named
in ``CONSTRUCTION_TIER_COUNTRIES`` and asserted against the tier instead.

Gated by ``OE_TEST_DB=pg`` (see conftest): it needs stored Project, BOQ and
TaxConfiguration rows and it reads the markups back off the table, because the
point is what a bill is actually seeded with rather than what a resolver
returns.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.boq.markup_templates import (
    CONSTRUCTION_TIER_COUNTRIES,
    DEFAULT_MARKUP_TEMPLATES,
    NON_SINGLE_TAX_REGIONS,
    REGION_BY_COUNTRY,
    resolve_region_lines,
)
from app.modules.boq.models import BOQ, BOQMarkup
from app.modules.boq.service import BOQService
from app.modules.i18n_foundation.models import TaxConfiguration
from app.modules.i18n_foundation.seed import load_tax_seed_rows, tax_configuration_from_seed_row
from app.modules.i18n_foundation.tax_rules import resolve as resolve_tax
from app.modules.i18n_foundation.tax_rules import row_from_mapping
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


#: Countries the bill prices from a region line because the shipped tax seed
#: has no row for them, with the reason each is left that way.
#:
#: Every one of them owns its region outright - the region serves that country
#: and nobody else - so the number on the line is that country's own rate,
#: written in the markup table instead of the effective-dated one. That is why
#: none of them is a rate invented to fill a gap: there is nothing here to
#: correct, only a fact recorded in one table and not the other. A row guessed
#: for any of them would be a confident number where a visible absence is.
#:
#: This is the list that must not grow by itself. A country added to a SHARED
#: region with no seed row of its own would be a real defect and is not
#: excused by anything here; it fails
#: ``test_the_countries_priced_without_a_seed_row_are_exactly_the_named_set``.
_NO_SEED_ROW: dict[str, str] = {
    "AR": "sole country of region AR, whose line carries Argentina's own 21",
    "CL": "sole country of region CL, whose line carries Chile's own 19",
    "GR": "sole country of region GR, whose line carries Greece's own 24",
    "ID": "sole country of region ID, whose line carries Indonesia's own 11",
    "KE": "sole country of region KE, whose line carries Kenya's own 16",
    "MA": "sole country of region MA, whose line carries Morocco's own 20",
    "PE": "sole country of region PE, whose line carries Peru's own 18",
    "PH": "sole country of region PH, whose line carries the Philippines' own 12",
    "TH": "sole country of region TH, whose line carries Thailand's own 7",
    "VN": "sole country of region VN, whose line carries Vietnam's own 10",
}

#: Countries whose stack carries two consumption levies or none, so no single
#: number is "the VAT rate" and the swap is refused inside
#: ``resolve_region_lines``. Named rather than derived from
#: ``NON_SINGLE_TAX_REGIONS`` so that mapping a country onto one of those
#: regions is a decision somebody writes down here.
_NO_SINGLE_TAX_LINE: dict[str, str] = {
    "BR": "PIS + COFINS at 3.65 and ISS at 3, two levies at two statutory rates",
    "CA": "GST and the provincial rates are levied per province, not on the contract sum",
    "CO": "IVA sits in the unit rate rather than on a bill-level line",
    "MY": "SST is charged on taxable supplies, not as one rate on the contract sum",
    "US": "sales tax is levied on materials at purchase and sits in the unit rate",
}


def _priced_countries() -> dict[str, str]:
    """Countries whose region carries exactly one tax line, mapped to it."""
    out: dict[str, str] = {}
    for country, region in REGION_BY_COUNTRY.items():
        if region in NON_SINGLE_TAX_REGIONS:
            continue
        lines = [line for line in DEFAULT_MARKUP_TEMPLATES[region] if line.get("category") == "tax"]
        if len(lines) != 1:
            raise AssertionError(
                f"region {region} carries {len(lines)} tax lines and is not named in "
                f"NON_SINGLE_TAX_REGIONS, so no single number is its VAT rate. Name it there "
                f"with the reason rather than letting this population shrink in silence."
            )
        out[country.upper()] = region
    return out


def _seed_rate(country: str) -> Decimal | None:
    """The rate the shipped seed states as in force for a country, or None."""
    rows = [row_from_mapping(row) for row in load_tax_seed_rows()]
    resolution = resolve_tax(rows, country)
    if not resolution.resolved or resolution.combined_rate_pct is None:
        return None
    return Decimal(resolution.combined_rate_pct)


async def _install_tax_seed(session) -> int:
    """Put every shipped tax row on the table, as a seeded install has them."""
    rows = load_tax_seed_rows()
    for row in rows:
        session.add(tax_configuration_from_seed_row(row))
    await session.flush()
    return len(rows)


async def _bill_for(session, country: str | None, *, vat: str | None = None, base_date: str | None = None) -> BOQ:
    """A stored project in one country and an empty bill on it."""
    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"vat-{tag}@example.test", hashed_password="x", full_name="VAT")
    session.add(owner)
    await session.flush()

    project = Project(
        name=f"Bill {country or 'nowhere'} {tag}",
        owner_id=owner.id,
        currency="EUR",
        country_code=country,
        default_vat_rate=vat,
    )
    session.add(project)
    await session.flush()

    boq = BOQ(project_id=project.id, name=f"Bill {tag}", base_date=base_date)
    session.add(boq)
    await session.flush()
    return boq


async def _tax_lines(session, boq_id) -> list[BOQMarkup]:
    """The seeded tax lines, read back off the table rather than returned."""
    result = await session.execute(select(BOQMarkup).where(BOQMarkup.boq_id == boq_id, BOQMarkup.category == "tax"))
    return list(result.scalars().all())


async def test_every_priced_country_is_billed_its_own_rate(pg_session) -> None:
    """The gate. A bill's tax line equals its own country's rate in the seed."""
    await _install_tax_seed(pg_session)
    priced = _priced_countries()

    checked: list[str] = []
    unmeasured: list[str] = []
    tiered: list[str] = []
    wrong: list[str] = []

    for country in sorted(priced):
        expected = _seed_rate(country)
        boq = await _bill_for(pg_session, country)
        await BOQService(pg_session).apply_default_markups(boq.id)
        lines = await _tax_lines(pg_session, boq.id)
        assert len(lines) == 1, f"{country} seeded {len(lines)} tax lines, expected one"
        billed = Decimal(lines[0].percentage)

        if expected is None:
            unmeasured.append(country)
            if country not in _NO_SEED_ROW:
                wrong.append(
                    f"{country} has no row in the shipped tax seed and is not named in _NO_SEED_ROW. "
                    f"Its bill is charged {billed} from region {priced[country]}."
                )
            continue

        if country in CONSTRUCTION_TIER_COUNTRIES:
            # Not compared against the seed's answer, because the seed answers
            # a different question here. Asserted against the construction tier
            # instead, in ``test_a_construction_tier_survives_its_countrys_headline_rate``.
            tiered.append(country)
            continue

        checked.append(country)
        if billed != expected:
            wrong.append(f"{country} is billed {billed} from region {priced[country]} but its own rate is {expected}")

    print(
        f"\npopulation: {len(priced)} countries priced with a single tax line\n"
        f"  {len(checked)} resolved from the seed and compared\n"
        f"  {len(unmeasured)} have no seed row, so the region's line stood and nothing was compared: "
        f"{sorted(unmeasured)}\n"
        f"  {len(tiered)} charge construction at a tier of their own and are asserted elsewhere: "
        f"{sorted(tiered)}\n"
        f"  {len(_NO_SINGLE_TAX_LINE)} more countries carry two levies or none and are not in this population"
    )

    assert not wrong, "\n".join(["a bill is priced at a rate that is not its country's:", *wrong])
    assert checked, "nothing was compared, so this gate proved nothing"


async def test_the_countries_priced_without_a_seed_row_are_exactly_the_named_set(pg_session) -> None:
    """The excused set is pinned, so it can neither grow nor shrink unread.

    Fails in both directions on purpose. A country that gains a seed row stops
    needing its entry, and an entry left behind would excuse the next real
    defect there in silence.
    """
    measured = {country for country in _priced_countries() if _seed_rate(country) is None}

    assert measured == set(_NO_SEED_ROW), (
        f"the countries the bill prices without a rate of their own have changed.\n"
        f"  measured: {sorted(measured)}\n"
        f"  named:    {sorted(_NO_SEED_ROW)}\n"
        f"  newly unseeded and unnamed: {sorted(measured - set(_NO_SEED_ROW))}\n"
        f"  named but seeded now:       {sorted(set(_NO_SEED_ROW) - measured)}\n"
        f"Add a seed row, or name it here with the reason it is left without one."
    )
    for country, reason in _NO_SEED_ROW.items():
        assert reason.strip(), f"{country} is excused with an empty reason, which excuses nothing"


async def test_a_construction_tier_survives_its_countrys_headline_rate(pg_session) -> None:
    """China's bill stays at 9 when the seed says its standard rate is 13.

    The regression this exists to stop is the one that looks like a fix.
    Resolving a country's own rate from the seed is right almost everywhere,
    and here it swaps a correct construction rate for a correct general one:
    both numbers are defensible, only one is about building work, and nothing
    in the unit lane can see it. The drift gate excuses China on exactly this
    axis, so it stayed green while the bill moved from 9 to 13.

    A project that states its own rate still wins, because that is somebody
    answering the question rather than a table answering a different one.
    """
    await _install_tax_seed(pg_session)
    assert set(CONSTRUCTION_TIER_COUNTRIES) == {"CN"}, (
        "a country was added to or removed from the construction-tier set without this test "
        "being told which rate its bill should carry"
    )
    assert _seed_rate("CN") == Decimal("13"), "China's headline rate is no longer 13, so this proves nothing"

    tier = Decimal(
        str([line for line in resolve_region_lines("CN", vat_rate=None) if line["category"] == "tax"][0]["percentage"])
    )
    assert tier == Decimal("9.0"), "the Chinese stack no longer carries the 9 percent construction tier"

    boq = await _bill_for(pg_session, "CN")
    await BOQService(pg_session).apply_default_markups(boq.id)
    line = (await _tax_lines(pg_session, boq.id))[0]
    assert Decimal(line.percentage) == tier, (
        f"a Chinese bill was seeded at {line.percentage}. Construction is charged at {tier} there; "
        f"{_seed_rate('CN')} is the headline rate and answers a different question."
    )
    assert line.metadata_.get("vat_rate_source") == "region_template"

    stated = await _bill_for(pg_session, "CN", vat="6")
    await BOQService(pg_session).apply_default_markups(stated.id)
    line = (await _tax_lines(pg_session, stated.id))[0]
    assert Decimal(line.percentage) == Decimal("6"), "a project that stated its own rate was overruled by the tier"
    assert line.metadata_["vat_rate_source"] == "project"

    for country, reason in CONSTRUCTION_TIER_COUNTRIES.items():
        assert reason.strip(), f"{country} claims a construction tier with no reason, which claims nothing"


async def test_a_country_with_no_single_tax_line_keeps_its_own_rates(pg_session) -> None:
    """Brazil's two levies survive a country that has a seed rate of its own.

    The guard lives inside ``resolve_region_lines``, so asserting on its return
    value proves nothing about the bill: what has to be shown is that the new
    country-rate lookup does not reach these regions by another path. The seed
    names 18 for Brazil, which is exactly the number that once doubled the tax
    on a Brazilian bill by being applied to both levies.
    """
    await _install_tax_seed(pg_session)
    assert _seed_rate("BR") == Decimal("18"), "Brazil no longer has a seed rate, so this proves nothing"

    boq = await _bill_for(pg_session, "BR")
    await BOQService(pg_session).apply_default_markups(boq.id)
    lines = await _tax_lines(pg_session, boq.id)

    template = {
        str(line["name"]): line for line in resolve_region_lines("BR", vat_rate=None) if line["category"] == "tax"
    }
    assert len(lines) == len(template) == 2

    for line in lines:
        expected = template[line.name]
        assert Decimal(line.percentage) == Decimal(str(expected["percentage"])), (
            f"Brazil's {line.name} was seeded at {line.percentage}, not the region's "
            f"{expected['percentage']}. A single VAT number reached a two-levy stack."
        )
        assert line.markup_type == str(expected.get("markup_type", "percentage"))
        assert line.apply_to == str(expected.get("apply_to", "direct_cost"))
        assert Decimal(line.fixed_amount) == Decimal(str(expected.get("fixed_amount", "0")))
        assert line.sort_order == int(expected["sort_order"])
        assert line.metadata_.get("vat_override") is None, "a multi-levy line reports a rate was swapped into it"
        assert line.metadata_.get("vat_rate_source") == "region_template"


async def test_a_database_with_no_tax_seed_still_seeds_a_bill(pg_session) -> None:
    """A fresh install has no tax table content, and must still price a bill.

    The failure this rules out is worse than the defect it replaces: a bill
    that refuses to seed because the rate lookup found nothing would break
    every install on its first project.
    """
    empty = (await pg_session.execute(select(TaxConfiguration))).scalars().all()
    assert not empty, "this test needs an unseeded tax table to mean anything"

    boq = await _bill_for(pg_session, "AT")
    created = await BOQService(pg_session).apply_default_markups(boq.id)
    assert created, "a bill on an unseeded database seeded no markups at all"

    lines = await _tax_lines(pg_session, boq.id)
    assert len(lines) == 1
    template = [line for line in resolve_region_lines("DACH", vat_rate=None) if line["category"] == "tax"][0]
    assert Decimal(lines[0].percentage) == Decimal(str(template["percentage"]))
    assert lines[0].metadata_.get("vat_rate_source") == "region_template", (
        "an unseeded database fell back to the region's line without saying so, which is "
        "indistinguishable from a rate that was resolved"
    )


async def test_where_the_rate_came_from_is_recorded_on_the_line(pg_session) -> None:
    """The three sources tell themselves apart on the stored markup.

    A boolean cannot say this. ``vat_override`` answers "was this line's rate
    replaced", which is true for a project override and for a country rate
    alike, so the case the region's own line stood is the one that has to stop
    being silent.
    """
    await _install_tax_seed(pg_session)
    service = BOQService(pg_session)

    from_project = await _bill_for(pg_session, "AT", vat="7")
    await service.apply_default_markups(from_project.id)
    line = (await _tax_lines(pg_session, from_project.id))[0]
    assert Decimal(line.percentage) == Decimal("7")
    assert line.metadata_["vat_rate_source"] == "project"
    assert line.metadata_["vat_override"] is True

    from_seed = await _bill_for(pg_session, "AT")
    await service.apply_default_markups(from_seed.id)
    line = (await _tax_lines(pg_session, from_seed.id))[0]
    assert Decimal(line.percentage) == Decimal("20"), "Austria is still billed Germany's rate"
    assert line.metadata_["vat_rate_source"] == "country_seed"

    from_region = await _bill_for(pg_session, "AR")
    await service.apply_default_markups(from_region.id)
    line = (await _tax_lines(pg_session, from_region.id))[0]
    assert line.metadata_["vat_rate_source"] == "region_template"
    assert line.metadata_.get("vat_override") is None


async def test_kuwait_is_billed_the_nothing_it_levies(pg_session) -> None:
    """Zero is a rate, and the one a truthiness test would throw away.

    Kuwait and Qatar sit on the Gulf stack with the UAE and Saudi Arabia and
    were billed its 5 percent. Their seed rows say 0, and every step between
    the resolver and the stored line has to carry that as a value rather than
    as an absence: ``"0" or None`` is the shape that would quietly send both
    back to 5 while every test on a non-zero country still passed.
    """
    await _install_tax_seed(pg_session)

    for country in ("KW", "QA"):
        assert _seed_rate(country) == Decimal("0")
        boq = await _bill_for(pg_session, country)
        await BOQService(pg_session).apply_default_markups(boq.id)
        line = (await _tax_lines(pg_session, boq.id))[0]

        assert Decimal(line.percentage) == Decimal("0"), (
            f"{country} levies no VAT and its bill charges {line.percentage}. The Gulf region's "
            f"5 percent belongs to the UAE and Saudi Arabia."
        )
        assert line.metadata_["vat_rate_source"] == "country_seed", (
            f"{country} was billed zero, but as the region's own line rather than as its own "
            f"resolved rate, so the two cases are still indistinguishable"
        )


async def test_a_quarter_label_in_base_date_does_not_pick_a_tax_window(pg_session) -> None:
    """``base_date`` is free text, and two of its shipped values sort opposite ways.

    The column is ``String(40)`` with no format validation and the shipped demo
    packs put ``"2026-Q1"`` and ``"2026-01"`` in it. ``active_rows`` compares
    date strings, so ``"2026-Q1"`` sorts ABOVE ``"2026-02-01"`` and
    ``"2026-01"`` sorts BELOW it: neither is a date, and passing them through
    would select windows in opposite directions without failing. Israel is the
    country where that shows, because it has two windows and the older one is
    the superseded 17.
    """
    await _install_tax_seed(pg_session)
    current = _seed_rate("IL")
    assert current == Decimal("18")

    for label in ("2026-Q1", "2026-01", "not a date", ""):
        boq = await _bill_for(pg_session, "IL", base_date=label)
        await BOQService(pg_session).apply_default_markups(boq.id)
        line = (await _tax_lines(pg_session, boq.id))[0]
        assert Decimal(line.percentage) == current, (
            f"base_date {label!r} was read as a date and selected a tax window: the bill was "
            f"charged {line.percentage} rather than the {current} in force today"
        )

    dated = await _bill_for(pg_session, "IL", base_date="2020-06-01")
    await BOQService(pg_session).apply_default_markups(dated.id)
    line = (await _tax_lines(pg_session, dated.id))[0]
    assert Decimal(line.percentage) == Decimal("17"), (
        "a real ISO base date must still price the window in force then, or this test is "
        "only proving that base_date is ignored altogether"
    )


async def test_a_broken_seed_row_falls_back_loudly(pg_session, caplog) -> None:
    """A row that is present and wrong is not the same event as one that is absent.

    Both end at the region's line and both stamp ``region_template``, because
    that is honestly where the number came from. What separates them is the
    log: an unseeded install is the expected state of a fresh database and
    says nothing, while a rate the resolver refuses is somebody's data defect
    and has to name itself. Austria is the country to prove it on, because its
    fallback is Germany's 19 against its own 20 - a number wrong enough to
    matter and plausible enough that nobody would question it on sight.
    """
    await _install_tax_seed(pg_session)
    austria = (
        (
            await pg_session.execute(
                select(TaxConfiguration).where(
                    TaxConfiguration.country_code == "AT",
                    TaxConfiguration.is_default.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(austria) == 1, (
        f"this test corrupts the rate Austria is billed at and needs exactly one row to carry it, found {len(austria)}"
    )
    assert austria[0].rate_pct == "20.0", "Austria's standard rate moved; corrupt the row that is still the one billed"
    austria[0].rate_pct = "twenty"
    await pg_session.flush()

    boq = await _bill_for(pg_session, "AT")
    with caplog.at_level(logging.WARNING, logger="app.modules.boq.service"):
        created = await BOQService(pg_session).apply_default_markups(boq.id)
    assert created, "a bill refused to seed because one tax row was unreadable"

    line = (await _tax_lines(pg_session, boq.id))[0]
    template = [entry for entry in resolve_region_lines("DACH", vat_rate=None) if entry["category"] == "tax"][0]
    assert Decimal(line.percentage) == Decimal(str(template["percentage"]))
    assert line.metadata_.get("vat_rate_source") == "region_template"

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING and "AT" in r.getMessage()]
    assert warnings, (
        "a bill was priced off its region's stack because Austria's tax rate does not parse, and "
        "nothing said so: the stored line reads region_template exactly as an unseeded database "
        "does, so this log line is the only place the two can be told apart"
    )
    assert "rate_not_numeric" in warnings[0].getMessage(), (
        f"the warning must name which rule the row breaks, got {warnings[0].getMessage()!r}"
    )
