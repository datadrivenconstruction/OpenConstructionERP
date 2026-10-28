"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The comparison answers more than cost, and says when it cannot.

A design option is a whole alternative, so a column carries the programme and
the embodied carbon of the things the option links, not only the money. These
tests pin the part that is easy to get wrong: an unanswered figure must stay
unanswered. A zero duration and "nobody has programmed this" are the same
number, and a comparison that lets them read alike would rank the option nobody
has planned as the fastest one in the set.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from tests.modules.design_options.conftest import (
    API_PREFIX,
    build_app,
    http_client,
    make_boq,
    make_option,
    make_position,
    make_project,
    make_set,
    make_user,
)


def _column(body: dict, name: str) -> dict:
    """The comparison column for the option with this name."""
    return next(col for col in body["options"] if col["name"] == name)


async def _option_with_bill(
    session: AsyncSession,
    option_set,  # noqa: ANN001 - DesignOptionSet, kept loose to avoid a circular import
    *,
    name: str,
    sort_order: int,
    unit_rate: str,
    **fields: object,
):  # noqa: ANN201 - DesignOption, same reason
    """A priced option carrying one leaf position, plus any extra columns."""
    boq = await make_boq(session, option_set.project_id, name=f"{name} bill")
    await make_position(session, boq.id, quantity="10", unit_rate=unit_rate, total=str(10 * int(unit_rate)))
    return await make_option(
        session,
        option_set,
        name=name,
        sort_order=sort_order,
        boq_id=boq.id,
        status="priced",
        **fields,
    )


async def test_a_column_carries_the_programme_and_carbon_the_option_links(session: AsyncSession) -> None:
    """The figures persisted at link time reach the comparison unchanged."""
    user = await make_user(session)
    project = await make_project(session, user.id, currency="EUR", gross_floor_area="100")
    option_set = await make_set(session, project.id)
    await _option_with_bill(
        session,
        option_set,
        name="Steel",
        sort_order=0,
        unit_rate="100",
        schedule_id=uuid.uuid4(),
        duration_days="180",
        finish_date="2027-02-01",
        carbon_inventory_id=uuid.uuid4(),
        embodied_carbon_kg="42000",
        carbon_per_m2="420",
    )
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{option_set.id}/comparison/")

    assert res.status_code == 200, res.text
    steel = _column(res.json(), "Steel")
    assert steel["has_programme"] is True
    assert Decimal(steel["duration_days"]) == Decimal("180")
    assert steel["finish_date"] == "2027-02-01"
    assert steel["has_carbon"] is True
    assert Decimal(steel["embodied_carbon_kg"]) == Decimal("42000")
    assert steel["carbon_unit"] == "kgCO2e"


async def test_an_option_with_no_schedule_reads_unanswered_not_zero_days(session: AsyncSession) -> None:
    """The flag, not the number, is what says whether the question was answered."""
    user = await make_user(session)
    project = await make_project(session, user.id, currency="EUR", gross_floor_area="100")
    option_set = await make_set(session, project.id)
    await _option_with_bill(session, option_set, name="Concrete", sort_order=0, unit_rate="100")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{option_set.id}/comparison/")

    assert res.status_code == 200, res.text
    concrete = _column(res.json(), "Concrete")
    assert concrete["has_programme"] is False
    assert concrete["has_carbon"] is False
    # The number is zero, which is exactly why the flag has to exist.
    assert Decimal(concrete["duration_days"]) == Decimal("0")
    assert concrete["delta_days_vs_baseline"] is None


async def test_a_delta_needs_both_sides_answered(session: AsyncSession) -> None:
    """A programmed option against an unprogrammed baseline has no delta.

    Subtracting from a zero nobody supplied would report a saving the size of
    the entire programme, which is the most flattering possible lie about an
    option that has never been planned.
    """
    user = await make_user(session)
    project = await make_project(session, user.id, currency="EUR", gross_floor_area="100")
    option_set = await make_set(session, project.id)
    baseline = await _option_with_bill(session, option_set, name="Baseline", sort_order=0, unit_rate="100")
    await _option_with_bill(
        session,
        option_set,
        name="Programmed",
        sort_order=1,
        unit_rate="120",
        schedule_id=uuid.uuid4(),
        duration_days="200",
        finish_date="2027-05-01",
    )
    option_set.baseline_option_id = baseline.id
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{option_set.id}/comparison/")

    assert res.status_code == 200, res.text
    body = res.json()
    assert _column(body, "Programmed")["delta_days_vs_baseline"] is None
    # The money delta, where both sides ARE answered, is still measured.
    assert Decimal(_column(body, "Programmed")["delta_vs_baseline"]) == Decimal("200")


