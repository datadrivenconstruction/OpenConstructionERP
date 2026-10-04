"""``load_base_market`` delivers the card's language or says it did not.

A market card on a national base names a language. The endpoint used to run the
text swap, ignore how it ended and reprice anyway, so a failed French swap still
answered "priced into France" over Turkish text. These tests pin the three
outcomes: the language lands, the language cannot land and the request fails
before the reprice, or no file holds the language and the base opens in its own.

They also pin what the switch records in the base's stored state: the market it
is in once the reprice landed, the market it was in when nothing was repriced,
and "switching" when the reprice itself broke half way.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.costs import router as costs_router
from tests._cost_base_state_fake import FakeStateStore


class _Result:
    def as_dict(self) -> dict[str, Any]:
        return {"items_repriced": 3}


class _Service:
    def __init__(self) -> None:
        self.applied: list[tuple[str, str]] = []
        self.raise_: Exception | None = None

    async def apply_market_catalog(self, base_region: str, market_token: str, rows: list) -> _Result:
        if self.raise_ is not None:
            raise self.raise_
        self.applied.append((base_region, market_token))
        return _Result()


class _Session:
    """Enough of a session for the catalogue mirror: it commits and rolls back."""

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"calls": [], "swap_result": {}, "loads": [], "mirrored": []}

    async def _load(db_id: str, session: Any, **kwargs: Any) -> dict:
        state["loads"].append((db_id, kwargs))
        return {"status": "already_loaded"}

    async def _ensure(base_region: str, lang: str | None, session: Any) -> str | None:
        state["calls"].append((base_region, lang))
        return state["swap_result"].get(lang, lang)

    async def _rows(base_region: str, market_token: str) -> list:
        return [{"resource_code": "R1", "price_avg": "1"}]

    async def _replace(session: Any, region: str, rows: list, *, source: str) -> dict:
        state["mirrored"].append((region, source, len(rows)))
        return {"region": region, "imported": len(rows), "source": source}

    import app.modules.catalog.router as catalog_router

    monkeypatch.setattr(costs_router, "load_cwicr_region", _load)
    monkeypatch.setattr(costs_router, "_ensure_region_text_language", _ensure)
    monkeypatch.setattr(costs_router, "_invalidate_cost_cache", lambda: None)
    monkeypatch.setattr(catalog_router, "fetch_market_catalog_rows", _rows)
    monkeypatch.setattr(catalog_router, "replace_imported_catalog_rows", _replace)
    state["service"] = _Service()
    state["store"] = FakeStateStore().install(monkeypatch)
    return state


def _call(state: dict[str, Any], base: str, market: str) -> dict:
    return asyncio.run(
        costs_router.load_base_market(base, market, session=_Session(), _user_id="u", service=state["service"])
    )


@pytest.mark.parametrize(("base", "market"), [("TR_NATIONAL", "FR_PARIS_fr"), ("ZH_CHINA", "FR_PARIS_fr")])
def test_french_card_swaps_to_french(wired: dict[str, Any], base: str, market: str) -> None:
    out = _call(wired, base, market)
    assert wired["calls"] == [(base, "fr")]
    assert out["text_language"] == "fr"
    assert out["text_language_requested"] == "fr"
    assert wired["service"].applied == [(base, market)]


def test_the_market_load_does_not_retry_the_home_language_first(wired: dict[str, Any]) -> None:
    """It is about to set the market's language, so a home swap first is wasted work."""
    _call(wired, "ZH_CHINA", "FR_PARIS_fr")
    assert wired["loads"] == [("ZH_CHINA", {"retry_home_language": False})]


def test_a_landed_switch_is_stored_as_the_active_market(wired: dict[str, Any]) -> None:
    _call(wired, "ZH_CHINA", "GB_LONDON_en")
    row = wired["store"].rows["ZH_CHINA"]
    assert row["active_market"] == "GB_LONDON_en"
    assert row["switching_to"] is None
    # "Switching" was said before anything moved.
    assert wired["store"].writes[0] == ("ZH_CHINA", {"switching_to": "GB_LONDON_en"})


def test_a_landed_switch_mirrors_the_market_catalogue(wired: dict[str, Any]) -> None:
    out = _call(wired, "ZH_CHINA", "GB_LONDON_en")
    assert wired["mirrored"] == [("ZH_CHINA", "market_import", 1)]
    assert out["catalog"]["imported"] == 1


def test_failed_french_swap_fails_before_the_reprice(wired: dict[str, Any]) -> None:
    wired["store"].rows["TR_NATIONAL"] = {"active_market": "DE_BERLIN_de", "switching_to": None}
    wired["swap_result"] = {"fr": None}
    with pytest.raises(HTTPException) as exc:
        _call(wired, "TR_NATIONAL", "FR_PARIS_fr")
    assert exc.value.status_code == 502
    assert wired["service"].applied == []
    # Nothing was repriced, so the base still reads as Berlin, not as switching.
    assert wired["store"].rows["TR_NATIONAL"] == {"active_market": "DE_BERLIN_de", "switching_to": None}
    assert wired["mirrored"] == []


def test_a_reprice_that_breaks_half_way_stays_reported_as_switching(wired: dict[str, Any]) -> None:
    wired["store"].rows["ZH_CHINA"] = {"active_market": "DE_BERLIN_de", "switching_to": None}
    wired["service"].raise_ = RuntimeError("connection lost")
    with pytest.raises(RuntimeError):
        _call(wired, "ZH_CHINA", "GB_LONDON_en")
    row = wired["store"].rows["ZH_CHINA"]
    # The rows may be half in London: neither Berlin nor London may be claimed.
    assert row["switching_to"] == "GB_LONDON_en"
    assert row["active_market"] == "DE_BERLIN_de"


def test_english_card_brings_a_chinese_base_back_to_english(wired: dict[str, Any]) -> None:
    out = _call(wired, "ZH_CHINA", "GB_LONDON_en")
    assert wired["calls"] == [("ZH_CHINA", "en")]
    assert out["text_language"] == "en"


def test_failed_fallback_swap_fails_before_the_reprice(wired: dict[str, Any]) -> None:
    """Turkiye has no English text, so the card falls back to Turkish, and that must land too."""
    wired["swap_result"] = {"tr": None}
    with pytest.raises(HTTPException) as exc:
        _call(wired, "TR_NATIONAL", "GB_LONDON_en")
    assert exc.value.status_code == 502
    assert wired["calls"] == [("TR_NATIONAL", "tr")]
    assert wired["service"].applied == []


def test_english_card_on_turkiye_opens_in_turkish_and_says_so(wired: dict[str, Any]) -> None:
    out = _call(wired, "TR_NATIONAL", "GB_LONDON_en")
    assert wired["calls"] == [("TR_NATIONAL", "tr")]
    assert out["text_language"] == "tr"
    assert out["text_language_requested"] == "en"
    assert wired["service"].applied == [("TR_NATIONAL", "GB_LONDON_en")]
