# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Revision v71 builds exactly the schema the plant register models build (and the site plant extension), and undoes it.

Up, down, up on PostgreSQL; the reflected schema from the revision must equal
the one ``create_all`` produces from the models, so a fresh install and an
upgraded one cannot drift.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.plant_register.models import ALL_MODELS
from app.modules.site_logistics.models import SitePlantPosition
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

TABLES = [m.__tablename__ for m in ALL_MODELS] + [SitePlantPosition.__tablename__]
# ``app.core.pg_optimizations`` adds ``ix_<table>_<cols>`` on every create_all and no
# revision reproduces them; compare only the names this module writes out.
_AUTO_PREFIXES = tuple(f"ix_{t}_" for t in TABLES)


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load("v71_plant_register")


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
            "columns": {
                c["name"]: (str(c["type"]), c["nullable"], c.get("default")) for c in inspector.get_columns(table)
            },
            "indexes": {
                (
                    i["name"],
                    bool(i.get("unique")),
                    tuple(i.get("column_names") or ()),
                    (i.get("dialect_options") or {}).get("postgresql_where"),
                )
                for i in inspector.get_indexes(table)
                if i.get("name") and not i["name"].startswith(_AUTO_PREFIXES)
            },
            "unique": {u["name"] for u in inspector.get_unique_constraints(table) if u.get("name")},
            "fks": {(f["name"], (f.get("options") or {}).get("ondelete")) for f in inspector.get_foreign_keys(table)},
        }
    return out


async def _drop_all(conn) -> None:
    for table in reversed(TABLES):
        await conn.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))


def test_revision_branches_from_governance() -> None:
    assert _rev.revision == "v71_plant_register"
    assert _rev.down_revision == "v73_permits"


async def test_revision_reproduces_the_model_schema_up_down_up() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            from_models = await conn.run_sync(_reflect)
        assert set(TABLES) <= from_models["tables"]
        assert ("uq_oe_plant_quote_basis", True, ("plant_item_id",), "is_basis") in (
            from_models["oe_plant_lead_time_quote"]["indexes"]
        )
        # A raw insert gets the same defaults as an ORM one, on a fresh install and on an upgraded one.
        item_columns = from_models["oe_plant_item"]["columns"]
        assert item_columns["status"][2] == "'identified'::character varying"
        assert item_columns["quantity"][2] == "'1'::numeric"
        assert from_models["oe_plant_lead_time_quote"]["columns"]["is_basis"][2] == "false"
        for table in ("lead_time_quote", "slot_reservation", "decision_paper", "delivery_limit", "spare_part"):
            names = {i[0]: i[2] for i in from_models[f"oe_plant_{table}"]["indexes"]}
            assert ("project_id",) in names.values(), table
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
