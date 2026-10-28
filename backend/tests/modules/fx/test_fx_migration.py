# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Executes the FX migration in both directions against real PostgreSQL.

Reading a migration proves nothing about it. The two claims worth checking are
the two that only show up in production: that ``upgrade()`` is a no-op against a
database that already carries the tables (this platform materialises schema with
``create_all`` and then stamps, so the very first thing the migration meets is a
database that does not need it), and that ``downgrade()`` genuinely reverses it
rather than being the ``pass`` that so many downgrades quietly are.

The migration is driven directly through an Alembic ``MigrationContext`` instead
of ``alembic upgrade head``, so that what is under test is this revision's own
SQL rather than the state of the graph around it.

That choice used to be excused here by the claim that the graph had several
independent heads and no linear run reached this revision. The claim was
accurate, and it was describing a bug rather than a quirk. This revision names
``v3234_cost_search_trgm`` as its parent, a node ``v3250_merge_open_heads`` had
already folded into the mainline, so it sat alone on a second head and
``alembic upgrade head`` refused to run at all. Since this file is the only
one that creates the three tables below, every install built by migrations
instead of ``create_all`` was missing the whole rate register.
``v3268_merge_fx_branch`` folds the branch back in, and
``tests/unit/test_alembic_single_head.py`` now fails if any revision opens a
second head again. Whether this revision is reachable is that test's job, and
deliberately not this one's.

Everything runs against a throwaway database from ``isolated_engine()``, which
is cloned per test and dropped afterwards. The shared unit database is off
limits for this - dropping tables in it would take down every other test in the
session.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection

from tests._pg import isolated_engine

#: backend/tests/modules/fx/<this file> -> backend/alembic/versions/<migration>
MIGRATION_PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "v3255_fx_rate_sets_and_policy.py"

FX_TABLES = frozenset({"oe_fx_rate_set", "oe_fx_rate_quote", "oe_fx_policy"})

#: The named constraints and indexes the migration itself creates. Anything in
#: here that does not come back after a downgrade/upgrade round trip is a
#: migration that does not reproduce its own schema.
MIGRATION_OBJECTS: dict[str, frozenset[str]] = {
    "oe_fx_rate_set": frozenset({"uq_oe_fx_rate_set_base_date_source", "ix_oe_fx_rate_set_base_date"}),
    "oe_fx_rate_quote": frozenset(
        {
            "uq_oe_fx_rate_quote_set_currency",
            "fk_oe_fx_rate_quote_rate_set",
            "ix_oe_fx_rate_quote_rate_set_id",
        }
    ),
    "oe_fx_policy": frozenset(
        {
            "uq_oe_fx_policy_project",
            "fk_oe_fx_policy_pinned_rate_set",
            "ix_oe_fx_policy_pinned_rate_set_id",
        }
    ),
}

#: Indexes that ``create_all`` adds through the platform's ``after_create`` hook
#: (``app.core.pg_optimizations`` gives every table carrying both ``project_id``
#: and ``created_at`` a composite index) rather than through any revision. No
#: migration in the repository creates these, and this one follows that
#: convention, so a round trip legitimately does not bring them back - the hook
#: does, on the next ``create_all``. Pinned by name so the difference stays a
#: known one instead of quietly widening.
HOOK_INDEXES: frozenset[str] = frozenset({"ix_oe_fx_policy_project_id_created_at"})


