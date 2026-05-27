"""Tests for HTTPException detail i18n wiring (errors.* namespace).

Covers:
  - Every audited ``errors.*`` key resolves in en / de / ru bundles
  - get_lang dependency resolves Accept-Language properly
  - Sample routers actually return localized detail strings when an upstream
    Accept-Language header is supplied
"""

from __future__ import annotations

import pytest

from app.core.validation.messages import is_key_present, reload_bundle, translate
from app.dependencies import get_lang

# Keys that this round wired through translate(). Mirrors the audit's
# Section 3 table (Suggested Key column) verbatim.
_AUDIT_KEYS = [
    "errors.resource_not_found",
    "errors.project_not_found",
    "errors.vendor_not_found",
    "errors.template_not_found",
    "errors.position_not_found",
    "errors.session_not_found",
    "errors.document_not_found",
    "errors.invitation_not_found",
    "errors.agreement_not_found",
    "errors.rejection_not_found",
    "errors.claim_not_found",
    "errors.plot_not_found",
    "errors.survey_not_found",
    "errors.diary_video_not_found",
    "errors.diary_photo_not_found",
    "errors.bidder_not_found",
    "errors.webhook_not_found",
    "errors.submission_not_found",
    "errors.measurement_not_found",
    "errors.salescontract_not_found",
    "errors.prompt_not_found",
    "errors.prequalification_not_found",
    "errors.purchase_requisition_not_found",
    "errors.purchase_order_not_found",
    "errors.group_not_found",
    "errors.final_account_not_found",
    "errors.estimate_job_not_found",
    "errors.escrow_not_found",
    "errors.commission_accrual_not_found",
    "errors.baseline_not_found",
]


@pytest.fixture(autouse=True)
def _fresh_bundle() -> None:
    """Drop any cached locale data so the fixtures see disk-current JSON."""
    reload_bundle()


# ── Coverage tests: every audited key has a translation per locale ──────────


@pytest.mark.parametrize("key", _AUDIT_KEYS)
def test_key_present_in_en(key: str) -> None:
    assert is_key_present(key, "en"), f"missing in en.json: {key}"


@pytest.mark.parametrize("key", _AUDIT_KEYS)
def test_key_present_in_de(key: str) -> None:
    assert is_key_present(key, "de"), f"missing in de.json: {key}"


@pytest.mark.parametrize("key", _AUDIT_KEYS)
def test_key_present_in_ru(key: str) -> None:
    assert is_key_present(key, "ru"), f"missing in ru.json: {key}"


# ── Translation correctness ────────────────────────────────────────────────


def test_translate_en_matches_audit_text() -> None:
    """English strings must be lift-and-shift identical to the original
    hardcoded strings — no copy improvements in this pass."""
    assert translate("errors.resource_not_found", locale="en") == "Resource not found"
    assert translate("errors.project_not_found", locale="en") == "Project not found"
    assert translate("errors.vendor_not_found", locale="en") == "Vendor not found"
    assert translate("errors.purchase_order_not_found", locale="en") == "PO not found"
    assert translate("errors.commission_accrual_not_found", locale="en") == "CommissionAccrual not found"


def test_translate_de_is_german_not_english() -> None:
    """German bundle must actually return German strings (sanity check —
    the fallback path through en.json would still return English on a
    missing key, which the coverage tests above already guard against,
    but check distinctness here for the 3 most-common keys)."""
    assert translate("errors.project_not_found", locale="de") == "Projekt nicht gefunden"
    assert translate("errors.position_not_found", locale="de") == "Position nicht gefunden"
    assert translate("errors.document_not_found", locale="de") == "Dokument nicht gefunden"


def test_translate_ru_is_russian_not_english() -> None:
    assert translate("errors.project_not_found", locale="ru") == "Проект не найден"
    assert translate("errors.position_not_found", locale="ru") == "Позиция не найдена"
    assert translate("errors.document_not_found", locale="ru") == "Документ не найден"


def test_translate_unknown_locale_falls_back_to_en() -> None:
    """Asking for a locale that doesn't ship returns the English text
    (not a raw key, not None)."""
    out = translate("errors.project_not_found", locale="xx-fake")
    assert out == "Project not found"


