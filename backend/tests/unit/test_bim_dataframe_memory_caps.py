"""BIM Parquet sidecar reads stay bounded: capped DuckDB, batch-wise pyarrow."""

import sys

import pyarrow.parquet as pq
import pytest

from app.modules.bim_hub import dataframe_store as ds


def test_duckdb_config_defaults_are_conservative(monkeypatch):
    monkeypatch.delenv("OE_BIM_DUCKDB_MEMORY_LIMIT", raising=False)
    monkeypatch.delenv("OE_BIM_DUCKDB_THREADS", raising=False)
    assert ds._duckdb_config() == {"memory_limit": "256MB", "threads": 2}


def test_duckdb_config_reads_env_and_survives_garbage(monkeypatch):
    monkeypatch.setenv("OE_BIM_DUCKDB_MEMORY_LIMIT", "512MB")
    monkeypatch.setenv("OE_BIM_DUCKDB_THREADS", "4")
    assert ds._duckdb_config() == {"memory_limit": "512MB", "threads": 4}
    monkeypatch.setenv("OE_BIM_DUCKDB_THREADS", "lots")
    assert ds._duckdb_config()["threads"] == ds.DEFAULT_DUCKDB_THREADS


def test_every_duckdb_connection_carries_the_caps(tmp_path, monkeypatch):
    duckdb = pytest.importorskip("duckdb")
    monkeypatch.delenv("OE_BIM_DUCKDB_MEMORY_LIMIT", raising=False)
    seen: list[dict] = []
    real_connect = duckdb.connect

    def spy(*args, **kwargs):
        seen.append(kwargs.get("config") or {})
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", spy)
    ds.write_dataframe("p", "m", [{"id": str(i), "Fire": f"F{i % 3}"} for i in range(9)], data_root=tmp_path)
    assert ds.query_parquet("p", "m", columns=["id"], limit=5, data_root=tmp_path)
    assert ds.column_value_counts_page("p", "m", "Fire", 10, tmp_path)["total"] == 3
    assert len(seen) >= 2
    assert all(cfg.get("memory_limit") == "256MB" and cfg.get("threads") == 2 for cfg in seen)

    # And DuckDB actually applies it (not just accepts the kwarg).
    conn = ds._duckdb_connect(duckdb)
    try:
        applied = conn.execute("SELECT current_setting('memory_limit')").fetchone()[0]
    finally:
        conn.close()
    assert applied.replace(" ", "").upper().startswith(("256MB", "244.1MIB", "244MIB"))


@pytest.fixture
def no_whole_table_reads(monkeypatch):
    """Fail if any pyarrow path loads the whole table; force tiny batches."""

    def boom(*_a, **_kw):
        raise AssertionError("pq.read_table materialises the whole sidecar")

    monkeypatch.setattr(pq, "read_table", boom)
    monkeypatch.setattr(ds, "_ARROW_BATCH_ROWS", 4)
    monkeypatch.setitem(sys.modules, "duckdb", None)


def _write(tmp_path, n=25):
    rows = [{"id": f" e{i} ", "Fire": f"F{i % 3}", "Width": i} for i in range(n)]
    ds.write_dataframe("p", "m", rows, data_root=tmp_path)


def test_pyarrow_query_walks_batches_and_stops_at_limit(tmp_path, no_whole_table_reads):
    _write(tmp_path)
    rows = ds.query_parquet(
        "p", "m", columns=["id"], filters=[{"column": "Fire", "op": "=", "value": "F1"}], limit=3, data_root=tmp_path
    )
    assert [r["id"].strip() for r in rows] == ["e1", "e4", "e7"]


def test_pyarrow_value_counts_walks_batches(tmp_path, no_whole_table_reads):
    _write(tmp_path)
    page = ds.column_value_counts_page("p", "m", "Fire", 10, tmp_path)
    assert page["total"] == 3
    assert page["items"] == [{"value": "F0", "count": 9}, {"value": "F1", "count": 8}, {"value": "F2", "count": 8}]


def test_element_cells_filter_per_batch(tmp_path, no_whole_table_reads):
    _write(tmp_path)
    columns, cells = ds.read_element_cells("p", "m", ["width"], ["e2", "e21"], data_root=tmp_path)
    assert columns == {"width": "Width"}
    assert {k: {c: str(v) for c, v in row.items()} for k, row in cells.items()} == {
        "e2": {"Width": "2"},
        "e21": {"Width": "21"},
    }
