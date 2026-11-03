# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Encoders that turn feed rows into CSV, Parquet or JSON bytes.

Each encoder takes rows as tuples in column order, in chunks, and returns the
whole body from :meth:`finish`, so memory is bounded by the encoded size and
never by a list of ORM objects. Values follow one contract in every format:
money and decimals are exact (strings in CSV and JSON, ``decimal128(38,6)`` in
Parquet), instants are ISO 8601 in UTC, booleans are ``true``/``false``.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal
from typing import Any

from app.core.csv_safety import neutralise_formula
from app.modules.bi_feed.feeds import DECIMAL_PRECISION, DECIMAL_SCALE, NUMERIC_KINDS

CSV_BOM = b"\xef\xbb\xbf"
_QUANTUM = Decimal(1).scaleb(-DECIMAL_SCALE)
_CONTEXT = Context(prec=DECIMAL_PRECISION, rounding=ROUND_HALF_EVEN)


def iso_utc(value: datetime) -> str:
    """ISO 8601 UTC with a Z suffix; a naive value is taken as UTC."""
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.strftime("%Y-%m-%dT%H:%M:%SZ")


def decimal_text(value: Decimal) -> str:
    """Plain dot notation, never scientific, without trailing zeros beyond what was stored."""
    return format(value, "f")


def to_text(value: Any, kind: str) -> str | None:
    """The text form of one cell for CSV and JSON; ``None`` stays ``None``."""
    if value is None:
        return None
    if kind in NUMERIC_KINDS:
        return decimal_text(value if isinstance(value, Decimal) else Decimal(str(value)))
    if kind == "datetime" and isinstance(value, datetime):
        return iso_utc(value)
    if kind == "date" and isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


class CsvEncoder:
    """UTF-8 with a BOM so Excel opens it as UTF-8; CRLF line ends; formulas neutralised in text cells."""

    media_type = "text/csv; charset=utf-8"
    extension = "csv"

    def __init__(self, columns: list[tuple[str, str]]) -> None:
        self._kinds = [kind for _, kind in columns]
        self._buffer = io.StringIO(newline="")
        self._writer = csv.writer(self._buffer, lineterminator="\r\n")
        self._chunks: list[bytes] = [CSV_BOM]
        self._writer.writerow([name for name, _ in columns])
        self._flush()

    def _flush(self) -> None:
        self._chunks.append(self._buffer.getvalue().encode("utf-8"))
        self._buffer.seek(0)
        self._buffer.truncate()

    def add(self, rows: list[tuple[Any, ...]]) -> None:
        """Append a chunk of rows."""
        for row in rows:
            cells = []
            for value, kind in zip(row, self._kinds, strict=True):
                text = to_text(value, kind)
                if text is None:
                    cells.append("")
                else:
                    # Numbers and dates are written as-is: a leading minus is a sign, not a formula.
                    cells.append(neutralise_formula(text) if kind == "text" else text)
            self._writer.writerow(cells)
        self._flush()

    def finish(self) -> bytes:
        return b"".join(self._chunks)


class JsonEncoder:
    """``{"columns": [...], "rows": [{...}]}``; exact decimals travel as strings."""

    media_type = "application/json"
    extension = "json"

    def __init__(self, columns: list[tuple[str, str]], *, total: int | None = None) -> None:
        self._columns = columns
        self._total = total
        self._rows: list[dict[str, Any]] = []

    def add(self, rows: list[tuple[Any, ...]]) -> None:
        for row in rows:
            record: dict[str, Any] = {}
            for value, (name, kind) in zip(row, self._columns, strict=True):
                if kind in ("int", "bool") and value is not None:
                    record[name] = value
                else:
                    record[name] = to_text(value, kind)
            self._rows.append(record)

    def finish(self) -> bytes:
        body = {
            "columns": [{"name": n, "kind": k} for n, k in self._columns],
            "total": self._total if self._total is not None else len(self._rows),
            "rows": self._rows,
        }
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class ParquetEncoder:
    """Parquet with exact ``decimal128(38,6)`` money; written in row groups as chunks arrive."""

    media_type = "application/vnd.apache.parquet"
    extension = "parquet"

    def __init__(self, columns: list[tuple[str, str]]) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        self._pa = pa
        self._columns = columns
        self._schema = pa.schema([(name, self._arrow_type(kind)) for name, kind in columns])
        self._sink = io.BytesIO()
        self._writer = pq.ParquetWriter(self._sink, self._schema, compression="zstd")

    def _arrow_type(self, kind: str) -> Any:
        pa = self._pa
        if kind in NUMERIC_KINDS:
            return pa.decimal128(DECIMAL_PRECISION, DECIMAL_SCALE)
        return {
            "int": pa.int64(),
            "bool": pa.bool_(),
            "datetime": pa.timestamp("us", tz="UTC"),
        }.get(kind, pa.string())

    def _cell(self, value: Any, kind: str) -> Any:
        if value is None:
            return None
        if kind in NUMERIC_KINDS:
            number = value if isinstance(value, Decimal) else Decimal(str(value))
            return number.quantize(_QUANTUM, context=_CONTEXT)
        if kind == "datetime" and isinstance(value, datetime):
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value
        if kind in ("int", "bool"):
            return value
        return to_text(value, kind)

    def add(self, rows: list[tuple[Any, ...]]) -> None:
        if not rows:
            return
        arrays = [
            self._pa.array([self._cell(row[i], kind) for row in rows], type=self._schema.field(i).type)
            for i, (_, kind) in enumerate(self._columns)
        ]
        self._writer.write_table(self._pa.Table.from_arrays(arrays, schema=self._schema))

    def finish(self) -> bytes:
        self._writer.close()
        return self._sink.getvalue()


ENCODERS = {"csv": CsvEncoder, "parquet": ParquetEncoder, "json": JsonEncoder}