def _load_migration() -> ModuleType:
    """Import the revision file by path.

    Alembic version files are not a package, so they are not importable by name.
    """
    spec = importlib.util.spec_from_file_location("fx_rate_sets_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.fail(f"Cannot load the migration at {MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _apply(sync_conn: Connection, step: Callable[[], None]) -> None:
    """Run one migration function with ``op`` bound to this connection."""
    context = MigrationContext.configure(sync_conn)
    with Operations.context(context):
        step()


def _tables(sync_conn: Connection) -> set[str]:
    return set(sa.inspect(sync_conn).get_table_names())


def _constraints(sync_conn: Connection, table: str) -> set[str]:
    inspector = sa.inspect(sync_conn)
    names = {row["name"] for row in inspector.get_unique_constraints(table)}
    names |= {row["name"] for row in inspector.get_foreign_keys(table)}
    names |= {row["name"] for row in inspector.get_indexes(table)}
    return {name for name in names if name}


def test_migration_identifies_itself_and_chains_off_an_existing_revision() -> None:
    module = _load_migration()

    assert module.revision == "v3255_fx_rate_sets_and_policy"
    assert module.down_revision == "v3234_cost_search_trgm"
    parent = MIGRATION_PATH.parent / "v3234_cost_search_trgm.py"
    assert parent.is_file(), "down_revision must name a revision file that exists"


@pytest.mark.asyncio
async def test_upgrade_is_a_no_op_on_a_database_that_already_has_the_tables() -> None:
    """The production path is create_all then stamp, so this is the usual case."""
    module = _load_migration()

    async with isolated_engine() as engine, engine.begin() as conn:
        before = await conn.run_sync(_tables)
        assert before >= FX_TABLES, "the schema template should already carry the FX tables"

        await conn.run_sync(_apply, module.upgrade)

        assert await conn.run_sync(_tables) == before


@pytest.mark.asyncio
async def test_downgrade_removes_the_tables_and_upgrade_rebuilds_them_exactly() -> None:
    """Down then up, twice each, and the named constraints have to come back."""
    module = _load_migration()

    async with isolated_engine() as engine, engine.begin() as conn:
        before = {table: await conn.run_sync(_constraints, table) for table in MIGRATION_OBJECTS}
        for table, owned in MIGRATION_OBJECTS.items():
            assert owned <= before[table], f"{table} is not built the way the migration describes it"

        await conn.run_sync(_apply, module.downgrade)
        assert not (FX_TABLES & await conn.run_sync(_tables))
        # A second downgrade must not trip over the tables it already dropped.
        await conn.run_sync(_apply, module.downgrade)

        await conn.run_sync(_apply, module.upgrade)
        assert await conn.run_sync(_tables) >= FX_TABLES
        # And a second upgrade must not trip over the tables it just created.
        await conn.run_sync(_apply, module.upgrade)

        for table, owned in MIGRATION_OBJECTS.items():
            rebuilt = await conn.run_sync(_constraints, table)
            assert owned <= rebuilt, f"{table} lost {sorted(owned - rebuilt)} across the round trip"
            lost = before[table] - rebuilt
            assert lost <= HOOK_INDEXES, f"{table} lost {sorted(lost - HOOK_INDEXES)}, which no hook will put back"


@pytest.mark.asyncio
async def test_the_rebuilt_tables_still_cascade_and_still_reject_a_duplicate_quote() -> None:
    """The round trip has to restore behaviour, not just object names."""
    module = _load_migration()

    async with isolated_engine() as engine, engine.begin() as conn:
        await conn.run_sync(_apply, module.downgrade)
        await conn.run_sync(_apply, module.upgrade)

        await conn.execute(
            sa.text(
                "INSERT INTO oe_fx_rate_set (id, base_currency, rate_date, source) "
                "VALUES ('set-1', 'EUR', DATE '2026-03-02', 'ecb')"
            )
        )
        await conn.execute(
            sa.text(
                "INSERT INTO oe_fx_rate_quote (id, rate_set_id, currency, rate) VALUES ('q-1', 'set-1', 'TRY', 42.5)"
            )
        )

        # Inside a savepoint: the violation aborts whatever transaction it runs
        # in, and the outer one still has to survive to the end of the test.
        nested = await conn.begin_nested()
        with pytest.raises(sa.exc.IntegrityError):
            await conn.execute(
                sa.text(
                    "INSERT INTO oe_fx_rate_quote (id, rate_set_id, currency, rate) "
                    "VALUES ('q-2', 'set-1', 'TRY', 43.0)"
                )
            )
        await nested.rollback()

        kept = await conn.execute(sa.text("SELECT count(*) FROM oe_fx_rate_quote WHERE rate_set_id = 'set-1'"))
        assert kept.scalar_one() == 1


@pytest.mark.asyncio
async def test_deleting_a_rebuilt_rate_set_takes_its_quotes_with_it() -> None:
    """ON DELETE CASCADE has to survive the round trip too."""
    module = _load_migration()

    async with isolated_engine() as engine, engine.begin() as conn:
        await conn.run_sync(_apply, module.downgrade)
        await conn.run_sync(_apply, module.upgrade)

        await conn.execute(
            sa.text(
                "INSERT INTO oe_fx_rate_set (id, base_currency, rate_date, source) "
                "VALUES ('set-2', 'EUR', DATE '2026-03-02', 'ecb')"
            )
        )
        await conn.execute(
            sa.text(
                "INSERT INTO oe_fx_rate_quote (id, rate_set_id, currency, rate) VALUES ('q-3', 'set-2', 'USD', 1.085)"
            )
        )
        await conn.execute(sa.text("DELETE FROM oe_fx_rate_set WHERE id = 'set-2'"))

        remaining = await conn.execute(sa.text("SELECT count(*) FROM oe_fx_rate_quote WHERE rate_set_id = 'set-2'"))
        assert remaining.scalar_one() == 0
