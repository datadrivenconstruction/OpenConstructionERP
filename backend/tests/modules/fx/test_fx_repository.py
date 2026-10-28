# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the FX repository (PostgreSQL).

Covers the storage rules the rest of the module leans on: point-in-time
resolution, idempotent re-ingest, the lock that makes a pin worth having, and
the relationship loading strategies. The loading-strategy tests are written to
fail if the strategy is loosened, which is the only way a ``lazy=`` declaration
is actually covered - a test that passes under every strategy tests nothing.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.fx import repository as repo
from app.modules.fx.models import FxPolicy, FxRateQuote, FxRateSet
from app.modules.fx.repository import RateSetLockedError
from tests.modules.fx.conftest import make_policy, make_rate_set

MARCH_1 = date(2026, 3, 1)
MARCH_15 = date(2026, 3, 15)


# ── Rate sets ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_stores_quotes_and_provenance(session: AsyncSession) -> None:
    rate_set = await make_rate_set(
        session,
        rate_date=MARCH_1,
        rates={"USD": "1.0850", "TRY": "42.5"},
        source_ref="https://example.invalid/eurofxref-daily.xml",
        note="Reference rates",
    )
    assert rate_set.base_currency == "EUR"
    assert rate_set.source_ref == "https://example.invalid/eurofxref-daily.xml"
    assert rate_set.fetched_at is not None
    assert repo.quotes_as_map(rate_set) == {"USD": Decimal("1.0850"), "TRY": Decimal("42.5")}


@pytest.mark.asyncio
async def test_upsert_drops_the_base_currency_and_non_positive_rates(session: AsyncSession) -> None:
    """A base quoted against itself, or a zero rate, would break the next division."""
    rate_set = await make_rate_set(
        session,
        rate_date=MARCH_1,
        rates={"EUR": "1", "USD": "1.085", "XXX": "0", "YYY": "-3"},
    )
    assert sorted(repo.quotes_as_map(rate_set)) == ["USD"]


@pytest.mark.asyncio
async def test_reingesting_the_same_key_replaces_rather_than_duplicates(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08", "TRY": "42.5"})
    replaced = await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.09"})

    assert await repo.count_rate_sets(session) == 1
    # The currency the new publication no longer carries is retired, not left
    # behind as a stale quote nobody notices.
    assert repo.quotes_as_map(replaced) == {"USD": Decimal("1.09")}


@pytest.mark.asyncio
async def test_a_locked_set_refuses_to_be_rewritten(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"}, lock=True)
    with pytest.raises(RateSetLockedError, match="locked"):
        await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "99.00"})


@pytest.mark.asyncio
async def test_a_locked_set_refuses_to_be_deleted(session: AsyncSession) -> None:
    rate_set = await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"}, lock=True)
    with pytest.raises(RateSetLockedError, match="locked"):
        await repo.delete_rate_set(session, rate_set)


@pytest.mark.asyncio
async def test_unlocking_lets_a_set_be_rewritten_again(session: AsyncSession) -> None:
    rate_set = await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"}, lock=True)
    await repo.set_rate_set_locked(session, rate_set, locked=False)
    replaced = await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.09"})
    assert repo.quotes_as_map(replaced)["USD"] == Decimal("1.09")


@pytest.mark.asyncio
async def test_deleting_a_set_takes_its_quotes_with_it(session: AsyncSession) -> None:
    rate_set = await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08", "TRY": "42.5"})
    await repo.delete_rate_set(session, rate_set)
    remaining = (await session.execute(select(FxRateQuote))).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_rate_precision_survives_the_round_trip(session: AsyncSession) -> None:
    """Ten decimals are stored, so an inverse against a weak currency stays usable."""
    await make_rate_set(session, rate_date=MARCH_1, rates={"VND": "27500.0000000000", "USD": "1.0850123456"})
    session.expunge_all()
    stored = await repo.latest_rate_set(session)
    assert stored is not None
    assert repo.quotes_as_map(stored)["USD"] == Decimal("1.0850123456")
    assert repo.quotes_as_map(stored)["VND"] == Decimal("27500")


# ── Point-in-time resolution ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_latest_rate_set_returns_the_set_in_force_on_a_date(session: AsyncSession) -> None:
    """A rate published on the 1st still applies on the 10th; the 15th supersedes it."""
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"})
    await make_rate_set(session, rate_date=MARCH_15, rates={"USD": "1.12"})

    on_the_tenth = await repo.latest_rate_set(session, on_date=date(2026, 3, 10))
    assert on_the_tenth is not None
    assert on_the_tenth.rate_date == MARCH_1

    latest = await repo.latest_rate_set(session)
    assert latest is not None
    assert latest.rate_date == MARCH_15


