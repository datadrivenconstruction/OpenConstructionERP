# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A foreign key from an existing table to a brand-new one must survive the upgrade boot.

The boot heals existing tables (``postgres_auto_migrate``) BEFORE
``create_all`` builds the tables this release introduces. A model that adds a
column with a foreign key to one of those new tables therefore asked the heal
for ``ALTER TABLE ... ADD CONSTRAINT ... REFERENCES <new table>`` while the new
table did not exist yet. PostgreSQL refused it, the refusal was recorded, the
boot reported ``schema_heal_incomplete`` and the key was missing until some later
boot happened to retry. Site logistics took its keys out of the models to get
through (``LaydownZone.site_area_id``, ``DeliveryBooking.transport_id``).

The heal now defers such a key instead of issuing it, and
``heal_deferred_foreign_keys`` adds it once ``create_all`` has built the target.

The tables here live in a private ``MetaData`` so the test controls exactly
which tables exist and touches nothing in the application schema. The migrator
commits its own transaction, so cleanup is a ``finally``.
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table, inspect, text

from app.core.postgres_migrator import heal_deferred_foreign_keys, postgres_auto_migrate

PARENT = "oe_test_heal_order_parent"
CHILD = "oe_test_heal_order_child"
FK_NAME = "fk_oe_test_heal_order_child_parent_id"


def _model() -> SimpleNamespace:
    """The release being booted: CHILD gained ``parent_id`` pointing at the new PARENT."""
    md = MetaData()
    Table(PARENT, md, Column("id", Integer, primary_key=True))
    Table(
        CHILD,
        md,
        Column("id", Integer, primary_key=True),
        Column(
            "parent_id",
            Integer,
            ForeignKey(f"{PARENT}.id", ondelete="SET NULL", name=FK_NAME),
            nullable=True,
        ),
    )
    return SimpleNamespace(metadata=md)


async def _previous_release(pg_engine) -> None:
    """The database of the release before: CHILD exists without the column, PARENT does not."""
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{CHILD}", "{PARENT}" CASCADE'))
        await conn.execute(text(f'CREATE TABLE "{CHILD}" (id integer PRIMARY KEY)'))


async def _drop(pg_engine) -> None:
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{CHILD}", "{PARENT}" CASCADE'))


async def _live_fks(pg_engine) -> list[dict]:
    async with pg_engine.connect() as conn:
        return await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_foreign_keys(CHILD))


async def test_the_heal_does_not_refuse_a_key_whose_target_table_is_still_missing(pg_engine) -> None:
    base = _model()
    await _previous_release(pg_engine)
    try:
        skipped: list = []
        await postgres_auto_migrate(pg_engine, base, skipped=skipped)

        refused_fks = [s for s in skipped if s.kind == "foreign_key"]
        assert refused_fks == [], (
            "the heal issued a foreign key to a table create_all has not built yet, and the boot "
            f"reports it as refused: {refused_fks}"
        )
    finally:
        await _drop(pg_engine)


async def test_the_deferred_key_lands_once_create_all_has_built_its_target(pg_engine) -> None:
    base = _model()
    await _previous_release(pg_engine)
    try:
        skipped: list = []
        deferred: list[str] = []
        await postgres_auto_migrate(pg_engine, base, skipped=skipped, deferred_foreign_keys=deferred)
        assert deferred == [CHILD]
        assert await _live_fks(pg_engine) == [], "the key cannot exist before its target table does"

        # What the boot does next.
        async with pg_engine.begin() as conn:
            await conn.run_sync(base.metadata.create_all)

        added = await heal_deferred_foreign_keys(pg_engine, base, deferred, skipped=skipped)

        assert added == 1
        assert skipped == []
        fks = await _live_fks(pg_engine)
        assert len(fks) == 1
        assert fks[0]["referred_table"] == PARENT
        assert fks[0]["constrained_columns"] == ["parent_id"]
        assert (fks[0].get("options") or {}).get("ondelete") == "SET NULL"

        # The next boot finds nothing left to do and no second copy of the key.
        again_deferred: list[str] = []
        assert await postgres_auto_migrate(pg_engine, base, skipped=skipped, deferred_foreign_keys=again_deferred) == 0
        assert again_deferred == []
        assert len(await _live_fks(pg_engine)) == 1
    finally:
        await _drop(pg_engine)


async def test_a_deferred_key_whose_target_never_appears_is_reported_not_dropped(pg_engine) -> None:
    """If the target is still missing on the second pass the refusal must be recorded, as before."""
    base = _model()
    await _previous_release(pg_engine)
    try:
        skipped: list = []
        deferred: list[str] = []
        await postgres_auto_migrate(pg_engine, base, skipped=skipped, deferred_foreign_keys=deferred)
        assert deferred == [CHILD]

        # create_all did not run (or failed): PARENT is still missing.
        added = await heal_deferred_foreign_keys(pg_engine, base, deferred, skipped=skipped)

        assert added == 0
        assert [(s.kind, s.table) for s in skipped] == [("foreign_key", CHILD)]
    finally:
        await _drop(pg_engine)
