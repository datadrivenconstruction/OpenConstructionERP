# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Revisions v90 and v97 build exactly the benchmark set table the model builds, and undo it.

Up, down, up on PostgreSQL; the reflected schema from the revision must equal the one ``create_all``
produces from the model, so a fresh install and an upgraded one cannot drift.
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

TABLE = "oe_bi_dashboards_benchmark_set"
_DECLARED = {"ix_oe_bi_dashboards_benchmark_set_owner_user_id"}


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load("v90_bi_benchmark_sets")
# v97 adds two columns the model now carries, so the chain v90 -> v97 is what must equal create_all.
_followers = [_load("v97_bi_benchmark_set_split_currency")]


def _upgrade() -> None:
    _rev.upgrade()
    for follower in _followers:
        follower.upgrade()


def _downgrade() -> None:
    for follower in reversed(_followers):
        follower.downgrade()
    _rev.downgrade()


def _run(sync_conn, direction) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        direction()


def _reflect(sync_conn) -> dict:
    inspector = sa.inspect(sync_conn)
    tables = set(inspector.get_table_names())
    if TABLE not in tables:
        return {"present": False}
    return {
        "present": True,
        "columns": {
            c["name"]: (str(c["type"]), c["nullable"], str(c.get("default"))) for c in inspector.get_columns(TABLE)
        },
        # The indexes the revision answers for; the ones the optimisation hook adds on create_all are left out.
        "indexes": {
            (i["name"], tuple(i["column_names"]))
            for i in inspector.get_indexes(TABLE)
            if i.get("name")
            and (i["name"] in _DECLARED or i["name"] != _index_name(TABLE, [c or "" for c in i["column_names"]]))
        },
        "pk": inspector.get_pk_constraint(TABLE).get("name"),
    }


def test_revision_names_a_parent_that_exists() -> None:
    assert _rev.revision == "v90_bi_benchmark_sets"
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    assert (versions / f"{_rev.down_revision}.py").exists(), _rev.down_revision


async def test_revision_reproduces_the_model_schema_up_down_up() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            from_models = await conn.run_sync(_reflect)
        assert from_models["present"]
        async with engine.begin() as conn:
            await conn.execute(sa.text(f"DROP TABLE IF EXISTS {TABLE} CASCADE"))
        async with engine.begin() as conn:
            await conn.run_sync(_run, _upgrade)
            first = await conn.run_sync(_reflect)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _downgrade)
            down = await conn.run_sync(_reflect)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _upgrade)
            second = await conn.run_sync(_reflect)

    assert down == {"present": False}
    assert first == from_models
    assert second == from_models


async def test_revision_is_a_no_op_over_a_create_all_schema() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            before = await conn.run_sync(_reflect)
            await conn.run_sync(_run, _upgrade)
            after = await conn.run_sync(_reflect)
    assert after == before
