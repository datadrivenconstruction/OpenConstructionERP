"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tax configurations: which rate is active, and what the module does not do.

Scope note that shapes this whole file: **the module never applies a tax.** It
stores ``rate_pct`` as a string and hands the row to whoever asked. There is no
service method that adds tax to an amount, so there is nothing here that could
be compound or additive - that choice belongs entirely to the caller, and no
backend module currently makes it. The tests below cover the one piece of tax
logic that does exist: deciding whether a stored rate is in force today.

Still true after v3302, with one addition. The data now records how a rate
combines with the federal rate of the same country, because in Canada a
harmonised provincial rate replaces the federal one while a separate
provincial rate adds to it. Nothing in this module acts on that, so the note
above stands; the arithmetic it makes possible is covered in
``test_i18n_foundation_tax_combination.py``.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.service import I18nFoundationService
from tests.modules.i18n_foundation.conftest import make_tax


def _iso(offset_days: int) -> str:
    """An ISO date ``offset_days`` away from today, for effective-window tests."""
    return (date.today() + timedelta(days=offset_days)).isoformat()


# ── Which rate is in force today ─────────────────────────────────────────────


async def test_an_open_ended_rate_is_active(session: AsyncSession) -> None:
    """A row with no dates at all is the plain current rate."""
    await make_tax(session, country_code="DE", rate_pct="19.0")
    service = I18nFoundationService(session)

    active = await service.get_active_taxes_for_country("DE")

    assert [t.rate_pct for t in active] == ["19.0"]


async def test_a_future_dated_rate_is_not_active_yet(session: AsyncSession) -> None:
    """DEFECT: ``effective_from`` was ignored, so scheduled rates read as current.

    Tax changes are announced in advance and loaded into the table before they
    apply. The query only filtered on ``effective_to``, so a rate starting next
    year was returned as "currently active" alongside the one actually in
    force, and a caller taking the first row could price today's work at a rate
    that does not exist yet.
    """
    await make_tax(session, country_code="DE", tax_name="Current VAT", rate_pct="19.0")
    await make_tax(
        session,
        country_code="DE",
        tax_name="Announced VAT",
        rate_pct="21.0",
        effective_from=_iso(365),
    )
    service = I18nFoundationService(session)

    active = await service.get_active_taxes_for_country("DE")

    assert [t.rate_pct for t in active] == ["19.0"]


async def test_an_expired_rate_is_not_active(session: AsyncSession) -> None:
    """A row whose window closed yesterday is gone."""
    await make_tax(session, country_code="DE", tax_name="Old VAT", rate_pct="16.0", effective_to=_iso(-1))
    await make_tax(session, country_code="DE", tax_name="Current VAT", rate_pct="19.0")
    service = I18nFoundationService(session)

    active = await service.get_active_taxes_for_country("DE")

    assert [t.rate_pct for t in active] == ["19.0"]


async def test_a_rate_starting_today_is_already_active(session: AsyncSession) -> None:
    """The ``effective_from`` boundary is inclusive - a rate starts on its first day."""
    await make_tax(session, country_code="DE", rate_pct="19.0", effective_from=_iso(0))
    service = I18nFoundationService(session)

    active = await service.get_active_taxes_for_country("DE")

    assert len(active) == 1


async def test_a_rate_ending_today_is_still_active(session: AsyncSession) -> None:
    """The ``effective_to`` boundary is inclusive - a rate lasts through its last day."""
    await make_tax(session, country_code="DE", rate_pct="19.0", effective_to=_iso(0))
    service = I18nFoundationService(session)

    active = await service.get_active_taxes_for_country("DE")

    assert len(active) == 1


async def test_a_closed_window_around_today_is_active(session: AsyncSession) -> None:
    """Both dates set, today inside them: in force."""
    await make_tax(
        session,
        country_code="DE",
        rate_pct="19.0",
        effective_from=_iso(-30),
        effective_to=_iso(30),
    )
    service = I18nFoundationService(session)

    active = await service.get_active_taxes_for_country("DE")

    assert len(active) == 1


async def test_a_wholly_past_window_is_not_active(session: AsyncSession) -> None:
    """Both dates set and both behind us: out of force."""
    await make_tax(
        session,
        country_code="DE",
        rate_pct="16.0",
        effective_from=_iso(-60),
        effective_to=_iso(-30),
    )
    service = I18nFoundationService(session)

    assert await service.get_active_taxes_for_country("DE") == []


async def test_active_rates_are_scoped_to_their_country(session: AsyncSession) -> None:
    """A neighbouring country's VAT never leaks into the answer."""
    await make_tax(session, country_code="DE", tax_name="German VAT", rate_pct="19.0")
    await make_tax(session, country_code="FR", tax_name="French VAT", rate_pct="20.0")
    service = I18nFoundationService(session)

    active = await service.get_active_taxes_for_country("de")

    assert [t.country_code for t in active] == ["DE"]


