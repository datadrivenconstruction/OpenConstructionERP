# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Dialect-aware numeric coercion for money-as-text columns.

Several monetary fields are stored as ``String`` for SQLite portability
(``CostItem.rate``, ``CatalogResource.base_price``, ``BudgetLine.planned_amount``,
``Position.total`` …) and then cast to a float inside SQL for range filters and
``SUM`` rollups. ``CAST(text AS REAL)`` is forgiving on SQLite - a non-numeric
string like ``""`` or ``"N/A"`` silently becomes ``0.0`` - but PostgreSQL's
``CAST(text AS DOUBLE PRECISION)`` raises ``invalid input syntax for type double
precision`` and aborts the whole query. One malformed legacy/seeded row is enough
to 500 a dashboard on PostgreSQL while it worked on SQLite.

``numeric_value(column)`` centralises a *tolerant* numeric coercion that behaves
identically on both backends: a clean decimal (optionally signed, with optional
fraction and exponent) is converted; anything else - including the empty string -
becomes ``0`` (matching SQLite's existing behaviour) instead of raising. ``NULL``
stays ``NULL`` on both dialects. Use it as a drop-in replacement for
``cast(column, Float)`` at SQL filter/aggregation sites.
"""

from __future__ import annotations

from sqlalchemy import Float
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import visitors
from sqlalchemy.sql.expression import ColumnElement

#: PostgreSQL POSIX regex matching a clean numeric literal (optional sign,
#: optional fraction, optional exponent). Strings that fail this are treated as 0
#: rather than fed to ``::double precision`` (which would raise).
_PG_NUMERIC_RE = r"^\s*[-+]?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?\s*$"


class numeric_value(ColumnElement):  # noqa: N801 - SQL construct, lowercase by convention
    """Coerce a text column to a float, tolerating non-numeric content.

    Compiles to ``CAST(col AS REAL)`` on SQLite (already tolerant) and to a
    guarded ``CASE WHEN col ~ '<numeric>' THEN col::double precision ELSE 0 END``
    on PostgreSQL so a malformed row can never abort the query.
    """

    inherit_cache = True
    type = Float()

    _traverse_internals = [
        ("column", visitors.InternalTraversal.dp_clauseelement),
    ]

    def __init__(self, column: ColumnElement) -> None:
        self.column = column


@compiles(numeric_value, "postgresql")
def _compile_postgresql(element: numeric_value, compiler: object, **kw: object) -> str:
    col = compiler.process(element.column, **kw)  # type: ignore[attr-defined]
    return f"(CASE WHEN {col} ~ '{_PG_NUMERIC_RE}' THEN ({col})::double precision ELSE 0 END)"


@compiles(numeric_value, "sqlite")
def _compile_sqlite(element: numeric_value, compiler: object, **kw: object) -> str:
    col = compiler.process(element.column, **kw)  # type: ignore[attr-defined]
    return f"CAST({col} AS REAL)"


@compiles(numeric_value)
def _compile_default(element: numeric_value, compiler: object, **kw: object) -> str:
    # Any other dialect: behave like SQLite's tolerant CAST.
    return _compile_sqlite(element, compiler, **kw)
