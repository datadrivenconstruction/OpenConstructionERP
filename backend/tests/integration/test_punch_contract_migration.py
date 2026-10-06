"""The optional contract link upgrades legacy rows without assigning their money."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from tests._pg import transactional_session


@pytest.mark.asyncio
async def test_contract_link_migration_is_idempotent_nullable_and_reversible(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/v56_punch_contract_scope.py"
    spec = importlib.util.spec_from_file_location("punch_contract_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    table = f"punch_migration_{uuid.uuid4().hex[:12]}"
    index = f"ix_{table}_contract_id"
    monkeypatch.setattr(migration, "_TABLE", table)
    monkeypatch.setattr(migration, "_INDEX", index)

    async with transactional_session() as session:

        def check(sync_session):
            connection = sync_session.connection()
            connection.execute(text(f'CREATE TABLE "{table}" (id VARCHAR(36) PRIMARY KEY, title TEXT NOT NULL)'))
            connection.execute(
                text(f'INSERT INTO "{table}" (id, title) VALUES (:id, :title)'), {"id": "old", "title": "Old snag"}
            )
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            migration.upgrade()
            row = connection.execute(text(f'SELECT title, contract_id FROM "{table}"')).one()
            assert row == ("Old snag", None)
            columns = {column["name"]: column for column in inspect(connection).get_columns(table)}
            assert columns["contract_id"]["nullable"] is True
            assert index in {item["name"] for item in inspect(connection).get_indexes(table)}
            migration.downgrade()
            migration.downgrade()
            assert "contract_id" not in {column["name"] for column in inspect(connection).get_columns(table)}
            assert connection.execute(text(f'SELECT title FROM "{table}"')).scalar_one() == "Old snag"
            migration.upgrade()
            assert connection.execute(text(f'SELECT contract_id FROM "{table}"')).scalar_one() is None

        await session.run_sync(check)
