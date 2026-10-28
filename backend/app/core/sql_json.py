# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Dialect-aware JSON access so queries run unchanged on SQLite and PostgreSQL.

Several columns (e.g. ``BIMElement.asset_info``, ``CostItem.data``) store a JSON
document as *text*. SQLite reads a scalar out of them with
``json_extract(col, '$.a.b')``; PostgreSQL has no ``json_extract`` function and
instead spells the same access ``(col::jsonb #>> '{a,b}')``.

``json_path_text(column, path)`` centralises that difference behind one construct
so call sites stay byte-for-byte identical on both backends. ``path`` keeps the
familiar SQLite ``$.a.b`` syntax everywhere, making it a drop-in replacement for
``func.json_extract(column, path)``.
"""

from __future__ import annotations

import re

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import visitors
from sqlalchemy.sql.expression import ColumnElement
from sqlalchemy.types import Text

# Path segments come exclusively from in-tree string literals (e.g. ``$.name``,
# ``$.classification.din276``). Validate anyway so a stray value can never be
# interpolated into raw SQL.
_KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _parse_path(path: str) -> tuple[str, ...]:
    """Turn a SQLite-style ``$.a.b`` path into ordered keys ``('a', 'b')``."""
    keys = tuple(k for k in path.lstrip("$").split(".") if k)
    if not keys:
        raise ValueError(f"JSON path must reference at least one key: {path!r}")
    for key in keys:
        if not _KEY_RE.match(key):
            raise ValueError(f"unsupported JSON path segment: {key!r}")
    return keys


class json_path_text(ColumnElement):  # noqa: N801 - SQL construct, lowercase by convention
    """Extract the scalar at ``path`` from a JSON(-text) column as text.

    Compiles to ``json_extract(col, '$.a.b')`` on SQLite and
    ``(col::jsonb #>> '{a,b}')`` on PostgreSQL. Both yield ``NULL`` when the
    path is absent, matching the previous SQLite-only behaviour.
    """

    inherit_cache = True
    type = Text()

    # Make the statement cache key depend on both the column and the path so two
    # different paths never collide on a cached compiled statement.
    _traverse_internals = [
        ("column", visitors.InternalTraversal.dp_clauseelement),
        ("keys", visitors.InternalTraversal.dp_plain_obj),
    ]

    def __init__(self, column: ColumnElement, path: str) -> None:
        self.column = column
        self.keys = _parse_path(path)


@compiles(json_path_text, "sqlite")
def _compile_sqlite(element: json_path_text, compiler: object, **kw: object) -> str:
    col = compiler.process(element.column, **kw)  # type: ignore[attr-defined]
    return f"json_extract({col}, '$.{'.'.join(element.keys)}')"


@compiles(json_path_text, "postgresql")
def _compile_postgresql(element: json_path_text, compiler: object, **kw: object) -> str:
    col = compiler.process(element.column, **kw)  # type: ignore[attr-defined]
    pg_path = "{" + ",".join(element.keys) + "}"
    return f"({col}::jsonb #>> '{pg_path}')"


@compiles(json_path_text)
def _compile_default(element: json_path_text, compiler: object, **kw: object) -> str:
    # Fallback for any other dialect: behave like SQLite's json_extract.
    return _compile_sqlite(element, compiler, **kw)
