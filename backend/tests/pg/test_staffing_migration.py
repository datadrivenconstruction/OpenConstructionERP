# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Revision v77 builds exactly the schema the staffing models build, and undoes it.

Up, down, up on PostgreSQL; the reflected schema from the revision must equal
the one ``create_all`` produces from the models, so a fresh install and an
upgraded one cannot drift. The booking column it adds to accommodation is
checked the same way.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.pg_optimizations import _index_name
from app.modules.staffing.models import ALL_MODELS
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

TABLES = [m.__tablename__ for m in ALL_MODELS]
BOOKING = "oe_accommodation_booking"
BOOKING_IX = "ix_oe_accommodation_booking_roster_member_id"


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load("v77_staffing")
_DECLARED = {name for _table, _columns, indexes in _rev._TABLES for name, _cols in indexes}


def _compared(table: str, indexes: list[dict]) -> set[tuple[str, tuple[str, ...]]]:
    """The indexes of ``table`` the revision answers for, each with its columns.

    ``app.core.pg_optimizations`` adds indexes of its own on every create_all and no revision
    reproduces them. Left out: an index the revision does not declare whose name is exactly the one
    the hook gives those columns. Everything else is compared, so a stray index is a difference.
    """
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
    out["booking"] = (
        {c["name"]: (str(c["type"]), c["nullable"]) for c in inspector.get_columns(BOOKING)}.get("roster_member_id"),
        BOOKING_IX in {i["name"] for i in inspector.get_indexes(BOOKING)},
    )
    return out


async def _drop_all(conn) -> None:
    for table in reversed(TABLES):
        await conn.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))
    await conn.execute(sa.text(f"DROP INDEX IF EXISTS {BOOKING_IX}"))
    await conn.execute(sa.text(f"ALTER TABLE {BOOKING} DROP COLUMN IF EXISTS roster_member_id"))


def test_revision_names_a_parent_that_exists() -> None:
    assert _rev.revision == "v77_staffing"
    # Where the revision sits in the chain is decided when the branches are joined.
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    assert (versions / f"{_rev.down_revision}.py").exists(), _rev.down_revision


def test_only_an_index_under_the_hooks_own_name_is_left_out_of_the_comparison() -> None:
    table = "oe_staffing_position"
    declared = {"name": "ix_oe_staff_position_project", "column_names": ["project_id"]}
    hook = {"name": _index_name(table, ["project_id", "status"]), "column_names": ["project_id", "status"]}
    # The hook's columns under another name, and a name that merely looks like the hook's: both stray.
    renamed = {"name": "ix_oe_staff_position_by_status", "column_names": ["project_id", "status"]}
    lookalike = {"name": "ix_oe_staffing_position_extra", "column_names": ["title"]}
    assert _compared(table, [declared, hook, renamed, lookalike]) == {
        ("ix_oe_staff_position_project", ("project_id",)),
        ("ix_oe_staff_position_by_status", ("project_id", "status")),
        ("ix_oe_staffing_position_extra", ("title",)),
    }


async def test_revision_reproduces_the_model_schema_up_down_up() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            from_models = await conn.run_sync(_reflect)
        assert set(TABLES) <= from_models["tables"]
        assert from_models["booking"][0] is not None and from_models["booking"][1]
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
    assert down["booking"] == (None, False)
    for table in TABLES:
        for key in ("columns", "indexes", "unique", "fks"):
            assert first[table][key] == from_models[table][key], (table, key)
            assert second[table][key] == from_models[table][key], (table, key)
    assert first["booking"] == second["booking"] == from_models["booking"]


async def test_revision_is_a_no_op_over_a_create_all_schema() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            before = await conn.run_sync(_reflect)
            await conn.run_sync(_run, _rev.upgrade)
            after = await conn.run_sync(_reflect)
    for table in TABLES:
        assert after[table] == before[table]
    assert after["booking"] == before["booking"]
