"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Resolving a Canadian tax rate: does asking for a province get that province?

The platform could always *store* a per-province rate. What it could not do was
*select* one. The province lived inside ``tax_code`` as a naming convention -
``HST_ON``, ``PST_BC`` - that no query could filter on and that only a helper in
one test file ever parsed, so asking for Canada's tax configuration handed back
thirteen undifferentiated rows and left the caller to do the arithmetic. The
obvious arithmetic, federal plus whatever my province charges, is right in
British Columbia and reports an 18 % Ontario invoice.

These tests run against real rows through the service, which is the half a
seed-file test cannot cover: the seed data being right proves nothing about a
resolver that never reads the province. The companion file
``test_i18n_foundation_tax_combination.py`` covers the other half, the shipped
data, using this same resolver.

**The control that matters most is Alberta.** Alberta levies no provincial
sales tax, so the correct answer there is the federal 5 % - and 5 % is also what
a resolver returns for a province it has never heard of, or for a project where
nobody recorded a province at all. Those three must not be one answer. Alberta
is a rate a quantity surveyor can put in a tender; the other two are questions
nobody answered, and this module returns no rate for them. If that distinction
ever collapses, ``test_alberta_and_an_unknown_province_do_not_answer_alike``
is what convicts it.

Rates and their sources, all read from a government publication in August 2026:

* federal GST 5 %, Excise Tax Act s.165(1)
* Ontario 13, New Brunswick 15, Newfoundland and Labrador 15, Prince Edward
  Island 15 - SOR/2016-119 and SOR/2016-212
* Nova Scotia 14 from 2025-04-01, 15 before it - SOR/2025-77, which cut the
  provincial component from 10 % to 9 %
* British Columbia PST 7 %, Saskatchewan PST 6 %, Manitoba RST 7 %, all on the
  pre-GST amount - the three provincial finance ministries
* Quebec QST 9.975 % on the pre-GST amount since 2013-01-01, and 9.5 % on the
  GST-included amount before it - Ministere des Finances du Quebec information
  bulletin 2012-4
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.service import I18nFoundationService
from app.modules.i18n_foundation.subdivisions import CANADA_SUBDIVISIONS
from tests.modules.i18n_foundation.conftest import make_tax

#: A date comfortably inside every current rate's window.
TODAY = "2026-08-26"

#: The thirteen shipped Canadian rows, minus the federal one, as
#: (tax_code, subdivision, rate, combination, tax_type, effective_from,
#: effective_to). Written out rather than loaded from the seed file on purpose:
#: this file is the instrument that checks the *resolver*, so its input has to
#: be independent of the file the other instrument checks. If both read the
#: same JSON, one typo passes twice.
_PROVINCIAL_ROWS = (
    ("HST_ON", "CA-ON", "13.0", "replaces_federal", "gst", "2010-07-01", None),
    ("HST_NS", "CA-NS", "15.0", "replaces_federal", "gst", "2010-07-01", "2025-03-31"),
    ("HST_NS", "CA-NS", "14.0", "replaces_federal", "gst", "2025-04-01", None),
    ("HST_NB", "CA-NB", "15.0", "replaces_federal", "gst", "2016-07-01", None),
    ("HST_NL", "CA-NL", "15.0", "replaces_federal", "gst", "2016-07-01", None),
    ("HST_PE", "CA-PE", "15.0", "replaces_federal", "gst", "2016-10-01", None),
    ("QST_QC", "CA-QC", "9.975", "stacks_on_federal", "vat", "2013-01-01", None),
    ("PST_BC", "CA-BC", "7.0", "stacks_on_federal", "sales_tax", "2013-04-01", None),
    ("PST_SK", "CA-SK", "6.0", "stacks_on_federal", "sales_tax", "2017-03-23", None),
    ("RST_MB", "CA-MB", "7.0", "stacks_on_federal", "sales_tax", "2019-07-01", None),
)

#: What a quantity surveyor in each of the thirteen jurisdictions pays, and how
#: the resolver is expected to have got there. The status is asserted alongside
#: the number because 5 % is the right answer in four places for one reason and
#: the wrong answer everywhere else for another.
_PUBLISHED = {
    "CA-ON": ("13", "harmonised"),
    "CA-NS": ("14", "harmonised"),
    "CA-NB": ("15", "harmonised"),
    "CA-NL": ("15", "harmonised"),
    "CA-PE": ("15", "harmonised"),
    "CA-QC": ("14.975", "stacked"),
    "CA-BC": ("12", "stacked"),
    "CA-SK": ("11", "stacked"),
    "CA-MB": ("12", "stacked"),
    "CA-AB": ("5", "federal_only"),
    "CA-YT": ("5", "federal_only"),
    "CA-NT": ("5", "federal_only"),
    "CA-NU": ("5", "federal_only"),
}


