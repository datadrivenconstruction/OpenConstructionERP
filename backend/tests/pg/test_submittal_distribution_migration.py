"""Revision vsub01 adds and removes the submittal distribution list column."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

TABLE = "oe_submittals_submittal"
COLUMN = "distribution_list"


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load("vsub01_submittal_distribution_list")


def _run(sync_conn, direction) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        direction()


def _column(sync_conn) -> dict | None:
    cols = {c["name"]: c for c in sa.inspect(sync_conn).get_columns(TABLE)}
    col = cols.get(COLUMN)
    return None if col is None else {"type": str(col["type"]), "nullable": col["nullable"]}


async def test_revision_chains_onto_the_previous_head() -> None:
    assert _rev.revision == "vsub01_submittal_distribution"
    assert _rev.down_revision == "vct01_cost_type_budget_lines"


async def test_up_down_up_matches_the_model_column() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            from_models = await conn.run_sync(_column)
            assert from_models is not None
            await conn.run_sync(_run, _rev.upgrade)  # already there: no-op
            assert await conn.run_sync(_column) == from_models
            await conn.run_sync(_run, _rev.downgrade)
            assert await conn.run_sync(_column) is None
            await conn.run_sync(_run, _rev.downgrade)  # twice: no-op
            await conn.run_sync(_run, _rev.upgrade)
            assert await conn.run_sync(_column) == from_models
