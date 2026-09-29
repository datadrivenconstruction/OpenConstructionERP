"""``load_base_market`` delivers the card's language or says it did not.

A market card on a national base names a language. The endpoint used to run the
text swap, ignore how it ended and reprice anyway, so a failed French swap still
answered "priced into France" over Turkish text. These tests pin the three
outcomes: the language lands, the language cannot land and the request fails
before the reprice, or no file holds the language and the base opens in its own.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.costs import router as costs_router


class _Result:
    def as_dict(self) -> dict[str, Any]:
        return {"items_repriced": 3}


class _Service:
    def __init__(self) -> None:
        self.applied: list[tuple[str, str]] = []

    async def apply_market_catalog(self, base_region: str, market_token: str, rows: list) -> _Result:
        self.applied.append((base_region, market_token))
        return _Result()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"calls": [], "swap_result": {}}

    async def _load(db_id: str, session: Any) -> dict:
        return {"status": "already_loaded"}

    async def _ensure(base_region: str, lang: str | None, session: Any) -> str | None:
        state["calls"].append((base_region, lang))
        return state["swap_result"].get(lang, lang)

    async def _rows(base_region: str, market_token: str) -> list:
        return []

    import app.modules.catalog.router as catalog_router

    monkeypatch.setattr(costs_router, "load_cwicr_region", _load)
    monkeypatch.setattr(costs_router, "_ensure_region_text_language", _ensure)
    monkeypatch.setattr(costs_router, "_invalidate_cost_cache", lambda: None)
    monkeypatch.setattr(catalog_router, "fetch_market_catalog_rows", _rows)
    state["service"] = _Service()
    return state


def _call(state: dict[str, Any], base: str, market: str) -> dict:
    return asyncio.run(
        costs_router.load_base_market(base, market, session=None, _user_id="u", service=state["service"])
    )


@pytest.mark.parametrize(("base", "market"), [("TR_NATIONAL", "FR_PARIS_fr"), ("ZH_CHINA", "FR_PARIS_fr")])
def test_french_card_swaps_to_french(wired: dict[str, Any], base: str, market: str) -> None:
    out = _call(wired, base, market)
    assert wired["calls"] == [(base, "fr")]
    assert out["text_language"] == "fr"
    assert out["text_language_requested"] == "fr"
    assert wired["service"].applied == [(base, market)]


def test_failed_french_swap_fails_before_the_reprice(wired: dict[str, Any]) -> None:
    wired["swap_result"] = {"fr": None}
    with pytest.raises(HTTPException) as exc:
        _call(wired, "TR_NATIONAL", "FR_PARIS_fr")
    assert exc.value.status_code == 502
    assert wired["service"].applied == []


def test_english_card_brings_a_chinese_base_back_to_english(wired: dict[str, Any]) -> None:
    out = _call(wired, "ZH_CHINA", "GB_LONDON_en")
    assert wired["calls"] == [("ZH_CHINA", "en")]
    assert out["text_language"] == "en"


def test_english_card_on_turkiye_opens_in_turkish_and_says_so(wired: dict[str, Any]) -> None:
    out = _call(wired, "TR_NATIONAL", "GB_LONDON_en")
    assert wired["calls"] == [("TR_NATIONAL", "tr")]
    assert out["text_language"] == "tr"
    assert out["text_language_requested"] == "en"
    assert wired["service"].applied == [("TR_NATIONAL", "GB_LONDON_en")]
