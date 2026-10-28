# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The schema is built two ways, and both ways must agree.

A fresh install gets its tables from ``Base.metadata.create_all``; an existing
deployment gets them from the migration. Every other test in this package runs
against the first path only, so the migration could be wrong in any way at all -
a missed index, a nullable column that should not be, a constraint under a name
nothing matches - and the suite would stay green right up until someone upgraded
a production database.

These tests apply the migration for real, to a throwaway database, and compare
the schema it produces against the schema the models produce. They also hold it
to the two properties claimed in its docstring: applying it to a database that
already has the table is a no-op, and the downgrade genuinely reverses it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection

from app.database import Base
from tests._pg import isolated_engine

_MIGRATION_PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "v3266_credentials_requirements.py"

# Both tables the migration touches: the one it creates and the one it extends.
_TABLES = ("oe_credentials_requirement", "oe_credentials_credential")

_ADDED_COLUMNS = ("verified_by", "verified_at")


def _load_migration() -> ModuleType:
    """Import the revision file directly, by path.

    Alembic's version directory is not a package, so this is how the revision is
    reached without standing up a full ``EnvironmentContext``.
    """
    spec = importlib.util.spec_from_file_location("credentials_v3266", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {_MIGRATION_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(connection: Connection, direction: str) -> None:
    """Run the revision's ``upgrade`` or ``downgrade`` against ``connection``.

    ``target_metadata`` is passed exactly as ``alembic/env.py`` passes it, so the
    naming convention that gives the models ``pk_oe_credentials_requirement``
    also applies to the table this builds. Without it Alembic would fall back to
    PostgreSQL's own ``..._pkey``, and the two build paths would disagree on a
    constraint name that nothing in the application ever types.
    """
    context = MigrationContext.configure(
        connection=connection,
        opts={"target_metadata": Base.metadata},
    )
    migration = _load_migration()
    with Operations.context(context):
        getattr(migration, direction)()


def _rewind(connection: Connection) -> None:
    """Put the database back to how it looked before this revision.

    The throwaway database is cloned from a template built by ``create_all``, so
    it already has everything. Removing it again is what makes the migration's
    own work observable.
    """
    connection.execute(sa.text(f"DROP TABLE IF EXISTS {_TABLES[0]}"))
    for column in _ADDED_COLUMNS:
        connection.execute(sa.text(f"ALTER TABLE {_TABLES[1]} DROP COLUMN IF EXISTS {column}"))


def _snapshot(connection: Connection, table: str) -> dict[str, Any]:
    """Everything about ``table`` that the two build paths could disagree on.

    Compared as a whole rather than field by field: the interesting failure is
    always the difference nobody thought to assert on.
    """
    inspector = sa.inspect(connection)
    return {
        "columns": {
            column["name"]: {
                "type": str(column["type"]),
                "nullable": column["nullable"],
                "default": column["default"],
            }
            for column in inspector.get_columns(table)
        },
        "primary_key": {
            "name": inspector.get_pk_constraint(table).get("name"),
            "columns": inspector.get_pk_constraint(table).get("constrained_columns"),
        },
        "foreign_keys": sorted(
            (
                fk["name"],
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                fk.get("options", {}).get("ondelete"),
            )
            for fk in inspector.get_foreign_keys(table)
        ),
        "unique_constraints": sorted(
            (uc["name"], tuple(uc["column_names"])) for uc in inspector.get_unique_constraints(table)
        ),
        "indexes": sorted(
            (ix["name"], tuple(ix["column_names"]), bool(ix.get("unique"))) for ix in inspector.get_indexes(table)
        ),
    }


def _snapshot_all(connection: Connection) -> dict[str, dict[str, Any]]:
    return {table: _snapshot(connection, table) for table in _TABLES}


def _differences(expected: Any, actual: Any, path: str = "") -> list[str]:
    """Readable leaf-level differences between two snapshots.

    ``assert a == b`` on a nested dict this size is truncated by pytest into
    something nobody can act on, and a schema mismatch is precisely the failure
    where the detail *is* the bug report.
    """
    if isinstance(expected, dict) and isinstance(actual, dict):
        found: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            where = f"{path}.{key}" if path else str(key)
            if key not in expected:
                found.append(f"{where}: only the migration has it ({actual[key]!r})")
            elif key not in actual:
                found.append(f"{where}: only the models have it ({expected[key]!r})")
            else:
                found.extend(_differences(expected[key], actual[key], where))
        return found
    if expected != actual:
        return [f"{path}: models={expected!r} migration={actual!r}"]
    return []


def _check_parity(connection: Connection) -> None:
    from_models = _snapshot_all(connection)
    _rewind(connection)
    _run(connection, "upgrade")
    from_migration = _snapshot_all(connection)

    drift = _differences(from_models, from_migration)
    assert not drift, (
        "the migration and the models describe different schemas, so a deployment "
        "upgraded through this revision would not match a fresh install:\n  " + "\n  ".join(drift)
    )


def _check_no_op_on_a_created_schema(connection: Connection) -> None:
    before = _snapshot_all(connection)
    _run(connection, "upgrade")  # everything is already there
    assert _snapshot_all(connection) == before

    # And from the other side: applying it twice is the same as applying it once.
    _rewind(connection)
    _run(connection, "upgrade")
    once = _snapshot_all(connection)
    _run(connection, "upgrade")
    assert _snapshot_all(connection) == once


def _check_downgrade_reverses_it(connection: Connection) -> None:
    _rewind(connection)
    _run(connection, "upgrade")
    _run(connection, "downgrade")

    inspector = sa.inspect(connection)
    assert _TABLES[0] not in inspector.get_table_names()
    remaining = {column["name"] for column in inspector.get_columns(_TABLES[1])}
    assert not remaining & set(_ADDED_COLUMNS)

    # The credential table itself must survive its columns being removed.
    assert "holder_name" in remaining

    # And the revision can be applied again afterwards, which is the whole
    # point of a downgrade that is not just a placeholder.
    _run(connection, "upgrade")
    assert _TABLES[0] in sa.inspect(connection).get_table_names()


async def test_the_migration_builds_what_the_models_declare() -> None:
    """Column types, nullability, defaults, keys, constraints and indexes."""
    async with isolated_engine() as engine, engine.begin() as connection:
        await connection.run_sync(_check_parity)


async def test_applying_the_revision_twice_changes_nothing() -> None:
    """The idempotency its docstring claims, on both entry states."""
    async with isolated_engine() as engine, engine.begin() as connection:
        await connection.run_sync(_check_no_op_on_a_created_schema)


async def test_the_downgrade_actually_reverses_the_upgrade() -> None:
    """A downgrade that is a ``pass`` would pass every other test in this file."""
    async with isolated_engine() as engine, engine.begin() as connection:
        await connection.run_sync(_check_downgrade_reverses_it)
