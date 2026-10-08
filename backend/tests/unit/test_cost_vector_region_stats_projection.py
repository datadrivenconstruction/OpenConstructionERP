"""Per-region vector stats count a projected ``region`` column, never the vectors."""

import pyarrow as pa

from app.modules.costs import router as cost_router


class _Query:
    def __init__(self, table: pa.Table, log: list) -> None:
        self._table = table
        self._log = log

    def select(self, cols):
        self._log.append(("select", list(cols)))
        self._table = self._table.select(cols)
        return self

    def limit(self, n):
        self._log.append(("limit", n))
        return self

    def to_arrow(self):
        return self._table


class _FakeLanceTable:
    def __init__(self, table: pa.Table) -> None:
        self._table = table
        self.log: list = []
        self.schema = table.schema

    def count_rows(self):
        return self._table.num_rows

    def search(self, *args):
        assert not args, "region stats must scan, not run a vector query"
        return _Query(self._table, self.log)

    def to_pandas(self):  # pragma: no cover - the regression this test pins
        raise AssertionError("to_pandas() materialises every embedding")

    to_arrow = to_pandas


def _table(regions):
    vectors = pa.array([[0.1] * 4 for _ in regions], type=pa.list_(pa.float32(), 4))
    return pa.table({"id": [str(i) for i in range(len(regions))], "region": regions, "vector": vectors})


def test_counts_by_region_from_a_region_only_projection():
    tbl = _FakeLanceTable(_table(["DE_BERLIN", "USA_USD", "DE_BERLIN", None, "", "DE_BERLIN"]))
    assert cost_router._lancedb_region_counts(tbl) == [
        {"region": "DE_BERLIN", "count": 3},
        {"region": "USA_USD", "count": 1},
    ]
    assert ("select", ["region"]) in tbl.log
    assert ("limit", 6) in tbl.log


def test_table_without_region_or_rows_returns_empty():
    assert cost_router._lancedb_region_counts(_FakeLanceTable(pa.table({"id": ["a"]}))) == []
    assert cost_router._lancedb_region_counts(_FakeLanceTable(_table([]))) == []
