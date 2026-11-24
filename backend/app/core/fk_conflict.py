# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Turn a foreign-key violation into a 409 body that names the blocking records.

A delete refused by the database because other records still point at the row
used to surface as an opaque 500. The client gets ``code="fk_conflict"`` and the
referencing table so the UI can say which linked records block the delete.
"""

import re

from sqlalchemy.exc import IntegrityError

# PostgreSQL: update or delete on table "a" violates foreign key constraint "fk" on table "b"
_PG_FK = re.compile(r'violates foreign key constraint "[^"]*" on table "(?P<table>[^"]+)"')
_SQLITE_FK = "FOREIGN KEY constraint failed"
_TABLE_PREFIX = re.compile(r"^oe_")


def _label(table: str) -> str:
    """Return a readable label for a table name, e.g. ``oe_contracts_contract`` -> ``contracts contract``."""
    return _TABLE_PREFIX.sub("", table).replace("_", " ").strip()


def foreign_key_conflict(exc: BaseException) -> dict[str, str | None] | None:
    """Return a 409 body when ``exc`` (or its cause chain) is a foreign-key violation.

    Args:
        exc: Any exception raised while handling a request.

    Returns:
        ``{"detail", "code", "blocked_by"}`` for FK violations, else ``None``.
        ``blocked_by`` is a readable table label, or ``None`` when the driver
        does not name the referencing table (SQLite).
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, IntegrityError):
            text = str(current.orig) if current.orig is not None else str(current)
            match = _PG_FK.search(text)
            if match or _SQLITE_FK in text:
                blocked_by = _label(match.group("table")) if match else None
                detail = (
                    f"This record is still referenced by {blocked_by} records; remove or relink them first."
                    if blocked_by
                    else "This record is still referenced by other records; remove or relink them first."
                )
                return {"detail": detail, "code": "fk_conflict", "blocked_by": blocked_by}
        current = current.__cause__ or current.__context__
    return None