async def seed_canada(session: AsyncSession) -> None:
    """Insert the federal rate and every provincial rate, as shipped."""
    await make_tax(
        session,
        country_code="CA",
        tax_name="GST",
        tax_code="GST",
        rate_pct="5.0",
        tax_type="gst",
        combination="federal",
        effective_from="2008-01-01",
    )
    for tax_code, subdivision, rate, combination, tax_type, start, end in _PROVINCIAL_ROWS:
        await make_tax(
            session,
            country_code="CA",
            tax_name=tax_code,
            tax_code=tax_code,
            rate_pct=rate,
            tax_type=tax_type,
            combination=combination,
            subdivision_code=subdivision,
            effective_from=start,
            effective_to=end,
            is_default=False,
        )


# ── Every jurisdiction, against its published figure ─────────────────────────


@pytest.mark.parametrize(("subdivision", "expected"), sorted(_PUBLISHED.items()))
async def test_the_combined_rate_matches_the_published_figure(
    session: AsyncSession,
    subdivision: str,
    expected: tuple[str, str],
) -> None:
    """All thirteen provinces and territories, rate and reasoning both."""
    await seed_canada(session)
    service = I18nFoundationService(session)

    resolution = await service.resolve_tax_rate("CA", subdivision, TODAY)

    rate, status = expected
    assert resolution.combined_rate_pct == rate
    assert resolution.status == status
    assert resolution.resolved is True


async def test_every_canadian_subdivision_is_covered_by_this_file() -> None:
    """The parametrize list is the registry, not a subset somebody trimmed.

    A published table that quietly stopped covering three territories would
    still be all green. This ties the two together so adding a subdivision to
    the registry without a figure fails here rather than going unnoticed.
    """
    assert set(_PUBLISHED) == set(CANADA_SUBDIVISIONS)


# ── The transposed defect: federal-only versus unanswerable ──────────────────


async def test_alberta_and_an_unknown_province_do_not_answer_alike(session: AsyncSession) -> None:
    """DEFECT GUARD: 5 % is a real Alberta rate and a wrong answer elsewhere.

    Alberta has no provincial sales tax, so the federal 5 % is the whole
    answer there. A resolver that simply returns the federal rate whenever it
    finds no provincial row gives 5 % for Alberta, 5 % for a misspelled
    province and 5 % for a project whose province nobody recorded - and all
    three look identical to the caller. Two of them are wrong.

    So the three are asserted apart here, by status and by whether a rate came
    back at all. This is the test a resolver that ignores its province
    argument entirely cannot pass.
    """
    await seed_canada(session)
    service = I18nFoundationService(session)

    alberta = await service.resolve_tax_rate("CA", "CA-AB", TODAY)
    nonsense = await service.resolve_tax_rate("CA", "CA-ZZ", TODAY)
    unstated = await service.resolve_tax_rate("CA", None, TODAY)

    assert (alberta.status, alberta.combined_rate_pct, alberta.resolved) == ("federal_only", "5", True)
    assert (nonsense.status, nonsense.combined_rate_pct, nonsense.resolved) == ("subdivision_unknown", None, False)
    assert (unstated.status, unstated.combined_rate_pct, unstated.resolved) == ("subdivision_unknown", None, False)

    # And the two unanswered ones still say what they do know, so a caller can
    # show the federal layer while telling the user the province is missing.
    assert nonsense.federal_rate_pct == "5"
    assert unstated.federal_rate_pct == "5"
    assert "subdivision" in (unstated.reason or "").lower()


async def test_two_provinces_do_not_answer_alike(session: AsyncSession) -> None:
    """The province argument is consulted at all.

    Ontario replaces the federal rate and British Columbia stacks on it. A
    resolver that ignored the argument would return one number for both, and
    every published-figure test above would still pass for whichever province
    happened to be first in the table.
    """
    await seed_canada(session)
    service = I18nFoundationService(session)

    ontario = await service.resolve_tax_rate("CA", "CA-ON", TODAY)
    british_columbia = await service.resolve_tax_rate("CA", "CA-BC", TODAY)

    assert ontario.combined_rate_pct != british_columbia.combined_rate_pct
    assert (ontario.combined_rate_pct, british_columbia.combined_rate_pct) == ("13", "12")


async def test_a_harmonised_province_does_not_add_the_federal_rate(session: AsyncSession) -> None:
    """The 18 % invoice, asserted as the thing that must not happen.

    Ontario's 13 % already contains the federal 5 %. Adding them is the single
    most likely wrong implementation, so the wrong answer is named rather than
    merely excluded by asserting the right one.
    """
    await seed_canada(session)
    service = I18nFoundationService(session)

    resolution = await service.resolve_tax_rate("CA", "CA-ON", TODAY)

    assert Decimal(resolution.combined_rate_pct or "0") != Decimal("18")
    assert resolution.combined_rate_pct == "13"
    # The federal layer is reported but is not part of the total.
    assert resolution.federal_rate_pct == "5"
    assert [c.tax_code for c in resolution.components] == ["HST_ON"]


