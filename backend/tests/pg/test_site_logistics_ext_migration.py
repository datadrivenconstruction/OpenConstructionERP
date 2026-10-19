# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Revision v78 builds exactly the schema the site-logistics models build, and undoes it.

Up, down, up on PostgreSQL for the fifteen new tables and the nullable columns
added to the gate, laydown zone and delivery tables. The reflected schema from
the revision must equal the one ``create_all`` produces (columns with types and
nullability, module indexes, unique constraints, foreign keys), so a fresh
install and an upgraded one cannot drift. Down must leave the three existing
tables exactly as they were before the extension.

v98 adds the two link keys v78 left out (zone to area, delivery to transport),
so the chain compared with the models is v78 then v98, and down runs v98 first.
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


_v78 = _load("v78_site_logistics_ext")
_v98 = _load("v98_site_logistics_link_keys")


class _Chain:
    """v78 and the revision that adds its two link keys, run as one step."""

    _TABLES = _v78._TABLES
    _EXTEND = _v78._EXTEND

    @staticmethod
    def upgrade() -> None:
        _v78.upgrade()
        _v98.upgrade()

    @staticmethod
    def downgrade() -> None:
        _v98.downgrade()
        _v78.downgrade()


_rev = _Chain
NEW_TABLES = [t for t, _c, _i in _rev._TABLES]
EXTENDED = sorted({t for t, _c, _f, _i in _rev._EXTEND})
ADDED = {(t, c().name) for t, c, _f, _i in _rev._EXTEND}
ALL = NEW_TABLES + EXTENDED


def _run(sync_conn, direction) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        direction()


# ``app.core.pg_optimizations`` adds ``ix_<table>_<columns>`` on every create_all and no
# revision reproduces those. The module names its own indexes ``ix_oe_site_<short>``; the
# extension's two column indexes are compared by their exact names.
_EXTEND_INDEXES = {ix for _t, _c, _f, ix in _rev._EXTEND if ix}


def _ours(name: str | None) -> bool:
    if not name:
        return False
    if name in _EXTEND_INDEXES or name.startswith("uq_oe_site_"):
        return True
    return name.startswith("ix_oe_site_") and not name.startswith("ix_oe_site_logistics_")


def _predicate(index: dict) -> str:
    where = (index.get("dialect_options") or {}).get("postgresql_where")
    return "" if where is None else str(where).replace("(", "").replace(")", "").strip().lower()


def _reflect(sync_conn) -> dict:
    """Everything the revision has to reproduce: names AND what they are made of."""
    inspector = sa.inspect(sync_conn)
    tables = set(inspector.get_table_names())
    out: dict = {"tables": tables}
    for table in ALL:
        if table not in tables:
            continue
        out[table] = {
            "columns": {c["name"]: (str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)},
            "indexes": {
                (i["name"], tuple(i["column_names"]), bool(i.get("unique")), _predicate(i))
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
            "defaults": {c["name"]: c.get("default") for c in inspector.get_columns(table)},
        }
    return out


async def test_revision_reproduces_the_model_schema_up_down_up() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            from_models = await conn.run_sync(_reflect)
        assert set(ALL) <= from_models["tables"]
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

    for snapshot in (down, down_again):
        assert not set(NEW_TABLES) & snapshot["tables"]
        for table in EXTENDED:
            assert table in snapshot["tables"]
            left = {(table, c) for c in snapshot[table]["columns"]} & ADDED
            assert not left, left
    assert down == down_again
    for table in ALL:
        for key in ("columns", "indexes", "unique", "fks"):
            assert first[table][key] == from_models[table][key], (table, key)
            assert second[table][key] == from_models[table][key], (table, key)
        # Server defaults exist only on the revision side (the ORM supplies the same
        # values itself), so they are compared between the two upgrades.
        assert first[table]["defaults"] == second[table]["defaults"], table
    plant = [
        i for i in first["oe_site_logistics_media_demand"]["indexes"] if i[0] == "uq_oe_site_demand_plant_position"
    ]
    assert plant == [
        (
            "uq_oe_site_demand_plant_position",
            ("project_id", "site_plant_position_id"),
            True,
            "site_plant_position_id is not null",
        )
    ]


async def test_revision_is_a_no_op_over_a_create_all_schema() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            before = await conn.run_sync(_reflect)
            await conn.run_sync(_run, _rev.upgrade)
            after = await conn.run_sync(_reflect)
    for table in ALL:
        assert after[table] == before[table], table


async def test_downgrade_removes_every_new_column_and_index_it_added() -> None:
    """The reflection really sees columns and index bodies: a renamed column would fail here."""
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            built = await conn.run_sync(_reflect)
    concept = built["oe_site_logistics_concept"]["columns"]
    assert concept["site_timezone"] == ("VARCHAR(64)", True)
    transport = built["oe_site_logistics_transport"]["columns"]
    assert transport["in_transit_on"] == ("DATE", True)
    assert transport["load_class"] == ("VARCHAR(40)", True)
    assert built["oe_site_logistics_delivery"]["columns"]["flow_code"] == ("VARCHAR(40)", True)
    stage = built["oe_site_logistics_stage"]["columns"]
    assert stage["plan_metres_per_pixel"] == ("NUMERIC(12, 6)", True)
    assert stage["plan_document_id"][1] is True
    assert stage["plan_origin_px"][1] is True
    assert built["oe_site_logistics_customs_line"]["columns"]["currency"] == ("VARCHAR(3)", True)
    assert ("uq_oe_site_concept_project", ("project_id",)) in built["oe_site_logistics_concept"]["unique"]
