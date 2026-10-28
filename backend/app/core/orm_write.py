# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Bulk-UPDATE helpers that leave the identity map honest.

A repository that issues ``UPDATE ... WHERE id = :pk`` writes past the ORM: the
row changes but any instance the session already holds still carries the old
values. The obvious repair, ``session.expire_all()``, is correct for that row
and wrong for everything else in the session, and under asyncio it is not even
a re-fetch. Expiring marks every loaded object stale, so the next attribute
read on any of them is a lazy load attempted from async code, which raises
``MissingGreenlet``. Reading the row you just updated fails the same way.

:func:`apply_update` does the narrow thing instead. Values the caller already
knows are written straight onto the instance, and only the ones the database
had to compute are expired so they get read back.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

__all__ = ["apply_update"]


async def apply_update(
    session: AsyncSession,
    model: Any,
    pk: uuid.UUID,
    **fields: Any,
) -> None:
    """Update one row by primary key and reconcile the loaded instance.

    Assumes the single-column ``id`` primary key every platform model uses.

    A field whose value is a SQL expression has no Python value until the
    database evaluates it, so it cannot be written onto the instance and is
    expired instead. Note what expiring buys and what it does not: the value is
    correct on the next read, but that read still needs an ``await`` (for
    example ``await session.refresh(obj, ["field"])``). The gain over
    ``expire_all`` is the blast radius, not the reachability of that attribute.

    Args:
        session: The active async session owning the transaction.
        model: The mapped class to update.
        pk: Primary key of the single row to update.
        **fields: Column names to new values. Plain Python values are written
            onto the loaded instance; SQL expressions are expired for re-read.
            Passing none is a no-op, since an UPDATE with no SET clause is a
            SQL error.

    Returns:
        None. The row is updated whether or not the session holds the instance.
    """
    if not fields:
        return
    await session.execute(update(model).where(model.id == pk).values(**fields))
    await session.flush()
    instance = session.identity_map.get(identity_key(model, pk))
    if instance is None:
        # Updating by id without having loaded the object is the common case in
        # services; there is simply nothing to reconcile.
        return
    computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
    for name, value in fields.items():
        if name not in computed:
            set_committed_value(instance, name, value)
    if computed:
        session.expire(instance, computed)
