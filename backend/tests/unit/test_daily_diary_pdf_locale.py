"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Localization tests for the daily-diary PDF export.

The diary PDF used to come out hardcoded English regardless of the
request language, and rendered the ``weather_summary`` snapshot as raw
dictionary keys (``temp_c: 20 · conditions: clear``). These tests pin
the fixed contract:

* a German request produces German section headers, localized dates and
  a human weather line, with none of the previously leaking raw keys or
  English labels;
* an English request keeps every original English label (the catalog's
  ``en`` table is byte-for-byte the old literals), with only the weather
  line and nothing else re-rendered;
* an unsupported locale falls back to English, text-identical to an
  explicit English export;
* the endpoint resolves ``?locale=`` / ``Accept-Language`` by primary
  subtag with an English fallback, and names the download accordingly.

PDF assertions go through ``pypdf`` text extraction. Byte-level equality
between two renders is not assertable (reportlab embeds a creation
timestamp and a document ID), so equality checks compare extracted text
with the generated-at footer line normalised out.
"""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from pypdf import PdfReader

from app.modules.daily_diary.pdf_export import generate_diary_pdf
from app.modules.daily_diary.pdf_translations import (
    diary_pdf_filename,
    normalize_pdf_locale,
    resolve_pdf_locale,
    weather_summary_text,
)
from tests.unit.test_daily_diary import _diary_payload, _make_service, _StubSession

# Raw weather_summary key patterns that used to leak into the document.
RAW_KEY_PATTERNS = ("temp_c", "conditions:")

# English labels that used to appear even on German requests.
ENGLISH_LABELS = (
    "Daily Site Diary",
    "Overview",
    "Site supervisor",
    "Labour on site",
    "Equipment on site",
    "Completeness",
    "Site record",
    "Conditions",
    "Not recorded",
    "No entries recorded for this diary.",
    "CLOSED",
    "Generated:",
    "Page 1",
)


def _pdf_text(pdf_bytes: bytes) -> str:
    """Extract the text of every page of a PDF as one string."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


_GENERATED_LINE_RE = re.compile(r"(Generated|Erstellt): [^\n]*")


def _stable_text(pdf_bytes: bytes) -> str:
    """Extracted text with the volatile generated-at line normalised."""
    return _GENERATED_LINE_RE.sub("<generated-at>", _pdf_text(pdf_bytes))


