# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``v3267_saved_views_team_share`` runs, reverses and re-runs on PostgreSQL.

Every other test in this directory builds its schema through
``Base.metadata.create_all``, so none of them executes a single line of the
migration. "Idempotent" and "has a real downgrade" would therefore stay claims
rather than results, and the three CHECK constraints go in as raw ``ALTER
TABLE`` strings that PostgreSQL would only parse the first time somebody
actually migrated a database.

The cycle run here is stamp-behind, upgrade, downgrade, upgrade:

1. A throwaway database cloned from the schema template already carries
   everything the migration adds, because ``create_all`` built it. Stamping it
   one revision behind and upgrading has to change nothing - that is the
   idempotency claim, tested against exactly the schema a fresh install has.
2. Downgrading has to remove the column, its index, its foreign key and the
   three constraints, and leave the rest of the table alone.
3. Upgrading again has to put them back through the raw DDL path, under the
   same names ``create_all`` produces. A name that only matches one of the two
   routes into this schema is a constraint nobody can drop.

The constraints are then shown to reject the rows they exist to reject, so a
constraint that was created but written wrong cannot pass as a working one.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

REVISION = "v3267_saved_views_team_share"
DOWN_REVISION = "v3266_credentials_requirements"
VIEW_TABLE = "oe_saved_views_view"
RUN_TABLE = "oe_saved_views_run"

BACKEND_DIR = Path(__file__).resolve().parents[3]

#: An arbitrary but valid id, reused for every column of a rejected row.
PROBE_ID = "00000000-0000-0000-0000-0000000004e7"


def _sync_url(async_url: str) -> str:
    """The psycopg2 form of an asyncpg URL."""
    return async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


def _run_alembic(args: list[str], async_url: str) -> None:
    """Run one alembic command against ``async_url`` in a child process.

    Alembic resolves its target from the settings, which are cached per process
    and were built for the shared test database. A child process with its own
    environment is the honest way to point it somewhere else.

    Args:
        args: Command line after ``alembic``, e.g. ``["upgrade", REVISION]``.
        async_url: Throwaway database to migrate.

    Raises:
        AssertionError: The command exited non-zero.
    """
    env = dict(os.environ)
    env["DATABASE_URL"] = async_url
    env["DATABASE_SYNC_URL"] = _sync_url(async_url)
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"alembic {' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}"


def _schema_snapshot(engine: Any) -> dict[str, set[str]]:
    """Columns, CHECK constraints, foreign keys and indexes this migration owns."""
    with engine.connect() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
                {"t": VIEW_TABLE},
            )
        }
        checks = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT con.conname FROM pg_constraint con "
                    "JOIN pg_class rel ON rel.oid = con.conrelid "
                    "WHERE rel.relname = ANY(:tables) AND con.contype = 'c'"
                ),
                {"tables": [VIEW_TABLE, RUN_TABLE]},
            )
        }
        foreign_keys = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT con.conname FROM pg_constraint con "
                    "JOIN pg_class rel ON rel.oid = con.conrelid "
                    "WHERE rel.relname = :t AND con.contype = 'f'"
                ),
                {"t": VIEW_TABLE},
            )
        }
        indexes = {
            row[0]
            for row in conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = :t"),
                {"t": VIEW_TABLE},
            )
        }
    return {"columns": columns, "checks": checks, "foreign_keys": foreign_keys, "indexes": indexes}


