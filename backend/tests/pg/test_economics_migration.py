# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Revision v79 builds exactly the schema the economics models build, and undoes it.

Up, down, up on PostgreSQL for the six tables. The reflected schema from the revision must equal the
one ``create_all`` produces (columns with types and nullability, the module's own indexes, unique
constraints, foreign keys), so a fresh install and an upgraded one cannot drift.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load("v79_economics")
TABLES = [t for t, _c, _i in _rev._TABLES]


def _run(sync_conn, direction) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        direction()


def _ours(name: str | None) -> bool:
    # ``app.core.pg_optimizations`` adds ``ix_<table>_<columns>`` on every create_all and no revision
    # reproduces those; the module names its own indexes ``ix_oe_eco_<short>``.
    return bool(name) and name.startswith("ix_oe_eco_")


def _reflect(sync_conn) -> dict:
    inspector = sa.inspect(sync_conn)
    tables = set(inspector.get_table_names())
    out: dict = {"tables": tables}
    for table in TABLES:
        if table not in tables:
            continue
        out[table] = {
            "columns": {c["name"]: (str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)},
            "indexes": {
                (i["name"], tuple(i["column_names"]), bool(i.get("unique")))
                for i in inspector.get_indexes(table)
                if _ours(i.get("name"))
            },
            "unique": {
                (u["name"], tuple(u["column_names"])) for u in inspector.get_unique_constraints(table) if u.get("name")
            },
            "fks": {
                (
                    f["name"],
                    tuple(f["constrained_columns"]),
                    f["referred_table"],
                    tuple(f["referred_columns"]),
                    (f.get("options") or {}).get("ondelete"),
                )
                for f in inspector.get_foreign_keys(table)
            },
        }
    return out


async def test_revision_reproduces_the_model_schema_up_down_up() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            from_models = await conn.run_sync(_reflect)
        assert set(TABLES) <= from_models["tables"]
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.downgrade)
            down = await conn.run_sync(_reflect)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.upgrade)
            first = await conn.run_sync(_reflect)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.downgrade)
            down_again = await conn.run_sync(_reflect)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.upgrade)
            second = await conn.run_sync(_reflect)

    assert not set(TABLES) & down["tables"]
    assert down == down_again
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
        assert after[table] == before[table], table


async def test_money_columns_are_exact_decimals() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            built = await conn.run_sync(_reflect)
    assert built["oe_economics_plan"]["columns"]["markup_allowance"] == ("NUMERIC(18, 4)", False)
    assert built["oe_economics_plan"]["columns"]["discount_rate_pct"][1] is True
