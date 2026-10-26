"""The minutes PDF prints the shared, translated "Page x of y" footer."""

import io
import uuid
from types import SimpleNamespace

import pytest

from app.modules.meetings.pdf import build_minutes_pdf, minutes_page_text


@pytest.fixture(autouse=True, scope="module")
def _catalogues() -> None:
    from app.core.i18n import load_translations

    load_translations()


def _pages(pdf: bytes) -> list[str]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return [page.extract_text() or "" for page in doc.pages]


def _render(language: str, agenda_items: int = 1) -> bytes:
    meeting = SimpleNamespace(title="Weekly", meeting_number="007", meeting_date="2026-07-17", project_id=uuid.uuid4())
    content = {
        "title": "Weekly",
        "language": language,
        "attendees_present": [{"name": "A. Boiko"}],
        "attendees_absent": [],
        "agenda": [
            {"number": n + 1, "topic": f"Topic {n}", "discussion": "Discussion text. " * 60, "decision": "Proceed"}
            for n in range(agenda_items)
        ],
        "action_items": [],
        "summary": "Done.",
    }
    minutes = SimpleNamespace(content=content, status="issued", issued_at=None)
    return build_minutes_pdf(meeting, minutes, "Demo Project", locale=language)


@pytest.mark.parametrize(
    ("locale", "expected"),
    [("en", "Page 2 of 5"), ("de", "Seite 2 von 5"), ("ru", "Стр. 2 из 5")],
)
def test_page_text_uses_shared_furniture(locale: str, expected: str) -> None:
    assert minutes_page_text(locale, 2, 5) == expected


def test_page_text_total_never_below_page() -> None:
    assert minutes_page_text("en", 3, 0) == "Page 3 of 3"


def test_unknown_language_falls_back_to_english() -> None:
    assert minutes_page_text("xx", 1, 2) == "Page 1 of 2"


@pytest.mark.parametrize(("language", "word"), [("en", "Page"), ("de", "Seite"), ("ru", "Стр.")])
def test_footer_printed_in_minutes_language_with_real_total(language: str, word: str) -> None:
    pages = _pages(_render(language, agenda_items=12))
    assert len(pages) > 1
    for number, text in enumerate(pages, start=1):
        assert f"{word} {number}" in text
        assert f" {len(pages)}" in text.splitlines()[-1] or str(len(pages)) in text
    assert "Page" not in "".join(pages) if language != "en" else True