def _seed_owner(engine: Any) -> None:
    """Insert the user every probe row points at.

    A saved view carries a real ``owner_id`` foreign key, so a row that is meant
    to be refused by a CHECK constraint would otherwise be refused by that key
    first and prove nothing about the constraint under test.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO oe_users_user "
                "(id, email, hashed_password, full_name, role, locale, is_active, created_at, updated_at) "
                "VALUES (:id, :email, 'not-a-real-hash', 'Migration Probe', 'admin', 'en', true, now(), now())"
            ),
            {"id": PROBE_ID, "email": f"saved-views-migration-{PROBE_ID}@test.io"},
        )


def _is_rejected(engine: Any, statement: str) -> bool:
    """Whether PostgreSQL refuses ``statement`` with a CHECK violation."""
    try:
        with engine.begin() as conn:
            conn.execute(text(statement))
    except Exception as exc:  # noqa: BLE001 - any other failure is not a pass
        return "violates check constraint" in str(exc)
    return False


@pytest.fixture
def migrated():
    """A throwaway database plus a sync engine on it, dropped on the way out."""
    from tests._pg import isolated_database_url

    with isolated_database_url() as async_url:
        engine = create_engine(_sync_url(async_url), future=True)
        try:
            yield async_url, engine
        finally:
            engine.dispose()


def test_the_migration_reverses_and_replays_onto_the_same_schema(migrated) -> None:
    """Up over a create_all schema is a no-op; down then up rebuilds it exactly."""
    async_url, engine = migrated

    from_create_all = _schema_snapshot(engine)
    assert "shared_team_id" in from_create_all["columns"]

    _run_alembic(["stamp", DOWN_REVISION], async_url)
    _run_alembic(["upgrade", REVISION], async_url)
    assert _schema_snapshot(engine) == from_create_all, (
        "the upgrade altered a schema that already had everything it adds"
    )

    _run_alembic(["downgrade", DOWN_REVISION], async_url)
    after_downgrade = _schema_snapshot(engine)
    assert "shared_team_id" not in after_downgrade["columns"]
    assert f"ck_{VIEW_TABLE}_share_scope" not in after_downgrade["checks"]
    assert f"ck_{VIEW_TABLE}_team_pin_scope" not in after_downgrade["checks"]
    assert f"ck_{RUN_TABLE}_outcome" not in after_downgrade["checks"]
    # Everything else on the table survives: a downgrade that took the module's
    # own columns with it would be a data-loss bug, not a reversal.
    assert {"owner_id", "project_id", "entity_type", "name", "spec", "share_scope"} <= after_downgrade["columns"]

    _run_alembic(["upgrade", REVISION], async_url)
    assert _schema_snapshot(engine) == from_create_all, (
        "the migration and create_all disagree about the finished schema"
    )


def test_the_constraints_reject_what_they_were_added_to_reject(migrated) -> None:
    """A constraint that exists under the right name may still be written wrong."""
    _, engine = migrated
    _seed_owner(engine)

    assert _is_rejected(
        engine,
        f"INSERT INTO {VIEW_TABLE} "
        "(id, owner_id, entity_type, name, spec, share_scope, is_pinned, metadata, created_at, updated_at) "
        f"VALUES ('{PROBE_ID}', '{PROBE_ID}', 'project', 'Unknown scope', '{{}}', 'public', "
        "false, '{}', now(), now())",
    ), "share_scope accepted a value outside the four known scopes"

    assert _is_rejected(
        engine,
        f"INSERT INTO {VIEW_TABLE} "
        "(id, owner_id, entity_type, name, spec, share_scope, shared_team_id, is_pinned, metadata, "
        "created_at, updated_at) "
        f"VALUES ('{PROBE_ID}', '{PROBE_ID}', 'project', 'Pinned project share', '{{}}', 'project', "
        f"'{PROBE_ID}', false, '{{}}', now(), now())",
    ), "a team pin was accepted on a share that is not a team share"

    assert _is_rejected(
        engine,
        f"INSERT INTO {RUN_TABLE} "
        "(id, owner_id, entity_type, row_count, truncated, elapsed_ms, outcome, metadata, created_at, updated_at) "
        f"VALUES ('{PROBE_ID}', '{PROBE_ID}', 'project', 0, false, 0, 'exploded', '{{}}', now(), now())",
    ), "outcome accepted a value the module never writes"

    # The reverse of the team-pin rule is deliberately unconstrained: dropping a
    # team SET NULLs the pin and the row must stay legal with scope 'team'.
    with engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {VIEW_TABLE} "  # noqa: S608 - table name is a module constant
                "(id, owner_id, entity_type, name, spec, share_scope, shared_team_id, is_pinned, "
                "metadata, created_at, updated_at) "
                "VALUES (:id, :id, 'project', 'Team share that lost its team', '{}', 'team', "
                "NULL, false, '{}', now(), now())"
            ),
            {"id": PROBE_ID},
        )