# ── Compounding: order changes the total ─────────────────────────────────────


async def test_a_compounding_rate_totals_more_than_the_same_rate_stacked(session: AsyncSession) -> None:
    """CONTROL: compounding is not a second name for stacking.

    Two identical 7 % provincial rates on the same 5 % federal rate, differing
    only in ``combination``. Stacked they come to 12; compounded, the province
    charges its 7 % on the federal-inclusive amount, so 7 x 1.05 = 7.35 and the
    total is 12.35. If these two come out equal, the compounding branch is dead
    code wearing a new name and every other test in this file would still pass.
    """
    await make_tax(
        session,
        country_code="CA",
        tax_name="GST",
        tax_code="GST",
        rate_pct="5.0",
        tax_type="gst",
        combination="federal",
    )
    await make_tax(
        session,
        country_code="CA",
        tax_name="Stacking province",
        tax_code="PST_BC",
        rate_pct="7.0",
        tax_type="sales_tax",
        combination="stacks_on_federal",
        subdivision_code="CA-BC",
        is_default=False,
    )
    await make_tax(
        session,
        country_code="CA",
        tax_name="Compounding province",
        tax_code="PST_MB",
        rate_pct="7.0",
        tax_type="sales_tax",
        combination="compounds_on_federal",
        subdivision_code="CA-MB",
        is_default=False,
    )
    service = I18nFoundationService(session)

    stacked = await service.resolve_tax_rate("CA", "CA-BC", TODAY)
    compounded = await service.resolve_tax_rate("CA", "CA-MB", TODAY)

    assert stacked.combined_rate_pct != compounded.combined_rate_pct
    assert (stacked.combined_rate_pct, stacked.status) == ("12", "stacked")
    assert (compounded.combined_rate_pct, compounded.status) == ("12.35", "compounded")


async def test_the_historical_quebec_rate_reproduces_the_published_effective_rate(
    session: AsyncSession,
) -> None:
    """The worked example the compounding member exists for.

    Until 2012-12-31 Quebec charged 9.5 % QST on the GST-included amount. The
    finance ministry's own bulletin puts the effective rate that produced at
    9.975 %, and that is why the rate became 9.975 % when the base changed to
    the pre-GST amount on 2013-01-01: the amount payable was not meant to move.

    So the two windows must total the same 14.975 % by two different routes,
    which is a stronger check than either alone - it pins the arithmetic
    against a number a government published rather than against itself.
    """
    await make_tax(
        session,
        country_code="CA",
        tax_name="GST",
        tax_code="GST",
        rate_pct="5.0",
        tax_type="gst",
        combination="federal",
    )
    await make_tax(
        session,
        country_code="CA",
        tax_name="QST (Quebec, GST-included base)",
        tax_code="QST_QC",
        rate_pct="9.5",
        tax_type="vat",
        combination="compounds_on_federal",
        subdivision_code="CA-QC",
        effective_to="2012-12-31",
        is_default=False,
    )
    await make_tax(
        session,
        country_code="CA",
        tax_name="QST (Quebec)",
        tax_code="QST_QC",
        rate_pct="9.975",
        tax_type="vat",
        combination="stacks_on_federal",
        subdivision_code="CA-QC",
        effective_from="2013-01-01",
        is_default=False,
    )
    service = I18nFoundationService(session)

    before = await service.resolve_tax_rate("CA", "CA-QC", "2012-12-31")
    after = await service.resolve_tax_rate("CA", "CA-QC", "2013-01-01")

    assert (before.status, before.combined_rate_pct) == ("compounded", "14.975")
    assert (after.status, after.combined_rate_pct) == ("stacked", "14.975")

    # The component breakdown is where the two differ, and it has to say so:
    # the old QST was charged on a bigger base, and its 9.5 % did the work of
    # 9.975 %.
    old_qst = [c for c in before.components if c.tax_code == "QST_QC"][0]
    assert (old_qst.rate_pct, old_qst.effective_rate_pct) == ("9.5", "9.975")
    assert old_qst.base == "consideration_plus_federal"

    new_qst = [c for c in after.components if c.tax_code == "QST_QC"][0]
    assert (new_qst.rate_pct, new_qst.effective_rate_pct) == ("9.975", "9.975")
    assert new_qst.base == "consideration"


# ── Dates ────────────────────────────────────────────────────────────────────


