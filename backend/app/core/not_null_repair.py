# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Restore a NOT NULL and its default on a column the boot heal added nullable.

The exact inverse of :func:`app.core.postgres_migrator._relax_not_null`, and it
exists for the opposite reason. The heal adds a missing column with
``ALTER TABLE ... ADD COLUMN``, and until ``ac29c96a2`` (2026-08-24) it could
only carry the model's NOT NULL when the column declared a *server* default.
A model whose default lived only in Python therefore got its column added bare:
nullable, and with no default. The revision that would have added it correctly
never runs on an ordinary install - the product moves its schema at boot and
then stamps head - so nothing tightened the column afterwards and nothing said
so. The database and the models then disagree for the life of the install.

That gap is now narrowed at the source: the heal reads a scalar Python default
through ``_literal_default`` and keeps the NOT NULL whenever it has one to
backfill with. This module is the other half, for the databases that were
bootstrapped before that landed. It is deliberately not part of the heal: the
heal only ever adds what is missing, and rewriting rows that are already there
is a different kind of act with a different risk, which is why the product
routes it through the data-repair registry where every run is recorded in
``oe_data_repair_ledger``.

Both halves of the divergence are repaired, because a heal-built database and a
migration-built one have to end up the same. Nullability is the half that
:func:`app.core.postgres_migrator.not_null_divergences` reports and the half a
reader notices; the missing ``DEFAULT`` is invisible to that check and would
leave the two build paths disagreeing about what an ``INSERT`` omitting the
column does.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Mapping

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Table and column names reach the SQL below by interpolation, because an
#: identifier cannot be a bind parameter. Every caller passes a module-level
#: constant rather than anything a user supplied, so this is a guard against a
#: future typo becoming an injection point rather than against today's callers.
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


async def tighten_not_null(
    session: AsyncSession,
    table: str,
    columns: Mapping[str, str],
) -> int:
    """Backfill NULLs, restore the ``DEFAULT``, then re-apply the ``NOT NULL``.

    Idempotent, which the data-repair registry requires: a column that is
    already ``NOT NULL`` with its default in place is read and skipped, no
    statement is issued for it, and the return value is 0. That is also the
    ordinary case - a database built by migrations, or by a heal running the
    current code, arrives here correct and this function does nothing at all.

    The order matters and is not interchangeable. ``SET NOT NULL`` scans the
    table and is refused outright if any row still holds NULL, so the backfill
    has to be the same transaction's first act. The caller must not commit
    between the two: a crash in the window would leave the rows filled and the
    constraint still missing, which is merely this defect again rather than a
    new one, but there is no reason to widen the window.

    ``SET NOT NULL`` takes an ACCESS EXCLUSIVE lock and scans the table. Every
    caller today names a table whose row count tracks a project's requirement
    or formwork register rather than its transaction history, so the scan is
    bounded. A table that grows per transaction does not belong here without
    measuring that scan first.

    Args:
        session: Open session. The caller owns the transaction and must commit;
            the registry's runner does exactly that.
        table: The table to repair, as the database names it.
        columns: Column name to the SQL literal its rows should be backfilled
            with and its ``DEFAULT`` set to - ``"''"``, ``"0"``, ``"1"``. Write
            the literal as SQL, quotes included, and take it from the revision
            that first declared the column so that the two build paths cannot
            disagree about the value.

    Returns:
        The number of rows backfilled, summed across ``columns``. Zero when
        there was nothing to do, and also zero when the columns were nullable
        but held no NULL rows - in which case the ALTERs still ran. Read it as
        "rows rewritten", not as "whether this did anything".

    Raises:
        ValueError: If a table or column name is not a plain lowercase
            identifier.
    """
    if not _IDENTIFIER.match(table):
        raise ValueError(f"not a plain table identifier: {table!r}")
    for column in columns:
        if not _IDENTIFIER.match(column):
            raise ValueError(f"not a plain column identifier: {column!r}")

    state = await session.execute(
        text(
            "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :table"
        ),
        {"table": table},
    )
    live = {name: (nullable == "YES", default) for name, nullable, default in state}
    if not live:
        # The module was never installed here, so there is no table to repair.
        # Not an error: a repair runs on every boot of every install, including
        # the ones that never had this module.
        return 0

    rewritten = 0
    for column, literal in columns.items():
        if column not in live:
            continue
        is_nullable, default = live[column]
        if not is_nullable and default is not None:
            continue  # Already what the models declare.

        backfilled = 0
        if is_nullable:
            result = await session.execute(
                text(f"UPDATE {table} SET {column} = {literal} WHERE {column} IS NULL")  # noqa: S608
            )
            backfilled = result.rowcount or 0
            rewritten += backfilled

        if default is None:
            await session.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {literal}"))

        if is_nullable:
            await session.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL"))

        logger.info(
            "Schema repair: %s.%s restored to NOT NULL DEFAULT %s (%d row(s) backfilled)",
            table,
            column,
            literal,
            backfilled,
        )

    return rewritten
