# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PostgreSQL auto-migrator (embedded and external PostgreSQL).

On startup, compares the live PostgreSQL schema against the SQLAlchemy models
and adds any missing columns via ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``
plus any missing model-declared plain-column indexes via
``CREATE INDEX IF NOT EXISTS`` (upgraded installs are alembic-STAMPED, not
alembic-run, so an index added in a later release - e.g.
``ix_oe_costs_item_catalog_id`` - would otherwise never materialise and the
largest table would seq-scan forever).

This is the PostgreSQL counterpart to :func:`app.core.sqlite_migrator.sqlite_auto_migrate`.
The embedded-PostgreSQL default runtime (v6.0.0+, no Docker) builds its schema
with ``Base.metadata.create_all``, which only ever creates *missing tables* and
never alters an existing one. So when the app is upgraded across versions, any
column added to an existing table (for example ``oe_boq_position.cost_line_id``
from the v6.4.0 cost spine) is absent from a database created under the older
version, and every ORM read of that table fails with ``UndefinedColumnError``.

This runs for the embedded server AND for external PostgreSQL. External
deployments are still expected to manage their schema with Alembic
(``alembic upgrade head``), but in practice many run the image without that
step, so an upgrade that added a column leaves the live table missing it and
every ORM read 500s. Every statement here is idempotent and non-destructive, so
it is safe to run as a belt-and-braces heal regardless of who owns the schema.
The call site wraps it non-fatally so a DB role without DDL rights simply skips
it.

Almost all of that is additive: ``ADD COLUMN`` / ``CREATE INDEX IF NOT EXISTS``
/ ``ADD CONSTRAINT``. The one alteration of an existing column is
``DROP NOT NULL``, which is here because it is the only one that cannot fail
against rows already in the table - it widens what the column accepts and no
existing row can contradict it. Adding a NOT NULL or changing a type can both
be refused by real data, so neither is attempted. Without the relaxation a
revision that widened a column never took effect on any install that upgrades
through this heal, and ordinary writes leaving that column empty raised
NotNullViolation.

