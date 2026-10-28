# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An upgrade lands on a database that already holds rows, and nothing tested that.

Every other test of the schema-building path starts from an empty database. That
is the one shape the upgrade path never has: an existing install boots with the
user's projects already in it, and the release's new columns arrive on tables
that are not empty. A revision that would fail on rows - a NOT NULL column with
no default, a unique constraint over values that already collide - passes on
every empty fixture and fails on the only database that matters.

What actually runs on an upgrade is not the migration chain. ``app/main.py``
never calls ``alembic upgrade``: it runs ``postgres_auto_migrate`` and then
``Base.metadata.create_all``. So the thing to test is the heal, against rows.

This reconstructs the shape a 14.8.1 database has when 15.0.x first boots on it:
the two columns v3297 adds to ``oe_boq_markup`` are removed, together with their
indexes and foreign keys, while a markup row stays in the table. Then the heal
runs, and the row has to come out the other side with its money unchanged and
the schema complete.

``oe_boq_markup`` is the table to prove it on. It carries the numbers a stored
estimate is priced with, so a column that fails to land here is not a missing
feature, it is a bill that answers differently than it did yesterday.

Self-restoring by construction: the heal is what puts the schema back, so the
cluster this shares with the rest of the lane ends the test healthy.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

_TABLE = "oe_boq_markup"
_NEW_COLUMNS = ("scope_position_id", "overrides_id")


