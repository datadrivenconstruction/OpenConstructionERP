"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What a tax row is not allowed to say, and where saying it is stopped.

The defect these rules exist for is a quiet one, which is what makes it worth
guarding rather than documenting. ``combination`` defaults to ``national`` and
so does the column, so a Canadian provincial rate created through the API
without setting it inherits a value that means "this country has no
federal/provincial split". Such a row is not merely wrong, it is *invisible*:
it matches no per-province lookup, the province falls through to the federal
5 %, and no error, no log line and no health signal reports that a rate was
missed. Nothing was missing. It was mislabelled.

Three layers stand between that row and the table, and each is tested here
because each catches something the others do not:

1. :func:`~app.modules.i18n_foundation.tax_rules.validate_tax_row`, the rules
   themselves, pure and callable from anywhere.
2. The service, which is the only path the router has and which supplies the
   one input the pure function cannot work out for itself - whether the
   country already carries a federal layer.
3. The table's own check constraint, which is the only one of the three that
   is a property of the data rather than of the code that wrote it, and so the
   only one a future writer cannot forget to call.

The seed loader is the fourth writer and it calls layer 1 directly; that is
covered in ``test_i18n_foundation_tax_combination.py``, against the file it
actually ships.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.models import SUBNATIONAL_COMBINATIONS, TAX_COMBINATIONS
from app.modules.i18n_foundation.service import I18nFoundationService
from app.modules.i18n_foundation.tax_rules import TaxRuleError, validate_tax_row
from tests.modules.i18n_foundation.conftest import (
    API_PREFIX,
    build_app,
    http_client,
    make_tax,
)


def _code(excinfo: pytest.ExceptionInfo[TaxRuleError]) -> str:
    return excinfo.value.code


# ── Layer 1: the rules, on their own ────────────────────────────────────────


@pytest.mark.parametrize("combination", SUBNATIONAL_COMBINATIONS)
def test_a_subnational_rate_must_name_its_subdivision(combination: str) -> None:
    """The invisible row, refused at the point it would be written."""
    with pytest.raises(TaxRuleError) as excinfo:
        validate_tax_row("CA", combination, None)

    assert _code(excinfo) == "subdivision_required"


@pytest.mark.parametrize("combination", ["national", "federal"])
def test_a_countrywide_rate_may_not_name_a_subdivision(combination: str) -> None:
    """The same mistake mirrored: a federal row that claims to be Ontario's."""
    with pytest.raises(TaxRuleError) as excinfo:
        validate_tax_row("CA", combination, "CA-ON")

    assert _code(excinfo) == "subdivision_not_allowed"


def test_a_canadian_rate_may_not_call_itself_national() -> None:
    """DEFECT GUARD: the default value is refused where it is meaningless.

    This is the rule that closes the original hole. Canada taxes by province,
    so a Canadian rate is either the federal layer or one province's - never
    "the whole country has one undifferentiated rate". Leaving the field at its
    default now fails loudly instead of computing at 5 % in silence.

    The default itself is untouched, which matters: a genuinely single-tier
    country still gets ``national`` for free and no existing client of a
    country without a subdivision axis has to change anything.
    """
    with pytest.raises(TaxRuleError) as excinfo:
        validate_tax_row("CA", "national", None)

    assert _code(excinfo) == "national_not_allowed"


def test_a_single_tier_country_still_accepts_the_default() -> None:
    """Germany is national and stays national. No exception."""
    validate_tax_row("DE", "national", None)


def test_a_country_with_a_federal_layer_cannot_be_national_either() -> None:
    """The rule reaches countries with no registry, via their own data.

    The United States has no enumerated subdivisions here, so the registry
    cannot speak for it. What it does have is a federal row, and a federal
    layer exists precisely so something can sit on top of it - so ``national``
    is as meaningless there as it is in Canada. The service supplies this flag
    from the table; the pure function cannot know it.
    """
    validate_tax_row("US", "national", None)  # without the flag, nothing to go on

    with pytest.raises(TaxRuleError) as excinfo:
        validate_tax_row("US", "national", None, country_has_federal_layer=True)

    assert _code(excinfo) == "national_not_allowed"


