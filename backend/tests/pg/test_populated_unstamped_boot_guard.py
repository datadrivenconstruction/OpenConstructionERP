"""MISC-14: refusing a guessed revision survives real PostgreSQL transactions.

Each case owns a new, empty database on the test session's cluster. No table in
the shared test schema is changed. The two-boot cases preserve both the missing
revision and the old data even after create_all has filled in missing tables.
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from app.core.alembic_version_table import database_is_populated_but_unstamped, stamp_head_if_unstamped

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def isolated_stamp_engine() -> Iterator[sa.Engine]:
    """Use a disposable database, never the cluster's shared application schema."""
    admin_url = make_url(os.environ["DATABASE_SYNC_URL"])
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    name = f"oe_test_unstamped_{uuid.uuid4().hex}"
    engine = sa.create_engine(admin_url.set(database=name))
    try:
        with admin.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
        try:
            yield engine
        finally:
            engine.dispose()
            with admin.connect() as conn:
                conn.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    finally:
        engine.dispose()
        admin.dispose()


def _current_schema() -> sa.MetaData:
    schema = sa.MetaData()
    sa.Table(
        "oe_legacy_item",
        schema,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("label", sa.String(100)),
        sa.Column("new_required_value", sa.Integer, nullable=False),
    )
    sa.Table("oe_new_item", schema, sa.Column("id", sa.Integer, primary_key=True))
    return schema


@pytest.mark.parametrize("empty_version_table", [False, True])
def test_refusal_preserves_unstamped_evidence_and_legacy_rows_across_two_boots(
    isolated_stamp_engine: sa.Engine, empty_version_table: bool, caplog: pytest.LogCaptureFixture
) -> None:
    with isolated_stamp_engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE oe_legacy_item (id INTEGER PRIMARY KEY, label VARCHAR(100))"))
        conn.execute(sa.text("INSERT INTO oe_legacy_item VALUES (1, 'keep me')"))
        if empty_version_table:
            conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))

    for _boot in range(2):
        with isolated_stamp_engine.begin() as conn:
            arrived = database_is_populated_but_unstamped(conn)
            assert arrived is True
            _current_schema().create_all(conn)
            assert stamp_head_if_unstamped(conn, refuse_when_populated=arrived) is None

        # A different connection reads the committed state, not uncommitted
        # writes in the transaction that just ran the guard.
        with isolated_stamp_engine.connect() as conn:
            inspector = sa.inspect(conn)
            assert inspector.has_table("oe_new_item")
            assert "new_required_value" not in {c["name"] for c in inspector.get_columns("oe_legacy_item")}
            assert conn.execute(sa.text("SELECT label FROM oe_legacy_item WHERE id = 1")).scalar_one() == "keep me"
            assert inspector.has_table("alembic_version") is empty_version_table
            if empty_version_table:
                assert conn.execute(sa.text("SELECT count(*) FROM alembic_version")).scalar_one() == 0
            assert database_is_populated_but_unstamped(conn) is True

    assert "Alembic head stamp REFUSED" in caplog.text
    assert "Run the migrations for this database rather than stamping it" in caplog.text


def test_a_fresh_database_can_still_be_stamped_after_schema_creation(isolated_stamp_engine: sa.Engine) -> None:
    with isolated_stamp_engine.begin() as conn:
        arrived = database_is_populated_but_unstamped(conn)
        assert arrived is False
        _current_schema().create_all(conn)
        assert stamp_head_if_unstamped(conn, refuse_when_populated=arrived)

    with isolated_stamp_engine.connect() as conn:
        assert database_is_populated_but_unstamped(conn) is False
        assert conn.execute(sa.text("SELECT count(*) FROM alembic_version")).scalar_one() >= 1


def test_an_existing_revision_is_preserved_even_if_the_refusal_flag_is_true(isolated_stamp_engine: sa.Engine) -> None:
    with isolated_stamp_engine.begin() as conn:
        _current_schema().create_all(conn)
        conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(sa.text("INSERT INTO alembic_version VALUES ('v3253_credentials')"))
        assert database_is_populated_but_unstamped(conn) is False
        assert stamp_head_if_unstamped(conn, refuse_when_populated=True) is None

    with isolated_stamp_engine.connect() as conn:
        assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "v3253_credentials"


def test_a_lost_stamp_is_indistinguishable_from_an_old_unstamped_schema(isolated_stamp_engine: sa.Engine) -> None:
    """The degraded flag asks for investigation; it does not prove missing columns."""
    with isolated_stamp_engine.begin() as conn:
        _current_schema().create_all(conn)
        # Model a successful schema creation followed by a failed stamp write.
        # On restart, no automatic inference is allowed even though our fixture
        # knows that every column is present.
        assert database_is_populated_but_unstamped(conn) is True
        assert stamp_head_if_unstamped(conn, refuse_when_populated=True) is None

    with isolated_stamp_engine.connect() as conn:
        assert "new_required_value" in {c["name"] for c in sa.inspect(conn).get_columns("oe_legacy_item")}
        assert not sa.inspect(conn).has_table("alembic_version")
