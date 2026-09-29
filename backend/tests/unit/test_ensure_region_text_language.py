"""The real text swap reports what landed, and only that.

``_ensure_region_text_language`` decides which file a national base's text comes
from and whether the switch happened. Its callers turn a ``None`` into an error
the user sees, so every way the switch can fail must come back as ``None`` with
a reason, and nothing may be recorded as the active language unless rows moved.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.modules.costs import router as costs_router


@pytest.fixture
def swap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    state: dict[str, Any] = {"looked_up": [], "file": tmp_path / "x.parquet", "updated": 5, "raise": None}

    async def _find(db_id: str) -> Path | None:
        state["looked_up"].append(db_id)
        return state["file"]

    def _swap(target: str, parquet: str, base_region: str, staging_region: str) -> int:
        if state["raise"] is not None:
            raise state["raise"]
        return state["updated"]

    monkeypatch.setattr(costs_router, "_find_cwicr_file", _find)
    monkeypatch.setattr(costs_router, "_swap_region_text_sync", _swap)
    monkeypatch.setattr(costs_router, "_invalidate_cost_cache", lambda: None)
    monkeypatch.setattr(costs_router, "_REGION_ACTIVE_LANG", {})
    monkeypatch.setattr(costs_router, "_LAST_TEXT_SWAP_ERROR", {})
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://x:y@127.0.0.1:1/z")
    return state


def _ensure(base: str, lang: str | None) -> str | None:
    return asyncio.run(costs_router._ensure_region_text_language(base, lang, None))


def test_french_reads_the_french_file(swap: dict[str, Any]) -> None:
    assert _ensure("ZH_CHINA", "fr") == "fr"
    assert swap["looked_up"] == ["ZH_CHINA_fr"]
    assert costs_router._REGION_ACTIVE_LANG["ZH_CHINA"] == "fr"


def test_english_reads_the_home_file(swap: dict[str, Any]) -> None:
    assert _ensure("ZH_CHINA", "en") == "en"
    assert swap["looked_up"] == ["ZH_CHINA"]


def test_es_mx_reads_the_spanish_file(swap: dict[str, Any]) -> None:
    assert _ensure("TR_NATIONAL", "es-MX") == "es"
    assert swap["looked_up"] == ["TR_NATIONAL_es"]


def test_no_file_for_the_language_is_none(swap: dict[str, Any]) -> None:
    assert _ensure("TR_NATIONAL", "en") is None
    assert swap["looked_up"] == []


def test_missing_file_is_none_with_a_reason(swap: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    swap["file"] = None
    monkeypatch.setitem(costs_router._LAST_DOWNLOAD_ERROR, "ZH_CHINA_fr", "GitHub unreachable")
    assert _ensure("ZH_CHINA", "fr") is None
    assert costs_router._LAST_TEXT_SWAP_ERROR["ZH_CHINA"] == "GitHub unreachable"
    assert "ZH_CHINA" not in costs_router._REGION_ACTIVE_LANG


def test_raising_swap_is_none_and_records_nothing(swap: dict[str, Any]) -> None:
    swap["raise"] = RuntimeError("db gone")
    assert _ensure("ZH_CHINA", "fr") is None
    assert "ZH_CHINA" not in costs_router._REGION_ACTIVE_LANG
    assert "RuntimeError" in costs_router._LAST_TEXT_SWAP_ERROR["ZH_CHINA"]


def test_a_swap_that_moved_no_rows_is_not_a_switch(swap: dict[str, Any]) -> None:
    swap["updated"] = 0
    assert _ensure("ZH_CHINA", "fr") is None
    assert "ZH_CHINA" not in costs_router._REGION_ACTIVE_LANG


def test_fresh_load_reports_a_home_swap_that_did_not_land(swap: dict[str, Any]) -> None:
    swap["file"] = None
    out = asyncio.run(costs_router._open_in_home_language("ZH_CHINA", None))
    assert out["text_language_requested"] == "zh"
    # The rows are still in the English home parquet, and the result says so.
    assert out["text_language"] == "en"
    assert out["text_language_error"]


def test_fresh_load_reports_the_home_language_when_it_lands(swap: dict[str, Any]) -> None:
    out = asyncio.run(costs_router._open_in_home_language("ZH_CHINA", None))
    assert out == {"text_language": "zh", "text_language_requested": "zh"}
    assert asyncio.run(costs_router._open_in_home_language("FR_PARIS", None)) == {}
