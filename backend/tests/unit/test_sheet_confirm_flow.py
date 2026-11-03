# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A scanned drawing set is read by OCR, held, and stacks only once a person confirms it.

The real split runs on rendered PDFs; the scan is an image-only PDF made with
PIL. tesseract is not installed in CI, so ``ocr_title_block`` is replaced.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents import service as documents_service
from app.modules.documents.models import Sheet
from app.modules.documents.schemas import SheetUpdate
from app.modules.documents.service import SheetService
from app.modules.documents.sheet_ocr import OcrUnavailable
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as sess:
        yield sess


@pytest.fixture(autouse=True)
def _isolated_sheet_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(documents_service, "UPLOAD_BASE", tmp_path / "uploads")
    monkeypatch.setattr(documents_service, "SHEET_THUMB_BASE", tmp_path / "sheets")


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, str]:
    user = User(
        email=f"sheet-ocr-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x",
        full_name="Sheet OCR Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Sheet OCR Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id, str(user.id)


def _text_pdf(lines: list[str]) -> bytes:
    canvas = pytest.importorskip("reportlab.pdfgen.canvas", reason="reportlab is not installed")
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for offset, line in enumerate(lines):
        pdf.drawString(60, 760 - offset * 20, line)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _scan_pdf(pages: int = 1) -> bytes:
    """An image-only PDF: no text layer at all."""
    image_mod = pytest.importorskip("PIL.Image")
    first = image_mod.new("RGB", (600, 800), "white")
    buffer = io.BytesIO()
    first.save(
        buffer, format="PDF", resolution=100, save_all=True, append_images=[first.copy() for _ in range(pages - 1)]
    )
    return buffer.getvalue()


def _upload(content: bytes, name: str = "drawings.pdf") -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(content), headers={"content-type": "application/pdf"})


def _ocr_returns(monkeypatch: pytest.MonkeyPatch, text: str, conf: float) -> None:
    def fake(path: Path, index: int, langs: Any = None, render_lock: Any = None) -> tuple[str, float]:
        return text, conf

    monkeypatch.setattr(documents_service, "ocr_title_block", fake)


def _ocr_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(*args: Any, **kwargs: Any) -> tuple[str, float]:
        raise OcrUnavailable("no tesseract")

    monkeypatch.setattr(documents_service, "ocr_title_block", fake)


async def _reload(session: AsyncSession, sheet_id: uuid.UUID) -> Sheet:
    await session.flush()
    row = (await session.execute(select(Sheet).where(Sheet.id == sheet_id))).scalar_one()
    await session.refresh(row)
    return row


FULL_TEXT = ["SHEET NO: A-101", "SHEET TITLE: Ground Floor Plan", "REV A", "DATE: 2025-03-12"]
SCAN_TEXT = "SHEET NO: A-101\nSHEET TITLE: Ground Floor Plan\nREV B\nDATE: 2025-04-01"


async def _first_text_sheet(session: AsyncSession, project_id: uuid.UUID, user_id: str) -> Sheet:
    sheets = await SheetService(session).split_pdf_to_sheets(project_id, _upload(_text_pdf(FULL_TEXT)), user_id)
    assert len(sheets) == 1
    return sheets[0]


