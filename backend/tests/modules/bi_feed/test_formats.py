# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Encoders and the statement-timeout mapping. No database."""

from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy.exc import DBAPIError

from app.modules.bi_feed.formats import CSV_BOM, CsvEncoder, JsonEncoder, ParquetEncoder, iso_utc
from app.modules.bi_feed.service import BiFeedService
from app.modules.bi_feed.validators import BiFeedError

PID = uuid.UUID("00000000-0000-0000-0000-000000000001")
COLUMNS = [
    ("id", "uuid"),
    ("description", "text"),
    ("quantity", "decimal"),
    ("total", "money"),
    ("currency", "text"),
    ("done", "bool"),
    ("days", "int"),
    ("due_date", "date"),
    ("updated_at", "datetime"),
]
STAMP = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
ROWS = [
    (PID, '=HYPERLINK("http://x")', Decimal("3.5"), Decimal("-1005.000000"), "EUR", True, 4, "2026-01-15", STAMP),
    (uuid.UUID(int=2), 'Concrete, "C30"\nline', Decimal("0.000001"), None, "EUR", False, None, None, None),
]


def test_csv_golden_bytes() -> None:
    enc = CsvEncoder(COLUMNS)
    enc.add(ROWS)
    expected = (
        "id,description,quantity,total,currency,done,days,due_date,updated_at\r\n"
        '00000000-0000-0000-0000-000000000001,"\'=HYPERLINK(""http://x"")",3.5,-1005.000000,EUR,true,4,'
        "2026-01-15,2026-01-02T03:04:05Z\r\n"
        '00000000-0000-0000-0000-000000000002,"Concrete, ""C30""\nline",0.000001,,EUR,false,,,\r\n'
    )
    assert enc.finish() == CSV_BOM + expected.encode("utf-8")


def test_csv_keeps_the_sign_of_a_negative_number() -> None:
    enc = CsvEncoder([("id", "uuid"), ("total", "money")])
    enc.add([(PID, Decimal("-0.5"))])
    assert enc.finish().endswith(b",-0.5\r\n")


def test_csv_header_only_when_there_are_no_rows() -> None:
    assert (
        CsvEncoder(COLUMNS).finish()
        == CSV_BOM + b"id,description,quantity,total,currency,done,days,due_date,updated_at\r\n"
    )


def test_csv_never_uses_scientific_notation() -> None:
    enc = CsvEncoder([("id", "uuid"), ("q", "decimal")])
    enc.add([(PID, Decimal("1E+3")), (PID, Decimal("0.0000001"))])
    assert b",1000\r\n" in enc.finish()


def test_parquet_round_trip_keeps_decimals_exact() -> None:
    enc = ParquetEncoder(COLUMNS)
    enc.add(ROWS[:1])
    enc.add(ROWS[1:])
    table = pq.read_table(io.BytesIO(enc.finish()))
    assert table.schema.field("total").type == pa.decimal128(38, 6)
    assert table.schema.field("updated_at").type == pa.timestamp("us", tz="UTC")
    rows = table.to_pylist()
    assert [r["total"] for r in rows] == [Decimal("-1005.000000"), None]
    assert rows[0]["quantity"] == Decimal("3.500000")
    assert rows[1]["quantity"] == Decimal("0.000001")
    assert rows[0]["updated_at"] == STAMP
    assert rows[0]["done"] is True and rows[0]["days"] == 4
    assert rows[0]["description"] == '=HYPERLINK("http://x")'  # binary format: no CSV escaping


def test_parquet_does_not_drift_on_a_large_money_value() -> None:
    value = Decimal("123456789012345678901234567890.123456")
    enc = ParquetEncoder([("id", "uuid"), ("total", "money")])
    enc.add([(PID, value)])
    assert pq.read_table(io.BytesIO(enc.finish())).to_pylist()[0]["total"] == value


def test_parquet_with_no_rows_is_a_valid_empty_file() -> None:
    table = pq.read_table(io.BytesIO(ParquetEncoder(COLUMNS).finish()))
    assert table.num_rows == 0 and table.column_names[0] == "id"


def test_json_carries_decimals_as_strings_and_reports_the_total() -> None:
    enc = JsonEncoder(COLUMNS, total=7)
    enc.add(ROWS)
    body = json.loads(enc.finish())
    assert body["total"] == 7
    assert body["columns"][3] == {"name": "total", "kind": "money"}
    first, second = body["rows"]
    assert first["total"] == "-1005.000000" and first["done"] is True and first["days"] == 4
    assert first["updated_at"] == "2026-01-02T03:04:05Z"
    assert second["total"] is None and second["days"] is None


def test_iso_utc_converts_offsets_and_assumes_utc_for_naive() -> None:
    assert iso_utc(datetime(2026, 1, 2, 4, 0, tzinfo=timezone(timedelta(hours=1)))) == "2026-01-02T03:00:00Z"
    assert iso_utc(datetime(2026, 1, 2, 3, 0)) == "2026-01-02T03:00:00Z"


class _TimedOutSession:
    async def execute(self, _stmt: object) -> None:
        raise DBAPIError("SELECT 1", {}, Exception("canceling statement due to statement timeout"))


class _BrokenSession:
    async def execute(self, _stmt: object) -> None:
        raise DBAPIError("SELECT 1", {}, Exception("connection reset"))


async def test_statement_timeout_becomes_a_named_504() -> None:
    service = BiFeedService(_TimedOutSession(), catalogue={})  # type: ignore[arg-type]
    with pytest.raises(BiFeedError) as info:
        await service._run("SELECT 1")
    assert (info.value.status_code, info.value.code) == (504, "BI_FEED_TIMEOUT")


async def test_other_database_errors_are_not_disguised_as_timeouts() -> None:
    service = BiFeedService(_BrokenSession(), catalogue={})  # type: ignore[arg-type]
    with pytest.raises(DBAPIError):
        await service._run("SELECT 1")


async def test_unknown_feed_is_a_404_with_a_code() -> None:
    with pytest.raises(BiFeedError) as info:
        BiFeedService(_TimedOutSession(), catalogue={}).feed("nope")  # type: ignore[arg-type]
    assert (info.value.status_code, info.value.code) == (404, "BI_FEED_UNKNOWN")
