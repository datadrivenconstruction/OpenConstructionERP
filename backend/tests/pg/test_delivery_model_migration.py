# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Revision v70 builds exactly the schema the delivery model models build, and undoes it.

Up, down, up on PostgreSQL; the reflected schema from the revision must equal
the one ``create_all`` produces from the models (type, nullability and server
default of every column), so a fresh install and an upgraded one cannot drift.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.delivery_model.models import ALL_MODELS
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

TABLES = [m.__tablename__ for m in ALL_MODELS]


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load("v70_delivery_model")
_contract = _load("v79_delivery_contract_items")


def _upgrade() -> None:
    """The module's tables come from its first revision and the one that added the contract side."""
    _rev.upgrade()
    _contract.upgrade()


def _downgrade() -> None:
    _contract.downgrade()
    _rev.downgrade()


def _run(sync_conn, direction) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        direction()


def _reflect(sync_conn) -> dict:
    inspector = sa.inspect(sync_conn)
    tables = set(inspector.get_table_names())
    out: dict = {"tables": tables}
    for table in TABLES:
        if table not in tables:
            continue
        out[table] = {
            # The server default is part of the comparison: a column that is NOT NULL in both but has a
            # default only in the models would make an insert from raw SQL fail on an upgraded install.
            "columns": {
                c["name"]: (str(c["type"]), c["nullable"], c.get("default")) for c in inspector.get_columns(table)
            },
            # ``app.core.pg_optimizations`` adds ``ix_oe_delivery_model_<table>_...`` on
            # every create_all and no revision reproduces them; compare only the
            # indexes this module declares (``ix_oe_dm_*``).
            "indexes": {
                i["name"]
                for i in inspector.get_indexes(table)
                if i.get("name") and not i["name"].startswith("ix_oe_delivery_model_")
            },
            "unique": {u["name"] for u in inspector.get_unique_constraints(table) if u.get("name")},
            "fks": {(f["name"], (f.get("options") or {}).get("ondelete")) for f in inspector.get_foreign_keys(table)},
        }
    return out


async def _drop_all(conn) -> None:
    for table in reversed(TABLES):
        await conn.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))


def test_revision_branches_from_governance() -> None:
    assert _rev.revision == "v70_delivery_model"
    assert _rev.down_revision == "v69_commitment_release"


async def test_revision_reproduces_the_model_schema_up_down_up() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            from_models = await conn.run_sync(_reflect)
        assert set(TABLES) <= from_models["tables"]
        async with engine.begin() as conn:
            await _drop_all(conn)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _upgrade)
            first = await conn.run_sync(_reflect)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _downgrade)
            down = await conn.run_sync(_reflect)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _upgrade)
            second = await conn.run_sync(_reflect)

    assert not set(TABLES) & down["tables"]
    for table in TABLES:
        for key in ("columns", "indexes", "unique", "fks"):
            assert first[table][key] == from_models[table][key], (table, key)
            assert second[table][key] == from_models[table][key], (table, key)


async def test_revision_is_a_no_op_over_a_create_all_schema() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            before = await conn.run_sync(_reflect)
            await conn.run_sync(_run, _upgrade)
            after = await conn.run_sync(_reflect)
    for table in TABLES:
        assert after[table] == before[table]


async def test_the_comparison_sees_server_defaults() -> None:
    """Guard on the guard: the reflection really carries defaults, so a dropped one would be seen."""
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            reflected = await conn.run_sync(_reflect)
    defaults = {
        (table, name): default
        for table in TABLES
        for name, (_, _, default) in reflected[table]["columns"].items()
        if default is not None
    }
    assert ("oe_delivery_model_decision", "approval_blocked_reason") in defaults
    assert len(defaults) >= len(TABLES)
