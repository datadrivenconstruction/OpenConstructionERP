"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The HTTP surface: status codes, serialization, and route ordering.

Route ordering is the reason this file exists as well as the service tests.
``/exchange-rates/convert/`` and ``/work-calendars/working-days/`` sit under the
same prefixes as ``/exchange-rates/{rate_id}`` and
``/work-calendars/{calendar_id}``, whose parameters are typed ``uuid.UUID``. If
the literal routes were ever declared after the parameterised ones, "convert"
would be matched as a UUID path segment and every conversion would 422. The
service layer cannot see that; only a request can.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from tests.modules.i18n_foundation.conftest import (
    API_PREFIX,
    build_app,
    http_client,
    make_calendar,
    make_country,
    make_rate,
    make_tax,
)

# ── Exchange rates ───────────────────────────────────────────────────────────


async def test_convert_is_routed_before_the_uuid_path(session: AsyncSession) -> None:
    """GET /exchange-rates/convert/ reaches the converter, not the by-id lookup."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(
            f"{API_PREFIX}/exchange-rates/convert/",
            params={"from_currency": "EUR", "to_currency": "USD", "amount": "1500.50"},
        )

    assert resp.status_code == 200
    assert resp.json()["converted_amount"] == "1628.0425"


async def test_convert_returns_money_as_json_strings(session: AsyncSession) -> None:
    """Every money field crosses the wire as a string, never as a JSON number.

    A JSON number would be parsed back as an IEEE double by every client, which
    is exactly the precision loss the string columns exist to prevent.
    """
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1", rate_date="2026-04-07")
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(
            f"{API_PREFIX}/exchange-rates/convert/",
            params={"from_currency": "EUR", "to_currency": "USD", "amount": "12345678901234.5678"},
        )

    body = resp.json()
    assert isinstance(body["converted_amount"], str)
    assert isinstance(body["rate"], str)
    assert body["converted_amount"] == "12345678901234.5678"


async def test_convert_with_a_non_finite_amount_is_a_400(session: AsyncSession) -> None:
    """The NaN guard holds at the HTTP edge, where the endpoint is public."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(
            f"{API_PREFIX}/exchange-rates/convert/",
            params={"from_currency": "EUR", "to_currency": "USD", "amount": "NaN"},
        )

    assert resp.status_code == 400


async def test_convert_with_an_unusable_stored_rate_is_a_422_not_a_500(session: AsyncSession) -> None:
    """A poisoned rate row is a client-visible 422, not a stack trace."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="n/a", rate_date="2026-04-07")
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(
            f"{API_PREFIX}/exchange-rates/convert/",
            params={"from_currency": "EUR", "to_currency": "USD", "amount": "100"},
        )

    assert resp.status_code == 422


async def test_convert_with_an_unknown_pair_is_a_404(session: AsyncSession) -> None:
    """No rate means no answer - the endpoint never invents parity."""
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(
            f"{API_PREFIX}/exchange-rates/convert/",
            params={"from_currency": "EUR", "to_currency": "ZWL", "amount": "100"},
        )

    assert resp.status_code == 404


async def test_a_two_letter_currency_is_rejected_by_the_query_schema(session: AsyncSession) -> None:
    """Currency codes are pinned to three characters at the edge."""
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(
            f"{API_PREFIX}/exchange-rates/convert/",
            params={"from_currency": "EU", "to_currency": "USD", "amount": "100"},
        )

    assert resp.status_code == 422


async def test_creating_a_rate_normalizes_the_currency_codes(session: AsyncSession) -> None:
    """POSTed lower-case codes are stored upper-case so lookups find them."""
    app = build_app(session, role="admin")

    async with http_client(app) as client:
        resp = await client.post(
            f"{API_PREFIX}/exchange-rates/",
            json={
                "from_currency": "eur",
                "to_currency": "usd",
                "rate": "1.0850",
                "rate_date": "2026-04-07",
                "source": "manual",
            },
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["from_currency"] == "EUR"
    assert body["to_currency"] == "USD"


async def test_the_metadata_field_ships_under_its_orm_name(session: AsyncSession) -> None:
    """GAP: the JSON key is ``metadata_``, with the trailing underscore.

    ``metadata`` is reserved on a declarative class, so the column is mapped as
    ``metadata_`` and the response schema declares ``Field(alias="metadata_")``
    to read it off the ORM object. FastAPI then serializes with
    ``by_alias=True``, so the alias goes back out onto the wire and the
    underscore the alias was meant to hide reaches the client instead.

    Pinned rather than fixed: correcting it means changing a published response
    shape on all four resources, which is an API decision, not a test fix. No
    frontend feature calls these endpoints today, so the cost of changing it is
    still low.
    """
    app = build_app(session, role="admin")

    async with http_client(app) as client:
        resp = await client.post(
            f"{API_PREFIX}/exchange-rates/",
            json={
                "from_currency": "EUR",
                "to_currency": "USD",
                "rate": "1.0850",
                "rate_date": "2026-04-07",
            },
        )

    body = resp.json()
    assert "metadata" not in body
    assert body["metadata_"] == {}


async def test_creating_a_rate_accepts_a_string_that_is_not_a_number(session: AsyncSession) -> None:
    """GAP: the create schema length-checks ``rate`` but never parses it.

    Recorded, not fixed. The rate is validated where it is used - the converter
    returns 422 rather than crashing - because the ECB fetcher writes through
    the repository and never sees this schema, so a validator here would cover
    only one of the two write paths. Tightening the schema as well is a
    deliberate second decision, not a silent side effect of this suite.
    """
    app = build_app(session, role="admin")

    async with http_client(app) as client:
        resp = await client.post(
            f"{API_PREFIX}/exchange-rates/",
            json={
                "from_currency": "EUR",
                "to_currency": "USD",
                "rate": "not a number",
                "rate_date": "2026-04-07",
            },
        )
        assert resp.status_code == 201

        convert = await client.get(
            f"{API_PREFIX}/exchange-rates/convert/",
            params={"from_currency": "EUR", "to_currency": "USD", "amount": "100"},
        )

    assert convert.status_code == 422


async def test_listing_rates_filters_and_counts(session: AsyncSession) -> None:
    """The list endpoint reports a total for the filter, not for the page."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0900", rate_date="2026-04-08")
    await make_rate(session, from_currency="EUR", to_currency="GBP", rate="0.8612", rate_date="2026-04-07")
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(f"{API_PREFIX}/exchange-rates/", params={"to_currency": "USD", "limit": 1})

    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    # Newest first.
    assert body["items"][0]["rate_date"] == "2026-04-08"


