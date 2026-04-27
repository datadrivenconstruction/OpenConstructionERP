# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""T10 unit tests — Multi-Source Project Federation.

Pins :mod:`app.modules.dashboards.federation`:

* Build path under each ``schema_align`` mode (intersect / union / strict)
* Provenance columns are always appended
* SQL whitelist rejects DDL/DML/multi-statement payloads
* Aggregate rollup produces correct counts/sums per project + snapshot
* Empty / oversized / invalid id lists are rejected
* Schema mismatch under strict mode raises 422
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pandas as pd
import pytest

from app.core.storage import LocalStorageBackend
from app.modules.dashboards.federation import (
    PROVENANCE_PROJECT_COL,
    PROVENANCE_SNAPSHOT_COL,
    EmptySnapshotListError,
    FederationParquetError,
    FederationSqlError,
    SchemaMismatchError,
    TooManySnapshotsError,
    _enforce_select_only,
    _resolve_columns,
    _validate_snapshot_ids,
    build_federated_view,
    federated_aggregate,
    federated_query,
)
from app.modules.dashboards.snapshot_storage import write_parquet

# ── Fixtures ────────────────────────────────────────────────────────────────


def _new_uuid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def project_a() -> str:
    return _new_uuid()


@pytest.fixture
def project_b() -> str:
    return _new_uuid()


