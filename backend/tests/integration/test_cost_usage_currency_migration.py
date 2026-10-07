"""Legacy usage amounts keep an unknown currency through the additive migration."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from tests._pg import transactional_session


@pytest.mark.asyncio
async def test_currency_migration_preserves_history_and_is_idempotent(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/v57_cost_usage_currency.py"
    spec = importlib.util.spec_from_file_location("usage_currency_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "v56_punch_contract_scope"
    table = f"usage_migration_{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(migration, "_TABLE", table)
    async with transactional_session() as session:

        def check(sync_session):
            connection = sync_session.connection()
            connection.execute(
                text(f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY, unit_rate_at_use NUMERIC(18,4) NOT NULL)')
            )
            connection.execute(text(f"INSERT INTO \"{table}\" VALUES ('legacy', 17.1250)"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            migration.upgrade()
            row = connection.execute(text(f'SELECT unit_rate_at_use, currency_at_use FROM "{table}"')).one()
            assert str(row[0]) == "17.1250"
            assert row[1] is None
            column = next(c for c in inspect(connection).get_columns(table) if c["name"] == "currency_at_use")
            assert column["nullable"] is True
            assert column["default"] is None
            connection.execute(text(f"INSERT INTO \"{table}\" VALUES ('new', 17.1250, 'KWD')"))
            migration.upgrade()
            assert (
                connection.execute(text(f"SELECT currency_at_use FROM \"{table}\" WHERE id='new'")).scalar_one()
                == "KWD"
            )
            migration.downgrade()
            migration.downgrade()
            assert "currency_at_use" not in {c["name"] for c in inspect(connection).get_columns(table)}
            assert connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one() == 2

        await session.run_sync(check)
