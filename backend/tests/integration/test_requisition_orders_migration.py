# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The requisition orders revision adds its columns and tables, runs twice, and can be undone.

Runs on PostgreSQL (the suite's database) and on a throwaway SQLite file, the
two engines an install meets.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect

from tests._pg import transactional_session

_PATH = Path(__file__).resolve().parents[2] / "alembic/versions/v96_requisition_orders_approvals_feed.py"
_TABLES = ("oe_procurement_project_settings", "oe_procurement_req_ext_line", "oe_procurement_req_change")
_COLUMNS = {"order_owner", "approval_chain", "approval_step", "row_version", "client_request_id"}


def _load():
    spec = importlib.util.spec_from_file_location("requisition_orders_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _walk(migration, connection, monkeypatch) -> None:
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))

    def tables() -> set[str]:
        return set(inspect(connection).get_table_names())

    def req_columns() -> set[str]:
        return {c["name"] for c in inspect(connection).get_columns("oe_procurement_requisition")}

    migration.upgrade()
    migration.upgrade()
    assert set(_TABLES) <= tables()
    assert req_columns() >= _COLUMNS
    migration.downgrade()
    assert not set(_TABLES) & tables()
    assert not _COLUMNS & req_columns()
    migration.downgrade()
    migration.upgrade()
    assert set(_TABLES) <= tables()
    assert req_columns() >= _COLUMNS
    uniques = {u["name"] for u in inspect(connection).get_unique_constraints("oe_procurement_req_ext_line")}
    assert "uq_procurement_req_ext_line_key" in uniques
    indexes = {i["name"] for i in inspect(connection).get_indexes("oe_procurement_req_change")}
    assert "ix_procurement_req_change_cursor" in indexes
    req_indexes = {i["name"] for i in inspect(connection).get_indexes("oe_procurement_requisition")}
    assert "ix_oe_procurement_requisition_client_request_id" in req_indexes
    _matches_the_models(connection)


def _matches_the_models(connection) -> None:
    """Every model column of the new tables exists with the same nullability, and nothing more."""
    from app.modules.procurement import models

    for table in (
        models.ProcurementProjectSettings.__table__,
        models.RequisitionExternalOrderLine.__table__,
        models.RequisitionChange.__table__,
    ):
        migrated = {c["name"]: c for c in inspect(connection).get_columns(table.name)}
        assert set(migrated) == {c.name for c in table.columns}, table.name
        for column in table.columns:
            assert migrated[column.name]["nullable"] == column.nullable, (table.name, column.name)
    migrated = {c["name"]: c for c in inspect(connection).get_columns("oe_procurement_requisition")}
    for name in _COLUMNS:
        assert migrated[name]["nullable"] is True, name


def test_the_revision_chains_after_the_payment_release() -> None:
    migration = _load()
    assert migration.revision == "v96_requisition_orders_approvals_feed"
    assert migration.down_revision == "v95_costmodel_forecast_documentation"


@pytest.mark.asyncio
async def test_upgrade_and_downgrade_on_postgresql(monkeypatch) -> None:
    migration = _load()
    async with transactional_session(disable_fks=True) as session:
        await session.run_sync(lambda s: _walk(migration, s.connection(), monkeypatch))


def test_upgrade_and_downgrade_on_sqlite(monkeypatch, tmp_path) -> None:
    migration = _load()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'requisition.db'}")
    with engine.begin() as connection:
        # The two tables the revision alters or points its foreign keys at.
        connection.execute(sa.text("CREATE TABLE oe_procurement_requisition (id CHAR(32) PRIMARY KEY, title TEXT)"))
        connection.execute(sa.text("CREATE TABLE oe_procurement_req_item (id CHAR(32) PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO oe_procurement_requisition (id, title) VALUES ('a', 'kept')"))
        _walk(migration, connection, monkeypatch)
        kept = connection.execute(sa.text("SELECT title FROM oe_procurement_requisition")).scalar_one()
        assert kept == "kept", "dropping the columns keeps the rows"
    engine.dispose()