async def test_getting_an_unknown_rate_is_a_404(session: AsyncSession) -> None:
    """A well-formed but unknown UUID is a 404, not a 500."""
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(f"{API_PREFIX}/exchange-rates/{uuid.uuid4()}")

    assert resp.status_code == 404


async def test_patching_and_deleting_a_rate(session: AsyncSession) -> None:
    """The edit path round-trips and the delete path answers 204 then 404."""
    rate = await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    app = build_app(session, role="admin")

    async with http_client(app) as client:
        patched = await client.patch(f"{API_PREFIX}/exchange-rates/{rate.id}", json={"rate": "1.0900"})
        assert patched.status_code == 200
        assert patched.json()["rate"] == "1.0900"

        deleted = await client.delete(f"{API_PREFIX}/exchange-rates/{rate.id}")
        assert deleted.status_code == 204

        gone = await client.get(f"{API_PREFIX}/exchange-rates/{rate.id}")

    assert gone.status_code == 404


# ── Work calendars ───────────────────────────────────────────────────────────


async def test_working_days_is_routed_before_the_uuid_path(session: AsyncSession) -> None:
    """GET /work-calendars/working-days/ reaches the calculator, not the by-id lookup."""
    await make_calendar(session, country_code="DE", year="2026")
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(
            f"{API_PREFIX}/work-calendars/working-days/",
            params={"country_code": "DE", "from_date": "2026-01-05", "to_date": "2026-01-18"},
        )

    assert resp.status_code == 200
    # Asserted whole rather than field by field, so a field added to the payload
    # has to be looked at instead of slipping through. ``years`` says how each
    # year in the range was resolved; here the one year has its own calendar.
    assert resp.json() == {
        "country_code": "DE",
        "jurisdiction": {
            "axis": "jurisdiction",
            "source": "declared",
            "requested": "DE",
            "used": "DE",
            "detail": "",
        },
        "from_date": "2026-01-05",
        "to_date": "2026-01-18",
        "working_days": 10,
        "calendar_days": 14,
        "years": [
            {
                "year": 2026,
                "work_week_source": "declared",
                "work_week_from_year": None,
                "holidays_applied": True,
            }
        ],
    }


async def test_working_days_with_a_bad_date_is_a_400(session: AsyncSession) -> None:
    """An unparseable date is a client error at the edge too."""
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(
            f"{API_PREFIX}/work-calendars/working-days/",
            params={"country_code": "DE", "from_date": "05.01.2026", "to_date": "2026-01-18"},
        )

    assert resp.status_code == 400


