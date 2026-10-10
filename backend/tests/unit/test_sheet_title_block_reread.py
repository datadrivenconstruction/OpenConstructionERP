# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Re-reading the title blocks of sheets already in the register.

The reader that registered an Italian drawing set at revision "ole" and with no
sheet numbers has been fixed, but the rows it wrote are still in the register.
Re-uploading the set would fix them and add a second copy of every drawing, so
the register offers a re-read: every sheet of the project is read again from
the PDF that is already stored, and the revision stacks are rebuilt from the
result. A field somebody corrected by hand is theirs and is not overwritten.

The rows are put into their pre-fix state directly, because the current reader
no longer produces it from any PDF.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents import service as documents_service
from app.modules.documents.models import Document, Sheet
from app.modules.documents.schemas import SheetBulkUpdate, SheetUpdate
from app.modules.documents.service import SheetService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session inside an outer, rolled back transaction."""
    async with transactional_session() as sess:
        yield sess


@pytest.fixture(autouse=True)
def _isolated_sheet_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the split's PDF and thumbnail writes inside the test's tmp dir."""
    monkeypatch.setattr(documents_service, "UPLOAD_BASE", tmp_path / "uploads")
    monkeypatch.setattr(documents_service, "SHEET_THUMB_BASE", tmp_path / "sheets")


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, str]:
    user = User(
        email=f"sheet-reread-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x",
        full_name="Sheet Reread Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Sheet Reread Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id, str(user.id)


def _pdf(pages: list[list[str]]) -> bytes:
    canvas = pytest.importorskip("reportlab.pdfgen.canvas", reason="reportlab is not installed")
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for lines in pages:
        for offset, line in enumerate(lines):
            pdf.drawString(60, 760 - offset * 20, line)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


async def _split(
    session: AsyncSession, project_id: uuid.UUID, user_id: str, lines: list[str], filename: str = "d.pdf"
) -> Sheet:
    upload = UploadFile(filename=filename, file=io.BytesIO(_pdf([lines])), headers={"content-type": "application/pdf"})
    sheets = await SheetService(session).split_pdf_to_sheets(project_id, upload, user_id)
    return sheets[0]


async def _as_the_old_reader_left_it(session: AsyncSession, sheet: Sheet, **fields: object) -> None:
    """Overwrite a row with what the pre-fix reader stored, and unlink it."""
    for name, value in fields.items():
        setattr(sheet, name, value)
    sheet.previous_version_id = None
    sheet.is_current = True
    await session.flush()


async def _reload(session: AsyncSession, sheet_id: uuid.UUID) -> Sheet:
    await session.flush()
    row = (await session.execute(select(Sheet).where(Sheet.id == sheet_id))).scalar_one()
    await session.refresh(row)
    return row


ITALIAN_PAGE = [
    "Pianta piano terra",
    "Porta scorrevole in vetro",
    "TAVOLA: ARC-03",
    "Oggetto: Pianta piano terra",
    "Data 12/03/2025",
    "Rev. 02",
]


async def test_a_reread_replaces_what_the_old_reader_got_wrong(session: AsyncSession) -> None:
    """Revision "ole" and a missing number become 02 and ARC-03, read from the stored PDF."""
    project_id, user_id = await _seed_project(session)
    sheet = await _split(session, project_id, user_id, ITALIAN_PAGE)
    await _as_the_old_reader_left_it(
        session, sheet, revision="ole", sheet_number=None, discipline=None, sheet_title=None, revision_date=None
    )

    summary = await SheetService(session).reread_title_blocks(project_id)

    row = await _reload(session, sheet.id)
    assert row.revision == "02"
    assert row.sheet_number == "ARC-03"
    assert row.discipline == "Architectural"
    assert row.sheet_title == "Pianta piano terra"
    assert row.revision_date is not None and row.revision_date.date().isoformat() == "2025-03-12"
    assert summary["sheets_checked"] == 1
    assert summary["sheets_updated"] == 1
    assert summary["files_missing"] == 0


async def test_a_field_corrected_by_hand_survives_a_reread(session: AsyncSession) -> None:
    """The edit form records what it changed, and the re-read leaves exactly that alone."""
    project_id, user_id = await _seed_project(session)
    sheet = await _split(session, project_id, user_id, ITALIAN_PAGE)
    await _as_the_old_reader_left_it(session, sheet, revision="ole", sheet_title=None)

    service = SheetService(session)
    edited = await service.update_sheet(sheet.id, SheetUpdate(sheet_title="Piano terra, variante"))
    assert edited.metadata_["manually_edited"] == ["sheet_title"]

    await service.reread_title_blocks(project_id)

    row = await _reload(session, sheet.id)
    assert row.sheet_title == "Piano terra, variante"
    assert row.revision == "02"


async def test_a_patch_records_only_the_fields_it_changed(session: AsyncSession) -> None:
    """Sending a field with its current value is not an edit of it."""
    project_id, user_id = await _seed_project(session)
    sheet = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV A"])

    service = SheetService(session)
    await service.update_sheet(sheet.id, SheetUpdate(sheet_number="A-101", revision="B"))
    row = await service.update_sheet(sheet.id, SheetUpdate(scale="1:50"))

    assert row.metadata_["manually_edited"] == ["revision", "scale"]


async def test_a_reread_rebuilds_the_stack_the_old_reader_could_not(session: AsyncSession) -> None:
    """Two uploads the old reader left unnumbered stack once their numbers are read."""
    project_id, user_id = await _seed_project(session)
    older = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV A"])
    newer = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV B"])
    await _as_the_old_reader_left_it(session, older, sheet_number=None, revision="EVIEWED")
    await _as_the_old_reader_left_it(session, newer, sheet_number=None, revision="EVIEWED")

    await SheetService(session).reread_title_blocks(project_id)

    older_row, newer_row = await _reload(session, older.id), await _reload(session, newer.id)
    assert newer_row.is_current is True
    assert newer_row.previous_version_id == older.id
    assert older_row.is_current is False


async def test_a_sheet_whose_drawing_is_no_longer_stored_is_counted_and_left_alone(session: AsyncSession) -> None:
    """No file, no reading: the row keeps what it has and the summary says why."""
    project_id, user_id = await _seed_project(session)
    sheet = await _split(session, project_id, user_id, ITALIAN_PAGE)
    await _as_the_old_reader_left_it(session, sheet, revision="ole")
    document = (await session.execute(select(Document).where(Document.id == uuid.UUID(sheet.document_id)))).scalar_one()
    Path(document.file_path).unlink()

    summary = await SheetService(session).reread_title_blocks(project_id)

    assert (await _reload(session, sheet.id)).revision == "ole"
    assert summary["files_missing"] == 1
    assert summary["sheets_updated"] == 0


async def test_a_reread_that_finds_nothing_new_changes_nothing(session: AsyncSession) -> None:
    """A correct register re-reads to itself: no updates, no restacking."""
    project_id, user_id = await _seed_project(session)
    first = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV A"])
    second = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV B"])

    summary = await SheetService(session).reread_title_blocks(project_id)

    assert summary["sheets_updated"] == 0
    assert (await _reload(session, second.id)).previous_version_id == first.id
    assert (await _reload(session, first.id)).is_current is False


async def test_a_reread_reads_a_file_name_as_the_split_did(session: AsyncSession) -> None:
    """The stored name is sanitised ("ARC PT 01" becomes "ARC_PT_01"), which the reader takes differently.

    A single-page drawing with nothing in its title block is read from its file
    name, so a re-read from the sanitised name would invent a number the split
    never read. The split keeps the name as uploaded, and the re-read uses it.
    """
    project_id, user_id = await _seed_project(session)
    sheet = await _split(session, project_id, user_id, ["Planimetria generale"], filename="ARC PT 01 R03 Pianta.pdf")
    before = (sheet.sheet_number, sheet.sheet_title, sheet.revision)

    summary = await SheetService(session).reread_title_blocks(project_id)

    row = await _reload(session, sheet.id)
    assert (row.sheet_number, row.sheet_title, row.revision) == before
    assert summary["sheets_updated"] == 0


async def test_setting_current_by_hand_is_recorded_as_a_hand_edit(session: AsyncSession) -> None:
    """A PATCH that flips is_current is a person's decision; one that resends it is not."""
    project_id, user_id = await _seed_project(session)
    sheet = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV A"])

    service = SheetService(session)
    same = await service.update_sheet(sheet.id, SheetUpdate(is_current=True))
    assert "manually_edited" not in (same.metadata_ or {})
    flipped = await service.update_sheet(sheet.id, SheetUpdate(is_current=False))

    assert flipped.metadata_["manually_edited"] == ["is_current"]


async def _stacked_pair_the_old_reader_misread(
    session: AsyncSession, project_id: uuid.UUID, user_id: str
) -> tuple[Sheet, Sheet]:
    """Revisions A then B of A-101, stacked, both revisions misread as "ole"."""
    older = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV A"])
    newer = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV B"])
    older.revision = "ole"
    newer.revision = "ole"
    await session.flush()
    return older, newer


async def test_a_reread_keeps_a_current_state_set_by_hand_and_names_the_conflict(session: AsyncSession) -> None:
    """Somebody made revision A current again; the restack would retire it, so it stays and is reported."""
    project_id, user_id = await _seed_project(session)
    older, newer = await _stacked_pair_the_old_reader_misread(session, project_id, user_id)
    service = SheetService(session)
    await service.update_sheet(older.id, SheetUpdate(is_current=True))

    summary = await service.reread_title_blocks(project_id)

    older_row, newer_row = await _reload(session, older.id), await _reload(session, newer.id)
    assert (older_row.revision, newer_row.revision) == ("A", "B")
    assert older_row.is_current is True
    # Not chosen between: the restack's own answer for the other sheet stands.
    assert newer_row.is_current is True
    assert summary["current_conflicts"] == [str(older.id)]


async def test_a_current_state_set_by_hand_that_the_restack_agrees_with_is_no_conflict(
    session: AsyncSession,
) -> None:
    """Retiring revision A by hand is what the corrected revisions say too."""
    project_id, user_id = await _seed_project(session)
    older, newer = await _stacked_pair_the_old_reader_misread(session, project_id, user_id)
    service = SheetService(session)
    # The old reader's stack had A over B; somebody fixed that by hand.
    older.previous_version_id, newer.previous_version_id = newer.id, None
    older.is_current, newer.is_current = True, False
    await session.flush()
    await service.update_sheet(older.id, SheetUpdate(is_current=False))
    await service.update_sheet(newer.id, SheetUpdate(is_current=True))

    summary = await service.reread_title_blocks(project_id)

    assert (await _reload(session, older.id)).is_current is False
    assert (await _reload(session, newer.id)).is_current is True
    assert summary["current_conflicts"] == []


async def test_a_bulk_edit_sets_the_shared_fields_on_every_sheet_as_hand_edits(session: AsyncSession) -> None:
    """One discipline and issue date for a whole set, recorded so a re-read keeps them."""
    project_id, user_id = await _seed_project(session)
    first = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV A"])
    second = await _split(session, project_id, user_id, ["SHEET NO: A-102", "REV A"])

    request = SheetBulkUpdate(
        project_id=project_id, sheet_ids=[first.id, second.id], discipline="Structural", revision_date="2026-03-12"
    )
    rows = await SheetService(session).bulk_update_sheets(project_id, request.sheet_ids, request.changes())

    assert [row.discipline for row in rows] == ["Structural", "Structural"]
    assert all(row.revision_date is not None and row.revision_date.date().isoformat() == "2026-03-12" for row in rows)
    assert all(row.metadata_["manually_edited"] == ["discipline", "revision_date"] for row in rows)
    assert [row.sheet_number for row in rows] == ["A-101", "A-102"]


async def test_a_bulk_edit_naming_a_sheet_of_another_project_changes_nothing(session: AsyncSession) -> None:
    """A foreign id fails the whole request before any sheet is written."""
    project_id, user_id = await _seed_project(session)
    other_project_id, other_user_id = await _seed_project(session)
    own = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV A"])
    foreign = await _split(session, other_project_id, other_user_id, ["SHEET NO: A-101", "REV A"])

    with pytest.raises(HTTPException) as caught:
        await SheetService(session).bulk_update_sheets(
            project_id, [own.id, foreign.id], SheetUpdate(discipline="Structural")
        )

    assert caught.value.status_code == 404
    assert (await _reload(session, own.id)).discipline != "Structural"