async def _live_columns(conn, table: str) -> dict[str, str]:
    rows = await conn.execute(
        text("SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    )
    return {name: nullable for name, nullable in rows.all()}


async def _live_foreign_keys(conn, table: str) -> dict[tuple[str, ...], str]:
    """Map each foreign key's constrained columns to its ON DELETE action."""
    rows = await conn.execute(
        text(
            """
            SELECT c.conname,
                   c.confdeltype,
                   ARRAY(
                       SELECT a.attname
                       FROM unnest(c.conkey) AS k(attnum)
                       JOIN pg_attribute a
                         ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                   ) AS cols
            FROM pg_constraint c
            WHERE c.conrelid = cast(:t AS regclass) AND c.contype = 'f'
            """
        ),
        {"t": table},
    )
    # ``confdeltype`` is PostgreSQL's internal ``"char"``, which asyncpg hands
    # back as a single byte rather than a string.
    return {
        tuple(cols): confdeltype.decode() if isinstance(confdeltype, bytes) else confdeltype
        for _name, confdeltype, cols in rows.all()
    }


async def _live_index_columns(conn, table: str) -> set[tuple[str, ...]]:
    rows = await conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE tablename = :t"),
        {"t": table},
    )
    covered: set[tuple[str, ...]] = set()
    for (indexdef,) in rows.all():
        inside = indexdef[indexdef.rindex("(") + 1 : indexdef.rindex(")")]
        covered.add(tuple(part.strip().strip('"') for part in inside.split(",")))
    return covered


async def _seed_a_priced_bill(engine) -> tuple[uuid.UUID, str]:
    """Write a user, a project, a bill and one markup line. Returns the markup id and its rate."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.boq.models import BOQ, BOQMarkup
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"upgrade-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Upgrading Estimator",
    )
    project = Project(id=uuid.uuid4(), name="Bill priced before the upgrade", owner_id=owner.id, currency="EUR")
    bill = BOQ(id=uuid.uuid4(), project_id=project.id, name="Tender bill")
    markup_id = uuid.uuid4()
    markup = BOQMarkup(
        id=markup_id,
        boq_id=bill.id,
        name="Overhead and profit",
        percentage="12.5",
    )

    # Flushed one at a time rather than in a single ``add_all``: the metadata
    # holds foreign-key cycles, so the unit of work cannot always sort these
    # four by dependency and falls back to the order they were added in.
    async with AsyncSession(engine) as session:
        for row in (owner, project, bill, markup):
            session.add(row)
            await session.flush()
        await session.commit()

    # ``markup_id`` rather than ``markup.id``: commit expires every attribute and
    # the instance is detached once the session closes.
    return markup_id, "12.5"


async def _strip_to_the_previous_release(engine) -> None:
    """Remove what v3297 adds, leaving the table in the shape 14.8.1 shipped."""
    async with engine.begin() as conn:
        for column in _NEW_COLUMNS:
            await conn.execute(text(f'ALTER TABLE "{_TABLE}" DROP COLUMN IF EXISTS "{column}" CASCADE'))


async def test_the_heal_restores_the_new_schema_without_touching_the_rows(pg_engine) -> None:
    """The columns, indexes and keys come back; the markup line keeps its rate."""
    from app.core.postgres_migrator import postgres_auto_migrate
    from app.database import Base

    markup_id, rate = await _seed_a_priced_bill(pg_engine)
    await _strip_to_the_previous_release(pg_engine)

    async with pg_engine.connect() as conn:
        before = await _live_columns(conn, _TABLE)
    for column in _NEW_COLUMNS:
        assert column not in before, f"{column} should be gone before the heal runs"

    # The row is still there, which is the whole point: this is not a fresh install.
    async with pg_engine.connect() as conn:
        surviving = (
            await conn.execute(text(f'SELECT count(*) FROM "{_TABLE}"'))  # noqa: S608 - constant identifier
        ).scalar_one()
    assert surviving >= 1, "the fixture must leave a markup row in the table"

    await postgres_auto_migrate(pg_engine, Base)

    async with pg_engine.connect() as conn:
        after = await _live_columns(conn, _TABLE)
        keys = await _live_foreign_keys(conn, _TABLE)
        indexes = await _live_index_columns(conn, _TABLE)
        kept = (
            await conn.execute(
                text(f'SELECT percentage FROM "{_TABLE}" WHERE id = :id'),  # noqa: S608 - constant identifier
                {"id": str(markup_id)},
            )
        ).scalar_one_or_none()

    for column in _NEW_COLUMNS:
        assert column in after, f"the heal did not add {column} back to an existing table"
        assert after[column] == "YES", f"{column} must arrive nullable so existing rows keep their meaning"

    # The rate the estimator entered is untouched by the upgrade.
    assert kept == rate, "the upgrade rewrote a stored markup rate"

    # ``c`` is CASCADE and ``n`` is SET NULL in pg_constraint.confdeltype. The
    # difference is the one v3297 argues for: deleting a position takes its
    # scoped line with it, deleting a bill-wide line leaves the scoped line
    # standing with nothing to override.
    assert keys.get(("scope_position_id",)) == "c", "scope_position_id lost its ON DELETE CASCADE"
    assert keys.get(("overrides_id",)) == "n", "overrides_id lost its ON DELETE SET NULL"

    for column in _NEW_COLUMNS:
        assert (column,) in indexes, f"the heal did not restore the index on {column}"


_BALANCE = "oe_supplier_catalogs_stock_balance"


async def _seed_a_stock_balance(engine) -> uuid.UUID:
    """Leave one row in the balances table, in the shape 15.3.x stored."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.supplier_catalogs.models import CatalogItem, StockBalance, Warehouse

    # A balance is a leaf: both of its parents carry a foreign key, so the row
    # cannot exist without them and the test would be measuring the insert
    # rather than the heal.
    warehouse = Warehouse(id=uuid.uuid4(), code=f"WH-{uuid.uuid4().hex[:8]}", name="Yard")
    item = CatalogItem(id=uuid.uuid4(), sku=f"SKU-{uuid.uuid4().hex[:8]}", name="Rebar B500B 12mm")
    balance_id = uuid.uuid4()
    # Bound to the lane engine rather than the module-level factory, the same
    # way the bill fixture above is, so this writes into the cluster the test
    # then strips and heals.
    async with AsyncSession(engine) as session:
        for row in (
            warehouse,
            item,
            StockBalance(
                id=balance_id,
                warehouse_id=warehouse.id,
                catalog_item_id=item.id,
                batch_lot="",
            ),
        ):
            session.add(row)
            await session.flush()
        await session.commit()
    return balance_id


async def test_the_heal_gives_a_not_null_column_the_default_that_backfills_it(pg_engine) -> None:
    """A NOT NULL column whose default lives only in Python still lands NOT NULL.

    The heal can only mark a column NOT NULL if it also has a default to fill
    the rows already in the table with. It used to look for that default in
    ``server_default`` alone, so a column carrying a plain Python default was
    added nullable, and the model and the database disagreed about it from
    then on. Nothing reported it: the column exists, it selects, the health
    endpoint says the schema healed and the alembic head matches.

    ``cost_state`` is the column that caught it. Its alembic revision does
    declare ``server_default``, so a database that ran the chain was always
    right and only the heal path was wrong, which is why the two lanes
    disagreed and the upgrade lane was the one telling the truth.
    """
    from app.core.postgres_migrator import postgres_auto_migrate
    from app.database import Base
    from app.modules.supplier_catalogs.models import COST_STATE_UNKNOWN

    balance_id = await _seed_a_stock_balance(pg_engine)
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'ALTER TABLE "{_BALANCE}" DROP COLUMN IF EXISTS "cost_state" CASCADE'))

    async with pg_engine.connect() as conn:
        assert "cost_state" not in await _live_columns(conn, _BALANCE)

    await postgres_auto_migrate(pg_engine, Base)

    async with pg_engine.connect() as conn:
        after = await _live_columns(conn, _BALANCE)
        value = (
            await conn.execute(
                text(f'SELECT cost_state FROM "{_BALANCE}" WHERE id = :id'),  # noqa: S608 - constant identifier
                {"id": str(balance_id)},
            )
        ).scalar_one_or_none()

    assert "cost_state" in after, "the heal did not add cost_state back"
    assert after["cost_state"] == "NO", (
        "cost_state came back accepting NULL. The model declares it NOT NULL "
        "with a default, so the heal had everything it needed to say so."
    )
    # The row that predates the column is filled, not left empty. A NOT NULL
    # column that arrived without backfilling its rows could not have been
    # added at all, so this is the half of the claim the nullability check
    # cannot make on its own.
    assert value == COST_STATE_UNKNOWN, f"the pre-existing row reads {value!r} rather than the default"
