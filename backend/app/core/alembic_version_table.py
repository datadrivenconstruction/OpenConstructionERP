"""Single source of truth for the width of alembic's own version table.

Alembic's ``DefaultImpl.version_table_impl`` hardcodes
``version_num VARCHAR(32)``. Many revision ids in this project are long
readable slugs: 30 of them exceed 32 characters and the longest,
``v3103_propdev_lead_reservation_spa_schedule_parties``, is 51. SQLite ignores
a declared VARCHAR length, so this stays invisible there, but PostgreSQL
enforces it and any alembic operation that records one of those ids into a
32-character column aborts with ``value too long for type character
varying(32)`` before a single schema change is applied.

Two entry points create that table, and until issue #399 they disagreed.
``alembic/env.py`` installed the widening hook, so a database created by
``alembic upgrade head`` got a 255-character column. The application's own
boot-time stamp configures a bare ``MigrationContext``, which never loads
``env.py``, so every database created by the canonical "boot the app first"
install got the stock 32-character column instead. The head id is short, so
the stamp itself succeeded and nothing surfaced at boot; the narrow column then
persisted for the life of the database, because alembic creates its version
table only once. The widening therefore protected the databases that did not
need it and missed the ones that did.

Because the table is created once, covering both entry points takes two steps:

* :func:`install_wide_version_table` fixes every version table created from
  now on, whichever entry point creates it.
* :func:`widen_existing_version_table` repairs the ones already in the field,
  which no creation-time hook can reach.

:func:`ensure_wide_version_table` does both and is what the callers use.
Everything here is idempotent and inert on anything but PostgreSQL: SQLite
neither enforces the length nor supports ``ALTER COLUMN ... TYPE``.

Note for future migrations: a couple of revisions (v3189, v3190) carry a
docstring saying their id is deliberately kept under 32 characters to survive
the boot-stamp path. That constraint is what this module removes; ids are
bounded by :data:`VERSION_NUM_LENGTH` now, and
``test_alembic_version_width.py`` holds that line.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

# Width every revision id has to fit into. Alembic's own default is 32.
VERSION_NUM_LENGTH = 255

# Alembic's default version-table name. The project never overrides it (no
# ``version_table=`` is passed anywhere), so the repair below can address it
# by name.
VERSION_TABLE = "alembic_version"

_WIDEN_SQL = f"ALTER TABLE {VERSION_TABLE} ALTER COLUMN version_num TYPE VARCHAR({VERSION_NUM_LENGTH})"


def _wide_version_table_impl(
    self: object,  # noqa: ARG001 - bound method signature, alembic passes the impl
    *,
    version_table: str,
    version_table_schema: str | None,
    version_table_pk: bool,
    **kw: object,  # noqa: ARG001 - future alembic kwargs, deliberately ignored
) -> sa.Table:
    """Alembic's version-table factory, with ``version_num`` widened.

    Mirrors ``DefaultImpl.version_table_impl`` exactly apart from the column
    length. ``version_table_impl`` is a documented third-party override hook
    (alembic 1.14+), so this is a supported extension point rather than a
    private-API patch.
    """
    table = sa.Table(
        version_table,
        sa.MetaData(),
        sa.Column("version_num", sa.String(VERSION_NUM_LENGTH), nullable=False),
        schema=version_table_schema,
    )
    if version_table_pk:
        table.append_constraint(sa.PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc"))
    return table


def install_wide_version_table() -> None:
    """Make alembic create its version table with a ``VARCHAR(255)`` column.

    Idempotent and safe to call from anywhere, including repeatedly: it only
    rebinds a class attribute. Must run BEFORE ``MigrationContext.configure``,
    which snapshots the version table through ``version_table_impl`` while it
    builds the context.

    Affects only tables created from this point on. An existing table keeps
    whatever width it was created with, which is what
    :func:`widen_existing_version_table` is for.
    """
    from alembic.ddl.impl import DefaultImpl

    DefaultImpl.version_table_impl = _wide_version_table_impl


def widen_existing_version_table(connection: Connection) -> bool:
    """Widen an already-created ``alembic_version.version_num`` in place.

    This is the half that reaches the databases already in the field: alembic
    creates its version table with ``checkfirst=True`` and never revisits it,
    so a database stamped by an older release keeps its 32-character column
    forever no matter what the creation hook does now.

    Widening a ``varchar`` in PostgreSQL is a catalog-only change (no table
    rewrite, no scan) on a table holding one row, so it is cheap enough to run
    on every boot. Wrapped in a savepoint so a failure (an external database
    whose version table is owned by the ops role, not the app role) rolls back
    to the savepoint and leaves the caller's transaction usable.

    Args:
        connection: A synchronous connection. Non-PostgreSQL dialects are
            skipped: SQLite does not enforce the declared length and cannot
            ``ALTER COLUMN ... TYPE`` at all.

    Returns:
        True when the column was actually widened, False when there was
        nothing to do (wrong dialect, no version table, already wide enough).
    """
    if connection.dialect.name != "postgresql":
        return False

    inspector = sa.inspect(connection)
    if not inspector.has_table(VERSION_TABLE):
        return False

    for column in inspector.get_columns(VERSION_TABLE):
        if column["name"] != "version_num":
            continue
        length = getattr(column["type"], "length", None)
        if length is None or length >= VERSION_NUM_LENGTH:
            return False
        with connection.begin_nested():
            connection.execute(sa.text(_WIDEN_SQL))
        logger.info(
            "Widened %s.version_num from VARCHAR(%d) to VARCHAR(%d)",
            VERSION_TABLE,
            length,
            VERSION_NUM_LENGTH,
        )
        return True
    return False


def ensure_wide_version_table(connection: Connection) -> bool:
    """Guarantee ``version_num`` can hold any revision id in the tree.

    Covers both populations in one call: installs the creation hook for a
    version table that does not exist yet, and repairs one that already does.
    Call it before anything writes a revision id.

    A repair failure is logged and swallowed. The caller is usually mid-boot,
    and a database we cannot ``ALTER`` is no worse off than before the call;
    the operator still gets the actionable line in the log.

    Args:
        connection: A synchronous connection.

    Returns:
        True when an existing column was widened, False otherwise.
    """
    install_wide_version_table()
    try:
        return widen_existing_version_table(connection)
    except Exception:
        logger.warning(
            "Could not widen %s.version_num; a later migration through a long revision id may fail",
            VERSION_TABLE,
            exc_info=True,
        )
        return False


def database_is_populated_but_unstamped(sync_connection: Connection) -> bool:
    """Did this database arrive holding application tables with no revision recorded?

    **Must be evaluated before ``create_all`` runs.** Afterwards every database
    has ``oe_*`` tables, so the question this answers can no longer be asked -
    which is exactly why the caller captures it early and carries the answer.

    This is the cohort whose schema is NOT at head despite looking ordinary.
    Releases before 15.4.0 shipped no ``alembic.ini``, so their databases record
    no revision at all. ``create_all`` then creates whatever tables are wholly
    absent and cannot alter the ones already there, so a populated database is
    left part-migrated while :func:`stamp_head_if_unstamped` writes head over
    the top - and the missing revision is then the only thing that ever said the
    database was odd. Once head is written that evidence is gone permanently,
    every later upgrade skips the same revisions with no signal, and nothing
    left in the database can tell anyone which version wrote it.

    Returns True only when both are true: at least one ``oe_*`` table exists and
    no revision is recorded. A blank database answers False (no app tables), and
    so does any database that already names its revision.
    """
    from alembic.runtime.migration import MigrationContext

    inspector = sa.inspect(sync_connection)
    if not any(name.startswith("oe_") for name in inspector.get_table_names()):
        return False
    return MigrationContext.configure(sync_connection).get_current_revision() is None


def stamp_head_if_unstamped(sync_connection: Connection, *, refuse_when_populated: bool = False) -> str | None:
    """Stamp the alembic version table at head when no revision is recorded yet.

    The app's boot path materialises the full current schema with
    ``create_all``, so the database is by definition at head; recording that
    lets the health check report a clean state instead of "degraded" on every
    fresh install, and makes a later ``alembic upgrade head`` a correct no-op
    rather than an attempt to replay the whole chain against tables that are
    already there. This is the runtime counterpart of ``alembic/env.py``'s
    fresh-blank-DB shortcut, which only fires when ops run migrations before
    the app ever boots.

    The column width is settled first, unconditionally, including on databases
    that are already stamped: those are precisely the ones an older release
    left at ``VARCHAR(32)``, and they only break later, when an upgrade
    traverses a long revision id.

    The premise above - ``create_all`` materialises the full schema, so the
    database is by definition at head - is true of a BLANK database and false of
    a POPULATED one, where ``create_all`` creates absent tables and cannot alter
    the ones already present. ``refuse_when_populated`` is how the caller says it
    checked, because the check is only answerable before ``create_all`` runs. See
    :func:`database_is_populated_but_unstamped`.

    Args:
        sync_connection: A synchronous connection, typically obtained through
            ``AsyncConnection.run_sync``.
        refuse_when_populated: When True, decline to stamp. The caller passes
            the answer :func:`database_is_populated_but_unstamped` gave BEFORE
            the schema was materialised. Declining leaves the database
            unstamped, which is the only durable record that it is not at head;
            stamping is a one-way door and refusing it is reversible, so while
            the repair for this cohort is undecided the reversible branch is the
            one to take.

    Returns:
        The head revision that was stamped - every head, comma-joined, on a
        forked tree - or None when the database was already stamped,
        ``alembic.ini`` could not be located, or the stamp was refused because
        the database is populated and unstamped.
    """
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    ensure_wide_version_table(sync_connection)

    mig_ctx = MigrationContext.configure(sync_connection)
    if mig_ctx.get_current_revision() is not None:
        return None  # already stamped - leave existing state untouched
    if refuse_when_populated:
        # Populated and unstamped. Writing head here would claim a schema state
        # nothing verified and destroy the only evidence to the contrary.
        logger.warning(
            "Alembic head stamp REFUSED: this database already held application tables and records no "
            "revision, so it is not known to be at head. Leaving it unstamped keeps that fact "
            "recoverable; stamping would not. Run the migrations for this database rather than "
            "stamping it."
        )
        return None
    # ``app/core/x.py`` -> ``app/core`` -> ``app`` -> the directory holding
    # ``alembic.ini`` (the repo's ``backend/``, or the wheel's install root).
    ini = Path(__file__).resolve().parent.parent.parent / "alembic.ini"
    if not ini.is_file():
        return None
    script = ScriptDirectory.from_config(Config(str(ini)))
    mig_ctx.stamp(script, "heads")
    # ``get_heads`` and not ``get_current_head``. The stamp above is already
    # plural - it writes a row per head - while ``get_current_head`` raises
    # ``CommandError`` outright on a tree with more than one, and it raises
    # AFTER the rows are written. The caller runs this inside
    # ``async with engine.begin()``, so that exception rolls the stamp back and
    # the install ends the boot unstamped, logged as "stamp skipped
    # (non-fatal)" - a stamp that succeeded, reported as one that did not
    # happen, on a line that reads like nothing was lost.
    #
    # A fork is meant to be caught before it ships (scripts/check_migration_heads.py,
    # Repo hygiene) and today the tree has exactly one head, so this is about
    # what the failure costs if one ever gets through rather than about a live
    # defect. It costs a lot. Every install created while the fork is out never
    # records a revision; once the branches are merged those same databases hold
    # ``oe_*`` tables and no stamp, which is the cohort
    # :func:`database_is_populated_but_unstamped` identifies and this function
    # then refuses to stamp - permanently, on every later boot. Losing the write
    # here is what converts a packaging mistake into an install that can never
    # be stamped by the boot path again.
    #
    # Joined rather than picked, because there is no basis for choosing one of
    # two heads and the caller only logs this. ``or None`` keeps the documented
    # contract for a tree with no revisions at all, where ``get_heads`` is empty
    # and ``get_current_head`` answered None.
    return ", ".join(script.get_heads()) or None