# ── get_lang dependency ────────────────────────────────────────────────────


class _StubRequest:
    """Tiny stand-in matching the Starlette ``Request`` surface
    ``get_lang`` exercises (``query_params`` mapping + ``headers``
    case-insensitive mapping)."""

    def __init__(
        self,
        accept_language: str | None = None,
        locale_param: str | None = None,
    ) -> None:
        self.query_params = {"locale": locale_param} if locale_param else {}
        # Starlette's headers are case-insensitive; the helper calls
        # ``.get("accept-language", "")`` so a plain dict is fine for the
        # lower-case key.
        self.headers = {"accept-language": accept_language} if accept_language else {}


def test_get_lang_defaults_to_en() -> None:
    assert get_lang(_StubRequest()) == "en"


def test_get_lang_picks_first_tag_from_accept_language() -> None:
    assert get_lang(_StubRequest(accept_language="de-DE,en;q=0.8")) == "de"
    assert get_lang(_StubRequest(accept_language="ru,en;q=0.9")) == "ru"


def test_get_lang_query_param_overrides_header() -> None:
    req = _StubRequest(accept_language="de-DE", locale_param="ru")
    assert get_lang(req) == "ru"


def test_get_lang_strips_region_suffix() -> None:
    assert get_lang(_StubRequest(accept_language="pt-BR")) == "pt"
    assert get_lang(_StubRequest(accept_language="zh-Hant-TW")) == "zh"


# ── Endpoint integration: representative routes return localized detail ────
#
# We assemble a tiny FastAPI app that wires three sample handlers exactly
# the same way real routers do — call ``translate("errors.X",
# locale=get_locale())`` inside an ``HTTPException`` — and run them
# through the project's ``AcceptLanguageMiddleware`` so the contextvar
# resolution path is exercised end-to-end. This avoids the lifespan +
# aiosqlite event-loop coupling that makes spinning up the full app
# inside pytest-asyncio fragile on Windows / Python 3.13.


@pytest.fixture(scope="module")
def mini_client():
    """A minimal app exposing 3 audit-list endpoints wired through
    ``translate()`` exactly like the production routers."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app.core.i18n import get_locale, load_translations
    from app.middleware.accept_language import AcceptLanguageMiddleware

    # Ensure core i18n is initialised (SUPPORTED_LOCALES gates middleware
    # matching). Idempotent if already loaded.
    load_translations()

    app = FastAPI()
    app.add_middleware(AcceptLanguageMiddleware)

    @app.get("/resource")
    async def get_resource() -> None:
        raise HTTPException(
            status_code=404,
            detail=translate("errors.resource_not_found", locale=get_locale()),
        )

    @app.get("/project")
    async def get_project() -> None:
        raise HTTPException(
            status_code=404,
            detail=translate("errors.project_not_found", locale=get_locale()),
        )

    @app.get("/position")
    async def get_position() -> None:
        raise HTTPException(
            status_code=404,
            detail=translate("errors.position_not_found", locale=get_locale()),
        )

    return TestClient(app)


def test_resource_404_localized_de(mini_client) -> None:
    """Accept-Language: de → German detail."""
    resp = mini_client.get("/resource", headers={"Accept-Language": "de"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Ressource nicht gefunden"


def test_project_404_localized_ru(mini_client) -> None:
    """Accept-Language: ru → Russian detail."""
    resp = mini_client.get("/project", headers={"Accept-Language": "ru"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Проект не найден"


def test_position_404_localized_de_with_region_tag(mini_client) -> None:
    """Region-tagged Accept-Language (``de-DE``) falls back to base ``de``."""
    resp = mini_client.get("/position", headers={"Accept-Language": "de-DE,en;q=0.5"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Position nicht gefunden"


def test_position_404_default_en(mini_client) -> None:
    """No Accept-Language → English (lift-and-shift of the original
    hardcoded string)."""
    resp = mini_client.get("/position")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Position not found"


def test_resource_404_query_param_overrides_header(mini_client) -> None:
    """``?locale=ru`` beats ``Accept-Language: de``."""
    resp = mini_client.get(
        "/resource",
        params={"locale": "ru"},
        headers={"Accept-Language": "de"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Ресурс не найден"
