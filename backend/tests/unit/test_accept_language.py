"""Tests for the Accept-Language middleware and its helper functions.

Covers:
  - parse_accept_language() with valid, weighted, and malformed headers
  - match_locale() with exact, prefix, and no-match scenarios
  - Full middleware dispatch (mock request with Accept-Language header)
  - Query param ?locale= override
  - Content-Language response header
"""

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.i18n import SUPPORTED_LOCALES, _translations, get_locale
from app.middleware.accept_language import (
    AcceptLanguageMiddleware,
    match_locale,
    parse_accept_language,
)

# ── parse_accept_language ───────────────────────────────────────────────────


class TestParseAcceptLanguage:
    """Tests for the RFC 7231 Accept-Language parser."""

    def test_simple_single_tag(self) -> None:
        result = parse_accept_language("en")
        assert result == [("en", 1.0)]

    def test_multiple_tags_without_quality(self) -> None:
        result = parse_accept_language("de, en, fr")
        assert len(result) == 3
        # All default to q=1.0, order preserved
        tags = [tag for tag, _q in result]
        assert "de" in tags
        assert "en" in tags
        assert "fr" in tags

    def test_quality_factors_sorted_descending(self) -> None:
        result = parse_accept_language("de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7")
        assert len(result) == 4
        # First entry should be de-DE (q=1.0)
        assert result[0] == ("de-DE", 1.0)
        assert result[1] == ("de", 0.9)
        assert result[2] == ("en-US", 0.8)
        assert result[3] == ("en", 0.7)

    def test_explicit_q_1_0(self) -> None:
        result = parse_accept_language("en;q=1.0")
        assert result == [("en", 1.0)]

    def test_q_zero_is_kept(self) -> None:
        result = parse_accept_language("en;q=0")
        assert result == [("en", 0.0)]

    def test_empty_string(self) -> None:
        result = parse_accept_language("")
        assert result == []

    def test_whitespace_only(self) -> None:
        result = parse_accept_language("   ")
        assert result == []

    def test_garbage_input(self) -> None:
        result = parse_accept_language("!!!@@@###")
        assert result == []

    def test_mixed_valid_and_invalid(self) -> None:
        result = parse_accept_language("en, !!!invalid!!!, de;q=0.5")
        tags = [tag for tag, _q in result]
        assert "en" in tags
        assert "de" in tags
        assert len(result) == 2

    def test_wildcard_tag(self) -> None:
        result = parse_accept_language("*;q=0.1")
        assert result == [("*", 0.1)]

    def test_complex_real_world_header(self) -> None:
        """Chrome-style Accept-Language header."""
        header = "en-US,en;q=0.9,de-DE;q=0.8,de;q=0.7,ru;q=0.6"
        result = parse_accept_language(header)
        assert len(result) == 5
        assert result[0][0] == "en-US"
        assert result[0][1] == 1.0
        assert result[-1][0] == "ru"
        assert result[-1][1] == pytest.approx(0.6)

    def test_whitespace_around_parts(self) -> None:
        result = parse_accept_language("  en , de ; q=0.8 ")
        assert len(result) == 2


# ── match_locale ────────────────────────────────────────────────────────────


class TestMatchLocale:
    """Tests for matching parsed tags to supported locales."""

    def test_exact_match(self) -> None:
        tags = [("de", 1.0)]
        assert match_locale(tags) == "de"

    def test_prefix_match_de_DE(self) -> None:
        tags = [("de-DE", 1.0)]
        assert match_locale(tags) == "de"

    def test_prefix_match_en_US(self) -> None:
        tags = [("en-US", 1.0)]
        assert match_locale(tags) == "en"

    def test_prefix_match_zh_CN(self) -> None:
        tags = [("zh-CN", 1.0)]
        assert match_locale(tags) == "zh"

    def test_prefix_match_pt_BR(self) -> None:
        tags = [("pt-BR", 1.0)]
        assert match_locale(tags) == "pt"

    def test_no_match_falls_back_to_en(self) -> None:
        tags = [("xx-YY", 1.0), ("zz", 0.5)]
        assert match_locale(tags) == "en"

    def test_empty_tags_returns_en(self) -> None:
        assert match_locale([]) == "en"

    def test_priority_order_respected(self) -> None:
        """First matching tag wins, even if a later one is also valid."""
        tags = [("fr", 1.0), ("de", 0.9), ("en", 0.8)]
        assert match_locale(tags) == "fr"

    def test_custom_supported_list(self) -> None:
        tags = [("de", 1.0), ("en", 0.5)]
        assert match_locale(tags, supported=["en", "fr"]) == "en"

    def test_custom_supported_no_match(self) -> None:
        tags = [("de", 1.0)]
        assert match_locale(tags, supported=["fr", "es"]) == "en"

    def test_case_insensitive(self) -> None:
        tags = [("DE-DE", 1.0)]
        assert match_locale(tags) == "de"