def _audit_diary(**overrides: Any) -> SimpleNamespace:
    """A closed diary shaped like the one the German export bug showed."""
    base: dict[str, Any] = {
        "diary_date": "2028-03-23",
        "status": "closed",
        "labour_count": 13,
        "equipment_count": 4,
        "weather_summary": {"temp_c": 20, "conditions": "clear"},
        "notes": "Kranbetrieb ohne Einschraenkungen.",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _completion_entry() -> SimpleNamespace:
    return SimpleNamespace(
        entry_type="completion",
        entry_time=datetime(2028, 3, 23, 9, 0, tzinfo=UTC),
        title="Decke 3. OG betoniert",
        description="C30/37, 55 m3.",
    )


# ── Locale resolution (query param → Accept-Language → en) ───────────────


# These tests spell the unsupported case ``zz``, never a real language.
# A mechanism pinned with ``fr`` stops testing the mechanism on the day the
# catalogue gains French, and until then it reads as though English were the
# considered answer for a French reader rather than the fallback it is.


def test_resolve_pdf_locale_matches_primary_subtag_of_accept_language() -> None:
    assert resolve_pdf_locale(None, "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7") == "de"
    assert resolve_pdf_locale(None, "de") == "de"
    assert resolve_pdf_locale(None, "en-GB,en;q=0.9") == "en"
    # First supported tag wins in header order even behind an unsupported one.
    assert resolve_pdf_locale(None, "zz-ZZ,de;q=0.5") == "de"


def test_resolve_pdf_locale_unsupported_degrades_to_english() -> None:
    """English here is a fallback, not a match. The route says so in the header."""
    assert resolve_pdf_locale(None, "zz-ZZ,zz;q=0.9") == "en"
    assert resolve_pdf_locale(None, "*") == "en"
    assert resolve_pdf_locale(None, "") == "en"
    assert resolve_pdf_locale(None, None) == "en"
    assert resolve_pdf_locale("xx", None) == "en"


def test_resolve_pdf_locale_query_param_wins_over_header() -> None:
    assert resolve_pdf_locale("de", "en-US,en;q=0.9") == "de"
    assert resolve_pdf_locale("de-DE", None) == "de"
    # An unsupported explicit param falls through to the header.
    assert resolve_pdf_locale("xx", "de-DE") == "de"


def test_normalize_pdf_locale() -> None:
    assert normalize_pdf_locale("de") == "de"
    assert normalize_pdf_locale("DE-AT") == "de"
    assert normalize_pdf_locale("zz") == "en"
    assert normalize_pdf_locale(None) == "en"


def test_diary_pdf_filename_is_localized() -> None:
    assert diary_pdf_filename("2026-04-10", "en") == "diary-2026-04-10.pdf"
    assert diary_pdf_filename("2026-04-10", "de") == "bautagebuch-2026-04-10.pdf"
    # Unsupported locale keeps the English name.
    assert diary_pdf_filename("2026-04-10", "zz") == "diary-2026-04-10.pdf"


# ── Weather summary: human text, never raw keys ──────────────────────────


def test_weather_summary_text_renders_human_line() -> None:
    summary = {"temp_c": 20, "conditions": "clear"}
    assert weather_summary_text(summary, "en") == "20 °C, clear"
    assert weather_summary_text(summary, "de") == "20 °C, klar"


def test_weather_summary_text_translates_condition_codes() -> None:
    assert weather_summary_text({"conditions": "partly_cloudy"}, "de") == "wechselnd bewölkt"
    assert weather_summary_text({"conditions": "rain"}, "de") == "Regen"
    assert weather_summary_text({"conditions": "partly_cloudy"}, "en") == "partly cloudy"


def test_weather_summary_text_never_emits_snake_case_keys() -> None:
    out = weather_summary_text({"visibility_m": 800, "temp_c": 4}, "en")
    assert "visibility_m" not in out
    assert "800" in out
    assert "4 °C" in out


def test_weather_summary_text_free_text_passes_through() -> None:
    assert weather_summary_text({"conditions": "Partly cloudy, mild"}, "de") == "Partly cloudy, mild"


def test_weather_summary_text_empty_input_is_empty() -> None:
    assert weather_summary_text({}, "de") == ""
    assert weather_summary_text({"temp_c": None, "conditions": None}, "de") == ""


# ── German export ────────────────────────────────────────────────────────


def _german_pdf_text() -> str:
    pdf = generate_diary_pdf(
        _audit_diary(),
        project_name="Bürogebäude Frankfurt Europaviertel",
        entries=[_completion_entry()],
        locale="de",
    )
    assert pdf.startswith(b"%PDF")
    return _pdf_text(pdf)


def test_de_pdf_has_german_sections_dates_and_weather() -> None:
    text = _german_pdf_text()
    for expected in (
        "Bautagebuch",
        "Übersicht",
        "Bauleiter",
        "Arbeitskräfte vor Ort",
        "Geräte vor Ort",
        "Vollständigkeit",
        "Wetter",
        "Tagesprotokoll",
        "Notizen",
        "GESCHLOSSEN",
        "23.03.2028",
        "20 °C, klar",
        "Ausgeführte Arbeiten",
        "Seite 1",
        "Erstellt:",
    ):
        assert expected in text, f"missing German fragment: {expected!r}"


def test_de_pdf_has_no_raw_keys_and_no_english_labels() -> None:
    text = _german_pdf_text()
    for pattern in RAW_KEY_PATTERNS:
        assert pattern not in text, f"raw key leaked into German PDF: {pattern!r}"
    for label in ENGLISH_LABELS:
        assert label not in text, f"English label leaked into German PDF: {label!r}"
    # The ISO date must be re-rendered, not merely accompanied.
    assert "2028-03-23" not in text


# ── English export: original labels, human weather line ─────────────────


def test_en_pdf_keeps_every_original_label() -> None:
    pdf = generate_diary_pdf(
        _audit_diary(),
        project_name="Riverside Office Campus",
        entries=[_completion_entry()],
        locale="en",
    )
    text = _pdf_text(pdf)
    for expected in (
        "Daily Site Diary",
        "Overview",
        "Site supervisor",
        "Not recorded",
        "Labour on site",
        "Equipment on site",
        "Completeness",
        "Weather",
        "Site record",
        "Work performed",
        "Notes",
        "CLOSED",
        "2028-03-23",
        "Generated:",
        "Page 1",
    ):
        assert expected in text, f"missing original English fragment: {expected!r}"
    # The only intended change on the English side: the weather summary
    # is now a human line instead of raw key/value pairs.
    assert "20 °C, clear" in text
    for pattern in RAW_KEY_PATTERNS:
        assert pattern not in text, f"raw key survived in English PDF: {pattern!r}"


def test_en_is_the_default_locale() -> None:
    kwargs: dict[str, Any] = {
        "project_name": "Riverside Office Campus",
        "entries": [_completion_entry()],
    }
    implicit = generate_diary_pdf(_audit_diary(), **kwargs)
    explicit = generate_diary_pdf(_audit_diary(), locale="en", **kwargs)
    assert _stable_text(implicit) == _stable_text(explicit)


# ── Unknown locale falls back to English ─────────────────────────────────


@pytest.mark.parametrize("unknown", ["zz", "xx", "de_DE_bad", "zz-ZZ"])
def test_unknown_locale_falls_back_to_english(unknown: str) -> None:
    kwargs: dict[str, Any] = {
        "project_name": "Riverside Office Campus",
        "entries": [_completion_entry()],
    }
    fallback = generate_diary_pdf(_audit_diary(), locale=unknown, **kwargs)
    english = generate_diary_pdf(_audit_diary(), locale="en", **kwargs)
    assert _stable_text(fallback) == _stable_text(english)


# ── Endpoint: Accept-Language drives the document and the filename ──────


async def _allow_access(*_args: Any, **_kwargs: Any) -> None:
    return None


@pytest.mark.asyncio
async def test_diary_pdf_endpoint_german_via_accept_language() -> None:
    from app.modules.daily_diary import router as diary_router

    svc = _make_service()
    diary = await svc.create_diary(
        _diary_payload(weather_summary={"temp_c": 20, "conditions": "clear"}),
        user_id="u",
    )

    with patch.object(diary_router, "verify_project_access", _allow_access):
        response = await diary_router.diary_pdf(
            diary_id=diary.id,
            session=_StubSession(),
            locale=None,
            accept_language="de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            user_id="u",
            _perm=None,
            service=svc,
        )

    assert response.status_code == 200
    assert response.media_type == "application/pdf"
    assert "bautagebuch-2026-04-10.pdf" in response.headers["content-disposition"]
    assert response.headers["content-language"] == "de"

    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    text = _pdf_text(b"".join(chunks))

    assert "Übersicht" in text
    assert "10.04.2026" in text
    assert "2026-04-10" not in text  # the body date is re-rendered, not ISO
    assert "20 °C, klar" in text
    for pattern in RAW_KEY_PATTERNS:
        assert pattern not in text
    assert "Overview" not in text


@pytest.mark.asyncio
async def test_diary_pdf_endpoint_defaults_to_english_without_header() -> None:
    from app.modules.daily_diary import router as diary_router

    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")

    with patch.object(diary_router, "verify_project_access", _allow_access):
        response = await diary_router.diary_pdf(
            diary_id=diary.id,
            session=_StubSession(),
            locale=None,
            accept_language=None,
            user_id="u",
            _perm=None,
            service=svc,
        )

    assert "diary-2026-04-10.pdf" in response.headers["content-disposition"]

    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    text = _pdf_text(b"".join(chunks))
    assert "Overview" in text
    assert "Übersicht" not in text


@pytest.mark.asyncio
async def test_diary_pdf_endpoint_unsupported_header_degrades_and_declares_english() -> None:
    """The reader asked for a language the diary cannot be written in.

    Serving English is the behaviour we want; serving it while the response
    claimed to be in the requested language was the defect. The Accept-Language
    middleware fills ``Content-Language`` from the request, so the route has to
    overwrite it with the language it really rendered, and this asserts that it
    does - the degradation is now something a client can detect.
    """
    from app.modules.daily_diary import router as diary_router

    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")

    with patch.object(diary_router, "verify_project_access", _allow_access):
        response = await diary_router.diary_pdf(
            diary_id=diary.id,
            session=_StubSession(),
            locale=None,
            accept_language="zz-ZZ,zz;q=0.9",
            user_id="u",
            _perm=None,
            service=svc,
        )

    assert "diary-2026-04-10.pdf" in response.headers["content-disposition"]
    assert response.headers["content-language"] == "en"
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    assert "Overview" in _pdf_text(b"".join(chunks))
