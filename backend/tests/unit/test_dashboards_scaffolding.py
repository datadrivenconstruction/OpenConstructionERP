"""T00 smoke tests for the dashboards / compliance_ai / cost_match modules.

These tests assert the *wiring* is correct — manifests load, message
bundles round-trip en/de/ru, snapshot-storage helpers compose the
expected keys, and the DuckDB pool can open + query + invalidate a
read-only connection against a tiny Parquet fixture.

None of these tests exercise feature behaviour (T01 onwards does that);
they exist so we catch scaffolding regressions (missing file, import
error, missing locale key) in the fast unit-suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

from app.core.storage import LocalStorageBackend
from app.modules.compliance_ai.manifest import manifest as compliance_manifest
from app.modules.cost_match.manifest import manifest as cost_match_manifest
from app.modules.dashboards.duckdb_pool import (
    DuckDBPool,
    SnapshotHasNoEntitiesError,
)
from app.modules.dashboards.manifest import manifest as dashboards_manifest
from app.modules.dashboards.snapshot_storage import (
    ParquetNotLocalError,
    delete_snapshot_files,
    manifest_key,
    parquet_key,
    read_manifest,
    resolve_local_parquet_path,
    snapshot_prefix,
    write_manifest,
    write_parquet,
)

# ── Manifests ──────────────────────────────────────────────────────────────


class TestManifests:
    def test_dashboards_manifest_fields(self) -> None:
        assert dashboards_manifest.name == "oe_dashboards"
        assert dashboards_manifest.category == "core"
        assert dashboards_manifest.enabled is True
        # Dependencies that must exist — loader will error otherwise.
        assert "oe_projects" in dashboards_manifest.depends
        assert "oe_users" in dashboards_manifest.depends

    def test_compliance_ai_depends_on_dashboards_and_core_validation(self) -> None:
        assert compliance_manifest.name == "oe_compliance_ai"
        assert "oe_dashboards" in compliance_manifest.depends
        # oe_ai is optional — semantic / LLM features degrade gracefully.
        assert "oe_ai" in compliance_manifest.optional_depends

    def test_cost_match_depends_on_costs_and_dashboards(self) -> None:
        assert cost_match_manifest.name == "oe_cost_match"
        assert "oe_costs" in cost_match_manifest.depends
        assert "oe_dashboards" in cost_match_manifest.depends


# ── Routers load ────────────────────────────────────────────────────────────


class TestRouters:
    def test_dashboards_router_is_importable_and_mounts_health(self) -> None:
        from app.modules.dashboards.router import router

        # The module loader mounts at /api/v1/dashboards — the router itself
        # must not double-prefix, so /_health lives at the router root.
        paths = {route.path for route in router.routes}
        assert "/_health" in paths

    def test_compliance_router_is_importable(self) -> None:
        from app.modules.compliance_ai.router import router

        paths = {route.path for route in router.routes}
        assert "/compliance-ai/_health" in paths

    def test_cost_match_router_is_importable(self) -> None:
        from app.modules.cost_match.router import router

        paths = {route.path for route in router.routes}
        assert "/cost-match/_health" in paths


# ── i18n bundles ───────────────────────────────────────────────────────────


class TestDashboardsMessages:
    def test_default_locale_resolves(self) -> None:
        from app.modules.dashboards import messages

        out = messages.translate("snapshot.label.required")
        assert out != "snapshot.label.required"  # not fell back to raw key
        assert "label" in out.lower()

    def test_de_ru_coverage_matches_en(self) -> None:
        """Every key in en.json must exist in de.json and ru.json.

        Mirrors the validation i18n parity test — the release gate is
        "no missing translations slipping into a release".
        """
        from app.modules.dashboards import messages

        messages.reload_bundle()
        en_keys = {
            k for k in _load_bundle_keys("dashboards", "en")
        }
        de_keys = {k for k in _load_bundle_keys("dashboards", "de")}
        ru_keys = {k for k in _load_bundle_keys("dashboards", "ru")}
        assert en_keys == de_keys, f"DE missing: {en_keys - de_keys}; DE extra: {de_keys - en_keys}"
        assert en_keys == ru_keys, f"RU missing: {en_keys - ru_keys}; RU extra: {ru_keys - en_keys}"

    def test_placeholder_substitution(self) -> None:
        from app.modules.dashboards import messages

        out = messages.translate(
            "snapshot.manifest.missing_keys",
            locale="en",
            keys="project_name, units",
        )
        assert "project_name" in out


def _load_bundle_keys(module_name: str, locale: str) -> set[str]:
    path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "modules"
        / module_name
        / "messages"
        / f"{locale}.json"
    )
    with path.open(encoding="utf-8") as fh:
        return set(json.load(fh).keys())


# ── Snapshot storage keys ──────────────────────────────────────────────────


class TestSnapshotStorageKeys:
    def test_snapshot_prefix_shape(self) -> None:
        p = snapshot_prefix("proj-1", "snap-1")
        assert p == "dashboards/proj-1/snap-1"

    def test_parquet_key_shape(self) -> None:
        assert parquet_key("p", "s", "entities") == "dashboards/p/s/entities.parquet"
        assert parquet_key("p", "s", "attribute_value_index") == (
            "dashboards/p/s/attribute_value_index.parquet"
        )

    def test_manifest_key_shape(self) -> None:
        assert manifest_key("p", "s") == "dashboards/p/s/manifest.json"

    def test_empty_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            snapshot_prefix("", "s")
        with pytest.raises(ValueError):
            snapshot_prefix("p", "")


# ── Snapshot storage I/O on a real LocalStorageBackend ─────────────────────


@pytest.fixture
def local_backend(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(base_dir=tmp_path)


@pytest.mark.asyncio
class TestSnapshotStorageIO:
    async def test_write_and_read_manifest(self, local_backend: LocalStorageBackend) -> None:
        project_id = "proj-1"
        snap_id = str(uuid4())
        payload = {"label": "Initial", "total_entities": 10, "units": "metric"}

        await write_manifest(project_id, snap_id, payload, backend=local_backend)
        out = await read_manifest(project_id, snap_id, backend=local_backend)

        assert out == payload

    async def test_write_parquet_and_resolve_local_path(
        self, local_backend: LocalStorageBackend,
    ) -> None:
        project_id = "proj-1"
        snap_id = str(uuid4())
        df = pd.DataFrame(
            {
                "entity_guid": ["g1", "g2", "g3"],
                "category": ["walls", "walls", "doors"],
                "attributes": [
                    {"material": "Concrete", "thickness": "240"},
                    {"material": "Concrete", "thickness": "240"},
                    {"material": "Wood", "width": "900"},
                ],
            }
        )

        key = await write_parquet(
            project_id, snap_id, "entities", df, backend=local_backend,
        )
        assert key == f"dashboards/{project_id}/{snap_id}/entities.parquet"

        path = await resolve_local_parquet_path(
            project_id, snap_id, "entities", backend=local_backend,
        )
        assert Path(path).is_file()
        assert Path(path).stat().st_size > 0

    async def test_resolve_local_path_missing_file(
        self, local_backend: LocalStorageBackend,
    ) -> None:
        with pytest.raises(FileNotFoundError):
            await resolve_local_parquet_path(
                "proj-1", "never-written", "entities", backend=local_backend,
            )

    async def test_resolve_non_local_backend_raises(self) -> None:
        """Any backend that isn't :class:`LocalStorageBackend` must raise
        :class:`ParquetNotLocalError` until the httpfs path is wired."""

        class _FakeBackend:
            async def put(self, key: str, content: bytes) -> None: ...  # noqa: D401
            async def get(self, key: str) -> bytes: ...
            async def exists(self, key: str) -> bool: ...
            async def delete(self, key: str) -> None: ...
            async def delete_prefix(self, prefix: str) -> int: ...
            async def size(self, key: str) -> int: ...

        with pytest.raises(ParquetNotLocalError):
            await resolve_local_parquet_path(
                "p", "s", "entities", backend=_FakeBackend(),  # type: ignore[arg-type]
            )

    async def test_delete_snapshot_files_removes_all(
        self, local_backend: LocalStorageBackend,
    ) -> None:
        project_id = "proj-1"
        snap_id = str(uuid4())
        df = pd.DataFrame({"entity_guid": ["g1"], "category": ["walls"]})
        await write_parquet(project_id, snap_id, "entities", df, backend=local_backend)
        await write_manifest(project_id, snap_id, {"label": "x"}, backend=local_backend)

        n = await delete_snapshot_files(project_id, snap_id, backend=local_backend)
        assert n >= 2

        # Second delete is a no-op.
        n2 = await delete_snapshot_files(project_id, snap_id, backend=local_backend)
        assert n2 == 0


# ── DuckDB pool ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDuckDBPool:
    async def test_execute_against_tiny_snapshot(
        self, local_backend: LocalStorageBackend, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id = "proj-1"
        snap_id = str(uuid4())

        df = pd.DataFrame(
            {
                "entity_guid": ["g1", "g2", "g3", "g4"],
                "category": ["walls", "walls", "doors", "walls"],
            }
        )
        await write_parquet(project_id, snap_id, "entities", df, backend=local_backend)

        # Pool talks to snapshot_storage.get_storage_backend() — monkey-patch
        # to hand it our tmp-path backend so the test stays hermetic.
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        pool = DuckDBPool(max_size=4)
        try:
            rows = await pool.execute(
                snap_id, project_id,
                "SELECT category, COUNT(*) FROM entities GROUP BY 1 ORDER BY 1",
            )
            assert rows == [("doors", 1), ("walls", 3)]

            # Second call hits warm entry — same result.
            rows2 = await pool.execute(
                snap_id, project_id,
                "SELECT COUNT(*) FROM entities WHERE category = ?",
                ["walls"],
            )
            assert rows2 == [(3,)]
        finally:
            await pool.close_all()

    async def test_missing_entities_parquet_raises(
        self, local_backend: LocalStorageBackend, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )

        pool = DuckDBPool()
        try:
            with pytest.raises(SnapshotHasNoEntitiesError):
                await pool.execute(
                    "missing-snap", "proj-1",
                    "SELECT COUNT(*) FROM entities",
                )
        finally:
            await pool.close_all()

    async def test_lru_eviction(
        self, local_backend: LocalStorageBackend, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Inserting N + 1 snapshots into a pool sized N must evict the oldest."""
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )
        project_id = "proj-1"
        snap_ids = [str(uuid4()) for _ in range(3)]
        for sid in snap_ids:
            df = pd.DataFrame({"entity_guid": ["g1"], "category": ["walls"]})
            await write_parquet(project_id, sid, "entities", df, backend=local_backend)

        pool = DuckDBPool(max_size=2)
        try:
            for sid in snap_ids:
                await pool.execute(sid, project_id, "SELECT COUNT(*) FROM entities")
            # Only the 2 most recent should be warm now.
            assert len(pool._entries) == 2  # noqa: SLF001 — test-only introspection
            assert snap_ids[0] not in pool._entries
            assert snap_ids[1] in pool._entries
            assert snap_ids[2] in pool._entries
        finally:
            await pool.close_all()

    async def test_invalidate_closes_entry(
        self, local_backend: LocalStorageBackend, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.modules.dashboards.snapshot_storage.get_storage_backend",
            lambda: local_backend,
        )
        project_id = "proj-1"
        snap_id = str(uuid4())
        df = pd.DataFrame({"entity_guid": ["g1"], "category": ["walls"]})
        await write_parquet(project_id, snap_id, "entities", df, backend=local_backend)

        pool = DuckDBPool()
        try:
            await pool.execute(snap_id, project_id, "SELECT COUNT(*) FROM entities")
            assert snap_id in pool._entries  # noqa: SLF001

            await pool.invalidate(snap_id)
            assert snap_id not in pool._entries  # noqa: SLF001
        finally:
            await pool.close_all()


# ── Event taxonomy ─────────────────────────────────────────────────────────


class TestEventTaxonomy:
    def test_dashboards_events_have_source_module(self) -> None:
        from app.modules.dashboards import events

        assert events.SOURCE_MODULE == "oe_dashboards"
        # Every lifecycle event type starts with a verb-like noun we can
        # greppably classify in the audit log.
        assert events.SNAPSHOT_CREATED == "snapshot.created"
        assert events.SNAPSHOT_DELETED == "snapshot.deleted"
        assert events.DASHBOARD_SAVED == "dashboard.saved"

    def test_compliance_events_have_source_module(self) -> None:
        from app.modules.compliance_ai import events

        assert events.SOURCE_MODULE == "oe_compliance_ai"
        assert events.RULE_EVALUATED == "compliance.rule.evaluated"

    def test_cost_match_events_have_source_module(self) -> None:
        from app.modules.cost_match import events

        assert events.SOURCE_MODULE == "oe_cost_match"
        assert events.MATCH_COMPLETED == "cost.match.completed"
