"""Widen ``submitted_by_org`` to 255 characters on databases that predate it.

``Submittal.submitted_by_org`` holds a contact id or a typed company name. It
was declared ``String(36)`` while the API has always accepted 255 characters,
so PostgreSQL refused any name longer than a UUID. The model now declares 255,
and revision ``v67_statutory_tax_lines_and_submittal_register`` widens the
column for a database that is migrated.

Neither reaches an installation that is upgraded in place. ``create_all`` skips
a table that already exists, the auto-migrator that stands in for Alembic on
module tables only ever issues ``ADD COLUMN`` / ``ADD CONSTRAINT`` / ``CREATE
INDEX``, and such an installation is stamped at the head revision without the
revision being run. It would keep the 36 character column and keep the refusal.

So the widening happens here, in the boot path, next to the ``classified_at``
widening that lives there for the same reason. Lengthening a ``varchar`` is a
catalogue change in PostgreSQL: no row is rewritten and no stored value can
fail to fit.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

_TABLE = "oe_submittals_submittal"
_COLUMN = "submitted_by_org"
_LENGTH = 255

# Fixed table and column names, no user input reaches this statement.
_WIDEN = f'ALTER TABLE "{_TABLE}" ALTER COLUMN "{_COLUMN}" TYPE VARCHAR({_LENGTH})'  # noqa: S608


async def widen_submitted_by_org(conn: AsyncConnection) -> int:
    """Lengthen a ``submitted_by_org`` narrower than 255 characters.

    Args:
        conn: An open async PostgreSQL connection (inside a transaction).

    Returns:
        1 when the column was widened, 0 when there was nothing to do, which is
        the case on a fresh database and on every boot after the first.
    """
    if conn.dialect.name != "postgresql":
        return 0

    has_table = await conn.run_sync(lambda c: inspect(c).has_table(_TABLE))
    if not has_table:
        # Fresh database: create_all has not built the table yet, and it will
        # build the column at its declared length, so there is nothing to widen.
        return 0

    columns = await conn.run_sync(lambda c: inspect(c).get_columns(_TABLE))
    column = next((col for col in columns if col["name"] == _COLUMN), None)
    if column is None:
        return 0

    # The reflected length asks the database rather than assuming from the
    # version we upgraded from. ``None`` is a column with no limit at all,
    # which already holds anything the API accepts.
    length = getattr(column["type"], "length", None)
    if length is None or length >= _LENGTH:
        return 0

    await conn.execute(text(_WIDEN))
    logger.info("Widened %s.%s from %s to %s characters", _TABLE, _COLUMN, length, _LENGTH)
    return 1
