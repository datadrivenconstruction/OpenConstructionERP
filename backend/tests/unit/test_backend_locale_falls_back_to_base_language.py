# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A regional locale reads its base language, not English.

The UI offers five regional codes and resolves every one of them through its
base language, so a Brazilian reader sees the Portuguese strings. The backend
catalogue has a file for none of the five, and it used to go straight from a
missing pt-BR to English. The same person then read Portuguese on screen and
English in everything the server writes, with the Portuguese string sitting in
memory the whole time.

The gap between the two layers is the thing under test here, so the assertions
below are written against both sides rather than against the backend alone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.i18n import (
    get_all_translations,
    get_available_locales,
    load_translations,
    t,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
UI_LANGUAGES = REPO_ROOT / "frontend" / "src" / "app" / "i18n.ts"


@pytest.fixture(scope="module", autouse=True)
def _catalogue() -> None:
    load_translations()


def _offered_regional_codes() -> set[str]:
    source = UI_LANGUAGES.read_text(encoding="utf-8")
    offered = set(re.findall(r"^\s*\{ code: '([a-zA-Z-]+)'", source, re.M))
    return {code for code in offered if "-" in code}


def _key_that_really_differs(base: str) -> str:
    english = get_all_translations("en")
    translated = get_all_translations(base)
    for key, value in sorted(english.items()):
        if translated.get(key) and translated[key] != value:
            return key
    raise AssertionError(f"no key in {base} differs from English, so nothing here can discriminate")


def test_every_regional_code_the_ui_offers_reads_its_base_language() -> None:
    loaded = {entry["code"] for entry in get_available_locales() if entry["loaded"]}
    regional = _offered_regional_codes()
    assert regional, "no regional codes were read out of the UI language list"
    checked = 0
    for code in sorted(regional):
        base = code.split("-", 1)[0]
        if code in loaded or base not in loaded:
            continue  # a code with its own catalogue, or a base with none, is a different question
        if base == "en":
            # en-US resolves to en, which is also the last-resort fallback, so
            # no string can tell the two paths apart. Assert what can be told:
            # that it is the English catalogue itself and not a copy.
            assert get_all_translations(code) is get_all_translations("en")
            continue
        key = _key_that_really_differs(base)
        assert t(key, code) == t(key, base), (
            f"{code} has no catalogue of its own and {base} does, but the backend answered "
            f"{t(key, code)!r} instead of the {base} string {t(key, base)!r}"
        )
        assert get_all_translations(code) is get_all_translations(base)
        checked += 1
    assert checked >= 2, f"only {checked} regional codes were actually exercised, so this proves little"


def test_a_language_with_no_catalogue_at_all_still_reads_english() -> None:
    """The base-language step must not have swallowed the English fallback."""
    key = _key_that_really_differs("de")
    english = get_all_translations("en")[key]
    assert t(key, "zz") == english
    assert t(key, "zz-ZZ") == english
    assert get_all_translations("zz-ZZ") == english_catalogue()


def english_catalogue() -> dict[str, str]:
    return get_all_translations("en")


def test_an_unknown_key_still_comes_back_as_itself() -> None:
    assert t("no.such.key.anywhere", "pt-BR") == "no.such.key.anywhere"


def test_a_locale_with_its_own_catalogue_is_not_redirected() -> None:
    """The control on the other side: the new step must only fire when the exact
    code is absent, or a regional catalogue added later would be ignored."""
    key = _key_that_really_differs("de")
    assert t(key, "de") == get_all_translations("de")[key]
    assert t(key, "de") != get_all_translations("en")[key]


# ---------------------------------------------------------------------------
# The route, which is where the gap was actually reachable from.
#
# Resolving inside t() alone proved nothing about a request: the two /i18n
# routes tested membership of SUPPORTED_LOCALES, which holds base codes only,
# so every regional code was refused with a 404 before it could reach the
# resolver. Meanwhile the Accept-Language middleware, given the identical tag
# in a header, resolved it to the base language and served that. Same product,
# same code, two answers depending on which way the reader asked.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_route_serves_a_regional_code_from_its_base_language() -> None:
    from app.core.i18n_router import get_translations

    payload = await get_translations("pt-BR")
    meta = payload["_meta"]
    assert meta["fallback"] is False, "pt-BR was served Portuguese and reported as English"
    assert meta["resolved_locale"] == "pt"
    assert meta["locale"] == "pt-BR", "the request the client made has to survive in the answer"

    portuguese = get_all_translations("pt")
    key = _key_that_really_differs("pt")
    assert payload[key] == portuguese[key]
    assert payload[key] != get_all_translations("en")[key]


@pytest.mark.asyncio
async def test_the_route_and_the_header_resolve_the_same_tag_the_same_way() -> None:
    """The assertion this whole change exists for. A tag means one language."""
    from app.core.i18n_router import get_translations
    from app.middleware.accept_language import match_locale, parse_accept_language

    for tag in ("pt-BR", "es-MX", "en-US"):
        from_header = match_locale(parse_accept_language(tag))
        from_route = (await get_translations(tag))["_meta"]
        served = from_route.get("resolved_locale", from_route["locale"])
        assert served == from_header, (
            f"{tag} reads as {from_header!r} through the Accept-Language header and {served!r} "
            f"through the route, so the same reader gets two languages out of one product"
        )


@pytest.mark.asyncio
async def test_the_route_still_refuses_a_language_the_platform_does_not_have() -> None:
    """The control. Accepting regional codes must not have made the route
    accept everything, or a typo would silently return English forever."""
    from fastapi import HTTPException

    from app.core.i18n_router import get_locale_messages, get_translations

    for code in ("zz", "zz-ZZ", "klingon"):
        for route in (get_translations, get_locale_messages):
            with pytest.raises(HTTPException) as raised:
                await route(code)
            assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_a_supported_locale_with_no_file_is_still_announced_as_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``fallback`` has to keep meaning what it said. It is not a report on
    whether a file is named after the exact code, it is a warning that the
    reader is about to read English."""
    from app.core import i18n_router

    monkeypatch.setattr(i18n_router, "SUPPORTED_LOCALES", [*i18n_router.SUPPORTED_LOCALES, "qq"])
    payload = await i18n_router.get_translations("qq-QQ")
    assert payload["_meta"]["fallback"] is True
    assert payload["_meta"]["fallback_locale"] == "en"
    assert "resolved_locale" not in payload["_meta"]