async def test_a_country_with_no_rates_returns_an_empty_list(session: AsyncSession) -> None:
    """No configuration is an empty answer, not an error and not a default rate."""
    service = I18nFoundationService(session)

    assert await service.get_active_taxes_for_country("XX") == []


async def test_several_active_taxes_are_all_returned(session: AsyncSession) -> None:
    """A country can levy more than one tax; the caller picks, the module does not."""
    await make_tax(session, country_code="CA", tax_name="GST", rate_pct="5.0", tax_type="gst")
    await make_tax(session, country_code="CA", tax_name="PST", rate_pct="7.0", tax_type="sales_tax")
    service = I18nFoundationService(session)

    active = await service.get_active_taxes_for_country("CA")

    # Ordered by tax_name. Whether 5 and 7 combine to 12 additively or compound
    # to 12.35 is not decided here - the module returns both rows and stops.
    assert [(t.tax_name, t.rate_pct) for t in active] == [("GST", "5.0"), ("PST", "7.0")]


# ── The stored rate itself ───────────────────────────────────────────────────


async def test_rate_pct_is_stored_and_returned_as_an_exact_string(session: AsyncSession) -> None:
    """A percentage with trailing precision survives the round trip digit for digit."""
    await make_tax(session, country_code="IN", rate_pct="18.500", tax_type="gst")
    service = I18nFoundationService(session)

    active = await service.get_active_taxes_for_country("IN")

    assert active[0].rate_pct == "18.500"
    assert Decimal(active[0].rate_pct) == Decimal("18.500")


async def test_a_zero_rate_is_stored_and_returned_as_zero(session: AsyncSession) -> None:
    """Zero-rated is a real tax status, distinct from having no configuration.

    ``rate_pct`` is a non-nullable string, so "no rate" cannot be expressed as
    NULL. A zero-rated supply is "0.0"; the absence of any row is the absence
    of a configuration. This test pins that the two stay distinguishable.
    """
    await make_tax(session, country_code="GB", tax_name="Zero rated", rate_pct="0.0")
    service = I18nFoundationService(session)

    active = await service.get_active_taxes_for_country("GB")

    assert [t.rate_pct for t in active] == ["0.0"]
    assert await service.get_active_taxes_for_country("IE") == []


# ── Listing and lookup ───────────────────────────────────────────────────────


async def test_list_filters_by_country_and_type(session: AsyncSession) -> None:
    """Both filters narrow the list, and together they intersect."""
    await make_tax(session, country_code="CA", tax_name="GST", rate_pct="5.0", tax_type="gst")
    await make_tax(session, country_code="CA", tax_name="PST", rate_pct="7.0", tax_type="sales_tax")
    await make_tax(session, country_code="DE", tax_name="VAT", rate_pct="19.0", tax_type="vat")
    service = I18nFoundationService(session)

    assert len(await service.list_tax_configs(country_code="CA")) == 2
    assert len(await service.list_tax_configs(tax_type="gst")) == 1
    assert len(await service.list_tax_configs(country_code="CA", tax_type="sales_tax")) == 1
    assert len(await service.list_tax_configs()) == 3


async def test_list_includes_expired_rows(session: AsyncSession) -> None:
    """``list`` is the archive; only ``get_active_for_country`` filters by date."""
    await make_tax(session, country_code="DE", tax_name="Old VAT", rate_pct="16.0", effective_to=_iso(-1))
    service = I18nFoundationService(session)

    assert len(await service.list_tax_configs(country_code="DE")) == 1
    assert await service.get_active_taxes_for_country("DE") == []


async def test_get_by_unknown_id_is_a_404(session: AsyncSession) -> None:
    """A missing configuration is reported, not returned as None."""
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.get_tax_config(uuid.uuid4())

    assert excinfo.value.status_code == 404


async def test_update_writes_the_new_rate_and_keeps_the_rest(session: AsyncSession) -> None:
    """A partial update touches only the fields it names."""
    config = await make_tax(session, country_code="DE", tax_name="VAT", rate_pct="19.0", tax_code="VAT")
    service = I18nFoundationService(session)

    updated = await service.update_tax_config(config.id, {"rate_pct": "21.0"})

    assert updated.rate_pct == "21.0"
    assert updated.tax_name == "VAT"
    assert updated.tax_code == "VAT"


async def test_update_of_an_unknown_id_is_a_404(session: AsyncSession) -> None:
    """Updating a configuration that is not there fails loudly."""
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.update_tax_config(uuid.uuid4(), {"rate_pct": "21.0"})

    assert excinfo.value.status_code == 404


async def test_create_normalizes_the_country_code(session: AsyncSession) -> None:
    """A lower-case country code is stored upper-case so lookups find it."""
    service = I18nFoundationService(session)

    created = await service.create_tax_config(
        {
            "country_code": "pl",
            "tax_name": "VAT",
            "rate_pct": "23.0",
            "tax_type": "vat",
            "metadata": {},
        }
    )

    assert created.country_code == "PL"
    assert len(await service.get_active_taxes_for_country("PL")) == 1
