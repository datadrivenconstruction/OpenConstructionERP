"""T04 unit tests — Cascade Filter Engine.

Covers the pure DataFrame path AND the DuckDB-backed path against a
real Parquet fixture, mirroring the structure of
``test_dashboards_smart_values.py`` so the two systems share testing
conventions.

Slice map:

* DataFrame fallback:
    - single-filter cascade
    - multi-filter cascade
    - empty-array selection ignored
    - no-match returns empty list
    - q substring filter intersects with selection
    - selected column not in df → InvalidSelectedColumnError
    - target column not in df → ColumnNotFoundError
* DuckDB:
    - end-to-end cascade against entities.parquet
    - count rollup correctness (matched vs total)
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

from app.core.storage import LocalStorageBackend
from app.modules.dashboards.cascade import (
    CascadeMatch,
    InvalidSelectedColumnError,
    count_filtered_rows,
    fetch_cascade_values,
    fetch_cascade_values_from_dataframe,
)
from app.modules.dashboards.duckdb_pool import DuckDBPool
from app.modules.dashboards.smart_values import ColumnNotFoundError
from app.modules.dashboards.snapshot_storage import write_parquet

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def cascade_df() -> pd.DataFrame:
    """A small but heterogeneous snapshot.

    Distribution (designed so cascade interactions are unambiguous):

    | category  | supplier | material         | n |
    |-----------|----------|------------------|---|
    | Concrete  | AcmeCo   | C30/37           | 5 |
    | Concrete  | AcmeCo   | C25/30           | 3 |
    | Concrete  | BetaCo   | C30/37           | 4 |
    | Steel     | AcmeCo   | S235             | 6 |
    | Steel     | GammaCo  | S355             | 2 |
    | Wood      | BetaCo   | Pine             | 1 |
    """
    rows: list[dict] = []
    pattern: list[tuple[str, str, str]] = (
        [("Concrete", "AcmeCo", "C30/37")] * 5
        + [("Concrete", "AcmeCo", "C25/30")] * 3
        + [("Concrete", "BetaCo", "C30/37")] * 4
        + [("Steel", "AcmeCo", "S235")] * 6
        + [("Steel", "GammaCo", "S355")] * 2
        + [("Wood", "BetaCo", "Pine")] * 1
    )
    for i, (cat, sup, mat) in enumerate(pattern):
        rows.append(
            {
                "entity_guid": f"g{i}",
                "category": cat,
                "source_file_id": "src-1",
                "attributes": {"supplier": sup, "material": mat},
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def local_backend(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(base_dir=tmp_path)


# ── DataFrame fallback ─────────────────────────────────────────────────────


class TestDataFrameCascade:
    def test_single_filter_narrows_target(self, cascade_df: pd.DataFrame) -> None:
        # Pick category=Concrete; the supplier picker should show only
        # AcmeCo (8) and BetaCo (4), NOT GammaCo or unrelated suppliers.
        results = fetch_cascade_values_from_dataframe(
            cascade_df,
            selected={"category": ["Concrete"]},
            target_column="supplier",
        )
        names = {m.value: m.count for m in results}
        assert names == {"AcmeCo": 8, "BetaCo": 4}

    def test_multi_filter_intersection(self, cascade_df: pd.DataFrame) -> None:
        # Concrete AND AcmeCo → only the C30/37 (5) and C25/30 (3) rows.
        results = fetch_cascade_values_from_dataframe(
            cascade_df,
            selected={"category": ["Concrete"], "supplier": ["AcmeCo"]},
            target_column="material",
        )
        materials = {m.value: m.count for m in results}
        assert materials == {"C30/37": 5, "C25/30": 3}

    def test_empty_array_selection_ignored(self, cascade_df: pd.DataFrame) -> None:
        # supplier=[] must be ignored, NOT treated as "no rows match".
        with_empty = fetch_cascade_values_from_dataframe(
            cascade_df,
            selected={"category": ["Concrete"], "supplier": []},
            target_column="material",
        )
        without_empty = fetch_cascade_values_from_dataframe(
            cascade_df,
            selected={"category": ["Concrete"]},
            target_column="material",
        )
        assert [m.to_dict() for m in with_empty] == [
            m.to_dict() for m in without_empty
        ]

    def test_no_match_returns_empty(self, cascade_df: pd.DataFrame) -> None:
        # No rows have category=Steel AND supplier=BetaCo.
        results = fetch_cascade_values_from_dataframe(
            cascade_df,
            selected={"category": ["Steel"], "supplier": ["BetaCo"]},
            target_column="material",
        )
        assert results == []

    def test_q_filter_intersected_with_selection(
        self, cascade_df: pd.DataFrame,
    ) -> None:
        # Concrete + q="C30" → only the two C30/37 entries (Acme + Beta).
        results = fetch_cascade_values_from_dataframe(
            cascade_df,
            selected={"category": ["Concrete"]},
            target_column="material",
            query="C30",
        )
        names = {m.value: m.count for m in results}
        assert names == {"C30/37": 9}  # 5 (Acme) + 4 (Beta)

    def test_target_column_excluded_from_own_filter(
        self, cascade_df: pd.DataFrame,
    ) -> None:
        # When the user has chips on the supplier filter and is opening
        # the supplier picker again, the supplier filter must not gate
        # its own values — otherwise the picker would only show what's
        # already selected.
        results = fetch_cascade_values_from_dataframe(
            cascade_df,
            selected={"supplier": ["AcmeCo"]},
            target_column="supplier",
        )
        names = {m.value for m in results}
        # All four suppliers visible.
        assert names == {"AcmeCo", "BetaCo", "GammaCo"}

    def test_selected_column_not_in_snapshot_raises(
        self, cascade_df: pd.DataFrame,
    ) -> None:
        with pytest.raises(InvalidSelectedColumnError):
            fetch_cascade_values_from_dataframe(
                cascade_df,
                selected={"phantom": ["x"]},
                target_column="material",
            )

    def test_target_column_not_in_snapshot_raises(
        self, cascade_df: pd.DataFrame,
    ) -> None:
        with pytest.raises(ColumnNotFoundError):
            fetch_cascade_values_from_dataframe(
                cascade_df,
                selected={"category": ["Concrete"]},
                target_column="not_a_real_column",
            )

    def test_invalid_target_identifier_raises(
        self, cascade_df: pd.DataFrame,
    ) -> None:
        with pytest.raises(ColumnNotFoundError):
            fetch_cascade_values_from_dataframe(
                cascade_df,
                selected={},
                target_column="; DROP TABLE entities; --",
            )

    def test_limit_respected(self, cascade_df: pd.DataFrame) -> None:
        results = fetch_cascade_values_from_dataframe(
            cascade_df,
            selected={},
            target_column="material",
            limit=2,
        )
        assert len(results) == 2

    def test_oversized_selection_array_rejected(
        self, cascade_df: pd.DataFrame,
    ) -> None:
        many = [f"v{i}" for i in range(1000)]
        with pytest.raises(InvalidSelectedColumnError):
            fetch_cascade_values_from_dataframe(
                cascade_df,
                selected={"category": many},
                target_column="material",
            )

    def test_cascade_match_to_dict(self) -> None:
        m = CascadeMatch(value="x", count=3)
        assert m.to_dict() == {"value": "x", "count": 3}


# ── DuckDB-backed path ─────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDuckDBCascade:
    """End-to-end against a real :class:`DuckDBPool` + Parquet fixture."""

    async def _write(
        self,
        backend: LocalStorageBackend,
        df: pd.DataFrame,
        monkeypatch: pytest.MonkeyPatch,
    ) -> tuple[str, str]:
        project_id = "proj-cascade"
        snapshot_id = str(uuid4())
        await write_parquet(
            project_id, snapshot_id, "entities", df, backend=backend,
        )
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: backend,
        )
        return project_id, snapshot_id

    async def test_cascade_against_real_parquet(
        self,
        local_backend: LocalStorageBackend,
        cascade_df: pd.DataFrame,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id, snap_id = await self._write(
            local_backend, cascade_df, monkeypatch,
        )
        pool = DuckDBPool()
        try:
            results = await fetch_cascade_values(
                pool=pool,
                snapshot_id=snap_id,
                project_id=project_id,
                selected={"category": ["Concrete"]},
                target_column="supplier",
            )
            names = {r.value: r.count for r in results}
            assert names == {"AcmeCo": 8, "BetaCo": 4}
        finally:
            await pool.close_all()

    async def test_count_rollup_matches_selection(
        self,
        local_backend: LocalStorageBackend,
        cascade_df: pd.DataFrame,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id, snap_id = await self._write(
            local_backend, cascade_df, monkeypatch,
        )
        pool = DuckDBPool()
        try:
            # Concrete only → 5+3+4 = 12 of 21 rows.
            matched, total = await count_filtered_rows(
                pool=pool,
                snapshot_id=snap_id,
                project_id=project_id,
                selected={"category": ["Concrete"]},
            )
            assert total == 21
            assert matched == 12

            # Empty selection → matched == total.
            matched_empty, total_empty = await count_filtered_rows(
                pool=pool,
                snapshot_id=snap_id,
                project_id=project_id,
                selected={},
            )
            assert matched_empty == total_empty == 21
        finally:
            await pool.close_all()

    async def test_unknown_target_column_raises(
        self,
        local_backend: LocalStorageBackend,
        cascade_df: pd.DataFrame,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id, snap_id = await self._write(
            local_backend, cascade_df, monkeypatch,
        )
        pool = DuckDBPool()
        try:
            with pytest.raises(ColumnNotFoundError):
                await fetch_cascade_values(
                    pool=pool,
                    snapshot_id=snap_id,
                    project_id=project_id,
                    selected={},
                    target_column="not_a_real_column",
                )
        finally:
            await pool.close_all()

    async def test_unknown_selected_column_raises(
        self,
        local_backend: LocalStorageBackend,
        cascade_df: pd.DataFrame,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id, snap_id = await self._write(
            local_backend, cascade_df, monkeypatch,
        )
        pool = DuckDBPool()
        try:
            with pytest.raises(InvalidSelectedColumnError):
                await fetch_cascade_values(
                    pool=pool,
                    snapshot_id=snap_id,
                    project_id=project_id,
                    selected={"phantom": ["x"]},
                    target_column="supplier",
                )
        finally:
            await pool.close_all()
