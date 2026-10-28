# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Revision v73 builds exactly the schema the permits models build, and undoes it.

Up, down, up on PostgreSQL; the reflected schema from the revision must equal
the one ``create_all`` produces from the models.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.permits.models import ALL_MODELS
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

TABLES = [m.__tablename__ for m in ALL_MODELS]
# ``app.core.pg_optimizations`` adds ``ix_<table>_...`` indexes on every create_all that
# no revision reproduces; a prefix filter would collide with them, so only the index
# names the models declare are compared.
DECLARED = {ix.name for m in ALL_MODELS for ix in m.__table__.indexes if ix.name}


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load("v73_permits")


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
            "columns": {c["name"]: (str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)},
            "indexes": {i["name"] for i in inspector.get_indexes(table) if i.get("name") in DECLARED},
            "unique": {u["name"] for u in inspector.get_unique_constraints(table) if u.get("name")},
            "fks": {(f["name"], (f.get("options") or {}).get("ondelete")) for f in inspector.get_foreign_keys(table)},
        }
    return out


async def test_revision_reproduces_the_model_schema_up_down_up() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            from_models = await conn.run_sync(_reflect)
        assert set(TABLES) <= from_models["tables"]
        async with engine.begin() as conn:
            for table in reversed(TABLES):
                await conn.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.upgrade)
            first = await conn.run_sync(_reflect)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.downgrade)
            down = await conn.run_sync(_reflect)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.upgrade)
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
            await conn.run_sync(_run, _rev.upgrade)
            after = await conn.run_sync(_reflect)
    for table in TABLES:
        assert after[table] == before[table]
