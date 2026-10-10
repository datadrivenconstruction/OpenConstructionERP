"""Tests for the printable single-RFI PDF.

Before the export existed, the only way to put one RFI on paper was the
browser's print command on the detail page, which printed three A4 sheets for
a short RFI and left the project name off (it lives in the breadcrumb, which
the print stylesheet hides). These tests pin the document that replaces it:

* the form carries the project, the people by name, the question, the impact
  with the project's currency, the answer and the signature block;
* a person the lookup could not resolve is shortened, never printed as a whole
  UUID;
* every left-to-right language the interface offers and the font ladder can
  draw gets a document in that language, with day counts in the right
  grammatical form; right-to-left languages and Bengali get English;
* user text is printed as text, not parsed as reportlab markup;
* a question longer than the rest of page one starts on page one and runs on,
  rather than leaving page one empty under the grid;
* the route resolves ``?locale=`` and ``Accept-Language``, names the file after
  the RFI number, declares the language it rendered in ``Content-Language``, and
  refuses a caller the project check refuses.

Text assertions go through ``pypdf`` extraction, like the diary PDF tests.
"""

from __future__ import annotations

import io
import string
import unicodedata
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pypdf import PdfReader

from app.core.pdf_fonts import (
    BODY_FONT,
    BOLD_FONT,
    DEVANAGARI_FONT,
    THAI_FONT,
    font_can_draw_all,
    pdf_font_for_text,
)
from app.modules.rfi import intl
from app.modules.rfi import pdf_translations as catalogue
from app.modules.rfi.pdf_export import build_rfi_pdf
from app.modules.rfi.pdf_translations import (
    SUPPORTED_PDF_LOCALES,
    UNRENDERABLE_PDF_LOCALES,
    days_text,
    format_date,
    normalize_pdf_locale,
    priority_label,
    resolve_pdf_locale,
    rfi_pdf_filename,
    status_caps,
    tr,
)
from app.modules.rfi.service import RFIService


