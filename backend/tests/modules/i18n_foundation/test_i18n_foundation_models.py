"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The four tables: shape, constraints, and the loading policy that does not apply.

``test_no_model_declares_a_relationship`` is the one to read first. The platform
rule is that every ``relationship()`` must carry an explicit ``lazy=``
(``raise_on_sql`` for child-to-parent scalars and rarely-needed collections,
``selectin`` for a collection that is the point of its parent). This module
declares none at all - four flat reference tables whose only nested data lives
in JSON columns - so the rule has nothing to bind to here. The test states that
as a fact rather than leaving the reviewer to infer it from silence, and it
starts failing the day someone adds a relationship without a strategy.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.models import (
    Country,
    ExchangeRate,
    TaxConfiguration,
    WorkCalendar,
)
from app.modules.i18n_foundation.service import I18nFoundationService
from tests.modules.i18n_foundation.conftest import (
    make_calendar,
    make_country,
    make_rate,
    make_tax,
)

ALL_MODELS = [ExchangeRate, Country, WorkCalendar, TaxConfiguration]


# ── Loading policy ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("model", ALL_MODELS)
def test_no_model_declares_a_relationship(model: type) -> None:
    """No ORM relationship exists, so the explicit-``lazy=`` rule is not in play.

    If one is ever added, this fails and whoever adds it has to come back and
    choose a strategy deliberately instead of inheriting the default ``select``,
    which is a latent ``MissingGreenlet`` in an async session.
    """
    assert list(sa_inspect(model).relationships) == []


@pytest.mark.parametrize("model", ALL_MODELS)
def test_every_model_carries_the_json_metadata_column(model: type) -> None:
    """All four tables expose ``metadata`` under the ``metadata_`` attribute.

    ``metadata`` is reserved on a SQLAlchemy declarative class, so the column is
    mapped under a trailing underscore and renamed back for the API. Both names
    have to stay in step or the response schemas' ``alias="metadata_"`` breaks.
    """
    columns = sa_inspect(model).columns
    assert "metadata_" in columns
    assert columns["metadata_"].name == "metadata"


def test_table_names_are_module_prefixed() -> None:
    """Table names stay inside the module's ``oe_i18n_`` namespace."""
    assert ExchangeRate.__tablename__ == "oe_i18n_exchange_rate"
    assert Country.__tablename__ == "oe_i18n_country"
    assert WorkCalendar.__tablename__ == "oe_i18n_work_calendar"
    assert TaxConfiguration.__tablename__ == "oe_i18n_tax_config"


# ── Money and dates are stored as strings ────────────────────────────────────


@pytest.mark.parametrize(
    ("model", "column"),
    [
        (ExchangeRate, "rate"),
        (WorkCalendar, "work_hours_per_day"),
        (TaxConfiguration, "rate_pct"),
    ],
)
def test_decimal_bearing_columns_are_strings_not_floats(model: type, column: str) -> None:
    """Every decimal value is a VARCHAR, never a FLOAT.

    This is the structural half of the no-float rule. The behavioural half is
    ``test_conversion_never_routes_through_float`` in the currency suite: a
    column typed as text cannot lose digits, but only the arithmetic test shows
    the service does not parse it into a float on the way through.
    """
    col_type = sa_inspect(model).columns[column].type
    assert col_type.python_type is str


# ── Uniqueness ───────────────────────────────────────────────────────────────


async def test_one_rate_per_pair_per_day(session: AsyncSession) -> None:
    """A second rate for the same pair and date is refused by the database.

    This is what makes the ECB fetch safe to re-run: the skip in the service is
    the fast path, the constraint is the guarantee.
    """
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")

    with pytest.raises(IntegrityError):
        await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0900", rate_date="2026-04-07")


async def test_the_same_pair_on_another_day_is_fine(session: AsyncSession) -> None:
    """The constraint is on the pair *and* the date, so a series is allowed."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0900", rate_date="2026-04-08")

    _, total = await I18nFoundationService(session).list_exchange_rates()
    assert total == 2


async def test_one_calendar_per_country_per_year(session: AsyncSession) -> None:
    """A country cannot have two calendars for the same year."""
    await make_calendar(session, country_code="DE", year="2026")

    with pytest.raises(IntegrityError):
        await make_calendar(session, country_code="DE", year="2026")


async def test_one_row_per_iso_country_code(session: AsyncSession) -> None:
    """ISO codes are unique, so a lookup by code cannot be ambiguous."""
    await make_country(session, iso_code="DE", name_en="Germany")

    with pytest.raises(IntegrityError):
        await make_country(session, iso_code="DE", name_en="Germany again")


async def test_a_country_may_have_many_tax_rows(session: AsyncSession) -> None:
    """Tax configurations are deliberately not unique per country.

    A country levies several taxes and revises each of them over time, so the
    table carries an index rather than a constraint and the effective-window
    query is what narrows it down.
    """
    await make_tax(session, country_code="CA", tax_name="GST", rate_pct="5.0", tax_type="gst")
    await make_tax(session, country_code="CA", tax_name="PST", rate_pct="7.0", tax_type="sales_tax")
    await make_tax(session, country_code="CA", tax_name="Old GST", rate_pct="6.0", tax_type="gst")

    assert len(await I18nFoundationService(session).list_tax_configs(country_code="CA")) == 3


# ── Round-tripping the JSON columns ──────────────────────────────────────────


async def test_country_name_translations_survive_non_latin_scripts(session: AsyncSession) -> None:
    """Localized names are data, so Cyrillic and CJK go in and come back intact."""
    country = Country(
        iso_code="RU",
        iso_code_3="RUS",
        name_en="Russia",
        name_translations={"en": "Russia", "ru": "Россия", "zh": "俄罗斯"},
        currency_default="RUB",
        measurement_default="metric",
        phone_code="+7",
        region_group="CIS",
        is_active=True,
        metadata_={},
    )
    session.add(country)
    await session.flush()

    loaded = await I18nFoundationService(session).get_country_by_iso("ru")

    assert loaded.name_translations["ru"] == "Россия"
    assert loaded.name_translations["zh"] == "俄罗斯"


async def test_calendar_exceptions_keep_their_extra_fields(session: AsyncSession) -> None:
    """Holiday entries are free-form JSON; nothing is dropped on the way in."""
    calendar = await make_calendar(
        session,
        country_code="DE",
        year="2026",
        exceptions=[{"date": "2026-01-06", "name": "Epiphany", "regions": ["BY", "BW"], "paid": True}],
    )

    assert calendar.exceptions[0]["regions"] == ["BY", "BW"]
    assert calendar.exceptions[0]["paid"] is True
