"""The export handlers answer with the right file, name and language header.

The builders are covered row by row in
``test_pilot_documents_render_in_turkish.py``. What is pinned here is the thin
layer between a request and a builder, which every register and record route
shares: the language is taken from ``?locale=`` before ``Accept-Language``,
``Content-Language`` names the language the body is really in (English when
the one asked for is not in the catalogue), the filename is the localized
one, and ``?format=`` picks a workbook or a PDF.

No database: the handlers are called directly with a stub session, and the
two lookups that need one (project access, project header) are replaced.
"""

from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from app.core.register_export import ProjectHeader
from app.modules.submittals import export_routes

PROJECT_ID = uuid.UUID(int=7)
PROJECT = ProjectHeader(name="Işıklı Veri Merkezi", code="TR-001", currency="TRY", country="TR")


def _submittal() -> SimpleNamespace:
    return SimpleNamespace(
        project_id=PROJECT_ID,
        submittal_number="SUB-012",
        title="Soğutma grubu ölçüm çizimi",
        submittal_type="shop_drawing",
        spec_section="23 64 00",
        current_revision=1,
        status="under_review",
        date_submitted="2026-10-01",
        date_required="2026-10-10",
        date_returned=None,
        reviewer_id=None,
        approver_id=None,
        ball_in_court=None,
        submitted_by_org=None,
        metadata_={},
    )


class _Session:
    """Answers the one query a register route runs with a fixed list of rows."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, _statement: Any) -> Any:
        rows = self._rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


@pytest.fixture(autouse=True)
def _no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _allowed(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _header(*_args: Any, **_kwargs: Any) -> ProjectHeader:
        return PROJECT

    async def _names(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        return {}

    async def _one(_self: Any, _submittal_id: uuid.UUID) -> SimpleNamespace:
        return _submittal()

    monkeypatch.setattr(export_routes, "verify_project_access", _allowed)
    monkeypatch.setattr(export_routes, "load_project_header", _header)
    monkeypatch.setattr(export_routes, "resolve_party_names", _names)
    monkeypatch.setattr(export_routes.SubmittalService, "get_submittal", _one)
    monkeypatch.setattr("app.core.company_profile.read_company_profile", lambda: {})


async def _body(response: Any) -> bytes:
    chunks = [chunk async for chunk in response.body_iterator]
    return b"".join(chunk if isinstance(chunk, bytes) else chunk.encode() for chunk in chunks)


async def _register(**params: Any) -> Any:
    return await export_routes.export_submittal_register(
        user_id="user", session=_Session([_submittal()]), project_id=PROJECT_ID, **params
    )


@pytest.mark.asyncio
async def test_register_defaults_to_a_workbook_in_the_language_asked_for() -> None:
    response = await _register(export_format="xlsx", locale="tr", accept_language="en-US,en;q=0.9")
    assert response.headers["content-language"] == "tr"
    assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert 'filename="onay-belgeleri-takip-listesi.xlsx"' in response.headers["content-disposition"]
    sheet = load_workbook(io.BytesIO(await _body(response))).active
    cells = [cell for row in sheet.iter_rows(values_only=True) for cell in row if isinstance(cell, str)]
    assert "Onay Belgeleri Takip Listesi" in cells
    assert "İnceleniyor" in cells or "İncelemede" in cells
    assert "SUB-012" in cells


@pytest.mark.asyncio
async def test_register_as_a_pdf_follows_accept_language() -> None:
    response = await _register(export_format="pdf", locale=None, accept_language="tr-TR,tr;q=0.9,en;q=0.8")
    assert response.headers["content-language"] == "tr"
    assert response.media_type == "application/pdf"
    assert 'filename="onay-belgeleri-takip-listesi.pdf"' in response.headers["content-disposition"]
    body = await _body(response)
    assert body.startswith(b"%PDF")
    text = " ".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(body)).pages)
    assert "Sayfa 1 / 1" in " ".join(text.split())


@pytest.mark.asyncio
async def test_a_language_the_catalogue_lacks_is_answered_in_english_and_says_so() -> None:
    response = await _register(export_format="pdf", locale="zz", accept_language="zz-ZZ")
    assert response.headers["content-language"] == "en"
    text = " ".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(await _body(response))).pages)
    assert "Page 1 of 1" in " ".join(text.split())


@pytest.mark.asyncio
async def test_one_record_is_a_pdf_named_after_its_number() -> None:
    response = await export_routes.export_submittal_pdf(
        submittal_id=uuid.UUID(int=9), user_id="user", session=_Session([]), locale="tr", accept_language=None
    )
    assert response.headers["content-language"] == "tr"
    assert response.media_type == "application/pdf"
    assert 'filename="SUB-012.pdf"' in response.headers["content-disposition"]
    body = await _body(response)
    assert body.startswith(b"%PDF")
    text = " ".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(body)).pages)
    assert "SUB-012" in text