@pytest.fixture(autouse=True)
def _no_company_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a company profile on the machine running the tests out of them.

    The profile is read from the real data dir, and a letterhead on top of the
    form would move the page counts asserted below. The letterhead has its own
    tests in ``test_pdf_letterhead``.
    """
    monkeypatch.setattr("app.core.company_profile.read_company_profile", lambda: {})


RAISER = uuid.UUID("8f6203d9-f81a-41f9-acb3-d67bc5d8187c")
ANSWERER = uuid.UUID("0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d")
PEOPLE = {str(RAISER): "Maria Keller", str(ANSWERER): "Tom Architect"}


def _rfi(**overrides: Any) -> SimpleNamespace:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "rfi_number": "RFI-007",
        "subject": "External walls - lintel detail at grid C/4",
        "question": "Drawing A-201 shows a precast lintel.\nS-110 shows an in-situ beam. Which governs?",
        "raised_by": RAISER,
        "assigned_to": ANSWERER,
        "ball_in_court": ANSWERER,
        "status": "answered",
        "official_response": "Use the in-situ beam per S-110 rev B.",
        "responded_by": ANSWERER,
        "responded_at": "2026-09-14T10:22:31+00:00",
        "cost_impact": True,
        "cost_impact_value": "12000",
        "schedule_impact": True,
        "schedule_impact_days": 3,
        "date_required": "2026-09-20",
        "response_due_date": "2026-09-18",
        "linked_drawing_ids": [],
        "attachments": [],
        "change_order_id": None,
        "priority": "high",
        "discipline": "structural",
        "created_at": datetime(2026, 9, 10, 8, 15, tzinfo=UTC),
    }
    row.update(overrides)
    return SimpleNamespace(**row)


def _render(rfi: SimpleNamespace | None = None, **kwargs: Any) -> bytes:
    params: dict[str, Any] = {
        "project_name": "Residential House",
        "project_code": "RH-01",
        "currency": "USD",
        "people": PEOPLE,
    }
    params.update(kwargs)
    return build_rfi_pdf(rfi or _rfi(), **params)


def _pages(pdf: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages]


def _text(pdf: bytes) -> str:
    # An amount and its currency code are joined by a no-break space.
    return "\n".join(_pages(pdf)).replace("\u00a0", " ")


# ── Renderer ──────────────────────────────────────────────────────────────


def test_english_form_carries_every_field() -> None:
    pdf = _render(documents=["A-201 Elevations rev C.pdf"], variation="CO-003 - Lintel change")
    assert pdf.startswith(b"%PDF")
    text = _text(pdf)
    for expected in (
        "Request for Information",
        "RFI-007",
        "Residential House (RH-01)",
        "External walls - lintel detail at grid C/4",
        "Which governs?",
        "Maria Keller",
        "Tom Architect",
        "2026-09-10",
        "2026-09-18",
        "2026-09-20",
        "High",
        "Structural",
        "A-201 Elevations rev C.pdf",
        "Yes, 12,000.00 USD",
        "Yes, 3 days",
        "Use the in-situ beam per S-110 rev B.",
        "2026-09-14",
        "CO-003 - Lintel change",
        "Signatures",
        "ANSWERED",
    ):
        assert expected in text, expected


def test_a_short_rfi_prints_on_one_page() -> None:
    """The browser print of the same RFI took three sheets; the form takes one."""
    assert len(_pages(_render(documents=["A-201.pdf", "S-110.pdf"], variation="CO-003"))) == 1


def test_people_print_by_name_and_an_unknown_id_is_a_dash() -> None:
    stranger = uuid.UUID("11111111-2222-4333-8444-555555555555")
    text = _text(_render(_rfi(assigned_to=stranger, ball_in_court=None)))
    assert "Maria Keller" in text
    # No part of a UUID is printed on a document meant for people.
    assert "11111111" not in text
    assert str(stranger) not in text
    assert str(RAISER) not in text


def test_no_answer_prints_the_blank_answer_box() -> None:
    text = _text(_render(_rfi(status="open", official_response=None, responded_by=None, responded_at=None)))
    assert "No response recorded yet." in text
    assert "OPEN" in text
    # Nobody answered, so there is no "Answered by / Answer date" row, only the
    # signature line waiting for a name.
    assert "Answer date" not in text


def test_no_impact_says_no() -> None:
    text = _text(_render(_rfi(cost_impact=False, cost_impact_value=None, schedule_impact=False)))
    assert "Cost impact" in text
    assert "Yes," not in text


def test_german_request_renders_german() -> None:
    text = _text(_render(locale="de"))
    for expected in ("Technische Anfrage (RFI)", "Frage", "Offizielle Antwort", "Ja, 3 Tage", "10.09.2026", "Tragwerk"):
        assert expected in text, expected
    for english in ("Request for Information", "Question", "Official response"):
        assert english not in text, english


def test_russian_request_renders_russian_with_the_right_day_form() -> None:
    text = _text(_render(_rfi(schedule_impact_days=21), locale="ru"))
    for expected in ("Запрос информации (RFI)", "Вопрос", "Официальный ответ", "Да, 21 день", "10.09.2026"):
        assert expected in text, expected
    assert "Question" not in text


@pytest.mark.parametrize("locale", ["ar", "he", "bn", "zz"])
def test_unsupported_locale_falls_back_to_english(locale: str) -> None:
    assert "Request for Information" in _text(_render(locale=locale))


def test_user_text_is_printed_not_parsed_as_markup() -> None:
    subject = '<font color="white">hidden</font> & <b>bold</b>'
    pdf = _render(_rfi(subject=subject, question='<img src="x" onerror="alert(1)"/> <para>'))
    text = _text(pdf)
    assert '<font color="white">hidden</font>' in text
    assert '<img src="x"' in text


def test_cjk_subject_renders() -> None:
    text = _text(_render(_rfi(subject="结构：C/4轴窗过梁节点澄清")))
    assert "结构：C/4轴窗过梁节点澄清" in text


def test_a_long_question_starts_on_page_one_and_runs_on() -> None:
    """A question taller than the rest of page one used to push its heading and
    box to page two, leaving page one empty under the grid."""
    long_question = ("Please confirm the lintel detail at every opening on the east elevation. " * 12 + "\n") * 40
    pages = _pages(_render(_rfi(question=long_question)))
    assert len(pages) > 1
    assert "Question" in pages[0]
    assert "Please confirm the lintel detail" in pages[0]


def test_referenced_documents_report_what_is_gone_and_the_attachment_count() -> None:
    text = _text(
        _render(
            _rfi(attachments=["rfi/attachments/a.pdf", "rfi/attachments/b.jpg"]),
            documents=["A-201.pdf"],
            unavailable_documents=2,
        )
    )
    assert "A-201.pdf" in text
    assert "Linked documents no longer available: 2" in text
    assert "Attached files: 2" in text


# ── Catalogue helpers ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "1 день"),
        (2, "2 дня"),
        (4, "4 дня"),
        (5, "5 дней"),
        (11, "11 дней"),
        (12, "12 дней"),
        (14, "14 дней"),
        (21, "21 день"),
        (22, "22 дня"),
        (111, "111 дней"),
        (112, "112 дней"),
    ],
)
def test_russian_day_forms(count: int, expected: str) -> None:
    assert days_text(count, "ru") == expected


def test_english_and_german_day_forms() -> None:
    assert days_text(1, "en") == "1 day"
    assert days_text(3, "en") == "3 days"
    assert days_text(1, "de") == "1 Tag"
    assert days_text(3, "de") == "3 Tage"


def test_format_date_reads_every_stored_shape() -> None:
    assert format_date(datetime(2026, 4, 6, 23, 0, tzinfo=UTC), "de") == "06.04.2026"
    assert format_date("2026-04-06", "en") == "2026-04-06"
    assert format_date("2026-04-06T10:22:31.123456+00:00", "ru") == "06.04.2026"
    assert format_date("2026-04-06T10:22:31Z", "en") == "2026-04-06"
    assert format_date("next Tuesday", "en") == "next Tuesday"
    assert format_date(None, "en") == "-"
    assert format_date("  ", "en") == "-"


def test_a_regional_locale_reads_its_language() -> None:
    # The lookups are public, so a caller may hand them "de-AT" rather than
    # the resolved "de"; that must not drop the page back to English.
    assert priority_label("low", "de-AT") == priority_label("low", "de") == "Niedrig"
    assert days_text(3, "ru-RU") == days_text(3, "ru") == "3 дня"
    assert format_date("2026-04-06", "de-CH") == "06.04.2026"
    assert tr("DE", "question") == tr("de", "question")


def test_filename_follows_the_rfi_number() -> None:
    assert rfi_pdf_filename("RFI-007") == "RFI-007.pdf"
    assert rfi_pdf_filename("RFI 7/B") == "RFI_7_B.pdf"
    assert rfi_pdf_filename("") == "rfi.pdf"


def test_locale_resolution() -> None:
    assert resolve_pdf_locale("de", "ru-RU,ru;q=0.9") == "de"
    assert resolve_pdf_locale(None, "ru-RU,ru;q=0.9,en;q=0.8") == "ru"
    assert resolve_pdf_locale(None, "fr-FR,fr;q=0.9") == "fr"
    assert resolve_pdf_locale("pt-BR", None) == "pt"
    assert resolve_pdf_locale("es-MX", None) == "es"
    assert resolve_pdf_locale("en-GB", None) == "en"
    assert resolve_pdf_locale(None, "ar-SA,ar;q=0.9") == "en"
    assert resolve_pdf_locale(None, "ar-SA,ar;q=0.9,fr;q=0.8") == "fr"
    assert resolve_pdf_locale(None, None) == "en"


# ── Every supported language ─────────────────────────────────────────────

# Thai and Hindi are shaped on the way to the page, and reportlab writes the
# substituted glyphs without a text mapping, so text extraction drops tone
# marks and vowel signs. Their documents are checked by the face they are drawn
# in rather than by extracted words; the page itself was checked by rendering it.
_SHAPED_LOCALES = {"th": THAI_FONT, "hi": DEVANAGARI_FONT}
_NON_ENGLISH = [loc for loc in SUPPORTED_PDF_LOCALES if loc != "en"]


def _fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _page_fonts(pdf: bytes) -> set[str]:
    names: set[str] = set()
    for page in PdfReader(io.BytesIO(pdf)).pages:
        fonts = page["/Resources"].get("/Font") or {}
        for ref in fonts.values():
            names.add(str(ref.get_object()["/BaseFont"]))
    return names


def test_the_pdf_and_the_status_words_cover_the_same_languages() -> None:
    """A translated heading over an English status word is the defect the two
    tables exist to prevent, so they must list the same languages."""
    assert set(SUPPORTED_PDF_LOCALES) == intl._SUPPORTED_LOCALES
    assert set(SUPPORTED_PDF_LOCALES) == set(catalogue._STRINGS)
    assert set(SUPPORTED_PDF_LOCALES) == set(catalogue._PRIORITY_LABELS)
    assert set(SUPPORTED_PDF_LOCALES) == set(catalogue._DAY_FORMS)
    assert set(SUPPORTED_PDF_LOCALES) == set(catalogue._PLURAL_RULES)
    assert not set(SUPPORTED_PDF_LOCALES) & set(UNRENDERABLE_PDF_LOCALES)


@pytest.mark.parametrize("locale", _NON_ENGLISH)
def test_every_key_is_translated_with_the_same_placeholders(locale: str) -> None:
    english = catalogue._STRINGS["en"]
    table = catalogue._STRINGS[locale]
    assert set(table) == set(english)
    for key, template in english.items():
        assert table[key].strip(), key
        assert _fields(table[key]) == _fields(template), key
    assert set(catalogue._PRIORITY_LABELS[locale]) == set(catalogue._PRIORITY_LABELS["en"])
    # The date patterns must be ones strftime fills in completely.
    assert "%" not in date(2026, 9, 10).strftime(table["date_format"])
    assert "2026" in date(2026, 9, 10).strftime(table["date_format"])


@pytest.mark.parametrize("locale", SUPPORTED_PDF_LOCALES)
def test_every_string_draws_in_one_face(locale: str) -> None:
    """Each string the form prints, composed the way the renderer composes it,
    has a face on the ladder that carries every character, regular and bold."""
    strings = [
        tr(locale, key, count=2, detail="3", timestamp="2026-09-10 08:15 UTC", page=1)
        for key in catalogue._STRINGS["en"]
        if not key.endswith("_format")
    ]
    strings += list(catalogue._PRIORITY_LABELS[locale].values())
    strings += [intl.localize_status(s, locale) for s in intl.RFI_STATUSES]
    strings += [status_caps(intl.localize_status(s, locale), locale) for s in intl.RFI_STATUSES]
    strings += [intl.localize_discipline(d, locale) for d in intl.RFI_DISCIPLINES]
    strings += [days_text(n, locale) for n in (1, 3, 5, 21)]
    strings += [
        f"OpenConstructionERP  |  {tr(locale, 'footer_generated', timestamp='2026-09-10 08:15 UTC')}",
        f"{tr(locale, 'attachments')}: 2",
        f"{tr(locale, 'variation')}: CO-003",
        tr(locale, "yes_with", detail=days_text(3, locale)),
        tr(locale, "yes_with", detail="12000 USD"),
    ]
    for text in strings:
        for base in (BODY_FONT, BOLD_FONT):
            face = pdf_font_for_text(text, base=base)
            assert font_can_draw_all(face, text), (text, face)


@pytest.mark.parametrize("locale", _NON_ENGLISH)
def test_every_language_renders_its_own_document(locale: str) -> None:
    pdf = _render(locale=locale, documents=["A-201.pdf"], variation="CO-003")
    assert len(_pages(pdf)) == 1
    text = _text(pdf)
    for english in ("Request for Information", "Official response", "ANSWERED", "Schedule impact"):
        assert english not in text, english
    if locale in _SHAPED_LOCALES:
        assert any(_SHAPED_LOCALES[locale] in font for font in _page_fonts(pdf))
        assert "(RFI)" in text
        return
    flat = "".join(text.split())
    for expected in (
        tr(locale, "doc_title"),
        tr(locale, "question"),
        status_caps(intl.localize_status("answered", locale), locale),
        intl.localize_discipline("structural", locale),
        tr(locale, "yes_with", detail=days_text(3, locale)),
        format_date("2026-09-10", locale),
    ):
        assert expected in text or "".join(expected.split()) in flat, expected


@pytest.mark.parametrize("locale", sorted(UNRENDERABLE_PDF_LOCALES))
def test_right_to_left_and_uncovered_languages_resolve_to_english(locale: str) -> None:
    assert normalize_pdf_locale(locale) == "en"
    assert resolve_pdf_locale(locale, None) == "en"
    assert resolve_pdf_locale(None, f"{locale};q=0.9") == "en"
    assert tr(locale, "doc_title") == "Request for Information"
    assert intl.localize_status("open", locale) == "Open"


def test_bengali_stays_english_because_no_face_draws_it() -> None:
    """The evidence for keeping Bengali out. If a face that draws it is ever
    added to the ladder, this fails, and Bengali can join the catalogue."""
    bengali = "তথ্যের জন্য অনুরোধ"
    face = pdf_font_for_text(bengali)
    assert not font_can_draw_all(face, bengali)


@pytest.mark.parametrize(
    ("locale", "count", "expected"),
    [
        ("pl", 1, "1 dzień"),
        ("pl", 2, "2 dni"),
        ("pl", 5, "5 dni"),
        ("pl", 21, "21 dni"),
        ("cs", 1, "1 den"),
        ("cs", 3, "3 dny"),
        ("cs", 5, "5 dní"),
        ("cs", 22, "22 dní"),
        ("uk", 1, "1 день"),
        ("uk", 3, "3 дні"),
        ("uk", 11, "11 днів"),
        ("uk", 21, "21 день"),
        ("uk", 22, "22 дні"),
        ("hr", 1, "1 dan"),
        ("hr", 3, "3 dana"),
        ("hr", 11, "11 dana"),
        ("hr", 21, "21 dan"),
        ("ro", 1, "1 zi"),
        ("ro", 3, "3 zile"),
        ("ro", 19, "19 zile"),
        ("ro", 20, "20 de zile"),
        ("ro", 101, "101 zile"),
        ("ro", 120, "120 de zile"),
        ("fi", 1, "1 päivä"),
        ("fi", 3, "3 päivää"),
        ("et", 1, "1 päev"),
        ("et", 3, "3 päeva"),
        ("fr", 0, "0 jour"),
        ("fr", 1, "1 jour"),
        ("fr", 2, "2 jours"),
        ("es", 1, "1 día"),
        ("es", 3, "3 días"),
        ("el", 1, "1 ημέρα"),
        ("el", 3, "3 ημέρες"),
        ("bg", 1, "1 ден"),
        ("bg", 3, "3 дни"),
        ("ja", 1, "1日"),
        ("ja", 3, "3日"),
        ("zh", 3, "3天"),
        ("ko", 3, "3일"),
        ("th", 3, "3 วัน"),
        ("vi", 3, "3 ngày"),
        ("id", 3, "3 hari"),
        ("hu", 1, "1 nap"),
        ("hu", 3, "3 nap"),
        ("tr", 3, "3 gün"),
        ("kk", 3, "3 күн"),
        ("uz", 3, "3 kun"),
        ("fil", 3, "3 araw"),
        ("hi", 3, "3 दिन"),
    ],
)
def test_day_forms_per_language(locale: str, count: int, expected: str) -> None:
    assert days_text(count, locale) == expected


@pytest.mark.parametrize("locale", SUPPORTED_PDF_LOCALES)
def test_every_count_has_a_day_form(locale: str) -> None:
    for count in range(130):
        text = days_text(count, locale)
        assert str(count) in text
        assert "{" not in text


def test_status_caps_follows_the_language() -> None:
    assert status_caps("Geçersiz", "tr") == "GEÇERSİZ"
    assert status_caps("Kapalı", "tr") == "KAPALI"
    assert status_caps("Ανοιχτό", "el") == "ΑΝΟΙΧΤΟ"
    assert status_caps("Απαντήθηκε", "el") == "ΑΠΑΝΤΗΘΗΚΕ"
    assert status_caps("Beantwortet", "de") == "BEANTWORTET"
    assert status_caps("回答済み", "ja") == "回答済み"
    # Nothing the Greek rule leaves behind is a combining stress mark.
    for status in intl.RFI_STATUSES:
        caps = status_caps(intl.localize_status(status, "el"), "el")
        assert "́" not in unicodedata.normalize("NFD", caps)


def test_uzbek_uses_the_modifier_letters_not_apostrophes() -> None:
    """Uzbek writes o' and g' with U+02BB and the tutuq belgisi with U+02BC; a
    straight or curly quote there is a misspelling."""
    for text in catalogue._STRINGS["uz"].values():
        assert "'" not in text
        assert chr(0x2019) not in text
    assert chr(0x02BB) in tr("uz", "no")
    assert chr(0x02BC) in tr("uz", "impact")


# ── Route ─────────────────────────────────────────────────────────────────


class _StubRepo:
    def __init__(self, row: SimpleNamespace) -> None:
        self.row = row

    async def get_by_id(self, rfi_id: uuid.UUID) -> SimpleNamespace | None:
        return self.row if rfi_id == self.row.id else None


def _service(row: SimpleNamespace, *, country: str | None = None) -> RFIService:
    """An RFIService whose lookups answer from memory instead of the database."""
    service = RFIService.__new__(RFIService)
    service.session = None  # type: ignore[assignment]
    service.repo = _StubRepo(row)  # type: ignore[assignment]

    async def _project_header(_project_id: uuid.UUID) -> tuple[str, str | None, str, str | None]:
        return "Residential House", "RH-01", "USD", country

    async def _names(_ids: Any) -> dict[str, str]:
        return dict(PEOPLE)

    async def _documents(_project_id: uuid.UUID, _ids: Any) -> tuple[list[str], int]:
        return [], 0

    async def _variation(_project_id: uuid.UUID, _co_id: Any) -> None:
        return None

    service._project_header = _project_header  # type: ignore[method-assign]
    service.user_display_names = _names  # type: ignore[method-assign]
    service._linked_document_names = _documents  # type: ignore[method-assign]
    service._variation_label = _variation  # type: ignore[method-assign]
    return service


async def _allow_access(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _deny_access(*_args: Any, **_kwargs: Any) -> None:
    raise HTTPException(status_code=403, detail="Access denied")


async def _body(response: Any) -> bytes:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    return b"".join(chunks)


async def _call(row: SimpleNamespace, *, locale: str | None, accept_language: str | None, guard: Any = _allow_access):
    from app.modules.rfi import router as rfi_router

    with patch.object(rfi_router, "verify_project_access", guard):
        return await rfi_router.export_rfi_pdf(
            rfi_id=row.id,
            session=None,  # type: ignore[arg-type]
            user_id=str(RAISER),
            locale=locale,
            accept_language=accept_language,
            service=_service(row),
        )


@pytest.mark.asyncio
async def test_route_follows_accept_language_and_names_the_file() -> None:
    row = _rfi()
    response = await _call(row, locale=None, accept_language="de-DE,de;q=0.9,en;q=0.8")
    assert response.media_type == "application/pdf"
    assert response.headers["content-language"] == "de"
    assert "RFI-007.pdf" in response.headers["content-disposition"]
    text = _text(await _body(response))
    assert "Technische Anfrage (RFI)" in text
    assert "Maria Keller" in text


@pytest.mark.asyncio
async def test_route_query_parameter_wins_over_the_header() -> None:
    response = await _call(_rfi(), locale="ru", accept_language="de-DE,de;q=0.9")
    assert response.headers["content-language"] == "ru"
    assert "Запрос информации (RFI)" in _text(await _body(response))


@pytest.mark.asyncio
async def test_route_declares_english_when_it_cannot_render_the_asked_language() -> None:
    """The middleware fills Content-Language from the request; an Arabic reader
    gets an English document, and the header has to say English."""
    response = await _call(_rfi(), locale=None, accept_language="ar-SA,ar;q=0.9")
    assert response.headers["content-language"] == "en"
    assert "Request for Information" in _text(await _body(response))


@pytest.mark.asyncio
async def test_route_refuses_a_caller_the_project_check_refuses() -> None:
    with pytest.raises(HTTPException) as refused:
        await _call(_rfi(), locale=None, accept_language=None, guard=_deny_access)
    assert refused.value.status_code == 403


@pytest.mark.asyncio
async def test_route_404s_an_unknown_rfi() -> None:
    from app.modules.rfi import router as rfi_router

    row = _rfi()
    with patch.object(rfi_router, "verify_project_access", _allow_access), pytest.raises(HTTPException) as missing:
        await rfi_router.export_rfi_pdf(
            rfi_id=uuid.uuid4(),
            session=None,  # type: ignore[arg-type]
            user_id=str(RAISER),
            locale=None,
            accept_language=None,
            service=_service(row),
        )
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_the_service_hands_the_projects_country_to_the_form() -> None:
    """The form of a Turkish project printed in English dates the Turkish way, as the registers do."""
    row = _rfi()
    turkish, _number = await _service(row, country="TR").generate_rfi_pdf(row.id, locale="en")
    assert "20.09.2026" in _text(turkish)
    # The control: with no country on file the language decides, as before.
    plain, _number = await _service(row).generate_rfi_pdf(row.id, locale="en")
    assert "2026-09-20" in _text(plain)
    assert "20.09.2026" not in _text(plain)


# ── Page total, continuation header, the set's conventions ────────────────


def test_every_page_says_page_x_of_y_and_later_pages_name_the_rfi() -> None:
    long_question = ("Please confirm the lintel detail at every opening on the east elevation. " * 12 + "\n") * 40
    pages = [" ".join(page.replace("\u00a0", " ").split()) for page in _pages(_render(_rfi(question=long_question)))]
    assert len(pages) >= 3
    for number, page in enumerate(pages, 1):
        assert f"Page {number} of {len(pages)}" in page
        if number > 1:
            assert "RFI-007 · Residential House (RH-01)" in page, number
            assert tr("en", "doc_title") in page, number


def test_other_languages_keep_their_page_phrase_and_gain_the_total() -> None:
    assert catalogue.page_of_total(2, 5, "tr") == "Sayfa 2 / 5"
    assert catalogue.page_of_total(2, 5, "en") == "Page 2 of 5"
    assert catalogue.page_of_total(2, 5, "de") == "Seite 2 / 5"
    assert "Seite 1 / 1" in _text(_render(locale="de"))


def test_a_turkish_form_uses_the_sets_terms_currency_and_dates() -> None:
    text = " ".join(_text(_render(currency="TRY", country="TR", locale="tr")).split())
    for expected in (
        "Süre etkisi",
        "Adı Soyadı",
        "İhtiyaç tarihi",
        "Yanıt son tarihi",
        "Evet, 12.000,00 TL",
        "20.09.2026",
        "Sayfa 1 / 1",
    ):
        assert expected in text, expected
    for gone in ("Takvim etkisi", "Ad soyad", "TRY", "2026-09-20"):
        assert gone not in text, gone


def test_dates_follow_the_projects_country_in_english_and_only_then() -> None:
    assert "20.09.2026" in _text(_render(currency="TRY", country="TR"))
    # No country on file, or one the regional table does not know: the language decides.
    assert "2026-09-20" in _text(_render())
    assert "2026-09-20" in _text(_render(country="ZZ"))
    # A language the registers do not print in keeps its own way of writing a date.
    assert format_date("2026-09-20", "de") in _text(_render(country="US", locale="de"))