async def test_a_delta_is_measured_when_both_options_are_programmed(session: AsyncSession) -> None:
    """Two answered programmes give a real day count, signed against the baseline."""
    user = await make_user(session)
    project = await make_project(session, user.id, currency="EUR", gross_floor_area="100")
    option_set = await make_set(session, project.id)
    baseline = await _option_with_bill(
        session,
        option_set,
        name="Baseline",
        sort_order=0,
        unit_rate="100",
        schedule_id=uuid.uuid4(),
        duration_days="240",
        finish_date="2027-06-01",
    )
    await _option_with_bill(
        session,
        option_set,
        name="Faster",
        sort_order=1,
        unit_rate="120",
        schedule_id=uuid.uuid4(),
        duration_days="180",
        finish_date="2027-04-01",
    )
    option_set.baseline_option_id = baseline.id
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{option_set.id}/comparison/")

    assert res.status_code == 200, res.text
    assert Decimal(_column(res.json(), "Faster")["delta_days_vs_baseline"]) == Decimal("-60")


async def test_the_banner_says_when_only_some_options_carry_a_column(session: AsyncSession) -> None:
    """A half-answered column invites a ranking it cannot support, so it is flagged."""
    user = await make_user(session)
    project = await make_project(session, user.id, currency="EUR", gross_floor_area="100")
    option_set = await make_set(session, project.id)
    await _option_with_bill(
        session,
        option_set,
        name="Weighed",
        sort_order=0,
        unit_rate="100",
        carbon_inventory_id=uuid.uuid4(),
        embodied_carbon_kg="9000",
        carbon_per_m2="90",
    )
    await _option_with_bill(session, option_set, name="Unweighed", sort_order=1, unit_rate="110")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{option_set.id}/comparison/")

    assert res.status_code == 200, res.text
    notices = {w["key"]: w for w in res.json()["fairness"]["warnings"]}
    assert "designOptions.fairness.partialCarbon" in notices
    assert notices["designOptions.fairness.partialCarbon"]["context"] == {"answered": 1, "total": 2}
    # Nothing links a schedule, so the set is not nagged about a column it never
    # claimed to have.
    assert "designOptions.fairness.partialProgramme" not in notices


async def test_a_column_says_whether_its_bill_was_generated_or_linked(session: AsyncSession) -> None:
    """A linked estimate is shared with the rest of the project; the column says so."""
    user = await make_user(session)
    project = await make_project(session, user.id, currency="EUR", gross_floor_area="100")
    option_set = await make_set(session, project.id)
    await _option_with_bill(session, option_set, name="Linked", sort_order=0, unit_rate="100", boq_source="linked")
    await _option_with_bill(
        session,
        option_set,
        name="Generated",
        sort_order=1,
        unit_rate="110",
        boq_source="generated",
    )
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{option_set.id}/comparison/")

    assert res.status_code == 200, res.text
    body = res.json()
    assert _column(body, "Linked")["boq_source"] == "linked"
    assert _column(body, "Generated")["boq_source"] == "generated"


async def test_options_whose_bills_are_priced_in_different_currencies_compare_in_one(
    session: AsyncSession,
) -> None:
    """Each bill converts to the project base first; one factor then displays it.

    This is the answer to "what happens when two options reference bills in
    different currencies". Nothing new happens: the BOQ rollup converts every
    foreign-currency line into the project base BEFORE summing, so the two
    columns are already like for like, and the set's display currency is one
    uniform factor applied to both.
    """
    user = await make_user(session)
    project = await make_project(
        session,
        user.id,
        currency="EUR",
        gross_floor_area="100",
        fx_rates=[{"code": "USD", "rate": "0.5"}],
    )
    option_set = await make_set(session, project.id, comparison_currency="USD")

    euro_boq = await make_boq(session, project.id, name="Euro bill")
    await make_position(session, euro_boq.id, ordinal="01.001", quantity="10", unit_rate="100", total="1000")
    await make_option(session, option_set, name="Euro", sort_order=0, boq_id=euro_boq.id, status="priced")

    dollar_boq = await make_boq(session, project.id, name="Dollar bill")
    await make_position(
        session,
        dollar_boq.id,
        ordinal="01.001",
        quantity="10",
        unit_rate="100",
        total="1000",
        metadata_={"currency": "USD"},
    )
    await make_option(session, option_set, name="Dollar", sort_order=1, boq_id=dollar_boq.id, status="priced")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{option_set.id}/comparison/")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["comparison_currency"] == "USD"
    # Both columns report the SAME currency; neither carries its bill's own.
    assert {col["currency"] for col in body["options"]} == {"USD"}
    # The euro bill is 1000 EUR shown at the USD display rate; the dollar bill
    # was converted into EUR by the rollup and then shown at the same rate, so
    # the two are 2000 USD and 1000 USD rather than an unconverted 1000 each.
    assert Decimal(_column(body, "Euro")["grand_total"]) == Decimal("2000")
    assert Decimal(_column(body, "Dollar")["grand_total"]) == Decimal("1000")
    # Neither bill mixes currencies inside itself, so no blending notice fires.
    keys = {w["key"] for w in body["fairness"]["warnings"]}
    assert "designOptions.fairness.mixedCurrencyOption" not in keys