async def test_a_text_layer_sheet_is_stacked_without_review(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id, user_id = await _seed_project(session)
    first = await _first_text_sheet(session, project_id, user_id)
    second = (
        await SheetService(session).split_pdf_to_sheets(
            project_id, _upload(_text_pdf([*FULL_TEXT[:2], "REV B", FULL_TEXT[3]])), user_id
        )
    )[0]

    extraction = second.metadata_["extraction"]
    assert extraction["source"] == "text"
    assert extraction["confidence"] >= 0.8
    assert extraction["needs_review"] is False
    assert second.previous_version_id == first.id
    assert (await _reload(session, first.id)).is_current is False


async def test_a_scan_is_held_and_does_not_supersede_until_confirmed(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id, user_id = await _seed_project(session)
    service = SheetService(session)
    old = await _first_text_sheet(session, project_id, user_id)
    _ocr_returns(monkeypatch, SCAN_TEXT, 0.72)

    scan = (await service.split_pdf_to_sheets(project_id, _upload(_scan_pdf(), "scan.pdf"), user_id))[0]

    assert scan.sheet_number == "A-101"
    extraction = scan.metadata_["extraction"]
    assert extraction["source"] == "ocr"
    assert extraction["confidence"] == pytest.approx(0.72)
    assert extraction["needs_review"] is True
    assert scan.metadata_["status"] == "pending_review"
    assert scan.previous_version_id is None
    assert scan.is_current is False
    assert (await _reload(session, old.id)).is_current is True

    held, total = await service.list_sheets(project_id, needs_review=True)
    assert total == 1 and held[0].id == scan.id
    others, other_total = await service.list_sheets(project_id, needs_review=False)
    assert other_total == 1 and others[0].id == old.id

    confirmed = await service.confirm_extraction(scan.id, user_id)

    assert confirmed.metadata_["extraction"]["needs_review"] is False
    assert confirmed.metadata_["extraction"]["confirmed_by"] == user_id
    assert "status" not in confirmed.metadata_
    assert confirmed.is_current is True
    assert confirmed.previous_version_id == old.id
    assert (await _reload(session, old.id)).is_current is False


async def test_confirming_with_a_correction_records_a_hand_edit_and_stacks_on_the_corrected_number(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id, user_id = await _seed_project(session)
    service = SheetService(session)
    old = await _first_text_sheet(session, project_id, user_id)
    _ocr_returns(monkeypatch, "SHEET NO: A-1O1\nSHEET TITLE: Ground Floor Plan\nREV B", 0.7)
    scan = (await service.split_pdf_to_sheets(project_id, _upload(_scan_pdf(), "scan.pdf"), user_id))[0]
    assert scan.previous_version_id is None

    confirmed = await service.confirm_extraction(scan.id, user_id, SheetUpdate(sheet_number="A-101"))

    assert confirmed.sheet_number == "A-101"
    assert "sheet_number" in confirmed.metadata_["manually_edited"]
    assert confirmed.previous_version_id == old.id
    assert (await _reload(session, old.id)).is_current is False


async def test_confirming_twice_changes_nothing(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    project_id, user_id = await _seed_project(session)
    service = SheetService(session)
    old = await _first_text_sheet(session, project_id, user_id)
    _ocr_returns(monkeypatch, SCAN_TEXT, 0.72)
    scan = (await service.split_pdf_to_sheets(project_id, _upload(_scan_pdf(), "scan.pdf"), user_id))[0]

    once = await service.confirm_extraction(scan.id, user_id)
    stamp = once.metadata_["extraction"]["confirmed_at"]
    twice = await service.confirm_extraction(scan.id, "someone-else")

    assert twice.metadata_["extraction"]["confirmed_at"] == stamp
    assert twice.metadata_["extraction"]["confirmed_by"] == user_id
    assert twice.previous_version_id == old.id
    assert twice.is_current is True


async def test_an_unavailable_ocr_keeps_the_sheet_held_and_bulk_confirm_skips_it(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id, user_id = await _seed_project(session)
    service = SheetService(session)
    _ocr_missing(monkeypatch)

    sheets = await service.split_pdf_to_sheets(project_id, _upload(_scan_pdf(2), "scan.pdf"), user_id)

    assert len(sheets) == 2
    for sheet in sheets:
        assert sheet.metadata_["extraction"]["reason"] == "ocr_unavailable"
        assert sheet.metadata_["extraction"]["needs_review"] is True
        assert sheet.metadata_["status"] == "pending_review"

    counts = await service.confirm_bulk(project_id, user_id, 0.0)
    assert counts["confirmed"] == 0
    assert counts["ocr_unavailable"] == 2


async def test_bulk_confirm_respects_the_threshold(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    project_id, user_id = await _seed_project(session)
    service = SheetService(session)
    old = await _first_text_sheet(session, project_id, user_id)

    _ocr_returns(monkeypatch, SCAN_TEXT, 0.88)
    high = (await service.split_pdf_to_sheets(project_id, _upload(_scan_pdf(), "high.pdf"), user_id))[0]
    _ocr_returns(monkeypatch, "SHEET NO: S-201\nSHEET TITLE: Footings\nREV A", 0.55)
    low = (await service.split_pdf_to_sheets(project_id, _upload(_scan_pdf(), "low.pdf"), user_id))[0]

    counts = await service.confirm_bulk(project_id, user_id, 0.8)

    assert counts["confirmed"] == 1
    assert counts["below_threshold"] == 1
    assert (await _reload(session, high.id)).metadata_["extraction"]["needs_review"] is False
    assert (await _reload(session, low.id)).metadata_["extraction"]["needs_review"] is True
    assert (await _reload(session, old.id)).is_current is False


async def test_a_hand_edit_survives_a_reread(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    project_id, user_id = await _seed_project(session)
    service = SheetService(session)
    _ocr_returns(monkeypatch, SCAN_TEXT, 0.72)
    scan = (await service.split_pdf_to_sheets(project_id, _upload(_scan_pdf(), "scan.pdf"), user_id))[0]
    await service.confirm_extraction(scan.id, user_id, SheetUpdate(sheet_title="Level 0 Plan"))

    _ocr_returns(monkeypatch, "SHEET NO: A-101\nSHEET TITLE: Something Else\nREV C", 0.7)
    await service.reread_title_blocks(project_id)

    row = await _reload(session, scan.id)
    assert row.sheet_title == "Level 0 Plan"


async def test_intake_validation_lists_unconfirmed_reads(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id, user_id = await _seed_project(session)
    service = SheetService(session)
    old = await _first_text_sheet(session, project_id, user_id)
    _ocr_returns(monkeypatch, "SHEET NO: A-101\nSHEET TITLE: Ground Floor Plan\nREV 0", 0.8)
    await service.split_pdf_to_sheets(project_id, _upload(_scan_pdf(), "scan.pdf"), user_id)

    rows = await service.intake_validation_data(project_id)
    held = [r for r in rows if r["needs_review"]]
    assert len(held) == 1 and held[0]["current_revisions"] == [old.revision]

    report = await service.check_intake(project_id, user_id=uuid.UUID(user_id))
    failing = {r["rule_id"] for r in report["results"] if not r["passed"]}
    assert "sheet.low_confidence_unconfirmed" in failing