@pytest.fixture
def local_backend(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(base_dir=tmp_path)


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """Build a DataFrame whose columns include the canonical
    ``entity_guid`` + ``category`` columns to match the snapshot
    layout the federation module reads."""
    return pd.DataFrame(rows)


@pytest.fixture
def snapshot_a(local_backend, project_a):
    """One snapshot with columns ``entity_guid, category, area_m2``."""
    sid = _new_uuid()
    df = _make_df(
        [
            {"entity_guid": "a1", "category": "wall", "area_m2": 10.0},
            {"entity_guid": "a2", "category": "wall", "area_m2": 12.5},
            {"entity_guid": "a3", "category": "door", "area_m2": 2.0},
        ]
    )
    asyncio.run(write_parquet(project_a, sid, "entities", df, backend=local_backend))
    return sid


@pytest.fixture
def snapshot_a2(local_backend, project_a):
    """Second snapshot in project A — same schema as ``snapshot_a``."""
    sid = _new_uuid()
    df = _make_df(
        [
            {"entity_guid": "a4", "category": "wall", "area_m2": 30.0},
            {"entity_guid": "a5", "category": "slab", "area_m2": 100.0},
        ]
    )
    asyncio.run(write_parquet(project_a, sid, "entities", df, backend=local_backend))
    return sid


@pytest.fixture
def snapshot_b_extra_col(local_backend, project_b):
    """Snapshot in project B with an EXTRA column ``volume_m3``.

    Schemas: ``entity_guid, category, area_m2, volume_m3``.
    """
    sid = _new_uuid()
    df = _make_df(
        [
            {"entity_guid": "b1", "category": "wall", "area_m2": 5.0, "volume_m3": 1.0},
            {"entity_guid": "b2", "category": "door", "area_m2": 2.0, "volume_m3": 0.4},
        ]
    )
    asyncio.run(write_parquet(project_b, sid, "entities", df, backend=local_backend))
    return sid


# ── Pure helpers ────────────────────────────────────────────────────────────


class TestValidateSnapshotIds:
    def test_empty_list_rejected(self) -> None:
        with pytest.raises(EmptySnapshotListError):
            _validate_snapshot_ids([])

    def test_invalid_uuid_rejected(self) -> None:
        with pytest.raises(EmptySnapshotListError):
            _validate_snapshot_ids(["not-a-uuid"])

    def test_too_many_rejected(self) -> None:
        ids = [str(uuid.uuid4()) for _ in range(40)]
        with pytest.raises(TooManySnapshotsError):
            _validate_snapshot_ids(ids)

    def test_happy_path(self) -> None:
        ids = [str(uuid.uuid4()) for _ in range(3)]
        out = _validate_snapshot_ids(ids)
        assert out == ids


class TestResolveColumns:
    def test_intersect_keeps_only_common_columns(self) -> None:
        cols, dtypes = _resolve_columns(
            [
                [("entity_guid", "string"), ("category", "string"), ("a", "int")],
                [("entity_guid", "string"), ("category", "string"), ("b", "int")],
            ],
            schema_align="intersect",
        )
        assert cols == ["entity_guid", "category"]
        assert "a" not in dtypes
        assert "b" not in dtypes

    def test_union_keeps_every_column(self) -> None:
        cols, dtypes = _resolve_columns(
            [
                [("entity_guid", "string"), ("a", "int")],
                [("entity_guid", "string"), ("b", "int")],
            ],
            schema_align="union",
        )
        assert sorted(cols) == ["a", "b", "entity_guid"]
        assert "a" in dtypes
        assert "b" in dtypes

    def test_union_dtype_conflict_falls_back_to_varchar(self) -> None:
        _, dtypes = _resolve_columns(
            [
                [("x", "int")],
                [("x", "double")],
            ],
            schema_align="union",
        )
        assert dtypes["x"] == "VARCHAR"

    def test_strict_raises_on_mismatch(self) -> None:
        with pytest.raises(SchemaMismatchError):
            _resolve_columns(
                [
                    [("a", "int")],
                    [("b", "int")],
                ],
                schema_align="strict",
            )


class TestSqlWhitelist:
    def test_select_allowed(self) -> None:
        _enforce_select_only("SELECT 1")

    def test_with_cte_allowed(self) -> None:
        _enforce_select_only("WITH x AS (SELECT 1) SELECT * FROM x")

    def test_empty_rejected(self) -> None:
        with pytest.raises(FederationSqlError):
            _enforce_select_only("")

    def test_attach_rejected(self) -> None:
        with pytest.raises(FederationSqlError):
            _enforce_select_only("ATTACH 'evil.db' AS evil")

    def test_install_rejected(self) -> None:
        with pytest.raises(FederationSqlError):
            _enforce_select_only("INSTALL httpfs")

    def test_drop_rejected(self) -> None:
        with pytest.raises(FederationSqlError):
            _enforce_select_only("DROP TABLE entities")

    def test_multi_statement_rejected(self) -> None:
        with pytest.raises(FederationSqlError):
            _enforce_select_only("SELECT 1; SELECT 2")

    def test_pragma_rejected(self) -> None:
        with pytest.raises(FederationSqlError):
            _enforce_select_only("PRAGMA database_list")

    def test_set_rejected(self) -> None:
        with pytest.raises(FederationSqlError):
            _enforce_select_only("SET memory_limit='1GB'")

    def test_comments_stripped_before_check(self) -> None:
        # A DROP inside a comment is removed before keyword scanning,
        # so the residual statement is a benign SELECT and is accepted.
        # The opposite scenario — a comment that PRECEDES a DROP and
        # tries to hide it — must still trip the denylist.
        _enforce_select_only("SELECT 1 /* DROP TABLE x */")
        with pytest.raises(FederationSqlError):
            _enforce_select_only("SELECT 1 -- harmless\nDROP TABLE x")


# ── Build path ──────────────────────────────────────────────────────────────


class TestBuildFederatedView:
    @pytest.mark.asyncio
    async def test_intersect_two_snapshots_one_project(
        self,
        snapshot_a,
        snapshot_a2,
        project_a,
        monkeypatch,
        local_backend,
    ) -> None:
        # Federation reads via resolve_local_parquet_path which uses the
        # global storage backend — patch it to our temp local backend.
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        view = await build_federated_view(
            [snapshot_a, snapshot_a2],
            project_id_for={snapshot_a: project_a, snapshot_a2: project_a},
            schema_align="intersect",
        )
        try:
            assert view.snapshot_count == 2
            assert view.project_count == 1
            assert PROVENANCE_PROJECT_COL in view.columns
            assert PROVENANCE_SNAPSHOT_COL in view.columns
            # Both snapshots share schema, so all original cols survive.
            assert "entity_guid" in view.columns
            assert "category" in view.columns
            assert "area_m2" in view.columns
            assert view.row_count == 5  # 3 + 2
        finally:
            await view.close()

    @pytest.mark.asyncio
    async def test_intersect_drops_columns_only_in_one(
        self,
        snapshot_a,
        snapshot_b_extra_col,
        project_a,
        project_b,
        monkeypatch,
        local_backend,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        view = await build_federated_view(
            [snapshot_a, snapshot_b_extra_col],
            project_id_for={
                snapshot_a: project_a,
                snapshot_b_extra_col: project_b,
            },
            schema_align="intersect",
        )
        try:
            # ``volume_m3`` is only in B → must be excluded under
            # intersect.
            assert "volume_m3" not in view.columns
            assert view.project_count == 2
            assert view.snapshot_count == 2
            assert view.row_count == 5  # 3 + 2
        finally:
            await view.close()

    @pytest.mark.asyncio
    async def test_union_keeps_all_columns_with_nulls(
        self,
        snapshot_a,
        snapshot_b_extra_col,
        project_a,
        project_b,
        monkeypatch,
        local_backend,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        view = await build_federated_view(
            [snapshot_a, snapshot_b_extra_col],
            project_id_for={
                snapshot_a: project_a,
                snapshot_b_extra_col: project_b,
            },
            schema_align="union",
        )
        try:
            assert "volume_m3" in view.columns
            # Rows from snapshot_a have NULL volume_m3 — verify by query.
            rows = await federated_query(
                view,
                f"SELECT volume_m3 FROM \"{view.view_name}\" WHERE entity_guid='a1'",
                limit=10,
            )
            assert len(rows) == 1
            assert rows[0]["volume_m3"] is None
        finally:
            await view.close()

    @pytest.mark.asyncio
    async def test_strict_raises_on_mismatch(
        self,
        snapshot_a,
        snapshot_b_extra_col,
        project_a,
        project_b,
        monkeypatch,
        local_backend,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        with pytest.raises(SchemaMismatchError):
            await build_federated_view(
                [snapshot_a, snapshot_b_extra_col],
                project_id_for={
                    snapshot_a: project_a,
                    snapshot_b_extra_col: project_b,
                },
                schema_align="strict",
            )

    @pytest.mark.asyncio
    async def test_missing_parquet_raises_404(
        self,
        project_a,
        monkeypatch,
        local_backend,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )
        ghost = _new_uuid()
        with pytest.raises(FederationParquetError):
            await build_federated_view(
                [ghost],
                project_id_for={ghost: project_a},
                schema_align="intersect",
            )

    @pytest.mark.asyncio
    async def test_provenance_columns_carry_correct_ids(
        self,
        snapshot_a,
        snapshot_a2,
        project_a,
        monkeypatch,
        local_backend,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        view = await build_federated_view(
            [snapshot_a, snapshot_a2],
            project_id_for={snapshot_a: project_a, snapshot_a2: project_a},
            schema_align="intersect",
        )
        try:
            rows = await federated_query(
                view,
                f'SELECT "{PROVENANCE_PROJECT_COL}", "{PROVENANCE_SNAPSHOT_COL}" '
                f'FROM "{view.view_name}"',
                limit=20,
            )
            project_ids = {r[PROVENANCE_PROJECT_COL] for r in rows}
            snapshot_ids = {r[PROVENANCE_SNAPSHOT_COL] for r in rows}
            assert project_ids == {project_a}
            assert snapshot_ids == {snapshot_a, snapshot_a2}
        finally:
            await view.close()


# ── Aggregate path ─────────────────────────────────────────────────────────


class TestFederatedAggregate:
    @pytest.mark.asyncio
    async def test_count_by_category_with_provenance(
        self,
        snapshot_a,
        snapshot_a2,
        project_a,
        monkeypatch,
        local_backend,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        view = await build_federated_view(
            [snapshot_a, snapshot_a2],
            project_id_for={snapshot_a: project_a, snapshot_a2: project_a},
            schema_align="intersect",
        )
        try:
            rows = await federated_aggregate(
                view,
                group_by=["category"],
                measure="*",
                agg="count",
                limit=20,
            )
            # Every row carries provenance.
            for r in rows:
                assert PROVENANCE_PROJECT_COL in r
                assert PROVENANCE_SNAPSHOT_COL in r
                assert "category" in r
                assert "measure_value" in r

            # Total count across rows must equal sum of source rows.
            total = sum(int(r["measure_value"]) for r in rows)
            assert total == 5
        finally:
            await view.close()

    @pytest.mark.asyncio
    async def test_sum_measure_per_snapshot(
        self,
        snapshot_a,
        snapshot_a2,
        project_a,
        monkeypatch,
        local_backend,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        view = await build_federated_view(
            [snapshot_a, snapshot_a2],
            project_id_for={snapshot_a: project_a, snapshot_a2: project_a},
            schema_align="intersect",
        )
        try:
            rows = await federated_aggregate(
                view,
                group_by=[],
                measure="area_m2",
                agg="sum",
                limit=20,
            )
            # group_by=[] still produces a row per (project, snapshot).
            assert len(rows) == 2
            # Sums per snapshot:
            #  snapshot_a    : 10 + 12.5 + 2 = 24.5
            #  snapshot_a2   : 30 + 100    = 130
            sums = sorted(float(r["measure_value"]) for r in rows)
            assert sums == [24.5, 130.0]
        finally:
            await view.close()

    @pytest.mark.asyncio
    async def test_unsafe_group_by_rejected(
        self,
        snapshot_a,
        project_a,
        monkeypatch,
        local_backend,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        view = await build_federated_view(
            [snapshot_a],
            project_id_for={snapshot_a: project_a},
            schema_align="intersect",
        )
        try:
            with pytest.raises(FederationSqlError):
                await federated_aggregate(
                    view,
                    group_by=["; DROP TABLE entities; --"],
                    measure="*",
                    agg="count",
                )
            with pytest.raises(FederationSqlError):
                await federated_aggregate(
                    view,
                    group_by=["category"],
                    measure="not_a_column",
                    agg="sum",
                )
        finally:
            await view.close()


# ── Query path ─────────────────────────────────────────────────────────────


class TestFederatedQuery:
    @pytest.mark.asyncio
    async def test_select_returns_rows(
        self,
        snapshot_a,
        project_a,
        monkeypatch,
        local_backend,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        view = await build_federated_view(
            [snapshot_a],
            project_id_for={snapshot_a: project_a},
            schema_align="intersect",
        )
        try:
            rows = await federated_query(
                view,
                f'SELECT entity_guid, category FROM "{view.view_name}" '
                f"ORDER BY entity_guid",
                limit=10,
            )
            guids = [r["entity_guid"] for r in rows]
            assert guids == ["a1", "a2", "a3"]
        finally:
            await view.close()

    @pytest.mark.asyncio
    async def test_query_after_close_raises(
        self,
        snapshot_a,
        project_a,
        monkeypatch,
        local_backend,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        view = await build_federated_view(
            [snapshot_a],
            project_id_for={snapshot_a: project_a},
            schema_align="intersect",
        )
        await view.close()
        with pytest.raises(Exception):
            await federated_query(
                view, f'SELECT 1 FROM "{view.view_name}"', limit=10,
            )

    @pytest.mark.asyncio
    async def test_query_rejects_drop(
        self,
        snapshot_a,
        project_a,
        monkeypatch,
        local_backend,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        view = await build_federated_view(
            [snapshot_a],
            project_id_for={snapshot_a: project_a},
            schema_align="intersect",
        )
        try:
            with pytest.raises(FederationSqlError):
                await federated_query(
                    view, "DROP TABLE entities", limit=10,
                )
        finally:
            await view.close()
