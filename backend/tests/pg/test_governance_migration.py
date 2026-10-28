# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Revision v68 builds exactly the schema the governance models build, and undoes it.

Up, down, up on PostgreSQL; the reflected schema from the revision must equal
the one ``create_all`` produces from the models (columns with types,
nullability and server defaults, the column lists of indexes and unique
constraints, and for each foreign key its columns, its target and its delete
rule), so a fresh install and an upgraded one cannot drift.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.project_governance import models as gm
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

_MODELS = (
    gm.GovernanceCatalogue,
    gm.GovernanceCatalogueVersion,
    gm.GovernanceModel,
    gm.GovernanceArea,
    gm.GovernanceGate,
    gm.GovernanceDocument,
    gm.GovernanceCheck,
    gm.GovernanceDecision,
    gm.GovernanceCondition,
    gm.GovernanceChangeRequest,
)
TABLES = [m.__tablename__ for m in _MODELS]
_PARTS = ("columns", "primary_key", "indexes", "unique", "fks")


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load("v68_project_governance")


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
            "primary_key": inspector.get_pk_constraint(table).get("constrained_columns"),
            # ``app.core.pg_optimizations`` adds ``ix_oe_governance_<table>_project_id...``
            # on every create_all; no revision in the tree reproduces those, so
            # only the indexes this module declares (``ix_oe_gov_*``) are compared.
            "indexes": {
                i["name"]: (list(i["column_names"]), bool(i.get("unique")))
                for i in inspector.get_indexes(table)
                if i.get("name") and not i["name"].startswith("ix_oe_governance_")
            },
            "unique": {
                u["name"]: list(u["column_names"]) for u in inspector.get_unique_constraints(table) if u.get("name")
            },
            "fks": {
                f["name"]: (
                    list(f["constrained_columns"]),
                    f["referred_table"],
                    list(f["referred_columns"]),
                    (f.get("options") or {}).get("ondelete"),
                )
                for f in inspector.get_foreign_keys(table)
            },
        }
    return out


async def _drop_all(conn) -> None:
    for table in reversed(TABLES):
        await conn.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))


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
        for key in _PARTS:
            assert first[table][key] == from_models[table][key], (table, key)
            assert second[table][key] == from_models[table][key], (table, key)
    # The comparison read something: an empty reflection on both sides would compare equal.
    assert sum(len(from_models[t]["fks"]) for t in TABLES) >= 8
    assert sum(len(from_models[t]["indexes"]) for t in TABLES) >= 8
    assert from_models["oe_governance_gate"]["columns"]["created_at"][2] is not None
    assert all(from_models[t]["primary_key"] == ["id"] for t in TABLES)


async def test_revision_leaves_a_create_all_schema_alone_and_completes_a_partial_one() -> None:
    """The revision reaches databases ``create_all`` already built, whole or in part.

    Over a complete schema it changes nothing. Over one that lost a table and
    an index it creates exactly those again, each guard deciding per object.
    """
    lost_table = TABLES[-1]
    lost_index = "ix_oe_gov_catalogue_tenant"
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            before = await conn.run_sync(_reflect)
            await conn.run_sync(_run, _rev.upgrade)
            untouched = await conn.run_sync(_reflect)
        assert lost_index in before["oe_governance_catalogue"]["indexes"]
        async with engine.begin() as conn:
            await conn.execute(sa.text(f"DROP TABLE {lost_table} CASCADE"))
            await conn.execute(sa.text(f"DROP INDEX {lost_index}"))
            partial = await conn.run_sync(_reflect)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.upgrade)
            completed = await conn.run_sync(_reflect)

    assert lost_table not in partial["tables"]
    assert lost_index not in partial["oe_governance_catalogue"]["indexes"]
    for table in TABLES:
        for key in _PARTS:
            assert untouched[table][key] == before[table][key], (table, key)
            assert completed[table][key] == before[table][key], (table, key)
