"""The real text swap reports what landed, and only that.

``_ensure_region_text_language`` decides which file a national base's text comes
from and whether the switch happened. Its callers turn a ``None`` into an error
the user sees, so every way the switch can fail must come back as ``None`` with
a reason, and nothing may be recorded as the active language unless rows moved.

The language is recorded in the base's stored state (``base_state``), not in a
process-local dict. These tests stand a dict-backed store in for the table; the
round trip through the real table is covered by ``test_cost_base_state.py``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.modules.costs import router as costs_router
from tests._cost_base_state_fake import FakeStateStore


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStateStore:
    return FakeStateStore().install(monkeypatch)


@pytest.fixture
def swap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: FakeStateStore) -> dict[str, Any]:
    state: dict[str, Any] = {
        "looked_up": [],
        "file": tmp_path / "x.parquet",
        "updated": 5,
        "raise": None,
        "stored_during_swap": [],
    }

    async def _find(db_id: str) -> Path | None:
        state["looked_up"].append(db_id)
        return state["file"]

    def _swap(target: str, parquet: str, base_region: str, staging_region: str) -> int:
        # What a reader would see while the swap runs.
        state["stored_during_swap"].append(dict(store.rows.get(base_region, {})))
        if state["raise"] is not None:
            raise state["raise"]
        return state["updated"]

    monkeypatch.setattr(costs_router, "_find_cwicr_file", _find)
    monkeypatch.setattr(costs_router, "_swap_region_text_sync", _swap)
    monkeypatch.setattr(costs_router, "_invalidate_cost_cache", lambda: None)
    monkeypatch.setattr(costs_router, "_LAST_TEXT_SWAP_ERROR", {})
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://x:y@127.0.0.1:1/z")
    return state


def _ensure(base: str, lang: str | None) -> str | None:
    return asyncio.run(costs_router._ensure_region_text_language(base, lang, None))


def test_french_reads_the_french_file(swap: dict[str, Any], store: FakeStateStore) -> None:
    assert _ensure("ZH_CHINA", "fr") == "fr"
    assert swap["looked_up"] == ["ZH_CHINA_fr"]
    assert store.rows["ZH_CHINA"]["text_language"] == "fr"


def test_the_language_is_unknown_while_the_swap_runs(swap: dict[str, Any], store: FakeStateStore) -> None:
    """A process that dies mid-swap must not leave the old language claimed."""
    store.rows["ZH_CHINA"] = {"text_language": "de"}
    assert _ensure("ZH_CHINA", "fr") == "fr"
    assert swap["stored_during_swap"] == [{"text_language": None}]


def test_a_stored_language_skips_the_swap(swap: dict[str, Any], store: FakeStateStore) -> None:
    store.rows["ZH_CHINA"] = {"text_language": "fr"}
    assert _ensure("ZH_CHINA", "fr") == "fr"
    assert swap["looked_up"] == []


def test_an_unknown_language_never_skips_the_swap(swap: dict[str, Any], store: FakeStateStore) -> None:
    store.rows["ZH_CHINA"] = {"text_language": None, "active_market": "FR_PARIS_fr"}
    assert _ensure("ZH_CHINA", "fr") == "fr"
    assert swap["looked_up"] == ["ZH_CHINA_fr"]


def test_english_reads_the_home_file(swap: dict[str, Any]) -> None:
    assert _ensure("ZH_CHINA", "en") == "en"
    assert swap["looked_up"] == ["ZH_CHINA"]


def test_es_mx_reads_the_spanish_file(swap: dict[str, Any]) -> None:
    assert _ensure("TR_NATIONAL", "es-MX") == "es"
    assert swap["looked_up"] == ["TR_NATIONAL_es"]


def test_no_file_for_the_language_is_none(swap: dict[str, Any], store: FakeStateStore) -> None:
    assert _ensure("TR_NATIONAL", "en") is None
    assert swap["looked_up"] == []
    assert store.writes == []


def test_missing_file_is_none_with_a_reason(
    swap: dict[str, Any], store: FakeStateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    swap["file"] = None
    store.rows["ZH_CHINA"] = {"text_language": "de"}
    monkeypatch.setitem(costs_router._LAST_DOWNLOAD_ERROR, "ZH_CHINA_fr", "GitHub unreachable")
    assert _ensure("ZH_CHINA", "fr") is None
    assert costs_router._LAST_TEXT_SWAP_ERROR["ZH_CHINA"] == "GitHub unreachable"
    # Nothing was attempted, so nothing was written and German stands.
    assert store.writes == []
    assert store.rows["ZH_CHINA"]["text_language"] == "de"


def test_raising_swap_is_none_and_puts_the_old_language_back(swap: dict[str, Any], store: FakeStateStore) -> None:
    store.rows["ZH_CHINA"] = {"text_language": "de"}
    swap["raise"] = RuntimeError("db gone")
    assert _ensure("ZH_CHINA", "fr") is None
    assert store.rows["ZH_CHINA"]["text_language"] == "de"
    assert "RuntimeError" in costs_router._LAST_TEXT_SWAP_ERROR["ZH_CHINA"]


def test_a_swap_that_moved_no_rows_is_not_a_switch(swap: dict[str, Any], store: FakeStateStore) -> None:
    swap["updated"] = 0
    assert _ensure("ZH_CHINA", "fr") is None
    assert store.rows["ZH_CHINA"]["text_language"] is None


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