Concurrency- and traffic-safe on shared external databases: the heal takes a
transaction-scoped advisory lock (only one worker heals at a time), bounds each
DDL with ``SET LOCAL lock_timeout`` so it never blocks live queries behind an
open transaction, and wraps every statement in its own SAVEPOINT so a single
failure cannot poison the rest of the heal.
"""

import logging
from decimal import Decimal

from sqlalchemy import CheckConstraint, Column, Sequence, UniqueConstraint, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# Stable application-defined key for ``pg_try_advisory_xact_lock``. Serialises
# the heal across multiple workers / replicas pointed at the same external
# database so they never issue concurrent ALTER / CREATE INDEX against the same
# table. The value is arbitrary but must stay constant across releases.
_HEAL_ADVISORY_LOCK_KEY = 826340271


def _literal_default(col: Column) -> str:
    """Render a model-side scalar default as an ADD COLUMN DEFAULT clause.

    Returns ``""`` for anything that is not a plain literal. A callable
    (``uuid.uuid4``, ``datetime.utcnow``) is deliberately excluded: it has to
    run per row and a single frozen value would be wrong for every row after
    the first. So is a mutable container, because a JSON column default is a
    Python object rather than SQL text and rendering one here would be
    guessing at the dialect's literal syntax.

    Booleans are checked before integers on purpose: ``bool`` is a subclass of
    ``int`` in Python, and ``DEFAULT 1`` on a boolean column is a type error.
    """
    arg = getattr(col.default, "arg", None)
    if col.default is None or not getattr(col.default, "is_scalar", False):
        return ""
    if arg is None:
        return ""
    if isinstance(arg, bool):
        return " DEFAULT true" if arg else " DEFAULT false"
    if isinstance(arg, str):
        return " DEFAULT '" + arg.replace("'", "''") + "'"
    if isinstance(arg, (int, float, Decimal)):
        return f" DEFAULT {arg}"
    return ""


async def postgres_auto_migrate(engine: AsyncEngine, base) -> int:
    """Compare SQLAlchemy models against the PostgreSQL schema and heal it.

    Adds missing sequences that a column defaults from (``CREATE SEQUENCE IF NOT
    EXISTS``, and first, because the ADD COLUMN below needs them), missing
    columns (``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``) and
    missing model-declared single/multi-column btree indexes
    (``CREATE INDEX IF NOT EXISTS``). Functional / expression / dialect-
    specific indexes are skipped defensively - their SQL cannot be
    reconstructed reliably from the ``Index`` object.

    Also drops a NOT NULL the database still holds on a column the models now
    declare optional (``ALTER COLUMN ... DROP NOT NULL``), which is the one
    alteration of an existing column that no existing row can refuse. See
    :func:`_relax_not_null`.

    Args:
        engine: The async SQLAlchemy engine (must be PostgreSQL).
        base: The declarative ``Base`` whose metadata holds every model.

    Returns:
        Total number of schema repairs made (sequences + columns + indexes +
        constraints added, plus columns relaxed to accept NULL).
    """
    sequences_added = 0
    columns_added = 0
    indexes_added = 0
    constraints_added = 0
    nulls_relaxed = 0

    async with engine.begin() as conn:
        # Serialise the heal across processes: on a shared external database
        # several app workers (or replicas) can boot at once. Only one should
        # run the idempotent DDL; the others skip and rely on the holder. The
        # xact-scoped advisory lock auto-releases when this transaction ends, so
        # there is nothing to unlock by hand. On the single-process embedded
        # server the lock is always free, so this is a no-op there.
        got_lock = (
            await conn.execute(
                text("SELECT pg_try_advisory_xact_lock(:k)"),
                {"k": _HEAL_ADVISORY_LOCK_KEY},
            )
        ).scalar()
        if not got_lock:
            logger.info("PostgreSQL auto-migration: another worker holds the heal lock - skipping")
            return 0

        # Never stall live traffic on a busy external database: cap how long any
        # single DDL waits to acquire its table lock. If the table is busy the
        # statement raises (caught per-statement below) and the heal is simply
        # deferred to a later boot or the operator's ``alembic upgrade head``,
        # rather than blocking startup behind an open transaction.
        await conn.execute(text("SET LOCAL lock_timeout = '3s'"))

        existing_tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))

        # Sequences first: a column added below may default from one, and the
        # ADD COLUMN fails outright if the sequence is not there yet.
        sequences_added = await _heal_sequences(conn, base)

        for table in base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # New table - create_all handles it.

            # Nullability comes back with the names because the loop below needs
            # both: a column that is absent gets added, and a column that is
            # present may still disagree with the model about accepting NULL.
            existing_cols = await conn.run_sync(
                lambda sync_conn, tn=table.name: {
                    col["name"]: bool(col.get("nullable")) for col in inspect(sync_conn).get_columns(tn)
                }
            )
            # The live primary key, not the model's. DROP NOT NULL on a PK column
            # is rejected outright, and the two can disagree on an aged database.
            try:
                live_pk_cols = await conn.run_sync(
                    lambda sync_conn, tn=table.name: set(
                        inspect(sync_conn).get_pk_constraint(tn).get("constrained_columns") or ()
                    )
                )
            except Exception as exc:  # noqa: BLE001
                # Unreadable primary key means the guard below cannot be trusted,
                # so relax nothing on this table rather than guessing at it.
                logger.warning("PostgreSQL migration: could not read the primary key of %s: %s", table.name, exc)
                live_pk_cols = set(existing_cols)

            for col in table.columns:
                if col.name in existing_cols:
                    nulls_relaxed += await _relax_not_null(
                        conn, table, col, db_nullable=existing_cols[col.name], live_pk_cols=live_pk_cols
                    )
                    continue

                col_type = col.type.compile(engine.dialect)

                default = ""
                if col.server_default is None:
                    # No server default declared, but the model may still name
                    # a literal the rows can be backfilled from. Without this,
                    # a NOT NULL column whose default lives only in Python is
                    # added NULLABLE by the branch below, the model and the
                    # database then disagree about that column forever, and
                    # every health signal calls it a clean upgrade because the
                    # column is present and selectable. Caught by the upgrade
                    # lane on oe_supplier_catalogs_stock_balance.cost_state,
                    # where the alembic revision does declare a server default
                    # and only the heal path lost it.
                    default = _literal_default(col)
                if col.server_default is not None:
                    raw = col.server_default.arg
                    if isinstance(raw, str):
                        quoted = raw if raw.startswith("'") else "'" + raw.replace("'", "''") + "'"
                        default = f" DEFAULT {quoted}"
                    else:
                        # Expression default (func.now(), CURRENT_TIMESTAMP, ...).
                        # Compile it to literal SQL; PostgreSQL accepts a function
                        # or expression as an ADD COLUMN default, unlike SQLite.
                        try:
                            compiled = str(
                                raw.compile(
                                    dialect=engine.dialect,
                                    compile_kwargs={"literal_binds": True},
                                )
                            )
                        except Exception:  # noqa: BLE001
                            compiled = ""
                        if compiled:
                            default = f" DEFAULT {compiled}"

                # Only enforce NOT NULL when a default exists to backfill the
                # rows already in the table. Without a default, adding a NOT NULL
                # column to a populated table fails, so we add it nullable and
                # let the app's Python-side default cover new writes (mirrors the
                # defensive behaviour of the SQLite migrator).
                not_null = " NOT NULL" if (not col.nullable and default) else ""
                # Adding it nullable is the right call - the alternative fails
                # outright on a populated table - but it leaves the database and
                # the models disagreeing about this column for the life of the
                # install, because no revision body ever runs to tighten it
                # later. Until this flag existed that divergence was created in
                # silence: the column went in, the heal counted it as a success,
                # and nothing said the NOT NULL had been dropped on the way.
                # Read after the statement lands, so a column that was never
                # added is not reported as a divergence.
                not_null_declined = not col.nullable and not default

                sql = f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{col.name}" {col_type}{not_null}{default}'

                try:
                    # SAVEPOINT per statement: a failed DDL aborts only its own
                    # nested transaction, not the whole heal. Without this the
                    # first failure would poison the outer transaction and every
                    # later ADD COLUMN / CREATE INDEX would error with "current
                    # transaction is aborted", silently halting the heal.
                    async with conn.begin_nested():
                        await conn.execute(text(sql))
                    columns_added += 1
                    logger.info(
                        "PostgreSQL migration: added column %s.%s (%s)",
                        table.name,
                        col.name,
                        col_type,
                    )
                    if not_null_declined:
                        logger.warning(
                            "PostgreSQL migration: added %s.%s NULLABLE although the models declare it "
                            "NOT NULL, because it has no default to backfill the rows already in the "
                            "table. The database and the models disagree about this column until it is "
                            "backfilled and tightened by hand; nothing on the boot path will do it.",
                            table.name,
                            col.name,
                        )
                except Exception as exc:  # noqa: BLE001
                    # A rejected DEFAULT must not cost the column. The
                    # constrained form above is an improvement on the plain
                    # one, not a replacement for it, so when it will not go
                    # in, fall back to exactly what this line used to emit
                    # rather than leaving the table without the column and
                    # every ORM read of it a 500.
                    plain = f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{col.name}" {col_type}'
                    if sql != plain:
                        try:
                            async with conn.begin_nested():
                                await conn.execute(text(plain))
                            columns_added += 1
                            logger.warning(
                                "PostgreSQL migration: added %s.%s without its NOT NULL and default, "
                                "which the database refused (%s)",
                                table.name,
                                col.name,
                                exc,
                            )
                            continue
                        except Exception as plain_exc:  # noqa: BLE001
                            exc = plain_exc
                    logger.warning(
                        "PostgreSQL migration: failed to add %s.%s: %s",
                        table.name,
                        col.name,
                        exc,
                    )

            # ── Index healing ────────────────────────────────────────────
            # Upgraded embedded-PG installs stamp alembic instead of running
            # it, so indexes added in later releases never materialise via
            # create_all (it only creates missing TABLES). Compare model-
            # declared indexes against the live schema and create any that
            # are missing. Matching is by name AND by column tuple: names
            # longer than PostgreSQL's 63-byte identifier limit are stored
            # hash-mangled by SQLAlchemy, so a pure name comparison would
            # "re-create" (duplicate) those on every boot.
            try:
                live_indexes = await conn.run_sync(lambda sync_conn, tn=table.name: inspect(sync_conn).get_indexes(tn))
                live_constraints = await conn.run_sync(
                    lambda sync_conn, tn=table.name: inspect(sync_conn).get_unique_constraints(tn)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "PostgreSQL migration: could not inspect indexes on %s: %s",
                    table.name,
                    exc,
                )
                continue

            existing_names = {ix["name"] for ix in live_indexes if ix.get("name")}
            existing_names |= {uc["name"] for uc in live_constraints if uc.get("name")}
            existing_col_tuples = {tuple(ix.get("column_names") or ()) for ix in live_indexes}
            existing_col_tuples |= {tuple(uc.get("column_names") or ()) for uc in live_constraints}

            for index in table.indexes:
                if not index.name or index.name[:63] in existing_names:
                    continue
                if index.dialect_kwargs:
                    # Partial (postgresql_where) / USING-clause indexes carry
                    # dialect-specific SQL we do not reconstruct here.
                    continue
                expressions = list(index.expressions)
                index_cols = [expr for expr in expressions if isinstance(expr, Column)]
                if not index_cols or len(index_cols) != len(expressions):
                    # Functional / expression index - skip defensively.
                    continue
                if tuple(c.name for c in index_cols) in existing_col_tuples:
                    # Same column tuple already indexed live (typically the
                    # hash-mangled name of an over-long identifier, or a
                    # unique constraint covering the columns) - nothing to
                    # heal.
                    continue

                unique = "UNIQUE " if index.unique else ""
                cols_sql = ", ".join(f'"{c.name}"' for c in index_cols)
                sql = f'CREATE {unique}INDEX IF NOT EXISTS "{index.name}" ON "{table.name}" ({cols_sql})'

                try:
                    # SAVEPOINT per statement - see the ADD COLUMN note above:
                    # keeps one failed CREATE INDEX from poisoning the rest.
                    async with conn.begin_nested():
                        await conn.execute(text(sql))
                    indexes_added += 1
                    logger.info(
                        "PostgreSQL migration: created index %s on %s (%s)",
                        index.name,
                        table.name,
                        ", ".join(c.name for c in index_cols),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "PostgreSQL migration: failed to create index %s on %s: %s",
                        index.name,
                        table.name,
                        exc,
                    )

            constraints_added += await _heal_constraints(conn, table, existing_names, existing_col_tuples)

    if sequences_added > 0 or columns_added > 0 or indexes_added > 0 or constraints_added > 0 or nulls_relaxed > 0:
        logger.info(
            "PostgreSQL auto-migration complete: %d sequences, %d columns, %d indexes, %d constraints added, "
            "%d column(s) relaxed to accept NULL",
            sequences_added,
            columns_added,
            indexes_added,
            constraints_added,
            nulls_relaxed,
        )

    return sequences_added + columns_added + indexes_added + constraints_added + nulls_relaxed


async def not_null_divergences(engine: AsyncEngine, base) -> tuple[str, ...]:
    """Columns the models declare NOT NULL that the live database accepts NULL in.

    This asks the standing question - does the schema match the models *now* -
    rather than the question the heal's own log answers, which is what this boot
    happened to do. The two are not interchangeable. A column added nullable
    three releases ago is exactly as divergent as one added nullable a minute
    ago, and only the standing form sees it: the heal announces the decision on
    the boot that makes it and is silent on every boot afterwards, so on any
    install that upgraded before today the log says nothing at all.

    Nullability is the whole of what this reports, and that is a deliberate
    floor rather than the finished job. It is crisply answerable: a column is
    NOT NULL or it is not, and the two sides of the comparison cannot disagree
    for reasons of rendering. Type divergence is the other half of what the heal
    declines, and comparing a model type against a reflected one produces
    disagreements that are about spelling rather than about the schema, so it
    would need its own work and its own evidence before it could be trusted to
    degrade a health signal.

    Read-only. It issues no DDL and no DML on any code path, which is what makes
    it safe to run on every boot and against a production database.

    Args:
        engine: The async SQLAlchemy engine (must be PostgreSQL).
        base: The declarative ``Base`` whose metadata holds every model.

    Returns:
        ``table.column`` for each divergence, sorted, so the value is stable
        across boots and two runs can be compared directly.
    """
    found: list[str] = []

    async with engine.connect() as conn:
        # One catalog query rather than an inspector call per table. Asking the
        # inspector table by table is the obvious way to write this and it cost
        # 5.0s against 626 tables, measured, which is far too much to spend on
        # every boot for a diagnostic. The same answer in a single round trip
        # comes back in hundredths of a second, and it is the same answer:
        # nullability is one column of one catalog view.
        rows = await conn.execute(
            text(
                "SELECT table_name, column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = current_schema()"
            )
        )
        live: dict[tuple[str, str], bool] = {
            (table_name, column_name): is_nullable == "YES" for table_name, column_name, is_nullable in rows
        }

    live_tables = {table_name for table_name, _ in live}
    for table in base.metadata.sorted_tables:
        if table.name not in live_tables:
            continue  # Not built yet; create_all makes it correctly.
        for col in table.columns:
            if col.nullable or col.primary_key:
                continue  # The models allow NULL, or PostgreSQL forbids it anyway.
            if live.get((table.name, col.name)) is True:
                found.append(f"{table.name}.{col.name}")

    return tuple(sorted(found))


async def _relax_not_null(conn, table, col: Column, *, db_nullable: bool, live_pk_cols: set) -> int:
    """Drop a NOT NULL the database still holds and the models no longer declare.

    This is the one schema alteration that can never fail against the rows
    already in the table. Adding NOT NULL needs every existing row to satisfy it,
    and changing a type needs every existing value to cast, which is why neither
    belongs in a heal that runs unattended on someone else's data. Dropping it
    only ever widens what the column accepts, so no row can contradict it and no
    reader that worked before stops working.

    It is needed because the heal is what actually runs on upgrade for most
    installs, and a revision that widens a column therefore never runs. The old
    constraint survives, the models say the value is optional, and the first
    write that leaves it empty raises NotNullViolation on an ordinary request.
    Nothing reported the schema as unhealed, because until now the comparison
    only looked for the opposite mismatch.

    A primary key is skipped on both definitions, the model's and the live one.
    A PK column is implicitly NOT NULL in PostgreSQL and the ALTER is rejected,
    and an aged database can disagree with the models about which columns those
    are.

    Returns:
        1 if a NOT NULL was dropped, 0 if there was nothing to do or the
        statement was refused.
    """
    if db_nullable or not col.nullable:
        return 0
    if col.primary_key or col.name in live_pk_cols:
        return 0

    sql = f'ALTER TABLE "{table.name}" ALTER COLUMN "{col.name}" DROP NOT NULL'
    try:
        # SAVEPOINT per statement, as everywhere else in this heal: one refusal
        # must not abort the transaction the remaining statements run in.
        async with conn.begin_nested():
            await conn.execute(text(sql))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "PostgreSQL migration: failed to relax %s.%s to accept NULL: %s",
            table.name,
            col.name,
            exc,
        )
        return 0

    logger.info(
        "PostgreSQL migration: relaxed %s.%s to accept NULL, which the models declare optional",
        table.name,
        col.name,
    )
    return 1


async def _heal_sequences(conn, base) -> int:
    """Create the sequences that model columns default from, before the column heal.

    ``oe_progress_entry.seq`` is a BIGINT whose server default is
    ``nextval('oe_progress_entry_seq_seq')``. On a database created before that
    column existed, the column heal below emits
    ``ALTER TABLE ... ADD COLUMN ... DEFAULT nextval(...)`` - and PostgreSQL
    rejects that statement outright when the sequence is absent, taking the two
    indexes over the column and its unique constraint down with it, all at
    WARNING level while the boot carries on.

    **Do not assume ``create_all`` has this covered - it never will.** That
    assumption is what produced the bug. ``SchemaGenerator.visit_metadata``
    builds its standalone sequence list as
    ``[s for s in metadata._sequences.values() if s.column is None and ...]``,
    and a sequence passed to ``mapped_column`` has ``s.column`` set, so it is
    filtered out. Its only other route is ``CREATE TABLE``, which does not run
    for a table that already exists - precisely the databases that need healing.
    So the ordering of the two calls was never the issue: moving the heal after
    ``create_all`` would fix nothing. After this function, the heal is the only
    thing in the whole app-managed upgrade path that will ever create such a
    sequence. Verified against a live cluster in
    ``tests/pg/test_postgres_migrator_sequence_heal.py``.

    Deliberately no ``OWNED BY``. ``create_all`` does not emit it either, and
    this runs immediately before ``create_all`` against the same database, so
    matching it keeps one install from having two different sequence shapes
    depending on which statement got there first. (The Alembic path *does* set
    ``OWNED BY``, so the two schema-building routes already disagree - a
    divergence to settle deliberately, not to paper over here.)

    Args:
        conn: The open async connection running inside the heal transaction.
        base: The declarative ``Base`` whose metadata holds every model.

    Returns:
        Number of sequences created.
    """
    # A Sequence passed positionally to ``mapped_column`` lands on ``col.default``.
    wanted: dict[str | None, set[str]] = {}
    for table in base.metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.default, Sequence) and col.default.name:
                wanted.setdefault(col.default.schema, set()).add(col.default.name)

    added = 0
    for schema, names in wanted.items():
        try:
            live = await conn.run_sync(lambda sync_conn, s=schema: set(inspect(sync_conn).get_sequence_names(schema=s)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("PostgreSQL migration: could not inspect sequences: %s", exc)
            continue

        for name in sorted(names - live):
            qualified = f'"{schema}"."{name}"' if schema else f'"{name}"'
            if await _run_ddl(conn, f"CREATE SEQUENCE IF NOT EXISTS {qualified}", f"sequence {name}"):
                added += 1

    return added


#: PostgreSQL's identifier limit (NAMEDATALEN - 1).
_PG_IDENTIFIER_LIMIT = 63

#: The preparer SQLAlchemy uses to render constraint names in DDL.
_PREPARER = postgresql.dialect().identifier_preparer


def _effective_name(constraint) -> str:
    """The name this constraint actually has in the database.

    Do not compare ``constraint.name`` against what the database reports. The
    metadata naming convention in ``app.database`` re-wraps an already-prefixed
    name, so several model-declared constraints resolve to more than 63 bytes.
    ``create_all`` did not store those chopped at 63, it stored them
    **hash-mangled**: 64 characters of
    ``ck_oe_erp_chat_turn_feedback_ck_oe_erp_chat_turn_feedback_rating`` live in
    PostgreSQL as ``ck_oe_erp_chat_turn_feedback_ck_oe_erp_chat_turn_feedba_b8d8``.
    Neither the full name nor a plain ``[:63]`` slice matches that, so a name
    comparison decides the constraint is missing, and re-adding it under a raw
    ``ALTER TABLE`` produces a *second* constraint enforcing the same rule under a
    differently mangled name, on every upgrade.

    Comparing the expression instead does not work either: PostgreSQL rewrites
    what it stores, so ``rating IN (-1, 1)`` comes back as
    ``rating = ANY (ARRAY['-1'::integer, 1])``.

    So ask the component that produced the name in the first place. This is the
    same preparer ``create_all`` used, and it returns the identical string.
    """
    return _PREPARER.format_constraint(constraint)


async def _heal_constraints(conn, table, existing_names: set[str], existing_col_tuples: set[tuple[str, ...]]) -> int:
    """Add unique, check and foreign-key constraints the live table is missing.

    ``create_all`` builds a brand-new table with every constraint it declares, so
    a fresh install is never short of one. The gap is a constraint *added to a
    table that already exists*: alembic knows how to do that, this path did not,
    and an install upgraded through ``create_all`` lost it silently.

    The unique constraints are the ones that carry weight. Six tables generate
    their document number as ``MAX(suffix) + 1``, flush inside a savepoint, and
    catch ``IntegrityError`` to retry. The constraint is not a backstop sitting
    behind an application check, it **is** the check. Without it two people
    raising an NCR in the same moment both commit NCR-001, with no error, no
    warning and no log line, on an instrument that gets quoted by number in
    contractual claims.

    Two rules keep this from turning a broken install into an install that will
    not boot, which is the real hazard: the databases missing a constraint are
    exactly the ones that may hold rows violating it.

    * A unique is pre-flighted with ``GROUP BY ... HAVING count(*) > 1``. If the
      table already holds duplicates the constraint cannot be added at all, so we
      log loudly, name the columns, and leave the table alone rather than raise.
    * Check and foreign-key constraints go on as ``NOT VALID``. PostgreSQL then
      enforces them for every new row without scanning the rows already there, so
      the ``ALTER TABLE`` cannot fail on an install with bad history. The scan is
      not skipped, only deferred: :func:`validate_pending_constraints` runs it
      once this heal's transaction has committed and released its locks, and
      once the boot's data repairs have had their turn at the rows.

      That deferral used to be permanent, and the sentence here used to say such
      an install "keeps running", which was true of the install and false of the
      rows. ``NOT VALID`` exempts an existing row from the validation scan and
      from nothing after it - PostgreSQL re-checks a CHECK constraint on every
      UPDATE of the row, whatever column the update names - so a row that
      violates one becomes unwritable rather than merely unverified, and the
      install carries a patch of itself that answers 500 forever while reporting
      ``status: healthy``. The validation pass is where that is now found and
      said out loud.

    ``NOT NULL`` is deliberately not healed. It needs a backfill decision per
    column and it is the one that can destroy data.

    Every statement gets its own SAVEPOINT for the same reason the rest of this
    module does, and nothing here raises to the caller.

    **Names must be compared truncated, and this is not a detail.** The metadata
    naming convention in ``app.database`` re-wraps an already-prefixed constraint
    name, so a handful of model-declared names come out longer than PostgreSQL's
    63-byte identifier limit. ``create_all`` stored those truncated. Comparing the
    full model-side name against what the database reports therefore never
    matches, and the heal concludes a constraint is missing when it is sitting
    right there. Re-adding it does not collide either, because a raw ``ALTER
    TABLE`` truncates by a plain byte chop while SQLAlchemy's own compiler
    hash-mangles, so the result is a second constraint enforcing the same rule
    under a different name, added on every upgrade. Measured on
    ``oe_erp_chat_turn_feedback`` and ``oe_takeoff_measurement``. The index loop
    above has carried the same guard for the same reason since it was written.

    Uniques get a column-tuple fallback on top of the name check, since that is
    what actually identifies the constraint when its name cannot be trusted.

    Args:
        conn: The open async connection running inside the heal transaction.
        table: The SQLAlchemy table to heal.
        existing_names: Constraint and index names already live on the table.
        existing_col_tuples: Column tuples already covered by a live index or
            unique constraint, used to recognise a constraint whose name was
            truncated or mangled.

    Returns:
        Number of constraints added.
    """
    added = 0

    try:
        live_checks = await conn.run_sync(lambda sync_conn, tn=table.name: inspect(sync_conn).get_check_constraints(tn))
        live_fks = await conn.run_sync(lambda sync_conn, tn=table.name: inspect(sync_conn).get_foreign_keys(tn))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "PostgreSQL migration: could not inspect constraints on %s: %s",
            table.name,
            exc,
        )
        return 0

    live_check_names = {c["name"] for c in live_checks if c.get("name")}
    live_fk_names = {fk["name"] for fk in live_fks if fk.get("name")}
    live_fk_shapes = {
        (
            tuple(fk.get("constrained_columns") or ()),
            fk.get("referred_table"),
            tuple(fk.get("referred_columns") or ()),
        )
        for fk in live_fks
    }

    for constraint in table.constraints:
        if not isinstance(constraint, UniqueConstraint) or not constraint.name:
            continue
        # An unnamed unique cannot be matched on the next boot, so we would add a
        # fresh copy every time. SQLAlchemy also renders ``unique=True, index=True``
        # as an Index, which the loop above already heals; that lands in
        # ``existing_names`` so it is not duplicated here.
        name = _effective_name(constraint)
        if name in existing_names or constraint.name[:_PG_IDENTIFIER_LIMIT] in existing_names:
            continue
        cols = [c.name for c in constraint.columns]
        if not cols:
            continue
        if tuple(cols) in existing_col_tuples:
            # Same columns are already covered live, under a name we cannot match
            # because it was truncated or hash-mangled. Adding it again would
            # duplicate the constraint on every upgrade.
            continue

        cols_sql = ", ".join(f'"{c}"' for c in cols)
        # NULLs never collide under a unique constraint, but GROUP BY treats them
        # as equal, so exclude them or a column of NULLs reads as a duplicate and
        # we would skip a constraint that would have applied cleanly.
        not_null = " AND ".join(f'"{c}" IS NOT NULL' for c in cols)
        probe = (
            f'SELECT 1 FROM "{table.name}" WHERE {not_null} '  # noqa: S608 - identifiers come from the models
            f"GROUP BY {cols_sql} HAVING count(*) > 1 LIMIT 1"
        )
        try:
            async with conn.begin_nested():
                duplicated = (await conn.execute(text(probe))).first() is not None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PostgreSQL migration: could not check %s (%s) for duplicates: %s",
                table.name,
                ", ".join(cols),
                exc,
            )
            continue

        if duplicated:
            # Loud on purpose. This install has already lost the guarantee, and
            # the duplicate rows have to be reconciled by a human before the
            # constraint can go on.
            logger.warning(
                "PostgreSQL migration: %s already holds duplicate rows for (%s), so the unique "
                "constraint %s cannot be restored. Records sharing a value here were created "
                "without the protection this constraint provides and need reconciling by hand.",
                table.name,
                ", ".join(cols),
                constraint.name,
            )
            continue

        sql = f'ALTER TABLE "{table.name}" ADD CONSTRAINT {name} UNIQUE ({cols_sql})'
        if await _run_ddl(conn, sql, f"unique constraint {name} on {table.name}"):
            added += 1

    for constraint in table.constraints:
        if not isinstance(constraint, CheckConstraint) or not constraint.name:
            continue
        name = _effective_name(constraint)
        if name in live_check_names or constraint.name in live_check_names:
            continue
        try:
            expression = str(
                constraint.sqltext.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
        except Exception as exc:  # noqa: BLE001
            # An expression we cannot render verbatim is not one to guess at.
            logger.warning(
                "PostgreSQL migration: cannot render check constraint %s on %s: %s",
                constraint.name,
                table.name,
                exc,
            )
            continue

        sql = f'ALTER TABLE "{table.name}" ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID'
        if await _run_ddl(conn, sql, f"check constraint {name} on {table.name}"):
            added += 1

    for fk in table.foreign_key_constraints:
        if not fk.name:
            continue
        cols = [c.name for c in fk.columns]
        elements = list(fk.elements)
        if not cols or not elements:
            continue
        referred_table = elements[0].column.table.name
        referred_cols = [element.column.name for element in elements]
        shape = (tuple(cols), referred_table, tuple(referred_cols))
        if fk.name[:_PG_IDENTIFIER_LIMIT] in live_fk_names or shape in live_fk_shapes:
            continue

        cols_sql = ", ".join(f'"{c}"' for c in cols)
        ref_sql = ", ".join(f'"{c}"' for c in referred_cols)
        # Emit ON DELETE / ON UPDATE from the model. Healing a foreign key
        # without them would replace one divergence from alembic with another,
        # and a missing ON DELETE CASCADE turns a later delete into an error
        # rather than a cascade.
        actions = ""
        if fk.ondelete:
            actions += f" ON DELETE {fk.ondelete}"
        if fk.onupdate:
            actions += f" ON UPDATE {fk.onupdate}"

        sql = (
            f'ALTER TABLE "{table.name}" ADD CONSTRAINT "{fk.name}" '
            f'FOREIGN KEY ({cols_sql}) REFERENCES "{referred_table}" ({ref_sql}){actions} NOT VALID'
        )
        if await _run_ddl(conn, sql, f"foreign key {fk.name} on {table.name}"):
            added += 1

    return added


async def _run_ddl(conn, sql: str, description: str) -> bool:
    """Run one DDL statement inside its own SAVEPOINT. Never raises.

    A failure here must not stop the boot. The heal is best effort by design, and
    every install that reaches this code is already running.
    """
    try:
        async with conn.begin_nested():
            await conn.execute(text(sql))
    except Exception as exc:  # noqa: BLE001
        logger.warning("PostgreSQL migration: failed to add %s: %s", description, exc)
        return False
    logger.info("PostgreSQL migration: added %s", description)
    return True


# The constraints this database carries that PostgreSQL has never verified
# against the rows already in the table. One population, written once, because
# two consumers read it and they must not be able to disagree: the sweep below
# is what empties it, and ``/api/health`` counts what is left. A predicate
# spelled out separately in each place is how a green field ends up counting a
# different set from the one the fix drains.
#
# ``contype`` 'c' and 'f' are the only two kinds :func:`_heal_constraints` can
# leave unvalidated - it adds uniques outright or not at all - and
# ``convalidated`` is PostgreSQL's own record, so neither consumer needs to
# introspect a model or scan a table to ask the question.
_UNVALIDATED_CONSTRAINTS_FROM = (
    "FROM pg_constraint c "
    "JOIN pg_class t ON t.oid = c.conrelid "
    "JOIN pg_namespace n ON n.oid = t.relnamespace "
    "WHERE NOT c.convalidated AND c.contype IN ('c', 'f') "
    "AND n.nspname = current_schema()"
)

#: How many of them there are. Imported by ``app.main`` for ``/api/health``.
UNVALIDATED_CONSTRAINTS_SQL = f"SELECT count(*) {_UNVALIDATED_CONSTRAINTS_FROM}"

#: Which ones, so the sweep can name them in DDL and in the log.
_PENDING_CONSTRAINTS_SQL = f"SELECT c.conname, t.relname {_UNVALIDATED_CONSTRAINTS_FROM} ORDER BY t.relname, c.conname"


async def validate_pending_constraints(engine: AsyncEngine) -> tuple[int, tuple[str, ...]]:
    """Ask PostgreSQL to verify every CHECK and FOREIGN KEY still marked NOT VALID.

    :func:`_heal_constraints` adds both kinds ``NOT VALID`` because that is the
    only way onto a populated table that cannot fail on the rows already there.
    Its docstring says such an install "keeps running and can be cleaned up later
    with ``VALIDATE CONSTRAINT``". Nothing ever ran it, and "keeps running" was
    not true of the rows in question.

    ``NOT VALID`` exempts an existing row from the one-off validation scan. It
    does not exempt it from anything afterwards. PostgreSQL re-evaluates every
    CHECK constraint on any UPDATE of a row, whatever column the update names, so
    a row that violates one is refused by every write to it from then on -
    measured on ``oe_i18n_tax_config``, where ``SET tax_name = tax_name || '!'``
    and even ``SET id = id`` come back ``CheckViolation`` on a column the
    constraint does not mention. The screen that edits that row answers 500 for
    the life of the install, on a deployment reporting ``status: healthy``. A
    foreign key is narrower - its trigger fires only when the constrained columns
    change - but a row orphaned before the key arrived can never be repointed.

    So this runs the validation the heal deferred. On a database whose rows
    conform, which is nearly all of them, the constraint becomes ordinary and the
    question stops being asked on later boots. On one holding rows that do not,
    PostgreSQL refuses and names the constraint, and that refusal is the only
    place the unwritable rows are ever announced: it goes to the boot log with
    the table, and to ``/api/health`` as ``schema_constraints_validated: false``.

    Nothing is repaired here and nothing is dropped. Which rows are wrong, and
    what they should have said instead, is a question about the deployment's data
    that this function has nowhere to put an answer - a repair that guessed would
    be worse than the defect. Correcting them is a declared
    :mod:`app.core.data_repairs` repair or an operator's own UPDATE, and either
    way the constraint gets validated and the signal clears itself.

    Which is why where the caller puts this matters as much as that it calls it.
    :mod:`app.main` runs it after the boot's data repairs, not beside the heal
    that creates the constraints, because those repairs rewrite exactly the kind
    of row a restored constraint refuses - the shipped Canadian tax rows carry a
    sub-national ``combination`` and no ``subdivision_code``, and
    ``tax_subdivision_backfill`` fills them in on the same boot. Called before
    them, this refuses a constraint the boot is about to make valid, and the
    install spends one start reporting a fault it does not have. Called after,
    an operator's row is the only kind that can still be refused, which is the
    only kind worth telling them about.

    Deliberately outside :func:`postgres_auto_migrate`'s transaction. That one
    holds a single ``engine.begin()`` across the whole schema, so every
    ``ADD CONSTRAINT`` in it holds ACCESS EXCLUSIVE on its table until the heal
    commits; validating in there would put a full table scan under that lock.
    Here each constraint gets its own short transaction, taking only the SHARE
    UPDATE EXCLUSIVE that ``VALIDATE`` itself needs and releasing it immediately,
    so reads and writes carry on around it. Two workers racing to validate the
    same constraint is harmless - the loser finds it validated or fails the
    statement, and neither outcome changes the database.

    ``lock_timeout`` bounds the wait for the lock, like the heal's. The scan
    itself is not bounded: it happens once per constraint in the life of the
    database, and abandoning it half way would leave exactly the state this
    exists to end while making the health field say so for a reason that is not
    the operator's.

    Never raises. A boot must not fail over a diagnostic, and every install that
    reaches this code is already running.

    Args:
        engine: The async SQLAlchemy engine (must be PostgreSQL).

    Returns:
        ``(validated, refused)`` - how many constraints were verified, and
        ``table.constraint`` for each one PostgreSQL would not verify.
    """
    try:
        async with engine.connect() as conn:
            pending = (await conn.execute(text(_PENDING_CONSTRAINTS_SQL))).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PostgreSQL migration: could not list unvalidated constraints: %s", exc)
        return 0, ()

    validated = 0
    refused: list[str] = []
    for conname, relname in pending:
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SET LOCAL lock_timeout = '3s'"))
                await conn.execute(text(f'ALTER TABLE "{relname}" VALIDATE CONSTRAINT "{conname}"'))
        except Exception as exc:  # noqa: BLE001
            refused.append(f"{relname}.{conname}")
            logger.warning(
                "PostgreSQL migration: constraint %s on %s could not be validated, so rows that were "
                "already in that table when it was added do not satisfy it. Those rows are not merely "
                "unverified: PostgreSQL re-checks a CHECK constraint on every UPDATE of a row whatever "
                "column the update touches, so nothing can write them and whichever screen edits them "
                "answers 500 until they are corrected. Correct them and the next start validates the "
                "constraint. /api/health reports schema_constraints_validated=false. Cause: %s",
                conname,
                relname,
                exc,
            )
            continue
        validated += 1
        logger.info("PostgreSQL migration: validated constraint %s on %s", conname, relname)

    return validated, tuple(refused)
