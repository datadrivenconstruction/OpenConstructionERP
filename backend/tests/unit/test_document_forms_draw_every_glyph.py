# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every printed form draws every glyph of every language it is offered in.

A form is offered in a language once its labels are translated, but whether the
PDF can draw that script is a different question: a face with no glyph for a
character writes glyph zero, the box, and nothing raises. Two instruments:

* the labels of each form, in every offered language, are walked character by
  character against the face ladder the PDF layer uses (no rendering, so all
  languages are covered);
* each form is rendered through its production code path in a sample of scripts
  (Arabic, Persian, Hebrew, Urdu, Hindi, Thai, Japanese, Korean, Chinese, Greek,
  Vietnamese, Kazakh, Kyrgyz and two Latin ones) and the drawn page is read back:
  no character may sit in a face that has no glyph for it.

Right-to-left forms must also be shaped, as the register PDFs are.
"""

from __future__ import annotations

import io
import re
import types
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pypdf
import pytest

from app.core.document_forms_i18n import REGISTER_UNRENDERABLE, document_form_locales
from app.core.pdf_fonts import font_can_draw, pdf_font_runs, register_pdf_fonts
from tests.unit.test_registers_set_mixed_scripts_in_runs import _missing_glyphs

SAMPLE = ("en", "de", "ar", "fa", "he", "ur", "hi", "th", "ja", "ko", "zh", "el", "vi", "kk", "ky")
ARABIC_SCRIPT = ("ar", "fa", "ur")
LATIN = ("en", "de", "vi")
#: Shaping puts letters in the Arabic presentation blocks; the logical letters are not drawn.
_PRESENTATION = re.compile("[ﭐ-﷿ﹰ-﻿]")


@pytest.fixture(autouse=True)
def _fonts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.company_profile.read_company_profile", lambda: {})
    register_pdf_fonts()


def _text(pdf: bytes) -> str:
    return "".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def _assert_drawn(pdf: bytes, locale: str) -> str:
    assert pdf.startswith(b"%PDF")
    assert _missing_glyphs(pdf) == []
    text = _text(pdf)
    if locale not in LATIN and locale not in ("de",):
        # A sample in another script really put that script on the page.
        assert any(ord(ch) > 0x2FF for ch in text), locale
    return text


def _undrawable(strings: dict[str, str]) -> list[tuple[str, str]]:
    bad: list[tuple[str, str]] = []
    for key, value in strings.items():
        for face, chunk in pdf_font_runs(value):
            bad += [(key, ch) for ch in chunk if ch.isprintable() and not ch.isspace() and not font_can_draw(face, ch)]
    return bad


# -- the labels ----------------------------------------------------------------------


def _label_tables() -> dict[str, dict[str, dict[str, str]]]:
    from app.modules.boq.pdf_export import _PDF_LABELS
    from app.modules.einvoice import pdf_translations as einvoice
    from app.modules.reporting import report_translations as report

    return {"boq_pdf": _PDF_LABELS, "report": report._STRINGS, "einvoice_pdf": einvoice._STRINGS}


@pytest.mark.parametrize("form", ["boq_pdf", "report", "einvoice_pdf"])
def test_every_label_of_an_offered_language_has_a_glyph_in_some_face(form: str) -> None:
    tables = _label_tables()[form]
    offered = document_form_locales()[form]
    assert offered
    for locale in offered:
        assert _undrawable(tables[locale]) == [], (form, locale)


@pytest.mark.parametrize("form", ["boq_pdf", "report", "einvoice_pdf"])
def test_a_language_the_pdf_cannot_draw_is_not_offered(form: str) -> None:
    offered = document_form_locales()[form]
    assert not set(offered) & set(REGISTER_UNRENDERABLE)
    assert "bn" not in _label_tables()[form]


# -- the bill of quantities ----------------------------------------------------------


def _bill() -> Any:
    from tests.unit import test_boq_pdf_carries_what_the_browser_pdf_did as boq

    position = boq._position("01.001", "10", "5", "50", description="Concrete wall")
    return boq._bill([boq._section([position], "50")], markups=[boq._tax("VAT", 20, "10")])


@pytest.mark.parametrize("locale", SAMPLE)
def test_the_bill_of_quantities_draws_every_glyph(locale: str) -> None:
    from app.modules.boq.pdf_export import generate_boq_pdf

    pdf = generate_boq_pdf(_bill(), "Harbour", currency="EUR", prepared_by="A B", locale=locale)
    _assert_drawn(pdf, locale if locale != "zh" else "en")


@pytest.mark.parametrize("locale", ARABIC_SCRIPT)
def test_an_arabic_script_bill_is_shaped(locale: str) -> None:
    from app.modules.boq.pdf_export import _PDF_LABELS, generate_boq_pdf

    text = _text(generate_boq_pdf(_bill(), "Harbour", currency="EUR", locale=locale))
    assert _PRESENTATION.search(text)
    assert _PDF_LABELS[locale]["cost_estimate"] not in text  # the logical letters are not what is drawn


def test_a_hebrew_bill_carries_its_labels() -> None:
    from app.modules.boq.pdf_export import _PDF_LABELS, generate_boq_pdf

    text = _text(generate_boq_pdf(_bill(), "Harbour", currency="EUR", locale="he"))
    assert _PDF_LABELS["he"]["cost_estimate"] in text or _PDF_LABELS["he"]["cost_estimate"][::-1] in text


# -- the generated report ------------------------------------------------------------


@pytest.mark.parametrize("locale", SAMPLE)
def test_the_report_draws_every_glyph(locale: str) -> None:
    from tests.unit import test_a_generated_report_is_written_in_the_readers_language as report

    _assert_drawn(report._export("pdf", locale), locale)


# -- the e-invoice page --------------------------------------------------------------


@pytest.mark.parametrize("locale", SAMPLE)
def test_the_einvoice_page_draws_every_glyph(locale: str) -> None:
    from tests.unit import test_einvoice_pdf_locale as einvoice

    _assert_drawn(einvoice._build(locale), locale)


# -- the meeting minutes (labels are English; names and notes are the user's) --------

_MINUTES_SAMPLE = {
    "en": "Site meeting (Block A)",
    "ar": "اجتماع الموقع (المبنى A)",
    "fa": "جلسه کارگاه (بلوک A)",
    "he": "ישיבת אתר (בניין A)",
    "ur": "سائٹ میٹنگ صفحہ 2 (A)",
    "hi": "साइट बैठक (ब्लॉक A) m²",
    "th": "ประชุมไซต์ (อาคาร A) m²",
    "ja": "現場会議 (A棟)",
    "ko": "현장 회의 (A동)",
    "zh": "现场会议 (A栋)",
    "el": "Σύσκεψη εργοταξίου (Α)",
    "vi": "Họp công trường (Khối A)",
    "kk": "Құрылыс алаңы жиналысы (A)",
    "ky": "Курулуш жыйыны (A)",
}


@pytest.mark.parametrize("locale", sorted(_MINUTES_SAMPLE))
def test_the_meeting_minutes_draw_every_glyph(locale: str) -> None:
    from app.modules.meetings.pdf import build_minutes_pdf

    note = _MINUTES_SAMPLE[locale]
    content = {
        "title": note,
        "meeting_date": "2026-08-23",
        "location": note,
        "meeting_type": "site_meeting",
        "meeting_number": "001",
        "chairperson": note,
        "attendees_present": [{"name": note}],
        "attendees_absent": [{"name": note}],
        "agenda": [{"number": "1", "topic": note, "discussion": note, "decision": note, "required": True}],
        "action_items": [{"description": note, "owner": note, "due_date": "2026-09-01", "status": "open"}],
        "summary": note,
        "next_meeting_date": "2026-09-01",
    }
    meeting = types.SimpleNamespace(title=note, meeting_number="001", meeting_date="2026-08-23")
    minutes = types.SimpleNamespace(content=content, status="issued", issued_at=datetime.now(tz=UTC))
    pdf = build_minutes_pdf(meeting, minutes, note)
    _assert_drawn(pdf, locale)


# -- the property documents ----------------------------------------------------------


def _stub(**kw: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(**kw)


@pytest.mark.parametrize("locale", SAMPLE)
def test_the_property_documents_draw_every_glyph(locale: str) -> None:
    from app.modules.property_dev import document_templates as dt

    contract = _stub(
        id=uuid.uuid4(),
        contract_number="SPA-2026-001",
        signing_date="2026-06-01",
        currency="EUR",
        total_value=Decimal("450000"),
        status="draft",
        total_price_breakdown={"base": "450000", "vat": "0"},
        metadata_={},
    )
    installments = [
        _stub(
            sequence=1,
            milestone_label="Reservation",
            milestone_event="reservation",
            due_date="2026-06-01",
            amount=Decimal("10000"),
        )
    ]
    parties = [
        _stub(
            buyer_id=uuid.uuid4(),
            party_role="primary",
            ownership_pct=Decimal("100"),
            full_name="Buyer One",
            email="one@example.com",
        )
    ]
    plot = _stub(plot_number="A-01", area_m2=Decimal("120"), currency="EUR", metadata_={})
    development = _stub(name="Marina Heights", code="MAR01", metadata_={"regulator": "NONE"})
    reservation = _stub(
        id=uuid.uuid4(),
        reservation_number="RES-1",
        deposit_amount=Decimal("10000"),
        currency="EUR",
        expires_at="2026-06-15",
        cooling_off_until="2026-06-15",
        cooling_off_days=14,
        status="active",
    )
    handover = _stub(
        id=uuid.uuid4(), completed_at="2027-06-15", keys_handed_over_at="2027-06-15", snag_count_at_handover=2
    )
    signed = _stub(contract_number="SPA-2026-001", status="signed", id=uuid.uuid4(), currency="EUR")
    documents = [
        dt.render_sales_contract_pdf(
            contract, _stub(currency="EUR"), installments, parties, plot, development, locale=locale
        ),
        dt.render_reservation_receipt_pdf(
            reservation, plot, development, [_stub(full_name="John Doe", email="j@example.com")], locale=locale
        ),
        dt.render_handover_certificate_pdf(
            handover, signed, snag_count=2, plot=plot, development=development, locale=locale
        ),
    ]
    for pdf in documents:
        _assert_drawn(pdf, locale)
