# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Revision v79 builds exactly the schema the engineering brief models build, and undoes it.

Up, down, up on PostgreSQL; the reflected schema from the revision must equal the one ``create_all``
produces from the models, so a fresh install and an upgraded one cannot drift.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.pg_optimizations import _index_name
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

TABLES = [
    "oe_engbrief_brief",
    "oe_engbrief_concept",
    "oe_engbrief_programme",
    "oe_engbrief_milestone",
    "oe_engbrief_study",
    "oe_engbrief_issue",
]


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load("v79_engineering_brief")
_DECLARED = {name for _table, _columns, indexes in _rev._TABLES for name, _cols in indexes}


def _compared(table: str, indexes: list[dict]) -> set[tuple[str, tuple[str, ...]]]:
    """The indexes the revision answers for; the ones the optimisation hook adds on create_all are left out."""
    return {
        (i["name"], tuple(i["column_names"]))
        for i in indexes
        if i.get("name")
        and (i["name"] in _DECLARED or i["name"] != _index_name(table, [c or "" for c in i["column_names"]]))
    }


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
            "indexes": _compared(table, inspector.get_indexes(table)),
            "unique": {u["name"] for u in inspector.get_unique_constraints(table) if u.get("name")},
            "fks": {(f["name"], (f.get("options") or {}).get("ondelete")) for f in inspector.get_foreign_keys(table)},
        }
    return out


async def _drop_all(conn) -> None:
    for table in reversed(TABLES):
        await conn.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))


def test_revision_names_a_parent_that_exists() -> None:
    assert _rev.revision == "v79_engineering_brief"
    # Where the revision sits in the chain is decided when the branches are joined.
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    assert (versions / f"{_rev.down_revision}.py").exists(), _rev.down_revision


async def test_revision_reproduces_the_model_schema_up_down_up() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            from_models = await conn.run_sync(_reflect)
        assert set(TABLES) <= from_models["tables"]
        async with engine.begin() as conn:
            await _drop_all(conn)
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
