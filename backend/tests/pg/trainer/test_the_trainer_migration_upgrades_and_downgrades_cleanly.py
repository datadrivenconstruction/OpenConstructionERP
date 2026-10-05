# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: ``v53_trainer_tables`` builds exactly what ``create_all`` builds, and undoes it.

Production boots with ``create_all`` plus ``alembic stamp head``; a self-hoster
who upgrades in place walks the chain instead. Both must end with the same
seven tables, so this test takes the schema ``create_all`` built for the
session as the reference and runs the real revision file against it:

1. ``downgrade()`` drops all seven tables, children before the course table the
   enrolment foreign key restricts;
2. a second ``downgrade()`` finds nothing and changes nothing;
3. ``upgrade()`` rebuilds them, and every column type, nullability, primary
   key, foreign key (with its ``ON DELETE``), unique constraint and index comes
   back under the same name as ``create_all`` gave it;
4. a second ``upgrade()`` finds everything and changes nothing;
5. with one table missing, ``upgrade()`` creates that table alone.

``tests/integration/test_migrations_roundtrip.py`` also cycles this revision,
but it compares column names only. Constraint and index names are what a later
``ALTER`` or ``DROP`` revision addresses, so they are compared here.

All of it runs inside the per-test transaction ``pg_session`` rolls back;
PostgreSQL DDL is transactional, so the shared schema is untouched.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATION = pathlib.Path(__file__).resolve().parents[3] / "alembic" / "versions" / "v53_trainer_tables.py"

TABLES = (
    "oe_trainer_course",
    "oe_trainer_offer",
    "oe_trainer_enrolment",
    "oe_trainer_task_state",
    "oe_trainer_answer",
    "oe_trainer_attempt",
    "oe_trainer_webhook_event",
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_v53_trainer_tables", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot_sync(connection) -> dict[str, dict]:
    """Everything a later revision could address by name, per trainer table."""
    inspector = sa.inspect(connection)
    present = set(inspector.get_table_names())
    out: dict[str, dict] = {}
    for table in TABLES:
        if table not in present:
            continue
        out[table] = {
            "columns": {
                c["name"]: (str(c["type"]), c["nullable"], c.get("default") is not None)
                for c in inspector.get_columns(table)
            },
            "pk": inspector.get_pk_constraint(table)["name"],
            "fks": sorted(
                (fk["name"], tuple(fk["constrained_columns"]), fk["referred_table"], fk["options"].get("ondelete"))
                for fk in inspector.get_foreign_keys(table)
            ),
            "uniques": sorted((u["name"], tuple(u["column_names"])) for u in inspector.get_unique_constraints(table)),
            "indexes": sorted(
                (i["name"], tuple(i["column_names"]), bool(i["unique"])) for i in inspector.get_indexes(table)
            ),
        }
    return out


async def _snapshot(session) -> dict[str, dict]:
    connection = await session.connection()
    return await connection.run_sync(_snapshot_sync)


async def _run(session, direction: str) -> None:
    connection = await session.connection()

    def _apply(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            getattr(_load_migration(), direction)()

    await connection.run_sync(_apply)


@pytest.mark.asyncio
async def test_the_revision_rebuilds_what_create_all_built(pg_session) -> None:
    reference = await _snapshot(pg_session)
    assert set(reference) == set(TABLES), "create_all did not build every trainer table"

    await _run(pg_session, "downgrade")
    assert await _snapshot(pg_session) == {}

    await _run(pg_session, "downgrade")
    assert await _snapshot(pg_session) == {}

    await _run(pg_session, "upgrade")
    rebuilt = await _snapshot(pg_session)
    for table in TABLES:
        assert rebuilt[table] == reference[table], table

    await _run(pg_session, "upgrade")
    assert await _snapshot(pg_session) == reference


@pytest.mark.asyncio
async def test_upgrade_creates_only_the_table_that_is_missing(pg_session) -> None:
    reference = await _snapshot(pg_session)
    await pg_session.execute(sa.text("DROP TABLE oe_trainer_attempt"))
    assert "oe_trainer_attempt" not in await _snapshot(pg_session)

    await _run(pg_session, "upgrade")
    assert await _snapshot(pg_session) == reference


@pytest.mark.asyncio
async def test_the_enrolment_foreign_keys_carry_the_designed_on_delete(pg_session) -> None:
    """A course with learners cannot be deleted; a deleted user or project takes its row or link."""
    reference = await _snapshot(pg_session)
    fks = {fk[0]: fk for fk in reference["oe_trainer_enrolment"]["fks"]}
    assert fks["fk_oe_trainer_enrolment_course_id_oe_trainer_course"][3] == "RESTRICT"
    assert fks["fk_oe_trainer_enrolment_user_id_oe_users_user"][3] == "CASCADE"
    assert fks["fk_oe_trainer_enrolment_project_id_oe_projects_project"][3] == "SET NULL"
