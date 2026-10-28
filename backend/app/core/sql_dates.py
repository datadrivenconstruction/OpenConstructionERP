# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Dialect-aware date arithmetic for SQL expressions.

PostgreSQL subtracts one ``DATE`` from another and gives whole days as an
integer. SQLite has no date type at all - a ``Date`` column is stored as the
text ``YYYY-MM-DD`` - so the same question has to be asked through
``julianday``. The two spellings are not interchangeable, and writing either
one directly at a call site makes that call site work on one backend only.

``days_since(column)`` centralises the one form the platform needs: how many
whole days have passed since a stored date. It is the shape an aging question
takes when the answer has to stay correct in a definition somebody saved months
ago - "older than 90 days" keeps meaning what it said, where "before
2026-06-01" quietly stops being the question that was asked.

``NULL`` stays ``NULL`` on both backends, which matters more here than it looks:
an unrecorded date is not a fresh one, and a caller that reads an absent price
date as zero days old would report the stalest rows as the safest.
"""

from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import visitors
from sqlalchemy.sql.expression import ColumnElement


class days_since(ColumnElement):  # noqa: N801 - SQL construct, lowercase by convention
    """Whole days from a stored date up to today.

    Compiles to ``CURRENT_DATE - col`` on PostgreSQL and to a ``julianday``
    difference against the start of today on SQLite, so both count whole days
    rather than one counting a fraction of one. A date in the future gives a
    negative count on both, which is the honest reading of a price dated
    tomorrow.
    """

    inherit_cache = True
    type = Integer()

    _traverse_internals = [
        ("column", visitors.InternalTraversal.dp_clauseelement),
    ]

    def __init__(self, column: ColumnElement) -> None:
        self.column = column


@compiles(days_since, "postgresql")
def _compile_postgresql(element: days_since, compiler: object, **kw: object) -> str:
    col = compiler.process(element.column, **kw)  # type: ignore[attr-defined]
    return f"(CURRENT_DATE - {col})"


@compiles(days_since, "sqlite")
def _compile_sqlite(element: days_since, compiler: object, **kw: object) -> str:
    col = compiler.process(element.column, **kw)  # type: ignore[attr-defined]
    # ``date('now')`` rather than ``'now'`` so the difference is whole days.
    # Against the bare ``'now'`` every reading would carry the fraction of
    # today that has elapsed, and a price set this morning would be "0.4 days
    # old" on SQLite and "0" on PostgreSQL for the same row.
    return f"CAST(julianday(date('now')) - julianday({col}) AS INTEGER)"


@compiles(days_since)
def _compile_default(element: days_since, compiler: object, **kw: object) -> str:
    # Any other dialect: SQLite's spelling is the more portable of the two.
    return _compile_sqlite(element, compiler, **kw)
