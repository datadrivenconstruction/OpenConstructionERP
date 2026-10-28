# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The starter rate library has to survive contact with the real schema.

``_seed_demo_account`` calls this seeder inside a ``try/except`` that logs a
warning and carries on, which is the right behaviour at boot and the reason a
seeder written against a remembered field list can ship broken: the page stays
empty and nothing fails. So the seeder is run here against the real tables
rather than read.

Two runs in a row are the point of the second test. The seeder is called on
every startup, and its idempotency key is the template name, so a second pass
that inserted anything would double the library on the first restart.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.labor_rates.seed import DEFAULT_RATE_TEMPLATES, seed_labor_rates


@pytest.mark.asyncio
async def test_the_seeder_writes_every_template_with_its_components():
    """A field the schema does not carry fails here rather than in a log line."""
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.labor_rates.models import LaborRateTemplate

    owner_id = uuid.uuid4()
    async with async_session_factory() as session:
        counts = await seed_labor_rates(session, owner_id)
        await session.commit()

    assert counts["inserted"] == len(DEFAULT_RATE_TEMPLATES)

    async with async_session_factory() as session:
        rows = (
            (await session.execute(select(LaborRateTemplate).where(LaborRateTemplate.owner_id == owner_id)))
            .scalars()
            .all()
        )

    assert {row.name for row in rows} == {row["name"] for row in DEFAULT_RATE_TEMPLATES}
    by_name = {row.name: row for row in rows}
    for spec in DEFAULT_RATE_TEMPLATES:
        stored = by_name[spec["name"]]
        assert stored.base_wage == spec["base_wage"]
        assert stored.currency == spec["currency"]
        # The components are what turn a bare wage into an all-in rate, and
        # they are written through the relationship rather than added one by
        # one, so a cascade that did not fire would leave the template priced
        # at its bare wage with nothing to show for it.
        assert len(stored.components) == len(spec["components"])
        assert [c.label for c in stored.components] == [label for label, _kind, _value in spec["components"]]


@pytest.mark.asyncio
async def test_a_second_run_inserts_nothing():
    """The seeder runs on every startup; a second pass must be a no-op."""
    owner_id = uuid.uuid4()
    from app.database import async_session_factory

    async with async_session_factory() as session:
        first = await seed_labor_rates(session, owner_id)
        await session.commit()

    async with async_session_factory() as session:
        second = await seed_labor_rates(session, owner_id)
        await session.commit()

    assert first["inserted"] == len(DEFAULT_RATE_TEMPLATES)
    assert second["inserted"] == 0
    assert second["skipped"] == len(DEFAULT_RATE_TEMPLATES)


@pytest.mark.asyncio
async def test_the_library_is_scoped_to_its_owner():
    """Templates are owner-scoped, and a NULL owner is readable by admins alone.

    A seeder that wrote ownerless rows would fill the page for the one persona
    least likely to build a rate and leave it empty for the estimator, so the
    owner the caller names is the owner the rows carry.
    """
    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.modules.labor_rates.models import LaborRateTemplate

    mine = uuid.uuid4()
    someone_else = uuid.uuid4()
    async with async_session_factory() as session:
        await seed_labor_rates(session, mine)
        await session.commit()

    async with async_session_factory() as session:
        theirs = (
            await session.execute(
                select(func.count()).select_from(LaborRateTemplate).where(LaborRateTemplate.owner_id == someone_else),
            )
        ).scalar()
        ownerless = (
            await session.execute(
                select(func.count()).select_from(LaborRateTemplate).where(LaborRateTemplate.owner_id.is_(None)),
            )
        ).scalar()

    assert theirs == 0
    assert ownerless == 0