# ── AcceptLanguageMiddleware (integration) ──────────────────────────────────


def _make_app() -> Starlette:
    """Build a minimal Starlette app with the middleware applied."""

    async def locale_echo(request: Request) -> PlainTextResponse:
        """Return the active locale so the test can verify it."""
        return PlainTextResponse(get_locale())

    app = Starlette(routes=[Route("/locale", locale_echo)])
    app.add_middleware(AcceptLanguageMiddleware)
    return app


@pytest.fixture(autouse=True)
def _seed_translations():
    """Ensure ``set_locale`` can accept all supported locales.

    ``set_locale`` falls back to ``"en"`` when a locale is absent from the
    ``_translations`` dict (not loaded).  For middleware tests we seed every
    supported locale with an empty dict so the context variable is set as
    expected.
    """
    saved = dict(_translations)
    for loc in SUPPORTED_LOCALES:
        _translations.setdefault(loc, {})
    yield
    _translations.clear()
    _translations.update(saved)


@pytest.fixture
def client() -> TestClient:
    """Test client with AcceptLanguageMiddleware active."""
    return TestClient(_make_app())


class TestAcceptLanguageMiddleware:
    """Integration tests using a real Starlette TestClient."""

    def test_accept_language_header_de(self, client: TestClient) -> None:
        resp = client.get("/locale", headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.7"})
        assert resp.status_code == 200
        assert resp.text == "de"

    def test_accept_language_header_fr(self, client: TestClient) -> None:
        resp = client.get("/locale", headers={"Accept-Language": "fr;q=1.0,en;q=0.5"})
        assert resp.status_code == 200
        assert resp.text == "fr"

    def test_no_header_defaults_to_en(self, client: TestClient) -> None:
        resp = client.get("/locale")
        assert resp.status_code == 200
        assert resp.text == "en"

    def test_query_param_overrides_header(self, client: TestClient) -> None:
        resp = client.get(
            "/locale?locale=ru",
            headers={"Accept-Language": "de-DE,de;q=0.9"},
        )
        assert resp.status_code == 200
        assert resp.text == "ru"

    def test_query_param_prefix_normalization(self, client: TestClient) -> None:
        resp = client.get("/locale?locale=zh-CN")
        assert resp.status_code == 200
        assert resp.text == "zh"

    def test_invalid_query_param_falls_back_to_header(self, client: TestClient) -> None:
        resp = client.get(
            "/locale?locale=xx",
            headers={"Accept-Language": "es;q=0.9"},
        )
        assert resp.status_code == 200
        assert resp.text == "es"

    def test_content_language_response_header(self, client: TestClient) -> None:
        resp = client.get("/locale", headers={"Accept-Language": "ja"})
        assert resp.status_code == 200
        assert resp.headers["content-language"] == "ja"

    def test_content_language_default_en(self, client: TestClient) -> None:
        resp = client.get("/locale")
        assert resp.headers["content-language"] == "en"

    def test_unsupported_language_falls_back(self, client: TestClient) -> None:
        resp = client.get("/locale", headers={"Accept-Language": "tlh"})  # Klingon
        assert resp.status_code == 200
        assert resp.text == "en"
        assert resp.headers["content-language"] == "en"
