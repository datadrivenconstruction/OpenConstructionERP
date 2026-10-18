# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The payment release revision adds its three tables, runs twice, and can be undone.

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

_PATH = Path(__file__).resolve().parents[2] / "alembic/versions/v94_payment_release.py"
_TABLES = ("oe_payment_release_terms", "oe_payment_release_invoice", "oe_payment_release_posting")


def _load():
    spec = importlib.util.spec_from_file_location("payment_release_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _walk(migration, connection, monkeypatch) -> None:
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))

    def tables() -> set[str]:
        return set(inspect(connection).get_table_names())

    migration.upgrade()
    migration.upgrade()
    assert set(_TABLES) <= tables()
    migration.downgrade()
    assert not set(_TABLES) & tables()
    migration.downgrade()
    migration.upgrade()
    assert set(_TABLES) <= tables()
    uniques = {u["name"] for u in inspect(connection).get_unique_constraints("oe_payment_release_invoice")}
    assert "uq_payment_release_invoice_invoice" in uniques
    indexes = {i["name"] for i in inspect(connection).get_indexes("oe_payment_release_posting")}
    assert "ix_oe_payment_release_posting_contract_id" in indexes
    _matches_the_models(connection)


def _matches_the_models(connection) -> None:
    """Every model column exists in the migrated table with the same nullability, and nothing more."""
    from app.modules.payment_release import models

    for table in (models.PaymentTerms.__table__, models.InvoiceRelease.__table__, models.RetentionPosting.__table__):
        migrated = {c["name"]: c for c in inspect(connection).get_columns(table.name)}
        assert set(migrated) == {c.name for c in table.columns}, table.name
        for column in table.columns:
            assert migrated[column.name]["nullable"] == column.nullable, (table.name, column.name)


def test_the_revision_chains_after_the_cost_inheritance() -> None:
    migration = _load()
    assert migration.revision == "v94_payment_release"
    assert migration.down_revision == "v93_costmodel_cost_inheritance"


@pytest.mark.asyncio
async def test_upgrade_and_downgrade_on_postgresql(monkeypatch) -> None:
    migration = _load()
    async with transactional_session(disable_fks=True) as session:
        await session.run_sync(lambda s: _walk(migration, s.connection(), monkeypatch))


def test_upgrade_and_downgrade_on_sqlite(monkeypatch, tmp_path) -> None:
    migration = _load()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'release.db'}")
    with engine.begin() as connection:
        # The two tables the revision's foreign keys point at.
        connection.execute(sa.text("CREATE TABLE oe_projects_project (id CHAR(32) PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE oe_contracts_contract (id CHAR(32) PRIMARY KEY)"))
        _walk(migration, connection, monkeypatch)
    engine.dispose()
