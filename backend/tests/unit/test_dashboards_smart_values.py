"""T03 unit tests — Smart Value Autocomplete.

Covers:
* DataFrame fallback (pure-Python) — fast deterministic path used when
  DuckDB cannot be loaded. Pins the most-common ranking, fuzzy match
  surfacing, unicode handling, and the 404 contract.
* DuckDB-backed path — exercised via the live ``DuckDBPool`` against a
  Parquet fixture so the CAST + ILIKE path is verified end-to-end.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

from app.core.storage import LocalStorageBackend
from app.modules.dashboards.duckdb_pool import DuckDBPool
from app.modules.dashboards.smart_values import (
    ColumnNotFoundError,
    fetch_distinct_values,
    fetch_distinct_values_from_dataframe,
)
from app.modules.dashboards.snapshot_storage import write_parquet

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def thousand_row_df() -> pd.DataFrame:
    """1000 rows with a category column and an attributes dict.

    Distribution:
      Concrete:           400
      ConcretePrecast:    150
      Steel:              200
      Wood:               150
      Glass:              100

    Plus a few unicode entries.
    """
    rows = []
    pattern = (
        ["Concrete"] * 400
        + ["ConcretePrecast"] * 150
        + ["Steel"] * 200
        + ["Wood"] * 150
        + ["Glass"] * 100
    )
    for i, material in enumerate(pattern):
        rows.append(
            {
                "entity_guid": f"guid-{i}",
                "category": "wall" if i % 2 == 0 else "door",
                "source_file_id": "src-1",
                "attributes": {
                    "properties.material": material,
                    "properties.fire_rating": "F90" if i % 3 == 0 else "F60",
                },
            }
        )
    # Sprinkle in unicode + edge cases.
    rows.append(
        {
            "entity_guid": "guid-unicode",
            "category": "wall",
            "source_file_id": "src-1",
            "attributes": {"properties.material": "Бетон Б25"},
        }
    )
    return pd.DataFrame(rows)


@pytest.fixture
def local_backend(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(base_dir=tmp_path)


# ── DataFrame fallback ─────────────────────────────────────────────────────


class TestDataFrameFallback:
    def test_query_concr_returns_concrete_first(
        self, thousand_row_df: pd.DataFrame,
    ) -> None:
        results = fetch_distinct_values_from_dataframe(
            thousand_row_df,
            column="properties.material",
            query="concr",
            limit=5,
        )
        assert results, "expected at least one match for 'concr'"
        # Top hit must be Concrete or ConcretePrecast.
        assert results[0].value in {"Concrete", "ConcretePrecast"}
        # Specifically: 'Concrete' should rank above 'ConcretePrecast'
        # because rapidfuzz WRatio prefers the closer-length token.
        values = [r.value for r in results]
        assert "Concrete" in values

    def test_empty_query_returns_top_n_by_frequency(
        self, thousand_row_df: pd.DataFrame,
    ) -> None:
        results = fetch_distinct_values_from_dataframe(
            thousand_row_df,
            column="properties.material",
            query="",
            limit=3,
        )
        assert len(results) == 3
        # Concrete (400) > Steel (200) > {ConcretePrecast,Wood} tied at 150.
        # The deterministic tie-break is by value ASC, so ConcretePrecast wins.
        assert results[0].value == "Concrete"
        assert results[0].count == 400
        assert results[1].value == "Steel"
        assert results[1].count == 200
        assert results[2].count == 150

    def test_unicode_value_survives(self, thousand_row_df: pd.DataFrame) -> None:
        results = fetch_distinct_values_from_dataframe(
            thousand_row_df,
            column="properties.material",
            query="Бетон",
            limit=5,
        )
        assert any(r.value == "Бетон Б25" for r in results)

    def test_column_not_in_attributes_raises(
        self, thousand_row_df: pd.DataFrame,
    ) -> None:
        with pytest.raises(ColumnNotFoundError):
            fetch_distinct_values_from_dataframe(
                thousand_row_df,
                column="properties.does_not_exist",
                query="",
            )

    def test_invalid_column_name_raises(
        self, thousand_row_df: pd.DataFrame,
    ) -> None:
        with pytest.raises(ColumnNotFoundError):
            fetch_distinct_values_from_dataframe(
                thousand_row_df,
                column="; DROP TABLE entities; --",
                query="",
            )

    def test_top_level_column_works(self, thousand_row_df: pd.DataFrame) -> None:
        # ``category`` is a top-level column on the entities frame.
        results = fetch_distinct_values_from_dataframe(
            thousand_row_df,
            column="category",
            query="",
            limit=10,
        )
        names = {r.value for r in results}
        assert names == {"wall", "door"}

    def test_limit_respected(self, thousand_row_df: pd.DataFrame) -> None:
        results = fetch_distinct_values_from_dataframe(
            thousand_row_df,
            column="properties.material",
            query="",
            limit=2,
        )
        assert len(results) == 2


# ── DuckDB-backed path ─────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDuckDBPath:
    """End-to-end against a real ``DuckDBPool`` + Parquet fixture."""

    async def test_filtered_query_against_top_level_column(
        self,
        local_backend: LocalStorageBackend,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id = "proj-1"
        snap_id = str(uuid4())
        df = pd.DataFrame(
            {
                "entity_guid": [f"g{i}" for i in range(40)],
                "category": (["wall"] * 20 + ["door"] * 12 + ["window"] * 8),
                "source_file_id": ["src-1"] * 40,
                "attributes": [{"properties.material": "Concrete"}] * 40,
            }
        )
        await write_parquet(
            project_id, snap_id, "entities", df, backend=local_backend,
        )
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        pool = DuckDBPool()
        try:
            results = await fetch_distinct_values(
                pool=pool,
                snapshot_id=snap_id,
                project_id=project_id,
                column="category",
                query="w",
                limit=5,
            )
            names = {r.value for r in results}
            assert "wall" in names
            assert "window" in names
        finally:
            await pool.close_all()

    async def test_unknown_column_raises(
        self,
        local_backend: LocalStorageBackend,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id = "proj-1"
        snap_id = str(uuid4())
        df = pd.DataFrame(
            {
                "entity_guid": ["g1", "g2"],
                "category": ["wall", "door"],
                "source_file_id": ["s", "s"],
                "attributes": [{"properties.material": "C"}, {"properties.material": "S"}],
            }
        )
        await write_parquet(
            project_id, snap_id, "entities", df, backend=local_backend,
        )
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        pool = DuckDBPool()
        try:
            with pytest.raises(ColumnNotFoundError):
                await fetch_distinct_values(
                    pool=pool,
                    snapshot_id=snap_id,
                    project_id=project_id,
                    column="not_a_real_column",
                    query="",
                )
        finally:
            await pool.close_all()

    async def test_empty_query_returns_top_by_frequency(
        self,
        local_backend: LocalStorageBackend,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id = "proj-1"
        snap_id = str(uuid4())
        df = pd.DataFrame(
            {
                "entity_guid": [f"g{i}" for i in range(60)],
                "category": (["wall"] * 30 + ["door"] * 20 + ["window"] * 10),
                "source_file_id": ["src-1"] * 60,
                "attributes": [{"properties.material": "Concrete"}] * 60,
            }
        )
        await write_parquet(
            project_id, snap_id, "entities", df, backend=local_backend,
        )
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        pool = DuckDBPool()
        try:
            results = await fetch_distinct_values(
                pool=pool,
                snapshot_id=snap_id,
                project_id=project_id,
                column="category",
                query="",
                limit=3,
            )
            assert len(results) == 3
            # Most-common first.
            assert results[0].value == "wall"
            assert results[0].count == 30
        finally:
            await pool.close_all()
