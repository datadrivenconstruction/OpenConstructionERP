"""Real PostgreSQL coverage, replay and conservative ownership of v58 indexes."""

import importlib.util
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine

from tests._pg import schema_inspection_engine


@pytest.fixture
def migration_case(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/v58_owner_list_indexes.py"
    spec = importlib.util.spec_from_file_location("owner_list_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "v57_cost_usage_currency"
    engine = schema_inspection_engine()
    table = f"owner_index_test_{uuid.uuid4().hex[:12]}"
    names = (f"ix_{table}_owner", f"ix_{table}_project")
    with engine.begin() as conn:
        conn.execute(sa.text(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, owner_id TEXT, project_id TEXT)'))
        conn.execute(sa.text(f"INSERT INTO \"{table}\" VALUES (1, 'alice', 'project')"))
    monkeypatch.setattr(migration, "_INDEXES", ((table, names[0], "owner_id"), (table, names[1], "project_id")))

    def run(direction):
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            monkeypatch.setattr(migration, "op", Operations(context))
            with context.begin_transaction():
                getattr(migration, direction)()

    try:
        yield migration, engine, table, names, run
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text(f'DROP TABLE "{table}"'))
        engine.dispose()


def test_upgrade_replay_downgrade_replay_preserve_data(migration_case):
    _migration, engine, table, names, run = migration_case
    run("upgrade")
    run("upgrade")
    with engine.connect() as conn:
        assert {entry["name"] for entry in sa.inspect(conn).get_indexes(table)} == set(names)
    run("downgrade")
    run("downgrade")
    with engine.connect() as conn:
        assert sa.inspect(conn).get_indexes(table) == []
        assert conn.execute(sa.text(f'SELECT * FROM "{table}"')).all() == [(1, "alice", "project")]


@pytest.mark.parametrize("same_name", [False, True])
def test_preexisting_user_index_is_not_adopted_or_removed(migration_case, same_name):
    _migration, engine, table, names, run = migration_case
    user_name = names[0] if same_name else f"custom_{table}"
    columns = "owner_id" if same_name else "owner_id, project_id"
    with engine.begin() as conn:
        conn.execute(sa.text(f'CREATE INDEX "{user_name}" ON "{table}" ({columns})'))
        conn.execute(sa.text(f"COMMENT ON INDEX \"{user_name}\" IS 'user managed'"))
    run("upgrade")
    run("upgrade")
    with engine.connect() as conn:
        assert {entry["name"] for entry in sa.inspect(conn).get_indexes(table)} == {user_name, names[1]}
    run("downgrade")
    with engine.connect() as conn:
        assert {entry["name"] for entry in sa.inspect(conn).get_indexes(table)} == {user_name}
        assert (
            conn.scalar(sa.text("SELECT obj_description(to_regclass(:name), 'pg_class')"), {"name": user_name})
            == "user managed"
        )


def test_conflicting_name_does_not_overwrite_user_index(migration_case):
    _migration, engine, table, names, run = migration_case
    with engine.begin() as conn:
        conn.execute(sa.text(f'CREATE INDEX "{names[0]}" ON "{table}" (id)'))
    with pytest.raises(RuntimeError, match="different definition"):
        run("upgrade")
    run("downgrade")
    with engine.connect() as conn:
        assert sa.inspect(conn).get_indexes(table)[0]["column_names"] == ["id"]


def test_missing_module_table_is_a_noop(migration_case, monkeypatch):
    migration, _engine, table, names, run = migration_case
    monkeypatch.setattr(migration, "_INDEXES", ((f"{table}_absent", names[0], "owner_id"),))
    run("upgrade")
    run("downgrade")


def test_invalid_user_index_fails_closed_without_dropping_it(migration_case):
    _migration, engine, table, names, run = migration_case
    with engine.begin() as conn:
        conn.execute(sa.text(f"INSERT INTO \"{table}\" VALUES (2, 'alice', 'other')"))
    # An interrupted/failed concurrent build leaves an INVALID index behind.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text(f'CREATE UNIQUE INDEX CONCURRENTLY "{names[0]}" ON "{table}" (owner_id)'))
    with pytest.raises(RuntimeError, match="Invalid index"):
        run("upgrade")
    run("downgrade")
    with engine.connect() as conn:
        assert (
            conn.scalar(
                sa.text("SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"), {"name": names[0]}
            )
            is False
        )


@pytest.mark.asyncio
async def test_boot_heal_adds_missing_plain_indexes_and_replays(migration_case):
    from app.core.postgres_migrator import postgres_auto_migrate

    _migration, engine, table, names, run = migration_case
    metadata = sa.MetaData()
    sa.Table(
        table,
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Text),
        sa.Column("project_id", sa.Text),
        sa.Index(names[0], "owner_id"),
        sa.Index(names[1], "project_id"),
    )
    async_engine = create_async_engine(engine.url.set(drivername="postgresql+asyncpg"))
    refused = []
    try:
        assert await postgres_auto_migrate(async_engine, SimpleNamespace(metadata=metadata), skipped=refused) >= 2
        assert await postgres_auto_migrate(async_engine, SimpleNamespace(metadata=metadata), skipped=refused) == 0
        assert refused == []
    finally:
        await async_engine.dispose()
    run("downgrade")  # boot-owned indexes were not created by the migration
    with engine.connect() as conn:
        assert {entry["name"] for entry in sa.inspect(conn).get_indexes(table)} == set(names)


def test_or_owner_filter_uses_both_indexes_on_populated_table(migration_case):
    _migration, engine, table, names, run = migration_case
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                f'INSERT INTO "{table}" SELECT n, (n % 1000)::text, (n % 999)::text FROM generate_series(2, 20000) AS n'
            )
        )
        conn.execute(sa.text(f'ANALYZE "{table}"'))
    query = f"EXPLAIN (ANALYZE, FORMAT JSON) SELECT id FROM \"{table}\" WHERE owner_id = '99' OR project_id = '88'"
    with engine.connect() as conn:
        before = conn.execute(sa.text(query)).scalar_one()[0]
    run("upgrade")
    with engine.connect() as conn:
        after = conn.execute(sa.text(query)).scalar_one()[0]
    plan = json.dumps(after["Plan"])
    assert "BitmapOr" in plan
    assert all(name in plan for name in names)
    assert before["Plan"]["Actual Rows"] == after["Plan"]["Actual Rows"]
    print(json.dumps({"rows": 20000, "before": before, "after": after}))


def test_model_indexes_match_migration_for_fresh_install():
    from app.modules.assemblies.models import Assembly
    from app.modules.pipelines.models import Pipeline
    from app.modules.webhook_leads.models import WebhookSource

    for model, column in (
        (Assembly, "owner_id"),
        (Pipeline, "created_by"),
        (WebhookSource, "created_by"),
        (WebhookSource, "project_id"),
    ):
        assert any(list(index.columns.keys()) == [column] for index in model.__table__.indexes)
