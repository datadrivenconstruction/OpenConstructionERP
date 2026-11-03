# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Revision vsub9 adds the pass-through columns with safe defaults and removes them again."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

_NEW = {"owner_amount", "markup_pct", "time_impact_days", "owner_time_days"}


def _load():
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "vsub9_subco_change_passthrough.py"
    spec = importlib.util.spec_from_file_location("vsub9_subco_change_passthrough", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load()


def _run(conn: sa.Connection, fn) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _columns(conn: sa.Connection) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns("oe_subcontractors_change")}


async def test_upgrade_gives_existing_rows_zero_markup_and_downgrade_removes_the_columns() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await conn.execute(sa.text("DROP TABLE IF EXISTS oe_subcontractors_change CASCADE"))
            await conn.execute(
                sa.text("CREATE TABLE oe_subcontractors_change (id varchar(36) primary key, amount numeric(18,2))")
            )
            await conn.execute(sa.text("INSERT INTO oe_subcontractors_change (id, amount) VALUES ('c1', 100)"))

            await conn.run_sync(lambda c: _run(c, _rev.upgrade))
            await conn.run_sync(lambda c: _run(c, _rev.upgrade))  # replay-safe
            cols = await conn.run_sync(_columns)
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT markup_pct, time_impact_days, owner_amount, owner_time_days FROM oe_subcontractors_change"
                    )
                )
            ).one()

            await conn.run_sync(lambda c: _run(c, _rev.downgrade))
            after = await conn.run_sync(_columns)

    assert cols >= _NEW
    assert (row[0], row[1], row[2], row[3]) == (0, 0, None, None)
    assert not (_NEW & after) and "amount" in after
