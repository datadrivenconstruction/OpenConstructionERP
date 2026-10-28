"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared fixtures for the i18n Foundation test suite.

The session fixture runs against the shared PostgreSQL unit database from
``tests/_pg.py``, inside an outer transaction that is rolled back on teardown.

Foreign keys stay ON (no ``disable_fks``) simply because this module has none:
its four tables - exchange rates, countries, work calendars, tax configs - are
flat reference data with no cross-module columns, so nothing here needs the
replication role.

There are no validation rules to register: the module ships no ``validators.py``
at all, which the suite records as a finding rather than papering over.

Money is written and asserted as strings throughout. Every amount, rate and
percentage the module stores is a ``String`` column holding a decimal literal,
so a test that compares floats would be testing something the module never
does. Assertions are on the exact string.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.i18n_foundation.models import (
    Country,
    ExchangeRate,
    TaxConfiguration,
    WorkCalendar,
)
from app.modules.i18n_foundation.router import router as i18n_foundation_router
from tests._pg import transactional_session

API_PREFIX = "/v1/i18n-foundation"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session on the shared PostgreSQL unit database."""
    async with transactional_session() as s:
        yield s


# ── Row factories ────────────────────────────────────────────────────────────


async def make_rate(
    session: AsyncSession,
    *,
    from_currency: str = "EUR",
    to_currency: str = "USD",
    rate: str = "1.0850",
    rate_date: str = "2026-04-07",
    source: str = "manual",
    is_manual: bool = True,
) -> ExchangeRate:
    """Persist one exchange-rate row with the rate as a decimal string."""
    row = ExchangeRate(
        from_currency=from_currency,
        to_currency=to_currency,
        rate=rate,
        rate_date=rate_date,
        source=source,
        is_manual=is_manual,
        metadata_={},
    )
    session.add(row)
    await session.flush()
    return row


async def make_country(
    session: AsyncSession,
    *,
    iso_code: str = "DE",
    name_en: str = "Germany",
    currency_default: str | None = "EUR",
    region_group: str | None = "DACH",
    is_active: bool = True,
) -> Country:
    """Persist one country row."""
    row = Country(
        iso_code=iso_code,
        iso_code_3=None,
        name_en=name_en,
        name_translations={"en": name_en},
        currency_default=currency_default,
        measurement_default="metric",
        phone_code=None,
        region_group=region_group,
        is_active=is_active,
        metadata_={},
    )
    session.add(row)
    await session.flush()
    return row


async def make_calendar(
    session: AsyncSession,
    *,
    country_code: str = "DE",
    year: str = "2026",
    work_days: list[int] | None = None,
    exceptions: list[dict[str, Any]] | None = None,
    work_hours_per_day: str = "8",
) -> WorkCalendar:
    """Persist one work calendar. ``work_days`` are ISO weekdays, Monday=1."""
    row = WorkCalendar(
        country_code=country_code,
        name=f"{country_code} {year}",
        name_translations=None,
        year=year,
        work_hours_per_day=work_hours_per_day,
        work_days=[1, 2, 3, 4, 5] if work_days is None else work_days,
        exceptions=exceptions or [],
        metadata_={},
    )
    session.add(row)
    await session.flush()
    return row


async def make_tax(
    session: AsyncSession,
    *,
    country_code: str = "DE",
    tax_name: str = "Standard VAT",
    rate_pct: str = "19.0",
    tax_type: str = "vat",
    tax_code: str | None = "VAT",
    combination: str = "national",
    subdivision_code: str | None = None,
    effective_from: str | None = None,
    effective_to: str | None = None,
    is_default: bool = True,
) -> TaxConfiguration:
    """Persist one tax configuration with the percentage as a string.

    ``combination`` and ``subdivision_code`` default to a country-wide rate,
    which is what every test written before the subdivision axis assumed. They
    are checked against each other by a table constraint, so a caller passing
    one without the other gets an IntegrityError rather than a row that
    resolves to the wrong province.

    **Know what ``is_default=True`` is hiding before you add a case.** The
    resolver answers a country-wide question by taking the row flagged
    ``is_default``, and refuses with ``default_rate_ambiguous`` when the rows
    in force do not name exactly one. This default puts every fixture that does
    not say otherwise into the single unambiguous case - so a test built on it
    cannot tell "picks the right rate" apart from "there was only ever one
    candidate". That is not hypothetical: it is how a repair that could strip a
    country of its rate entirely passed its own tests, and it is the same
    blindness as the one-rate-per-country fixtures that let the resolver sum
    tiers for five markets undetected. Both are written up in
    ``internal design note VAT_RESOLVER_SUMMED_TIERS_2026-08-26``.

    If your case is about *selection* - which rate wins, or whether one wins at
    all - pass ``is_default`` explicitly on every row you create, and give the
    resolver more than one row to choose between.
    """
    row = TaxConfiguration(
        country_code=country_code,
        tax_name=tax_name,
        tax_name_translations=None,
        tax_code=tax_code,
        rate_pct=rate_pct,
        tax_type=tax_type,
        combination=combination,
        subdivision_code=subdivision_code,
        effective_from=effective_from,
        effective_to=effective_to,
        is_default=is_default,
        metadata_={},
    )
    session.add(row)
    await session.flush()
    return row


# ── HTTP plumbing ────────────────────────────────────────────────────────────


def build_app(
    db_session: AsyncSession,
    *,
    caller_id: uuid.UUID | str | None = None,
    role: str = "editor",
) -> FastAPI:
    """Mount the module router with the test session and a fixed caller.

    ``role`` defaults to ``editor`` because that is what the reads need and
    what this suite has always used. The writes need ``admin``: the seven
    create/update/delete routes on exchange rates, work calendars and tax
    configs are gated at ADMIN, since the three tables carry no tenant, owner
    or project column and a change to any of them is global to the install.
    An editor calling one of those gets a 403, and there is a test below that
    pins exactly that.
    """
    app = FastAPI()
    app.include_router(i18n_foundation_router, prefix=API_PREFIX)

    resolved_caller = str(caller_id) if caller_id is not None else str(uuid.uuid4())

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _user_override() -> str:
        return resolved_caller

    async def _payload_override() -> dict[str, Any]:
        return {"sub": resolved_caller, "role": role, "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


def http_client(app: FastAPI) -> AsyncClient:
    """In-process async client bound to ``app`` on the current event loop.

    ``httpx.AsyncClient`` over ``ASGITransport`` keeps the app on the test's own
    event loop; the synchronous ``TestClient`` would drive it from a worker
    thread on a second loop and break the asyncpg session created here.
    """
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
