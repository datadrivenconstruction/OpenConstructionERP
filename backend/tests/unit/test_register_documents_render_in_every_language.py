# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The register and record forms render in every language they are offered in.

``test_register_documents_speak_every_language.py`` pins the catalogues. This
file renders the documents themselves, with the rows of the Turkish pilot
tests, in every language of the catalogue, and holds two things:

* nothing raises, whatever the script: Latin, Cyrillic, Greek, Arabic and
  Hebrew (right to left), Devanagari, Thai and the CJK faces;
* the register's own title is on the page in the document language, so the
  document is not an English one with a translated filename;
* the catalogue strings themselves are drawable (see the speak-every-language
  file); row data in another script than the label is a per-string face limit
  of the printers and is not asserted here.

Scripts whose extracted text does not read back in logical order (shaped Arabic
and Hebrew are stored in presentation order) are held to the NUL check only.
"""

from __future__ import annotations

import io
import unicodedata
from typing import Any

import pytest
from pypdf import PdfReader

from app.core.document_forms_i18n import register_form_catalogue
from app.core.pdf_fonts import register_pdf_fonts
from app.core.register_export import RegisterDocument, register_layout
from app.modules.daily_diary.pdf_export import generate_diary_pdf
from tests.unit import test_daily_diary_pdf_turkish as diary_fixtures
from tests.unit import test_pilot_documents_render_in_turkish as pilot
from tests.unit.test_register_documents_speak_every_language import DOCUMENT_LOCALES

#: Scripts the extractor does not return as typed: right to left, and the shaped Devanagari and Thai.
VISUAL_ORDER = {"ar", "fa", "he", "ur", "hi", "th"}

#: The first string of each case that names the document, by catalogue key.
TITLE_KEYS = ("register_title", "variation_register_title")


@pytest.fixture(autouse=True)
def _no_company_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a company profile on the machine running the tests out of them."""
    monkeypatch.setattr("app.core.company_profile.read_company_profile", lambda: {})


def _text(pdf: bytes) -> str:
    raw = " ".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(pdf)).pages)
    return " ".join(unicodedata.normalize("NFC", raw).replace(" ", " ").split())


def test_the_bundled_faces_are_in_use() -> None:
    assert register_pdf_fonts() is True


@pytest.mark.parametrize("locale", DOCUMENT_LOCALES)
@pytest.mark.parametrize("case", pilot.CASES, ids=pilot.CASE_IDS)
def test_every_document_renders_in_the_language(case: Any, locale: str) -> None:
    assert register_pdf_fonts() is True
    documents = pilot._documents(case, locale)
    assert documents
    for document in documents:
        pdf = pilot._render(document)
        assert pdf.startswith(b"%PDF")
        text = _text(pdf)
        assert text.strip()
        if isinstance(document, RegisterDocument):
            layout = register_layout(document)
            assert layout.overflow == (), (case.name, locale, [document.columns[i].header for i in layout.overflow])
            assert layout.font_size >= 6.5
    if locale not in VISUAL_ORDER:
        titles = {document.title for document in documents}
        flat = _text(pilot._render(documents[0]))
        assert any(pilot._flat(title) in flat for title in titles), (case.name, locale, titles)


@pytest.mark.parametrize("locale", DOCUMENT_LOCALES)
def test_the_daily_diary_renders_in_the_language(locale: str) -> None:
    assert register_pdf_fonts() is True
    pdf = generate_diary_pdf(
        diary_fixtures._diary(),
        project_name="Işıklı Veri Merkezi",
        entries=diary_fixtures._entries(),
        weather_records=diary_fixtures._weather(),
        supervisor_name="Şükrü Iğdır",
        completeness=diary_fixtures.Decimal("0.85"),
        locale=locale,
    )
    assert pdf.startswith(b"%PDF")
    text = _text(pdf)
    if locale not in VISUAL_ORDER:
        title = register_form_catalogue("daily_diary").tr(locale, "doc_title")
        assert pilot._flat(title) in text, (locale, title)
