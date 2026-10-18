# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The forecast documentation revision adds its tables and columns, runs twice, and can be undone.

Runs on PostgreSQL (the suite's database) and on a throwaway SQLite file, the
two engines an install meets. A snapshot saved before the revision reads as
frozen after it, and survives the way back down.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect

from tests._pg import transactional_session

_PATH = Path(__file__).resolve().parents[2] / "alembic/versions/v95_costmodel_forecast_documentation.py"
_TABLES = (
    "oe_costmodel_cost_control_settings",
    "oe_costmodel_forecast_method",
    "oe_costmodel_forecast_snapshot_note",
)
_COLUMNS = {"status", "frozen_at", "frozen_by", "previous_snapshot_id", "meta"}
_SNAP = "oe_costmodel_forecast_snapshot"


def _load():
    spec = importlib.util.spec_from_file_location("forecast_documentation_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _walk(migration, connection, monkeypatch, snapshot_id: str) -> None:
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))

    def tables() -> set[str]:
        return set(inspect(connection).get_table_names())

    def columns() -> set[str]:
        return {c["name"] for c in inspect(connection).get_columns(_SNAP)}

    migration.upgrade()
    migration.upgrade()
    assert set(_TABLES) <= tables()
    assert columns() >= _COLUMNS
    status = connection.execute(sa.text(f"SELECT status FROM {_SNAP} WHERE id = :id"), {"id": snapshot_id}).scalar()
    assert status == "frozen"
    migration.downgrade()
    assert not set(_TABLES) & tables()
    assert not _COLUMNS & columns()
    assert connection.execute(sa.text(f"SELECT count(*) FROM {_SNAP}")).scalar() == 1
    migration.downgrade()
    migration.upgrade()
    assert set(_TABLES) <= tables()
    uniques = {u["name"] for u in inspect(connection).get_unique_constraints("oe_costmodel_forecast_snapshot_note")}
    assert "uq_costmodel_snapshot_note_row" in uniques
    indexes = {i["name"] for i in inspect(connection).get_indexes("oe_costmodel_forecast_method")}
    assert "ix_oe_costmodel_forecast_method_project_id" in indexes


def test_the_revision_chains_after_payment_release() -> None:
    migration = _load()
    assert migration.revision == "v95_costmodel_forecast_documentation"
    assert migration.down_revision == "v94_payment_release"


@pytest.mark.asyncio
async def test_upgrade_and_downgrade_on_postgresql(monkeypatch) -> None:
    migration = _load()
    async with transactional_session(disable_fks=True) as session:

        def run(sync_session) -> None:
            connection = sync_session.connection()
            # The suite's schema is built from the models: take the snapshot table back to before the revision.
            for table in _TABLES:
                connection.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            for column in _COLUMNS:
                connection.execute(sa.text(f"ALTER TABLE {_SNAP} DROP COLUMN IF EXISTS {column}"))
            snapshot_id = str(uuid.uuid4())
            connection.execute(
                sa.text(
                    f"INSERT INTO {_SNAP} (id, project_id, taken_on, created_at, updated_at) "
                    "VALUES (:id, :pid, '2026-09-30', now(), now())"
                ),
                {"id": snapshot_id, "pid": str(uuid.uuid4())},
            )
            _walk(migration, connection, monkeypatch, snapshot_id)

        await session.run_sync(run)


def test_upgrade_and_downgrade_on_sqlite(monkeypatch, tmp_path) -> None:
    migration = _load()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'forecast.db'}")
    snapshot_id = uuid.uuid4().hex
    with engine.begin() as connection:
        # The tables the revision's foreign keys point at, and the snapshot table as it stood before.
        connection.execute(sa.text("CREATE TABLE oe_projects_project (id CHAR(32) PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE oe_costmodel_cost_line (id CHAR(32) PRIMARY KEY)"))
        connection.execute(
            sa.text(
                f"CREATE TABLE {_SNAP} (id CHAR(32) PRIMARY KEY, project_id CHAR(32) NOT NULL, "
                "taken_on VARCHAR(10) NOT NULL, stage VARCHAR(30) NOT NULL DEFAULT 'forecast', "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        connection.execute(
            sa.text(f"INSERT INTO {_SNAP} (id, project_id, taken_on) VALUES (:id, :pid, '2026-09-30')"),
            {"id": snapshot_id, "pid": uuid.uuid4().hex},
        )
        _walk(migration, connection, monkeypatch, snapshot_id)
    engine.dispose()