@pytest.mark.parametrize(
    ("country", "subdivision", "expected"),
    [
        ("CA", "ON", "subdivision_malformed"),
        ("CA", "CA_ON", "subdivision_malformed"),
        ("CA", "US-CA", "subdivision_country_mismatch"),
        ("CA", "CA-ZZ", "subdivision_unknown"),
    ],
)
def test_a_malformed_or_foreign_subdivision_is_refused(country: str, subdivision: str, expected: str) -> None:
    """ISO 3166-2 shape, the right country, and a jurisdiction we carry."""
    with pytest.raises(TaxRuleError) as excinfo:
        validate_tax_row(country, "stacks_on_federal", subdivision)

    assert _code(excinfo) == expected


def test_an_unregistered_country_accepts_a_subdivision_it_cannot_check() -> None:
    """US-TX is allowed in, because refusing it would be a claim we cannot make.

    The platform enumerates Canadian subdivisions and no others. For a country
    with no registry the shape and the country prefix are all that can be
    checked, and pretending otherwise would block a deployment from loading its
    own state rates. The resolver is where that gap is made visible, by
    answering ``subdivision_unknown`` rather than a number.
    """
    validate_tax_row("US", "stacks_on_federal", "US-TX")


def test_an_unknown_combination_is_refused() -> None:
    with pytest.raises(TaxRuleError) as excinfo:
        validate_tax_row("DE", "sometimes", None)

    assert _code(excinfo) == "unknown_combination"


def test_the_subnational_members_are_a_subset_of_the_combinations() -> None:
    """The two tuples in models.py cannot drift apart unnoticed.

    Every rule in this file branches on membership of ``SUBNATIONAL_COMBINATIONS``
    while the schema and the column validate against ``TAX_COMBINATIONS``. A
    member in one and not the other would be accepted by the write path and
    ignored by the resolver, which is the invisible-row failure again by
    another route.
    """
    assert set(SUBNATIONAL_COMBINATIONS) < set(TAX_COMBINATIONS)


# ── Layer 2: the service, which is the only path the router has ─────────────


