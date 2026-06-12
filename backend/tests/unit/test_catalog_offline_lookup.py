"""Offline-first lookup for regional reference data.

A real customer on a fresh install with no GitHub access ended up with an
empty workspace because the regional CWICR catalog CSV and workitems parquet
were only fetched from GitHub at runtime. These tests prove the offline
lookup chain works with the network hard-disabled:

- catalog: local cache -> bundled package data (gz) -> GitHub (blocked here)
- costs:   local DDC_Toolkit -> persistent cache -> bundled dir -> GitHub

and that a total miss produces an actionable error, never a silent empty
catalog.
"""

from __future__ import annotations

import gzip
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


def test_bundled_catalog_csv_exists_for_every_region() -> None:
    """All 30 REGION_MAP regions ship a bundled gz catalog in the package."""
    missing = [
        region
        for region in catalog_router.REGION_MAP
        if not (catalog_router._BUNDLED_CATALOG_DIR / f"DDC_CWICR_{region}_Catalog.csv.gz").is_file()
    ]
    assert missing == [], f"regions without bundled catalog CSV: {missing}"


def test_catalog_resolves_from_bundled_data_without_network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(catalog_router, "_CATALOG_CACHE_DIR", tmp_path / "cache")
    raw, source = catalog_router._read_region_catalog_csv("RU_STPETERSBURG", "RU___DDC_CWICR")
    assert source == "bundled"
    header = raw.decode("utf-8-sig").splitlines()[0]
    assert "resource_code" in header
    assert len(raw) > 100_000


def test_catalog_prefers_local_cache_over_bundled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr(catalog_router, "_BUNDLED_CATALOG_DIR", tmp_path / "no-bundle")
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


def test_bundled_catalog_gz_total_size_within_budget() -> None:
    """Keep the wheel addition honest: all bundled catalogs < 40 MB total."""
    total = sum(f.stat().st_size for f in catalog_router._BUNDLED_CATALOG_DIR.glob("*.csv.gz"))
    assert 0 < total < 40 * 1024 * 1024


def test_bundled_catalog_gz_decompresses_to_csv() -> None:
    sample = catalog_router._BUNDLED_CATALOG_DIR / "DDC_CWICR_PL_WARSAW_Catalog.csv.gz"
    text = gzip.decompress(sample.read_bytes()).decode("utf-8-sig")
    assert "resource_code" in text.splitlines()[0]
