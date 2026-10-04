"""On PostgreSQL, the streamed cost import stores what the whole-frame import stored.

The unit tests compare what the two imports hand to the database layer. This
file compares what PostgreSQL ends up holding, through the real COPY, staging
table and ``ON CONFLICT (code, region) DO NOTHING``: the same parquet goes
through the frozen whole-frame import into one region and through the stream,
in batches of three rows, into another, and the two regions must hold the same
rows. The parquet is the hard-case file from ``tests/_cwicr_import_cases.py``,
so the comparison covers items split across batches, the two long codes that
collide on their stored code (only one may survive, and it must be the same
one), and the NUL character PostgreSQL refuses.

The second test cuts both imports off with a lost connection on the same flush
and compares what each left behind. The import commits flush by flush, so it
promises a resumable prefix rather than all-or-nothing; the stream must leave
the same prefix, and a rerun must complete it to the rows of a clean import.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg2
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.modules.costs import router
from tests._cwicr_import_cases import write_hard_case_parquet
from tests._cwicr_whole_frame_import import whole_frame_import
from tests._pg import isolated_database_url

WHOLE = "ZZ_WHOLE_FRAME"
STREAM = "ZZ_STREAMED"
CLEAN = "ZZ_CLEAN"

# Every stored column but the random id, the timestamps and the region itself.
_COLUMNS = (
    "code, description, unit, rate, currency, source, classification::text, tags::text, "
    "components::text, descriptions::text, is_active, metadata::text"
)


def _sync_url(async_url: str) -> str:
    return make_url(async_url).set(drivername="postgresql+psycopg2").render_as_string(hide_password=False)


@pytest.fixture
def sync_url():
    """A throwaway schema-loaded database, as the importer's sync URL."""
    with isolated_database_url() as url:
        yield _sync_url(url)


@pytest.fixture
def parquet(tmp_path: Path) -> str:
    path = tmp_path / "hard_case.parquet"
    write_hard_case_parquet(path)
    return str(path)


def _stored(sync_url: str, region: str) -> list[tuple]:
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT {_COLUMNS} FROM oe_costs_item WHERE region = :region ORDER BY code"),  # noqa: S608
                {"region": region},
            ).all()
    finally:
        engine.dispose()
    return [tuple(row) for row in rows]


def _cut_off_on(call: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the given flush lose its connection, as a server restart would."""
    real = router._pg_bulk_insert_cost_rows
    calls = {"n": 0}

    def _flaky(url: str, rows: list[tuple]) -> int:
        calls["n"] += 1
        if calls["n"] == call:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        return real(url, rows)

    monkeypatch.setattr(router, "_pg_bulk_insert_cost_rows", _flaky)


def test_the_streamed_import_stores_the_rows_the_whole_frame_stored(
    sync_url: str, parquet: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(router, "_INSERT_FLUSH_ROWS", 4)
    monkeypatch.setattr(router, "_PARQUET_READ_ROWS", 3)

    expected = whole_frame_import(parquet, WHOLE, sync_url)
    result = router._process_and_insert_cwicr(parquet, STREAM, sync_url)

    whole, streamed = _stored(sync_url, WHOLE), _stored(sync_url, STREAM)
    assert streamed == whole
    assert len(streamed) == result["imported"] > 30
    assert {k: v for k, v in result.items() if k != "database"} == {
        k: v for k, v in expected.items() if k != "database"
    }
    # PostgreSQL refused the NUL row and the two long codes kept one row.
    assert result["failed_codes"] == ["N"]
    assert len([row for row in streamed if row[0].startswith("LLLL")]) == 1


def test_a_flush_sent_as_many_copies_stores_what_one_copy_stored(
    sync_url: str, parquet: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The COPY text of a flush goes over in bounded pieces; one row per COPY must store the same rows.

    The pieces share the flush's staging table and transaction, so the NUL row
    still fails its whole flush and gets isolated, as with a single COPY.
    """
    monkeypatch.setattr(router, "_INSERT_FLUSH_ROWS", 50)
    monkeypatch.setattr(router, "_PARQUET_READ_ROWS", 3)

    expected = whole_frame_import(parquet, WHOLE, sync_url)
    monkeypatch.setattr(router, "_COPY_CHUNK_CHARS", 1)
    # COPYs per inserter call.
    copies: list[int] = []
    as_csv = router._cost_rows_as_csv

    def _counting(rows: list[tuple], max_chars: int | None = None) -> Iterator[Any]:
        copies.append(0)
        for buf in as_csv(rows, max_chars):
            copies[-1] += 1
            yield buf

    monkeypatch.setattr(router, "_cost_rows_as_csv", _counting)
    result = router._process_and_insert_cwicr(parquet, STREAM, sync_url)

    assert _stored(sync_url, STREAM) == _stored(sync_url, WHOLE)
    assert result["imported"] == expected["imported"]
    assert result["failed_codes"] == ["N"]
    # The case is only a case if the inserter did split a flush into several COPYs.
    assert max(copies) > 1, copies


def test_an_import_cut_off_leaves_the_same_rows_and_a_rerun_completes_them(
    sync_url: str, parquet: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(router, "_INSERT_FLUSH_ROWS", 4)
    monkeypatch.setattr(router, "_PARQUET_READ_ROWS", 3)
    real = router._pg_bulk_insert_cost_rows

    # The seventh call to the inserter: past the flush that holds the NUL row,
    # whose rows are retried in halves, so the cut lands after that isolation.
    _cut_off_on(7, monkeypatch)
    with pytest.raises(psycopg2.OperationalError):
        whole_frame_import(parquet, WHOLE, sync_url)
    _cut_off_on(7, monkeypatch)
    with pytest.raises(psycopg2.OperationalError):
        router._process_and_insert_cwicr(parquet, STREAM, sync_url)

    left = _stored(sync_url, STREAM)
    assert left == _stored(sync_url, WHOLE)

    monkeypatch.setattr(router, "_pg_bulk_insert_cost_rows", real)
    resumed = router._process_and_insert_cwicr(parquet, STREAM, sync_url)
    whole_frame_import(parquet, CLEAN, sync_url)

    clean = _stored(sync_url, CLEAN)
    assert 0 < len(left) < len(clean)
    assert _stored(sync_url, STREAM) == clean
    # The rerun added only what the cut-off import had not committed.
    assert resumed["imported"] == len(clean) - len(left)
