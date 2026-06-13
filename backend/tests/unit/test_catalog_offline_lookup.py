"""Offline-first lookup for regional reference data.

The regional CWICR catalog CSVs are not shipped inside the package; they are
downloaded on demand and cached, so a region imported once stays available
without network. These tests prove the lookup chains work with the network
hard-disabled once the data has been cached:

- catalog: local cache -> GitHub (blocked here)
- costs:   local DDC_Toolkit -> persistent cache -> bundled dir -> GitHub

and that a total miss produces an actionable error, never a silent empty
catalog.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.catalog import router as catalog_router
from app.modules.costs import router as costs_router


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard-disable both download paths used by the lookup chains."""

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted during offline test")

    # catalog router downloads via urllib.request.urlopen
    monkeypatch.setattr("urllib.request.urlopen", _refuse)
    # costs router downloads via httpx.stream (inside _download_to_file)
    monkeypatch.setattr(costs_router, "_download_to_file", _refuse)


# ── catalog: /api/v1/catalog/import/{region} resolver ─────────────────────


def test_catalog_resolves_from_local_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A region downloaded once resolves from the local cache, no network."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cached = cache_dir / "DDC_CWICR_DE_BERLIN_Catalog.csv"
    cached.write_bytes(b"resource_code,name\r\n" + b"x" * 2000)
    monkeypatch.setattr(catalog_router, "_CATALOG_CACHE_DIR", cache_dir)
    raw, source = catalog_router._read_region_catalog_csv("DE_BERLIN", "DE___DDC_CWICR")
    assert source == "cache"
    assert raw == cached.read_bytes()


def test_catalog_total_miss_raises_actionable_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(catalog_router, "_CATALOG_CACHE_DIR", tmp_path / "cache")
    with pytest.raises(RuntimeError) as exc_info:
        catalog_router._read_region_catalog_csv("FR_PARIS", "FR___DDC_CWICR")
    message = str(exc_info.value)
    assert "FR_PARIS" in message
    assert "raw.githubusercontent.com" in message
    assert "DDC_CWICR_FR_PARIS_Catalog.csv" in message


# ── costs: _find_cwicr_file resolver ───────────────────────────────────────


async def test_find_cwicr_file_uses_persistent_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cached = cache_dir / "RU_STPETERSBURG.parquet"
    cached.write_bytes(b"PAR1" + b"\x00" * 2000)
    monkeypatch.setattr(costs_router, "CWICR_SEARCH_PATHS", [str(tmp_path / "no-toolkit")])
    monkeypatch.setattr(costs_router, "_CWICR_CACHE_DIR", cache_dir)
    monkeypatch.setattr(costs_router, "_BUNDLED_CWICR_DIR", tmp_path / "no-bundle")
    assert await costs_router._find_cwicr_file("RU_STPETERSBURG") == cached


async def test_find_cwicr_file_uses_bundled_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    bundled = bundled_dir / "DE_BERLIN_workitems_costs_resources_DDC_CWICR.parquet"
    bundled.write_bytes(b"PAR1" + b"\x00" * 2000)
    monkeypatch.setattr(costs_router, "CWICR_SEARCH_PATHS", [str(tmp_path / "no-toolkit")])
    monkeypatch.setattr(costs_router, "_CWICR_CACHE_DIR", tmp_path / "no-cache")
    monkeypatch.setattr(costs_router, "_BUNDLED_CWICR_DIR", bundled_dir)
    assert await costs_router._find_cwicr_file("DE_BERLIN") == bundled


async def test_find_cwicr_file_skips_stuck_zero_byte_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A 0-byte leftover must not satisfy the cache lookup."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "UK_GBP.parquet").write_bytes(b"")
    monkeypatch.setattr(costs_router, "CWICR_SEARCH_PATHS", [str(tmp_path / "no-toolkit")])
    monkeypatch.setattr(costs_router, "_CWICR_CACHE_DIR", cache_dir)
    monkeypatch.setattr(costs_router, "_BUNDLED_CWICR_DIR", tmp_path / "no-bundle")
    assert await costs_router._find_cwicr_file("UK_GBP") is None
    # The failed (refused) download must leave an actionable error for the
    # 404 detail in load_cwicr_region, never a silent miss.
    assert "UK_GBP" in costs_router._LAST_DOWNLOAD_ERROR
    message = costs_router._LAST_DOWNLOAD_ERROR.pop("UK_GBP")
    assert "URL:" in message


def test_catalog_regions_are_not_bundled_in_the_package() -> None:
    """The custom CWICR catalog CSVs must not ship inside the package.

    They are downloaded on demand instead. This pins the decision so a future
    change cannot silently re-bundle the proprietary regional data.
    """
    data_root = Path(catalog_router.__file__).resolve().parents[2] / "data" / "catalog"
    assert not data_root.exists(), f"regional catalog data unexpectedly bundled at {data_root}"
    assert not hasattr(catalog_router, "_BUNDLED_CATALOG_DIR")
