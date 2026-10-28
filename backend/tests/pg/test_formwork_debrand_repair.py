# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The boot-path repair for trademarked formwork catalogue rows.

Runs against a real PostgreSQL cluster because the thing under test is a data rewrite and a
duplicate guard that compares a nullable ``tenant_id``, and both of those are exactly what an
in-memory stand-in gets wrong.

Two-sided on purpose. A test that only proves a branded catalogue is repaired has tested the
half that was never in doubt; the half that matters is that a catalogue which is already
correct comes back byte-identical, and that is asserted by comparing the rows themselves
rather than by the repair merely not raising.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.formwork.debrand import LEGACY_BRANDED_SYSTEMS, repair_branded_catalogue
from app.modules.formwork.models import FormworkSystem
from app.modules.formwork.schemas import default_seed_systems

pytestmark = pytest.mark.asyncio


def _branded_row(name: str, supplier: str, tenant_id: uuid.UUID | None = None) -> FormworkSystem:
    """One catalogue row as a pre-debrand seed would have written it."""
    return FormworkSystem(
        name=name,
        system_type="wall",
        supplier=supplier,
        material="steel",
        reuses_max=100,
        unit_rate=65,
        erect_strike_rate=16,
        strip_time_days=1,
        rate_basis="purchase",
        cycle_days=2,
        currency="",
        tenant_id=tenant_id,
    )


async def _snapshot(session) -> list[tuple[str, str | None]]:
    rows = (await session.execute(select(FormworkSystem.name, FormworkSystem.supplier))).all()
    return sorted((n, s) for n, s in rows)


async def test_an_upgraded_catalogue_is_repaired(pg_session) -> None:
    """The positive case: rows carrying the old names are renamed and the brand cleared."""
    for old, supplier, _ in LEGACY_BRANDED_SYSTEMS:
        pg_session.add(_branded_row(old, supplier))
    await pg_session.flush()

    renamed = await repair_branded_catalogue(pg_session)

    assert renamed == len(LEGACY_BRANDED_SYSTEMS)
    after = await _snapshot(pg_session)
    names = {n for n, _ in after}
    for old, _, new in LEGACY_BRANDED_SYSTEMS:
        assert old not in names, f"{old!r} survived the repair"
        assert new in names, f"{new!r} was not written"
    assert not [s for _, s in after if s], "a supplier still carries the original brand"


async def test_a_correct_catalogue_is_left_untouched(pg_session) -> None:
    """The negative control, asserted by comparing rows rather than by the absence of an error.

    A repair that quietly rewrote a clean catalogue would pass a test that only checked it did
    not raise, so the whole table is compared before and after.
    """
    for row in default_seed_systems():
        pg_session.add(FormworkSystem(tenant_id=None, **row))
    await pg_session.flush()
    before = await _snapshot(pg_session)

    renamed = await repair_branded_catalogue(pg_session)

    assert renamed == 0
    assert await _snapshot(pg_session) == before


async def test_the_repair_declines_where_the_replacement_already_exists(pg_session) -> None:
    """A tenant holding both rows keeps both, which is where ``v3271`` declines too.

    ``name`` carries no unique constraint, so an install that already re-ran seed-defaults
    holds the old row beside its replacement. Renaming would leave two identical names in one
    catalogue, and the old row may carry assignments, so it is left alone and counted.
    """
    old, supplier, new = LEGACY_BRANDED_SYSTEMS[0]
    tenant = uuid.uuid4()
    pg_session.add(_branded_row(old, supplier, tenant_id=tenant))
    pg_session.add(_branded_row(new, "", tenant_id=tenant))
    await pg_session.flush()

    renamed = await repair_branded_catalogue(pg_session)

    assert renamed == 0
    names = [n for n, _ in await _snapshot(pg_session)]
    assert sorted(names) == sorted([old, new]), "the blocked row was merged or dropped"


async def test_the_repair_is_idempotent(pg_session) -> None:
    """Safe to run on every start: the second run matches nothing and changes nothing."""
    for old, supplier, _ in LEGACY_BRANDED_SYSTEMS:
        pg_session.add(_branded_row(old, supplier))
    await pg_session.flush()

    assert await repair_branded_catalogue(pg_session) == len(LEGACY_BRANDED_SYSTEMS)
    after_first = await _snapshot(pg_session)

    assert await repair_branded_catalogue(pg_session) == 0
    assert await _snapshot(pg_session) == after_first