@pytest.mark.asyncio
async def test_latest_rate_set_is_none_before_any_set_existed(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_15, rates={"USD": "1.12"})
    assert await repo.latest_rate_set(session, on_date=date(2026, 1, 1)) is None


@pytest.mark.asyncio
async def test_latest_rate_set_can_be_restricted_to_one_source(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_15, rates={"USD": "1.12"}, source="ecb")
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.05"}, source="manual")

    contracted = await repo.latest_rate_set(session, source="manual")
    assert contracted is not None
    assert contracted.rate_date == MARCH_1


@pytest.mark.asyncio
async def test_latest_rate_set_is_scoped_to_the_base_currency(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_15, rates={"TRY": "42.5"}, base_currency="EUR")
    assert await repo.latest_rate_set(session, base_currency="USD") is None


@pytest.mark.asyncio
async def test_preceding_rate_set_finds_the_one_it_supersedes(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"})
    current = await make_rate_set(session, rate_date=MARCH_15, rates={"USD": "1.12"})

    previous = await repo.preceding_rate_set(session, current)
    assert previous is not None
    assert previous.rate_date == MARCH_1


@pytest.mark.asyncio
async def test_the_first_set_ever_has_no_predecessor(session: AsyncSession) -> None:
    first = await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"})
    assert await repo.preceding_rate_set(session, first) is None


@pytest.mark.asyncio
async def test_listing_is_newest_first_and_counts_the_filter(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"})
    await make_rate_set(session, rate_date=MARCH_15, rates={"USD": "1.12"})
    await make_rate_set(session, rate_date=MARCH_15, rates={"USD": "1.05"}, source="manual")

    listed = await repo.list_rate_sets(session)
    assert [item.rate_date for item in listed] == [MARCH_15, MARCH_15, MARCH_1]
    assert await repo.count_rate_sets(session, source="manual") == 1


# ── Relationship loading strategies ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_quotes_load_with_their_set_without_an_eager_option(session: AsyncSession) -> None:
    """``FxRateSet.quotes`` is ``selectin``: reading a set without its rates is useless."""
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08", "TRY": "42.5"})
    session.expunge_all()

    rate_set = (await session.execute(select(FxRateSet))).scalars().one()
    assert sorted(quote.currency for quote in rate_set.quotes) == ["TRY", "USD"]


@pytest.mark.asyncio
async def test_walking_up_from_a_lone_quote_raises_instead_of_emitting_sql(session: AsyncSession) -> None:
    """``FxRateQuote.rate_set`` is ``raise_on_sql``: the implicit walk up is refused.

    The quote is loaded on its own with the identity map cleared, so reaching
    for its parent genuinely needs a SELECT. That is the case the strategy
    exists to stop, and it is the only case that proves the declaration.
    """
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"})
    session.expunge_all()

    quote = (await session.execute(select(FxRateQuote))).scalars().one()
    with pytest.raises(InvalidRequestError, match="rate_set"):
        _ = quote.rate_set


@pytest.mark.asyncio
async def test_a_parent_already_in_memory_reads_without_sql_and_without_raising(
    session: AsyncSession,
) -> None:
    """``raise_on_sql`` is the middle ground: free reads stay free.

    Loading the set pulls its quotes eagerly, so the parent is already in the
    identity map and the back-reference costs nothing. The stricter ``raise``
    would fail here too, which is why it is not what the model declares.
    """
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"})
    session.expunge_all()

    rate_set = (await session.execute(select(FxRateSet))).scalars().one()
    assert rate_set.quotes[0].rate_set is rate_set


@pytest.mark.asyncio
async def test_an_eagerly_ordered_parent_is_readable_from_the_quote(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"})
    session.expunge_all()

    stmt = select(FxRateQuote).options(selectinload(FxRateQuote.rate_set))
    quote = (await session.execute(stmt)).scalars().one()
    assert quote.rate_set.rate_date == MARCH_1


@pytest.mark.asyncio
async def test_a_pinned_set_must_be_ordered_explicitly(session: AsyncSession) -> None:
    """``FxPolicy.pinned_rate_set`` is ``raise_on_sql``: the id is already on the row."""
    rate_set = await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"}, lock=True)
    await make_policy(session, rate_mode="pinned", pinned_rate_set_id=rate_set.id)
    session.expunge_all()

    policy = (await session.execute(select(FxPolicy))).scalars().one()
    with pytest.raises(InvalidRequestError, match="pinned_rate_set"):
        _ = policy.pinned_rate_set


@pytest.mark.asyncio
async def test_the_repository_can_order_the_pinned_set_eagerly(session: AsyncSession) -> None:
    rate_set = await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"}, lock=True)
    policy = await make_policy(session, rate_mode="pinned", pinned_rate_set_id=rate_set.id)
    project_id = policy.project_id
    session.expunge_all()

    loaded = await repo.get_policy(session, project_id, with_pinned_set=True)
    assert loaded is not None
    assert loaded.pinned_rate_set is not None
    assert loaded.pinned_rate_set.is_locked is True
    # The set's own quotes come with it, so a policy read renders in one go.
    assert repo.quotes_as_map(loaded.pinned_rate_set) == {"USD": Decimal("1.08")}


# ── Project policy ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_policy_upsert_is_one_row_per_project(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    await make_policy(session, project_id=project_id, reporting_currency="USD")
    updated = await make_policy(session, project_id=project_id, reporting_currency="GBP")

    assert updated.reporting_currency == "GBP"
    assert len(await repo.list_policies(session)) == 1


@pytest.mark.asyncio
async def test_policy_currencies_are_stored_uppercase(session: AsyncSession) -> None:
    policy = await repo.upsert_policy(
        session,
        uuid.uuid4(),
        estimating_currency="eur",
        procurement_currency="try",
        reporting_currency="usd",
        rate_mode="live",
    )
    assert (policy.estimating_currency, policy.procurement_currency, policy.reporting_currency) == (
        "EUR",
        "TRY",
        "USD",
    )


@pytest.mark.asyncio
async def test_deleting_a_policy_leaves_the_rate_set_alone(session: AsyncSession) -> None:
    rate_set = await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"}, lock=True)
    policy = await make_policy(session, rate_mode="pinned", pinned_rate_set_id=rate_set.id)
    await repo.delete_policy(session, policy)

    assert await repo.count_rate_sets(session) == 1


# ── Legacy cache and PPP ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_cache_upsert_refreshes_in_place(session: AsyncSession) -> None:
    written = await repo.upsert_latest_rates(session, {"USD": Decimal("1.08")}, MARCH_1, source="ecb")
    assert written == 1
    await repo.upsert_latest_rates(session, {"USD": Decimal("1.12")}, MARCH_15, source="ecb")

    rows = await repo.list_latest_rates(session)
    assert len(rows) == 1
    assert rows[0].rate == Decimal("1.120000")
    assert rows[0].rate_date == MARCH_15


@pytest.mark.asyncio
async def test_legacy_cache_only_if_empty_protects_live_values(session: AsyncSession) -> None:
    await repo.upsert_latest_rates(session, {"USD": Decimal("1.08")}, MARCH_1, source="ecb")
    written = await repo.upsert_latest_rates(
        session,
        {"USD": Decimal("9.99")},
        MARCH_15,
        source="seed",
        only_if_empty=True,
    )
    rows = await repo.list_latest_rates(session)
    assert written == 0
    assert rows[0].rate == Decimal("1.080000")


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_a_retired_ppp_factor_is_invisible_to_the_default_read(session: AsyncSession) -> None:
    """``is_active`` is honoured, so retiring an observation takes it out of service."""
    row = await repo.upsert_ppp_factor(session, "TUR", factor=Decimal("12.5"), year=2024, currency="TRY")
    row.is_active = False
    await session.flush()

    assert await repo.get_ppp_factor(session, "TUR") is None
    assert await repo.get_ppp_factor(session, "TUR", active_only=False) is not None
    assert await repo.count_ppp_factors(session) == 0


@pytest.mark.asyncio
async def test_refetching_a_retired_ppp_factor_puts_it_back_in_service(session: AsyncSession) -> None:
    row = await repo.upsert_ppp_factor(session, "TUR", factor=Decimal("12.5"), year=2024, currency="TRY")
    row.is_active = False
    await session.flush()

    refreshed = await repo.upsert_ppp_factor(session, "TUR", factor=Decimal("13.9"), year=2025, currency="TRY")
    assert refreshed.is_active is True
    assert refreshed.factor == Decimal("13.9")
    assert refreshed.currency == "TRY"
