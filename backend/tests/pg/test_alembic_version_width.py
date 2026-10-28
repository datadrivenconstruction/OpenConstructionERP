"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Width of alembic's own version table on real PostgreSQL (issue #399).

The app's boot path creates ``alembic_version`` itself, through a bare
``MigrationContext`` that never loads ``alembic/env.py``. It therefore used to
get alembic's stock ``version_num VARCHAR(32)`` while the widening hook in
``env.py`` only ever reached databases created by alembic directly. 30 revision
ids in this tree are longer than 32 characters, so the next ``alembic upgrade
head`` that traversed one of them aborted with ``value too long for type
character varying(32)`` and the database could not move.

These tests live in the PG lane because the defect is PostgreSQL-only: SQLite
ignores a declared VARCHAR length, which is exactly why the bug survived the
default suite. They need a blank database rather than the lane's schema-loaded
fixture, so they provision throwaway ones on the session cluster and never
touch the shared schema.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError

from app.core.alembic_version_table import (
    VERSION_NUM_LENGTH,
    VERSION_TABLE,
    ensure_wide_version_table,
    stamp_head_if_unstamped,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# The head an install stamped under an older release carries, and the
# 40-character revision immediately above it that a VARCHAR(32) column cannot
# record. Both are permanent history in ``alembic/versions``.
_SHORT_REVISION = "v3253_credentials"
_LONG_REVISION = "v3254_takeoff_measurement_color_nullable"


def _stock_version_table_impl(
    self: object,
    *,
    version_table: str,
    version_table_schema: str | None,
    version_table_pk: bool,
    **kw: object,
) -> sa.Table:
    """Alembic's own unpatched version-table factory, VARCHAR(32) and all."""
    table = sa.Table(
        version_table,
        sa.MetaData(),
        sa.Column("version_num", sa.String(32), nullable=False),
        schema=version_table_schema,
    )
    if version_table_pk:
        table.append_constraint(sa.PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc"))
    return table


@pytest.fixture
def stock_alembic_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin alembic back to its stock VARCHAR(32) factory for the test.

    The widening installs itself by rebinding a class attribute on
    ``DefaultImpl``, which is process-global and never undone. Without this
    fixture a test would pass merely because something earlier in the session
    (another test, or any import of ``alembic/env.py``) had already installed
    it, and the assertion would prove nothing about the code under test.
    ``monkeypatch`` restores whatever was bound before.
    """
    from alembic.ddl.impl import DefaultImpl

    monkeypatch.setattr(DefaultImpl, "version_table_impl", _stock_version_table_impl)


@pytest.fixture
def pg_sync_admin_url() -> str:
    """The session cluster's sync URL, as the test conftest published it.

    Indexed rather than fetched with a default on purpose, matching
    ``tests/_pg.py``: a missing cluster has to fail loudly here. Skipping
    instead would let the gate report green on a run where the three
    PostgreSQL tests below never executed, which is the one outcome this file
    exists to prevent.
    """
    return os.environ["DATABASE_SYNC_URL"]


@pytest.fixture
def blank_database_url(pg_sync_admin_url: str) -> Iterator[str]:
    """Create a throwaway EMPTY database on the session cluster, drop it after.

    The lane's ``pg_async_url`` fixture pays for an ``initdb`` plus a full
    ``create_all``; these tests only need an empty database and the version
    table they build themselves.
    """
    admin = make_url(pg_sync_admin_url)
    engine = sa.create_engine(admin, isolation_level="AUTOCOMMIT")
    name = f"oe_test_alembic_width_{uuid.uuid4().hex[:8]}"
    try:
        with engine.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
        try:
            yield admin.set(database=name).render_as_string(hide_password=False)
        finally:
            with engine.connect() as conn:
                conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        engine.dispose()


def _version_num_length(engine: sa.Engine) -> int | None:
    """Declared length of ``alembic_version.version_num``, None if absent."""
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        if not inspector.has_table(VERSION_TABLE):
            return None
        for column in inspector.get_columns(VERSION_TABLE):
            if column["name"] == "version_num":
                return column["type"].length
    return None


def _create_narrow_version_table(engine: sa.Engine, revision: str) -> None:
    """Reproduce what an older release's boot stamp left in the database.

    Written as explicit DDL rather than by calling alembic, so the arrangement
    is narrow by construction and cannot be quietly widened by a hook some
    other test installed.
    """
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                f"CREATE TABLE {VERSION_TABLE} ("
                f"version_num VARCHAR(32) NOT NULL, "
                f"CONSTRAINT {VERSION_TABLE}_pkc PRIMARY KEY (version_num))"
            )
        )
        conn.execute(sa.text(f"INSERT INTO {VERSION_TABLE} (version_num) VALUES (:rev)"), {"rev": revision})


def test_boot_stamp_creates_a_version_table_that_fits_every_revision_id(
    blank_database_url: str, stock_alembic_width: None
) -> None:
    """A database created by the app's boot stamp must not be born narrow.

    This is the population the original widening missed: the canonical install
    boots the app first, so the boot stamp is what CREATES ``alembic_version``,
    and it configures a bare ``MigrationContext`` that never loads ``env.py``.
    The stamp itself always succeeded (the head id is short), so nothing
    surfaced until the operator upgraded across a long id months later.
    """
    engine = sa.create_engine(blank_database_url)
    try:
        with engine.begin() as conn:
            stamped = stamp_head_if_unstamped(conn)

        assert stamped, "a blank database should have been stamped at head"
        assert _version_num_length(engine) == VERSION_NUM_LENGTH
    finally:
        engine.dispose()


def test_boot_stamp_repairs_a_narrow_version_table_left_by_an_older_release(
    blank_database_url: str, stock_alembic_width: None
) -> None:
    """Databases already in the field get repaired, not just future ones.

    Alembic creates its version table once, with ``checkfirst=True``, so a
    creation-time hook can never reach an install that is already running. Those
    installs are the ones actually broken today, and the boot path is the only
    code that visits them, so it has to widen the column even when it finds the
    database already stamped and stamps nothing itself.

    The first half of the test also pins the defect down: it is alembic's own
    bookkeeping UPDATE that fails, before any schema change is applied.
    """
    engine = sa.create_engine(blank_database_url)
    try:
        _create_narrow_version_table(engine, _SHORT_REVISION)
        assert _version_num_length(engine) == 32

        with pytest.raises(DataError), engine.begin() as conn:
            conn.execute(sa.text(f"UPDATE {VERSION_TABLE} SET version_num = :rev"), {"rev": _LONG_REVISION})

        with engine.begin() as conn:
            assert stamp_head_if_unstamped(conn) is None, "an already-stamped database must not be re-stamped"

        assert _version_num_length(engine) == VERSION_NUM_LENGTH
        with engine.begin() as conn:
            conn.execute(sa.text(f"UPDATE {VERSION_TABLE} SET version_num = :rev"), {"rev": _LONG_REVISION})
            recorded = conn.execute(sa.text(f"SELECT version_num FROM {VERSION_TABLE}")).scalar_one()
        assert recorded == _LONG_REVISION
    finally:
        engine.dispose()


def test_widening_is_idempotent_and_keeps_the_recorded_revision(
    blank_database_url: str, stock_alembic_width: None
) -> None:
    """Safe to run on every boot: a correct database is left completely alone.

    The repair runs unconditionally at startup, so "already wide" and "no
    version table at all" both have to be quiet no-ops rather than errors, and
    the recorded revision must survive a widening untouched.
    """
    engine = sa.create_engine(blank_database_url)
    try:
        with engine.begin() as conn:
            assert ensure_wide_version_table(conn) is False  # nothing to widen yet

        _create_narrow_version_table(engine, _SHORT_REVISION)

        with engine.begin() as conn:
            assert ensure_wide_version_table(conn) is True
        with engine.begin() as conn:
            assert ensure_wide_version_table(conn) is False  # second pass changes nothing

        assert _version_num_length(engine) == VERSION_NUM_LENGTH
        with engine.connect() as conn:
            recorded = conn.execute(sa.text(f"SELECT version_num FROM {VERSION_TABLE}")).scalar_one()
        assert recorded == _SHORT_REVISION
    finally:
        engine.dispose()


def test_widening_is_inert_on_sqlite(tmp_path: Path) -> None:
    """Non-PostgreSQL dialects must survive the call untouched.

    SQLite neither enforces a declared VARCHAR length nor supports
    ``ALTER COLUMN ... TYPE``, so attempting the repair there would raise on a
    database that was never at risk. Covers both shapes: with and without the
    version table.
    """
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'probe.db').as_posix()}")
    try:
        with engine.begin() as conn:
            assert ensure_wide_version_table(conn) is False
            conn.execute(sa.text(f"CREATE TABLE {VERSION_TABLE} (version_num VARCHAR(32) NOT NULL)"))
            assert ensure_wide_version_table(conn) is False
    finally:
        engine.dispose()


def test_every_revision_id_fits_the_version_column() -> None:
    """Guard the invariant the fix rests on, for revisions not written yet.

    Two revisions (v3189, v3190) document that their ids were deliberately kept
    under 32 characters to survive the boot stamp. That workaround is gone, so
    the only remaining bound on a revision id is the column width - assert it
    here rather than discovering it on someone's production upgrade. The lower
    check keeps the widening honest: it must stay load-bearing, not decorative.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    import app

    ini = Path(app.__file__).resolve().parent.parent / "alembic.ini"
    assert ini.is_file(), f"alembic.ini not found next to the app package: {ini}"

    ids = [script.revision for script in ScriptDirectory.from_config(Config(str(ini))).walk_revisions()]
    longest = max(ids, key=len)

    assert len(longest) <= VERSION_NUM_LENGTH, f"revision id {longest!r} does not fit VARCHAR({VERSION_NUM_LENGTH})"
    assert any(len(rev) > 32 for rev in ids), "no revision id exceeds 32 chars - the widening is no longer load-bearing"