async def test_creating_a_provincial_rate_without_a_province_is_a_422(session: AsyncSession) -> None:
    """Through the service, the row that used to compute as federal-only."""
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.create_tax_config(
            {
                "country_code": "CA",
                "tax_name": "PST (Somewhere)",
                "tax_code": "PST_XX",
                "rate_pct": "7.0",
                "tax_type": "sales_tax",
                "combination": "stacks_on_federal",
                "subdivision_code": None,
                "metadata": {},
            }
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["code"] == "subdivision_required"


async def test_creating_a_canadian_rate_at_the_default_is_a_422(session: AsyncSession) -> None:
    """The original complaint, reproduced and then refused.

    A caller who does not know the field exists sends everything else and gets
    ``national`` by default. Before this guard the row was accepted and the
    province computed at the federal 5 %. Now the call fails and says why.
    """
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.create_tax_config(
            {
                "country_code": "CA",
                "tax_name": "PST (British Columbia)",
                "tax_code": "PST_BC",
                "rate_pct": "7.0",
                "tax_type": "sales_tax",
                "metadata": {},
            }
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["code"] == "national_not_allowed"


async def test_a_correctly_stated_provincial_rate_is_accepted(session: AsyncSession) -> None:
    """The guard refuses contradictions, not the feature.

    Positive control. Without it every assertion above would still pass if the
    service simply rejected all Canadian rates.
    """
    service = I18nFoundationService(session)

    created = await service.create_tax_config(
        {
            "country_code": "ca",
            "tax_name": "PST (British Columbia)",
            "tax_code": "PST_BC",
            "rate_pct": "7.0",
            "tax_type": "sales_tax",
            "combination": "stacks_on_federal",
            "subdivision_code": "ca-bc",
            "metadata": {},
        }
    )

    assert created.country_code == "CA"
    assert created.subdivision_code == "CA-BC"


async def test_a_blank_subdivision_is_stored_as_null_not_as_empty(session: AsyncSession) -> None:
    """ "Not chosen" has exactly one spelling.

    An empty string and a NULL would both mean "no subdivision" while comparing
    unequal, so a row written with one would be missed by a query written for
    the other. The normalizer collapses blank to NULL on the way in, and the
    check constraint then refuses it alongside the combination.
    """
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.create_tax_config(
            {
                "country_code": "CA",
                "tax_name": "HST (Ontario)",
                "tax_code": "HST_ON",
                "rate_pct": "13.0",
                "tax_type": "gst",
                "combination": "replaces_federal",
                "subdivision_code": "   ",
                "metadata": {},
            }
        )

    assert excinfo.value.detail["code"] == "subdivision_required"


async def test_an_update_is_checked_against_the_row_it_would_produce(session: AsyncSession) -> None:
    """A patch cannot walk a valid row into an invalid one in two steps.

    Validating only the fields a patch names would let a caller clear the
    subdivision today and set the combination to ``national`` tomorrow, ending
    at a state neither request could have written in one go. So the merge is
    validated, not the patch.
    """
    row = await make_tax(
        session,
        country_code="CA",
        tax_name="HST (Ontario)",
        tax_code="HST_ON",
        rate_pct="13.0",
        tax_type="gst",
        combination="replaces_federal",
        subdivision_code="CA-ON",
        is_default=False,
    )
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.update_tax_config(row.id, {"subdivision_code": None})

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["code"] == "subdivision_required"


async def test_an_update_that_moves_a_rate_to_another_province_is_allowed(session: AsyncSession) -> None:
    """Positive control on the update path: a real correction still lands."""
    row = await make_tax(
        session,
        country_code="CA",
        tax_name="PST",
        tax_code="PST_BC",
        rate_pct="7.0",
        tax_type="sales_tax",
        combination="stacks_on_federal",
        subdivision_code="CA-BC",
        is_default=False,
    )
    service = I18nFoundationService(session)

    updated = await service.update_tax_config(row.id, {"subdivision_code": "CA-SK", "rate_pct": "6.0"})

    assert (updated.subdivision_code, updated.rate_pct) == ("CA-SK", "6.0")


# ── Layer 3: the table itself ───────────────────────────────────────────────


async def test_the_table_refuses_a_subnational_row_with_no_subdivision(session: AsyncSession) -> None:
    """Written straight to the ORM, bypassing every guard above.

    This is the layer that survives a future writer who does not know the
    service exists. The constraint is an equality of two booleans, so it
    catches both directions of the contradiction.
    """
    with pytest.raises(IntegrityError):
        await make_tax(
            session,
            country_code="CA",
            tax_name="Orphan provincial rate",
            tax_code="PST_BC",
            rate_pct="7.0",
            tax_type="sales_tax",
            combination="stacks_on_federal",
        )


async def test_the_table_refuses_a_countrywide_row_that_names_a_subdivision(session: AsyncSession) -> None:
    """The other direction, so neither half of the constraint is decorative."""
    with pytest.raises(IntegrityError):
        await make_tax(
            session,
            country_code="CA",
            tax_name="GST",
            tax_code="GST",
            rate_pct="5.0",
            tax_type="gst",
            combination="federal",
            subdivision_code="CA-ON",
        )


# ── The HTTP surface ────────────────────────────────────────────────────────


async def test_the_api_refuses_the_silent_provincial_row(session: AsyncSession) -> None:
    """End to end: the request that used to succeed now returns 422 and a code."""
    app = build_app(session, role="admin")

    async with http_client(app) as client:
        resp = await client.post(
            f"{API_PREFIX}/tax-configs/",
            json={
                "country_code": "CA",
                "tax_name": "PST (British Columbia)",
                "tax_code": "PST_BC",
                "rate_pct": "7.0",
                "tax_type": "sales_tax",
            },
        )

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "national_not_allowed"


async def test_the_api_round_trips_the_subdivision(session: AsyncSession) -> None:
    """The field is writable and readable, so the axis is usable by a client.

    A field the API accepts and never returns is half an axis: a caller cannot
    tell what it stored, and a UI cannot show it.
    """
    app = build_app(session, role="admin")

    async with http_client(app) as client:
        created = await client.post(
            f"{API_PREFIX}/tax-configs/",
            json={
                "country_code": "CA",
                "tax_name": "HST (Ontario)",
                "tax_code": "HST_ON",
                "rate_pct": "13.0",
                "tax_type": "gst",
                "combination": "replaces_federal",
                "subdivision_code": "CA-ON",
            },
        )
        assert created.status_code == 201
        assert created.json()["subdivision_code"] == "CA-ON"

        listed = await client.get(
            f"{API_PREFIX}/tax-configs/",
            params={"country_code": "CA", "subdivision_code": "CA-ON"},
        )

    assert listed.status_code == 200
    assert [row["tax_code"] for row in listed.json()["items"]] == ["HST_ON"]


async def test_the_resolve_route_is_reachable_and_declines_without_a_province(session: AsyncSession) -> None:
    """Route ordering, and the unresolved shape as a client sees it.

    ``/tax-configs/resolve/{country_code}`` sits under the same prefix as
    ``/tax-configs/{config_id}``, which is typed as a UUID. Only a request can
    show that "resolve" is not being matched as a config id.
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
        tax_name="HST (Ontario)",
        tax_code="HST_ON",
        rate_pct="13.0",
        tax_type="gst",
        combination="replaces_federal",
        subdivision_code="CA-ON",
        is_default=False,
    )
    app = build_app(session)

    async with http_client(app) as client:
        ontario = await client.get(
            f"{API_PREFIX}/tax-configs/resolve/CA",
            params={"subdivision_code": "CA-ON"},
        )
        unstated = await client.get(f"{API_PREFIX}/tax-configs/resolve/CA")
        picker = await client.get(f"{API_PREFIX}/subdivisions/CA")

    assert ontario.status_code == 200
    assert ontario.json()["combined_rate_pct"] == "13"
    assert ontario.json()["status"] == "harmonised"
    assert ontario.json()["resolved"] is True

    assert unstated.status_code == 200
    body = unstated.json()
    assert body["combined_rate_pct"] is None
    assert body["resolved"] is False
    assert body["status"] == "subdivision_unknown"
    assert body["reason"]

    assert picker.status_code == 200
    assert picker.json()["total"] == 13


# ── Layer 4: what the read side does with a table it cannot resolve ─────────


def test_a_rate_that_is_not_a_number_is_refused_on_the_way_in() -> None:
    """The rate column is text, so nothing but this checks that it is a rate.

    ``rate_pct`` is a ``String``. A row carrying "twelve" is accepted by the
    column, by the schema (which only limits its length) and by every other
    rule here, because none of them look at the rate. It fails later, in
    ``Decimal()``, on a *read* of the subdivision it belongs to - which turns a
    bad write into a permanent error on an unrelated request.
    """
    with pytest.raises(TaxRuleError) as excinfo:
        validate_tax_row("CA", "stacks_on_federal", "CA-BC", rate_pct="twelve")

    assert _code(excinfo) == "rate_not_numeric"


async def test_the_api_refuses_a_rate_that_is_not_a_number(session: AsyncSession) -> None:
    """The same rule where a client meets it."""
    await make_tax(
        session,
        country_code="CA",
        tax_name="GST",
        tax_code="GST",
        rate_pct="5.0",
        tax_type="gst",
        combination="federal",
    )
    app = build_app(session, role="admin")

    async with http_client(app) as client:
        response = await client.post(
            f"{API_PREFIX}/tax-configs/",
            json={
                "country_code": "CA",
                "tax_name": "PST (British Columbia)",
                "tax_code": "PST_BC",
                "rate_pct": "twelve",
                "tax_type": "sales_tax",
                "combination": "stacks_on_federal",
                "subdivision_code": "CA-BC",
            },
        )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "rate_not_numeric"


async def test_a_province_with_two_replacing_rates_declines_rather_than_crashes(
    session: AsyncSession,
) -> None:
    """A contradiction the write rules cannot see, met on the read path.

    ``validate_tax_row`` judges one row at a time, so nothing stops a second
    harmonised rate being added to a province that already has one - and the
    shipped table is one cleared ``effective_to`` away from that state, since
    Nova Scotia ships as two rows with adjacent windows. Two rates that each
    replace the federal one have no single total, and the resolver says so by
    raising rather than picking one.

    The status is 409, not 422: the request was well formed and the caller
    changed nothing: it is the stored configuration that contradicts itself.
    Before this was handled the same lookup returned a 500 with a traceback,
    permanently, for data the platform's own endpoints had accepted.
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
    for tax_code in ("HST_NS", "HST_NS_OLD"):
        await make_tax(
            session,
            country_code="CA",
            tax_name=f"HST (Nova Scotia) {tax_code}",
            tax_code=tax_code,
            rate_pct="14.0" if tax_code == "HST_NS" else "15.0",
            tax_type="gst",
            combination="replaces_federal",
            subdivision_code="CA-NS",
            is_default=False,
        )
    app = build_app(session)

    async with http_client(app) as client:
        clash = await client.get(
            f"{API_PREFIX}/tax-configs/resolve/CA",
            params={"subdivision_code": "CA-NS"},
        )
        # The neighbouring province is unaffected, which is what makes this a
        # report about two rows rather than about the country.
        alberta = await client.get(
            f"{API_PREFIX}/tax-configs/resolve/CA",
            params={"subdivision_code": "CA-AB"},
        )

    assert clash.status_code == 409
    assert clash.json()["detail"]["code"] == "multiple_replacing_rates"

    assert alberta.status_code == 200
    assert (alberta.json()["status"], alberta.json()["combined_rate_pct"]) == ("federal_only", "5")


async def test_a_rate_already_stored_as_text_declines_the_lookup(session: AsyncSession) -> None:
    """The row the new write rule cannot reach: one that is already there.

    Validating on write closes the door for rows written from now on. It does
    nothing for rows a deployment loaded straight into the table, or that
    predate the rule - and those are exactly the rows the read path meets. A
    lookup for the province holding one used to be a 500 with a traceback,
    which is why the resolver's error is caught rather than merely not raised.
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
        tax_name="PST (British Columbia)",
        tax_code="PST_BC",
        rate_pct="seven",
        tax_type="sales_tax",
        combination="stacks_on_federal",
        subdivision_code="CA-BC",
        is_default=False,
    )
    app = build_app(session)

    async with http_client(app) as client:
        response = await client.get(
            f"{API_PREFIX}/tax-configs/resolve/CA",
            params={"subdivision_code": "CA-BC"},
        )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "rate_not_numeric"
    assert "PST_BC" in response.json()["detail"]["message"]


async def test_a_patch_may_not_clear_the_rate_it_was_validated_against(session: AsyncSession) -> None:
    """The merge has to check the value it is about to store, not a neighbour.

    ``update_tax_config`` validates the row as it will be after the patch. The
    tempting spelling of that merge is ``data.get("rate_pct") or existing``,
    and it is wrong in one specific way: a patch that sends a falsy rate would
    be validated against the *old*, valid rate and then written anyway. The
    row would land holding an empty string or a null on a NOT NULL column, and
    the check that was supposed to prevent it would have passed.

    Both spellings of "clear the rate" are refused, and the row keeps what it
    had.
    """
    existing = await make_tax(
        session,
        country_code="CA",
        tax_name="GST",
        tax_code="GST",
        rate_pct="5.0",
        tax_type="gst",
        combination="federal",
    )
    config_id = existing.id
    service = I18nFoundationService(session)

    for cleared in (None, ""):
        with pytest.raises(HTTPException) as excinfo:
            await service.update_tax_config(config_id, {"rate_pct": cleared})

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["code"] == "rate_required"

    unchanged = await service.get_tax_config(config_id)
    assert unchanged.rate_pct == "5.0"


async def test_a_patch_that_leaves_the_rate_alone_still_passes(session: AsyncSession) -> None:
    """The control for the test above: absent is not the same as cleared.

    If the guard read "falsy" instead of "named in the patch", every edit that
    did not mention the rate would start failing. This is the case that
    separates the two readings.
    """
    existing = await make_tax(
        session,
        country_code="CA",
        tax_name="GST",
        tax_code="GST",
        rate_pct="5.0",
        tax_type="gst",
        combination="federal",
    )
    service = I18nFoundationService(session)

    updated = await service.update_tax_config(existing.id, {"tax_name": "Goods and Services Tax"})

    assert (updated.tax_name, updated.rate_pct) == ("Goods and Services Tax", "5.0")
