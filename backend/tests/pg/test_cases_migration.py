"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``v3281_cases_module`` builds the same schema ``create_all`` builds.

The platform installs its schema two ways: ``Base.metadata.create_all`` on a
fresh install, and the alembic chain on an existing deployment. A new module
whose revision disagrees with its models produces two different databases that
both look installed, and only one of them serves the module.

So this runs the revision's own ``upgrade()`` against a real PostgreSQL and
compares the result to what the ORM metadata emits, rather than to what the
revision was written to say. The chain itself is not replayed - the single-head
and identifier-length checks cover that - because replaying 300-odd revisions
to reach this one would test everything except the thing that is new.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.cases.models import CasePin, UserCase
from tests._pg import isolated_engine


def _load_revision(name: str):
    """Import one revision by path. ``alembic/versions`` is not a package."""
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load revision {name} from {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_revision = _load_revision("v3281_cases_module")
upgrade = _revision.upgrade
downgrade = _revision.downgrade

CASE = "oe_cases_user_case"
PIN = "oe_cases_pin"

pytestmark = pytest.mark.asyncio


def _run(sync_conn, direction) -> None:
    """Run one direction of the revision against an open sync connection."""
    context = MigrationContext.configure(sync_conn)
    with Operations.context(context):
        direction()


def _reflect(sync_conn) -> dict:
    inspector = sa.inspect(sync_conn)
    tables = set(inspector.get_table_names())
    out: dict = {"tables": tables}
    for table in (CASE, PIN):
        if table not in tables:
            continue
        out[table] = {
            "columns": {c["name"]: (str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)},
            "indexes": {i["name"] for i in inspector.get_indexes(table) if i.get("name")},
            "unique": {u["name"] for u in inspector.get_unique_constraints(table) if u.get("name")},
            "fks": {f["name"] for f in inspector.get_foreign_keys(table) if f.get("name")},
            "pk": inspector.get_pk_constraint(table).get("name"),
        }
    return out


async def test_revision_reproduces_the_create_all_schema() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            # The throwaway database is cloned from the schema-loaded template,
            # so the two tables are already there. Dropping them is what makes
            # this exercise the create path instead of the guarded no-op.
            await conn.execute(sa.text(f"DROP TABLE IF EXISTS {PIN} CASCADE"))
            await conn.execute(sa.text(f"DROP TABLE IF EXISTS {CASE} CASCADE"))
            expected = await conn.run_sync(_reflect)
        assert CASE not in expected["tables"]

        # Rebuild from the ORM metadata: this is the fresh-install schema, and
        # the standard every assertion below is made against.
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: UserCase.metadata.create_all(c, tables=[UserCase.__table__, CasePin.__table__])
            )
            from_models = await conn.run_sync(_reflect)

        async with engine.begin() as conn:
            await conn.execute(sa.text(f"DROP TABLE IF EXISTS {PIN} CASCADE"))
            await conn.execute(sa.text(f"DROP TABLE IF EXISTS {CASE} CASCADE"))

        async with engine.begin() as conn:
            await conn.run_sync(_run, upgrade)
            from_revision = await conn.run_sync(_reflect)

    for table in (CASE, PIN):
        assert table in from_revision["tables"], f"{table} was not created by the revision"
        # Column names, types and nullability all have to agree. A varchar(36)
        # id built one way and a native uuid built the other is the exact
        # divergence this file exists to catch.
        assert from_revision[table]["columns"] == from_models[table]["columns"], table
        assert from_revision[table]["indexes"] == from_models[table]["indexes"], table
        assert from_revision[table]["unique"] == from_models[table]["unique"], table
        assert from_revision[table]["fks"] == from_models[table]["fks"], table
        assert from_revision[table]["pk"] == from_models[table]["pk"], table


async def test_revision_is_idempotent_over_a_create_all_schema() -> None:
    # The documented deploy path is create_all plus ``alembic stamp head``, but
    # a site that stamped an older revision runs this over tables that already
    # exist. That has to be a no-op, not a duplicate-table error.
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await conn.run_sync(_run, upgrade)
            await conn.run_sync(_run, upgrade)
            reflected = await conn.run_sync(_reflect)
    assert CASE in reflected["tables"]
    assert PIN in reflected["tables"]


async def test_downgrade_removes_both_tables() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await conn.run_sync(_run, upgrade)
            await conn.run_sync(_run, downgrade)
            reflected = await conn.run_sync(_reflect)
    assert CASE not in reflected["tables"]
    assert PIN not in reflected["tables"]
