# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A cost item may not be stored without the currency its region names.

The authoritative signal is the region tag. A CWICR catalogue is imported one
region at a time and every rate inside it is denominated in that region's local
currency, so ``oe_costs_item.region`` states which money the rate is in even
though the source parquet carries no currency column. That is why
:data:`app.modules.costs.region_currency.REGION_CURRENCY` is keyed by region and
why an importer can stamp a whole file from a single lookup.

Measured on a real install before these tests were written: 55 718 of 123 485
cost rows carried an empty currency, every one of them ``source = 'cwicr'`` and
``region = 'ZH_SHANGHAI'``. Not one row of the other three regions in the same
table was affected. The cause was two tables that were supposed to say the same
thing: the loader takes the bases it will accept from ``base_registry``, while
the currency lookup was built from the v3 snapshot registry, and twelve of the
thirty-eight loadable regions were absent from it. ``ZH_SHANGHAI`` was one, so
its import resolved to ``""`` and wrote a catalogue of prices with no unit of
money on them.

These tests read the stored column, never a response schema. Three separate
read paths already fill a blank currency from the region on the way out (the
``CostItemResponse`` validator, ``_resolve_currency`` in the router, and the
matcher), so a test that creates an item and reads it back through the API
layer stays green with every write path broken. The assertions below re-query
the column with a fresh ``select()`` for the same reason ``session.get()`` is
avoided: the identity map would hand back the object still in memory rather
than what the database holds.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.costs.models import CostItem
from app.modules.costs.schemas import CostItemCreate
from app.modules.costs.service import CostItemService

# The region the 55 718 rows belong to, and the currency its own base variant
# declares. Not EUR and not USD, so a row that fell back to a popular default
# instead of reading the region would be visibly wrong rather than accidentally
# right.
_REGION = "ZH_SHANGHAI"
_CURRENCY = "CNY"

# Well-formed, and in neither the v3 registry nor the base registry. There is no
# Danish base to load, so nothing can derive a currency for it.
_UNKNOWN_REGION = "DK_COPENHAGEN"


def _payload(region: str | None, currency: str = "") -> CostItemCreate:
    return CostItemCreate(
        code=f"CUR-{uuid.uuid4().hex[:12]}",
        description="Currency write path probe",
        unit="m2",
        rate="10.00",
        currency=currency,
        region=region,
    )


async def _stored_currency(session, item_id: uuid.UUID) -> str:
    """Read the currency column back out of the database.

    A column select rather than an entity load, so the answer is the row as
    stored and not the instance the unit of work is still holding.
    """
    return (await session.execute(select(CostItem.currency).where(CostItem.id == item_id))).scalar_one()


async def test_created_item_stores_the_currency_its_region_names(pg_session) -> None:
    """The single-item write path fills a blank currency from the region."""
    service = CostItemService(pg_session)
    item = await service.create_cost_item(_payload(_REGION))
    await pg_session.flush()

    assert await _stored_currency(pg_session, item.id) == _CURRENCY


async def test_bulk_created_items_store_the_currency_their_region_names(pg_session) -> None:
    """The bulk import path fills it too.

    Worth its own test rather than a parametrisation of the one above: the two
    paths build the row separately, and the bulk path resolves catalog
    currencies in one batched query beforehand, so a fix applied to only one of
    them is exactly the shape of mistake this catches.
    """
    service = CostItemService(pg_session)
    created = await service.bulk_import([_payload(_REGION), _payload(_REGION)])
    await pg_session.flush()

    assert len(created) == 2
    for item in created:
        assert await _stored_currency(pg_session, item.id) == _CURRENCY


async def test_a_supplied_currency_is_never_overwritten_by_the_region(pg_session) -> None:
    """The region fills a blank; it does not correct a caller.

    A firm may legitimately price a foreign catalogue in its own currency, and
    the backfill of the existing rows relies on the same rule, so this is the
    assertion that keeps the repair from turning into a rewrite.
    """
    service = CostItemService(pg_session)
    item = await service.create_cost_item(_payload(_REGION, currency="USD"))
    await pg_session.flush()

    assert await _stored_currency(pg_session, item.id) == "USD"


@pytest.mark.parametrize("region", [_UNKNOWN_REGION, None])
async def test_an_underivable_currency_is_left_empty_rather_than_guessed(pg_session, region) -> None:
    """No signal means no currency, and that is the intended outcome.

    The temptation is to close the hole with a default. A rate labelled EUR
    because EUR is a common answer is worse than a rate labelled nothing: the
    blank is visibly unknown and is skipped by conversion, while the guess is
    indistinguishable from a currency someone chose and silently corrupts every
    total it reaches. The same rule governs the backfill migration, which
    reports the rows it could not derive instead of filling them.
    """
    service = CostItemService(pg_session)
    item = await service.create_cost_item(_payload(region))
    await pg_session.flush()

    assert await _stored_currency(pg_session, item.id) == ""
