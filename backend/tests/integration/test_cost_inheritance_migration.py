# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The cost inheritance revision adds the split table and five columns, runs twice, and can be undone."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect

from tests._pg import transactional_session

_PATH = Path(__file__).resolve().parents[2] / "alembic/versions/v93_costmodel_cost_inheritance.py"

_ADDED = {
    "oe_bid_management_line_item": {"cost_line_id"},
    "oe_contracts_contract": {"cost_line_id"},
    "oe_changeorders_item": {"cost_line_id", "cost_line_source"},
    "oe_finance_invoice_item": {"contract_line_id"},
}


def _load():
    spec = importlib.util.spec_from_file_location("cost_inheritance_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_revision_chains_after_the_cost_structure() -> None:
    migration = _load()
    assert migration.revision == "v93_costmodel_cost_inheritance"
    assert migration.down_revision == "v92_costmodel_cost_structure"


@pytest.mark.asyncio
async def test_upgrade_is_idempotent_and_downgrade_removes_everything(monkeypatch) -> None:
    migration = _load()

    async with transactional_session(disable_fks=True) as session:

        def check(sync_session) -> None:
            connection = sync_session.connection()
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))

            def columns(table: str) -> set[str]:
                return {c["name"] for c in inspect(connection).get_columns(table)}

            # The schema of this lane already has everything: a second run must be a no-op.
            migration.upgrade()
            migration.upgrade()
            for table, added in _ADDED.items():
                assert added <= columns(table), table
            assert "oe_costmodel_line_allocation" in inspect(connection).get_table_names()

            migration.downgrade()
            for table, added in _ADDED.items():
                assert not added & columns(table), table
            assert "oe_costmodel_line_allocation" not in inspect(connection).get_table_names()
            migration.downgrade()

            migration.upgrade()
            for table, added in _ADDED.items():
                assert added <= columns(table), table
            indexes = {i["name"] for i in inspect(connection).get_indexes("oe_costmodel_line_allocation")}
            assert "ix_costmodel_line_alloc_source" in indexes
            uniques = {u["name"] for u in inspect(connection).get_unique_constraints("oe_costmodel_line_allocation")}
            assert "uq_costmodel_line_alloc_source_line" in uniques

        await session.run_sync(check)