async def test_nova_scotia_reads_the_rate_that_was_in_force_on_the_day(session: AsyncSession) -> None:
    """SOR/2025-77 cut Nova Scotia from 15 % to 14 % on 2025-04-01.

    Both windows are on file, so a claim or a retention release dated before
    the cut has to price at the old rate. The boundary is asserted on both
    sides of one day, which is the only place an off-by-one could hide.
    """
    await seed_canada(session)
    service = I18nFoundationService(session)

    assert (await service.resolve_tax_rate("CA", "CA-NS", "2025-03-31")).combined_rate_pct == "15"
    assert (await service.resolve_tax_rate("CA", "CA-NS", "2025-04-01")).combined_rate_pct == "14"


async def test_a_province_resolves_to_federal_only_before_its_own_rate_began(session: AsyncSession) -> None:
    """Saskatchewan's current PST starts 2017-03-23; the day before is 5 %.

    Not "unknown": Saskatchewan is a province this platform knows, and on that
    date the rows on file say it levied nothing of its own. The distinction is
    the same one Alberta makes, reached through the effective-date window
    instead of through an absent row.
    """
    await seed_canada(session)
    service = I18nFoundationService(session)

    resolution = await service.resolve_tax_rate("CA", "CA-SK", "2017-03-22")

    assert (resolution.status, resolution.combined_rate_pct) == ("federal_only", "5")


# ── Countries without a subdivision axis ─────────────────────────────────────


async def test_a_single_tier_country_still_answers_without_a_subdivision(session: AsyncSession) -> None:
    """Germany has no provincial VAT, so asking without a province is fine.

    The subdivision axis must not turn into a requirement everywhere. A
    country with no sub-national rows and no registry answers exactly as it
    did before this feature existed.
    """
    await make_tax(session, country_code="DE", tax_name="VAT", rate_pct="19.0")
    service = I18nFoundationService(session)

    resolution = await service.resolve_tax_rate("DE", None, TODAY)

    assert (resolution.status, resolution.combined_rate_pct, resolution.resolved) == ("national", "19", True)


async def test_a_country_with_no_rows_says_so_rather_than_returning_zero(session: AsyncSession) -> None:
    """No configuration is not a zero rate."""
    service = I18nFoundationService(session)

    resolution = await service.resolve_tax_rate("XX", None, TODAY)

    assert (resolution.status, resolution.combined_rate_pct, resolution.resolved) == (
        "no_configuration",
        None,
        False,
    )


async def test_a_state_of_a_country_with_no_registry_is_unknown_not_federal_only(
    session: AsyncSession,
) -> None:
    """The United States has state rates on file but no enumerated states.

    California is loaded; Texas is not. Answering Texas with the 0 % federal
    layer would present a gap in our data as a priced answer, so it resolves
    as unknown instead. California, being on file, resolves normally.

    This is the rule that keeps the federal-only answer honest: it is reserved
    for subdivisions the platform actually enumerates, and the platform
    enumerates Canada and nowhere else.
    """
    await make_tax(
        session,
        country_code="US",
        tax_name="Federal (no VAT/GST)",
        tax_code="NONE",
        rate_pct="0.0",
        tax_type="sales_tax",
        combination="federal",
    )
    await make_tax(
        session,
        country_code="US",
        tax_name="California Sales Tax",
        tax_code="CA_SALES",
        rate_pct="7.25",
        tax_type="sales_tax",
        combination="stacks_on_federal",
        subdivision_code="US-CA",
        is_default=False,
    )
    service = I18nFoundationService(session)

    california = await service.resolve_tax_rate("US", "US-CA", TODAY)
    texas = await service.resolve_tax_rate("US", "US-TX", TODAY)

    assert (california.status, california.combined_rate_pct) == ("stacked", "7.25")
    assert (texas.status, texas.combined_rate_pct) == ("subdivision_unknown", None)


# ── Listing by subdivision ───────────────────────────────────────────────────


async def test_listing_can_narrow_to_one_province(session: AsyncSession) -> None:
    """The axis is queryable, which the naming convention never was."""
    await seed_canada(session)
    service = I18nFoundationService(session)

    ontario = await service.list_tax_configs(country_code="CA", subdivision_code="CA-ON")
    quebec = await service.list_tax_configs(country_code="CA", subdivision_code="CA-QC")

    assert [row.tax_code for row in ontario] == ["HST_ON"]
    assert [row.tax_code for row in quebec] == ["QST_QC"]


async def test_the_subdivision_list_offers_all_thirteen(session: AsyncSession) -> None:
    """A picker has something to show, and an unlisted country returns empty."""
    service = I18nFoundationService(session)

    assert len(service.list_subdivisions("CA")) == 13
    assert ("CA-ON", "Ontario") in service.list_subdivisions("ca")
    assert service.list_subdivisions("DE") == []
