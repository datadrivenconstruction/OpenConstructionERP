"""PostgreSQL auto-migrator (embedded PostgreSQL only).

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

This runs for the embedded server only. External PostgreSQL deployments still
manage their schema with Alembic (that path never calls this).
"""

import logging

from sqlalchemy import Column, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def postgres_auto_migrate(engine: AsyncEngine, base) -> int:
    """Compare SQLAlchemy models against the PostgreSQL schema and heal it.

    Adds missing columns (``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``) and
    missing model-declared single/multi-column btree indexes
    (``CREATE INDEX IF NOT EXISTS``). Functional / expression / dialect-
    specific indexes are skipped defensively - their SQL cannot be
    reconstructed reliably from the ``Index`` object.

    Args:
        engine: The async SQLAlchemy engine (must be PostgreSQL).
        base: The declarative ``Base`` whose metadata holds every model.

    Returns:
        Total number of schema objects added (columns + indexes).
    """
    columns_added = 0
    indexes_added = 0

    async with engine.begin() as conn:
        existing_tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))

        for table in base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # New table - create_all handles it.

            existing_cols = await conn.run_sync(
                lambda sync_conn, tn=table.name: {col["name"] for col in inspect(sync_conn).get_columns(tn)}
            )

            for col in table.columns:
                if col.name in existing_cols:
                    continue

                col_type = col.type.compile(engine.dialect)

                default = ""
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

                sql = f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{col.name}" {col_type}{not_null}{default}'

                try:
                    await conn.execute(text(sql))
                    columns_added += 1
                    logger.info(
                        "PostgreSQL migration: added column %s.%s (%s)",
                        table.name,
                        col.name,
                        col_type,
                    )
                except Exception as exc:  # noqa: BLE001
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

    if columns_added > 0 or indexes_added > 0:
        logger.info(
            "PostgreSQL auto-migration complete: %d columns, %d indexes added",
            columns_added,
            indexes_added,
        )

    return columns_added + indexes_added
