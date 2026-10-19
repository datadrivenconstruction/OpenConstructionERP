# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Revision v97 adds a benchmark set's split and reporting currency, keeps the rows, and undoes it.

On PostgreSQL and on SQLite (the desktop build): a set saved before the revision keeps its row and
reads NULL for both new columns, the downgrade drops only those two columns, and a second upgrade over
a schema that already has them changes nothing.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

TABLE = "oe_bi_dashboards_benchmark_set"
NEW = {"split_by", "reporting_currency"}


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_v90 = _load("v90_bi_benchmark_sets")
_rev = _load("v97_bi_benchmark_set_split_currency")


def _run(sync_conn, direction) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        direction()


def _columns(sync_conn) -> dict[str, tuple[str, bool]]:
    return {c["name"]: (str(c["type"]), c["nullable"]) for c in sa.inspect(sync_conn).get_columns(TABLE)}


def _seed(sync_conn) -> str:
    set_id = str(uuid.uuid4())
    sync_conn.execute(sa.text(f"INSERT INTO {TABLE} (id, name) VALUES (:id, 'Old set')"), {"id": set_id})
    return set_id


def _round_trip(sync_conn) -> dict:
    _run(sync_conn, _v90.upgrade)
    before = _columns(sync_conn)
    assert not NEW & set(before)
    set_id = _seed(sync_conn)
    _run(sync_conn, _rev.upgrade)
    up = _columns(sync_conn)
    row = sync_conn.execute(sa.text(f"SELECT name, split_by, reporting_currency FROM {TABLE}")).one()
    _run(sync_conn, _rev.upgrade)
    again = _columns(sync_conn)
    _run(sync_conn, _rev.downgrade)
    down = _columns(sync_conn)
    kept = sync_conn.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE} WHERE id = :id"), {"id": set_id}).scalar()
    return {"before": before, "up": up, "row": tuple(row), "again": again, "down": down, "kept": kept}


def _assert_round_trip(result: dict) -> None:
    assert set(result["up"]) - set(result["before"]) == NEW
    assert all(result["up"][name][1] for name in NEW)
    assert result["row"] == ("Old set", None, None)
    assert result["again"] == result["up"]
    assert result["down"] == result["before"]
    assert result["kept"] == 1


def test_revision_follows_the_benchmark_set_revision_line() -> None:
    assert _rev.revision == "v97_bi_benchmark_set_split_currency"
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    assert (versions / f"{_rev.down_revision}.py").exists(), _rev.down_revision


async def test_up_down_up_on_postgres_keeps_saved_sets() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f"DROP TABLE IF EXISTS {TABLE} CASCADE"))
        async with engine.begin() as conn:
            result = await conn.run_sync(_round_trip)
    _assert_round_trip(result)


async def test_up_down_up_on_sqlite_keeps_saved_sets(tmp_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'v97.db'}")
    try:
        with engine.begin() as conn:
            result = _round_trip(conn)
    finally:
        engine.dispose()
    _assert_round_trip(result)


async def test_revision_skips_a_database_without_the_table() -> None:
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            _run(conn, _rev.upgrade)
            _run(conn, _rev.downgrade)
            assert TABLE not in sa.inspect(conn).get_table_names()
    finally:
        engine.dispose()