async def test_two_rows_under_one_old_name_keep_the_second(pg_session) -> None:
    """The one place this repair is probably stricter than ``v3271``.

    What is asserted here is this repair's own behaviour: the loop renames the first row and
    the session autoflushes it before the next clash query runs, so the second is blocked.
    ``v3271`` is expected to rename both, because its single ``UPDATE`` evaluates ``NOT EXISTS``
    against the snapshot the statement started from - that is read off the SQL, not measured
    here, so this test does not assert it. Two rows sharing a name is the state the rename
    exists to avoid, so the duplicate is left under its old name where the next boot retries it.
    """
    old, supplier, new = LEGACY_BRANDED_SYSTEMS[0]
    pg_session.add(_branded_row(old, supplier))
    pg_session.add(_branded_row(old, supplier))
    await pg_session.flush()

    assert await repair_branded_catalogue(pg_session) == 1

    names = sorted(n for n, _ in await _snapshot(pg_session))
    assert names == sorted([old, new]), "both rows were renamed onto one name, or one was lost"


async def test_the_repair_commits_rather_than_leaving_the_work_in_a_session(pg_engine) -> None:
    """The repair's work outlives the session that did it.

    Every other test here runs on ``pg_session``, which is savepoint-joined and rolled back, so
    all of them pass whether or not a commit ever lands. This one runs the shape the boot path
    runs - a session of its own, committed - and reads the result back through a *different*
    session, which is the only way to tell a durable rewrite from one that vanished with its
    transaction.
    """
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    old_names = [old for old, _, _ in LEGACY_BRANDED_SYSTEMS]
    new_names = [new for _, _, new in LEGACY_BRANDED_SYSTEMS]

    try:
        async with factory() as planting:
            for old, supplier, _ in LEGACY_BRANDED_SYSTEMS:
                planting.add(_branded_row(old, supplier))
            await planting.commit()

        async with factory() as booting:
            renamed = await repair_branded_catalogue(booting)
            await booting.commit()
        assert renamed == len(LEGACY_BRANDED_SYSTEMS)

        async with factory() as reading:
            surviving = (
                (await reading.execute(select(FormworkSystem.name).where(FormworkSystem.name.in_(old_names))))
                .scalars()
                .all()
            )
            landed = (
                (await reading.execute(select(FormworkSystem.name).where(FormworkSystem.name.in_(new_names))))
                .scalars()
                .all()
            )
        assert not surviving, f"the old names are still in the database: {sorted(surviving)}"
        assert sorted(landed) == sorted(new_names), "the renamed rows did not survive the commit"
    finally:
        # These rows are committed, so unlike the rest of the file they outlive the test and
        # would be visible to everything else sharing this cluster.
        async with factory() as cleanup:
            await cleanup.execute(delete(FormworkSystem).where(FormworkSystem.name.in_(old_names + new_names)))
            await cleanup.commit()


async def test_the_module_startup_hook_is_what_actually_runs_the_repair(pg_engine, monkeypatch) -> None:
    """The wiring itself, exercised rather than read.

    A repair nothing calls is worse than none, because it reads as done, and nothing else in
    this file would notice if ``on_startup`` stopped calling it - every other test invokes
    ``repair_branded_catalogue`` directly. This one goes in through the entry point the module
    loader actually calls (``module_loader._load_one`` -> ``package.on_startup()``) and never
    names the repair, so deleting the call from the hook fails here.

    ``on_startup`` builds its own session from ``app.database.async_session_factory``, which
    this lane does not bind to the embedded cluster, so the factory is pointed at the test
    engine for the duration. That substitution is the only thing faked: the hook, the repair,
    the commit and the rows are all real.
    """
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.database
    from app.modules.formwork import on_startup

    factory = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(app.database, "async_session_factory", factory)
    old_names = [old for old, _, _ in LEGACY_BRANDED_SYSTEMS]
    new_names = [new for _, _, new in LEGACY_BRANDED_SYSTEMS]

    try:
        async with factory() as planting:
            for old, supplier, _ in LEGACY_BRANDED_SYSTEMS:
                planting.add(_branded_row(old, supplier))
            await planting.commit()

        await on_startup()

        async with factory() as reading:
            surviving = (
                (await reading.execute(select(FormworkSystem.name).where(FormworkSystem.name.in_(old_names))))
                .scalars()
                .all()
            )
        assert not surviving, f"the module startup hook left trademarked rows in the database: {sorted(surviving)}"
    finally:
        async with factory() as cleanup:
            await cleanup.execute(delete(FormworkSystem).where(FormworkSystem.name.in_(old_names + new_names)))
            await cleanup.commit()


async def test_every_replacement_name_is_one_the_seed_actually_ships() -> None:
    """The rename targets must be names ``default_seed_systems()`` carries.

    If the starter catalogue is ever re-worded without this list following, an upgraded
    install and a fresh one land on different names for the same concept, and nothing else in
    the suite would notice.
    """
    seeded = {row["name"] for row in default_seed_systems()}
    missing = sorted({new for _, _, new in LEGACY_BRANDED_SYSTEMS} - seeded)
    assert not missing, f"rename targets absent from the shipped seed catalogue: {missing}"