async def test_creating_a_calendar_round_trips_its_json_fields(session: AsyncSession) -> None:
    """Work days and holiday exceptions come back exactly as posted."""
    app = build_app(session, role="admin")

    async with http_client(app) as client:
        resp = await client.post(
            f"{API_PREFIX}/work-calendars/",
            json={
                "country_code": "AE",
                "name": "UAE 2026",
                "year": "2026",
                "work_hours_per_day": "8.5",
                "work_days": [7, 1, 2, 3, 4],
                "exceptions": [{"date": "2026-12-02", "name": "National Day"}],
            },
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["work_days"] == [7, 1, 2, 3, 4]
    assert body["exceptions"] == [{"date": "2026-12-02", "name": "National Day"}]
    assert body["work_hours_per_day"] == "8.5"


async def test_listing_calendars_filters_by_country_and_year(session: AsyncSession) -> None:
    """Both filters narrow the list."""
    await make_calendar(session, country_code="DE", year="2026")
    await make_calendar(session, country_code="DE", year="2027")
    await make_calendar(session, country_code="FR", year="2026")
    app = build_app(session)

    async with http_client(app) as client:
        by_country = await client.get(f"{API_PREFIX}/work-calendars/", params={"country_code": "DE"})
        by_year = await client.get(f"{API_PREFIX}/work-calendars/", params={"year": "2026"})

    assert by_country.json()["total"] == 2
    assert by_year.json()["total"] == 2


# ── Countries ────────────────────────────────────────────────────────────────


async def test_country_lookup_is_case_insensitive(session: AsyncSession) -> None:
    """A lower-case ISO code in the path finds the row."""
    await make_country(session, iso_code="DE", name_en="Germany")
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(f"{API_PREFIX}/countries/de")

    assert resp.status_code == 200
    assert resp.json()["iso_code"] == "DE"


async def test_an_unknown_country_is_a_404_naming_the_code(session: AsyncSession) -> None:
    """The error says which code was not found."""
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(f"{API_PREFIX}/countries/zz")

    assert resp.status_code == 404
    assert "ZZ" in resp.json()["detail"]


async def test_inactive_countries_are_left_out_of_the_list(session: AsyncSession) -> None:
    """The list is the pickable set, so retired entries do not appear."""
    await make_country(session, iso_code="DE", name_en="Germany", is_active=True)
    await make_country(session, iso_code="SU", name_en="Soviet Union", is_active=False)
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(f"{API_PREFIX}/countries/")

    body = resp.json()
    assert [c["iso_code"] for c in body["items"]] == ["DE"]
    assert body["total"] == 1


async def test_countries_can_be_filtered_by_region(session: AsyncSession) -> None:
    """The region filter is what a regional currency or calendar picker uses."""
    await make_country(session, iso_code="DE", name_en="Germany", region_group="DACH")
    await make_country(session, iso_code="FR", name_en="France", region_group="EU")
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(f"{API_PREFIX}/countries/", params={"region": "DACH"})

    assert [c["iso_code"] for c in resp.json()["items"]] == ["DE"]


# ── Tax configs ──────────────────────────────────────────────────────────────


async def test_by_country_is_routed_before_the_uuid_path(session: AsyncSession) -> None:
    """GET /tax-configs/by-country/{code} is not swallowed by /tax-configs/{id}."""
    await make_tax(session, country_code="DE", tax_name="VAT", rate_pct="19.0")
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(f"{API_PREFIX}/tax-configs/by-country/DE")

    assert resp.status_code == 200
    assert [t["rate_pct"] for t in resp.json()["items"]] == ["19.0"]


async def test_tax_rate_crosses_the_wire_as_a_string(session: AsyncSession) -> None:
    """A percentage keeps its trailing digits instead of becoming a JSON float."""
    await make_tax(session, country_code="IN", tax_name="GST", rate_pct="18.500", tax_type="gst")
    app = build_app(session)

    async with http_client(app) as client:
        resp = await client.get(f"{API_PREFIX}/tax-configs/by-country/IN")

    rate = resp.json()["items"][0]["rate_pct"]
    assert isinstance(rate, str)
    assert rate == "18.500"


async def test_creating_a_tax_config_returns_201_with_its_id(session: AsyncSession) -> None:
    """The create path answers with the stored row."""
    app = build_app(session, role="admin")

    async with http_client(app) as client:
        resp = await client.post(
            f"{API_PREFIX}/tax-configs/",
            json={
                "country_code": "PL",
                "tax_name": "VAT",
                "rate_pct": "23.0",
                "tax_type": "vat",
                "tax_code": "VAT",
            },
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["country_code"] == "PL"
    assert uuid.UUID(body["id"])


async def test_an_editor_cannot_rewrite_the_vat_rate(session: AsyncSession) -> None:
    """The writes on these three tables are ADMIN, and being logged in is not
    enough.

    Every route here used to take a ``CurrentUserId`` it underscore-prefixed
    and never read, with no permission beside it, so any authenticated account
    of any role could change or delete the VAT rate and the currency
    conversion that every tenant's estimates and invoices are computed from.
    The tables carry no tenant, owner or project column, so there was no
    ownership check underneath to catch it either.

    An editor is the right caller to prove it with: authenticated, ordinary,
    and exactly who the old gate let through.
    """
    app = build_app(session, role="editor")

    async with http_client(app) as client:
        resp = await client.post(
            f"{API_PREFIX}/tax-configs/",
            json={
                "country_code": "PL",
                "tax_name": "VAT",
                "rate_pct": "0.0",
                "tax_type": "vat",
                "tax_code": "VAT",
            },
        )

    assert resp.status_code == 403


async def test_an_editor_can_still_read_the_reference_tables(session: AsyncSession) -> None:
    """The reads stay open. Gating them would have been the wrong fix: this is
    global reference data with no tenant column, and the login page needs it
    before anyone has authenticated."""
    await make_tax(session)
    app = build_app(session, role="editor")

    async with http_client(app) as client:
        resp = await client.get(f"{API_PREFIX}/tax-configs/")

    assert resp.status_code == 200
