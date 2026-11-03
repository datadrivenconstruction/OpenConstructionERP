"""Revision vsci01 adds the SCIM columns and tables, and undoes them (up, down, up on PostgreSQL)."""

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


_rev = _load("vsci01_scim_provisioning")


def _run(sync_conn, direction) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        direction()


def _state(sync_conn) -> dict:
    insp = sa.inspect(sync_conn)
    tables = set(insp.get_table_names())
    cols = {c["name"] for c in insp.get_columns("oe_users_user")}
    out = {
        "user_cols": cols & {"external_id", "provisioned_by"},
        "unique_index": {i["name"] for i in insp.get_indexes("oe_users_user") if i["unique"]}
        & {"ix_oe_users_user_external_id"},
        "tables": tables & {"oe_scim_group", "oe_scim_group_member"},
    }
    if "oe_scim_group_member" in tables:
        out["member_fks"] = {
            (f["referred_table"], f["options"].get("ondelete")) for f in insp.get_foreign_keys("oe_scim_group_member")
        }
        out["member_pk"] = set(insp.get_pk_constraint("oe_scim_group_member")["constrained_columns"])
        out["group_unique"] = {tuple(u["column_names"]) for u in insp.get_unique_constraints("oe_scim_group")}
    return out


async def test_revision_chains_onto_the_assistant_revision() -> None:
    assert _rev.revision == "vsci01_scim_provisioning"
    assert _rev.down_revision == "vpar01_partner_api_keys_webhooks"


async def test_upgrade_downgrade_upgrade_on_postgres() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: _run(c, _rev.downgrade))
            gone = await conn.run_sync(_state)
            assert gone["user_cols"] == set() and gone["tables"] == set() and gone["unique_index"] == set()

            await conn.run_sync(lambda c: _run(c, _rev.upgrade))
            up = await conn.run_sync(_state)
            assert up["user_cols"] == {"external_id", "provisioned_by"}
            assert up["unique_index"] == {"ix_oe_users_user_external_id"}
            assert up["tables"] == {"oe_scim_group", "oe_scim_group_member"}
            assert up["member_fks"] == {("oe_scim_group", "CASCADE"), ("oe_users_user", "CASCADE")}
            assert up["member_pk"] == {"group_id", "user_id"}
            assert {("external_id",), ("display_name",)} <= up["group_unique"]

            await conn.run_sync(lambda c: _run(c, _rev.upgrade))  # idempotent
            await conn.run_sync(lambda c: _run(c, _rev.downgrade))
            await conn.run_sync(lambda c: _run(c, _rev.upgrade))
            assert (await conn.run_sync(_state)) == up
