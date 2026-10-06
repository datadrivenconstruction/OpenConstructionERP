# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""How revised drawings stack on top of each other in the sheet register.

A revised drawing arrives as a new PDF. The register recognises it as the next
revision of a sheet it already holds and retires the previous one. That used to
key on the sheet number exactly as printed, and it never looked at revisions:

* "A-101" and "A101" are the same drawing and did not stack.
* Uploading an older revision after a newer one retired the newer one, so the
  register named a superseded drawing as current.
* Correcting a misread number or revision by hand left the stack as the misread
  values had built it.

These tests run the real split on rendered PDFs and the real update path.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents import service as documents_service
from app.modules.documents.models import Sheet
from app.modules.documents.schemas import SheetUpdate
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
        email=f"sheet-stack-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x",
        full_name="Sheet Stack Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Sheet Stack Project", owner_id=user.id)
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


def _upload(content: bytes, name: str = "drawings.pdf") -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(content), headers={"content-type": "application/pdf"})


async def _split(session: AsyncSession, project_id: uuid.UUID, user_id: str, lines: list[str], name: str = "d.pdf"):
    sheets = await SheetService(session).split_pdf_to_sheets(project_id, _upload(_pdf([lines]), name), user_id)
    assert len(sheets) == 1
    return sheets[0]


async def _reload(session: AsyncSession, sheet_id: uuid.UUID) -> Sheet:
    await session.flush()
    row = (await session.execute(select(Sheet).where(Sheet.id == sheet_id))).scalar_one()
    await session.refresh(row)
    return row


async def test_a_number_written_with_or_without_a_dash_is_one_drawing(session: AsyncSession) -> None:
    """A-101 at revision A is superseded by A101 at revision B."""
    project_id, user_id = await _seed_project(session)
    first = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV A"])
    second = await _split(session, project_id, user_id, ["SHEET NO: A101", "REV B"])

    assert second.previous_version_id == first.id
    assert second.is_current is True
    assert (await _reload(session, first.id)).is_current is False


async def test_leading_zeros_and_underscores_do_not_split_a_stack(session: AsyncSession) -> None:
    """TAV_01 from one file name and TAV-1 from another are the same sheet.

    Neither carries a title, which is the common case for a CAD export whose
    text is outlined: a code with a word prefix stacks on the code alone.
    """
    project_id, user_id = await _seed_project(session)
    first = await _split(session, project_id, user_id, [""], name="TAV_01_rev01.pdf")
    second = await _split(session, project_id, user_id, [""], name="TAV-1 rev02.pdf")

    assert first.sheet_number == "TAV_01"
    assert first.revision == "01"
    assert second.previous_version_id == first.id
    assert (await _reload(session, first.id)).is_current is False


async def test_an_older_revision_uploaded_after_a_newer_one_is_stored_as_history(session: AsyncSession) -> None:
    """Revision B stays current when revision A arrives later; A joins the stack beneath it."""
    project_id, user_id = await _seed_project(session)
    newer = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV B"])
    older = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV A"])

    assert older.is_current is False
    newer = await _reload(session, newer.id)
    assert newer.is_current is True
    # A sits beneath B in the stack: B now names A as the revision it replaced.
    assert newer.previous_version_id == older.id

    chain = await SheetService(session).repo.get_version_chain(newer.id)
    assert [s.revision for s in chain] == ["A", "B"]


async def test_preliminary_revisions_come_before_construction_revisions(session: AsyncSession) -> None:
    """P03 uploaded after C01 does not take the stack back to a preliminary issue."""
    project_id, user_id = await _seed_project(session)
    construction = await _split(session, project_id, user_id, ["SHEET NO: S-200", "REV C01"])
    preliminary = await _split(session, project_id, user_id, ["SHEET NO: S-200", "REV P03"])

    assert preliminary.is_current is False
    assert (await _reload(session, construction.id)).is_current is True


async def test_revisions_that_cannot_be_compared_keep_the_latest_upload_and_say_so(session: AsyncSession) -> None:
    """02 then B: the later upload is current and carries the unclear-order flag."""
    project_id, user_id = await _seed_project(session)
    first = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV 02"])
    second = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV B"])

    assert second.is_current is True
    assert second.previous_version_id == first.id
    assert (second.metadata_ or {}).get("revision_order_unclear") is True


async def test_two_disciplines_numbering_from_one_do_not_stack(session: AsyncSession) -> None:
    """Tavola 1 of the architecture set and Tavola 1 of the structures set stay apart."""
    project_id, user_id = await _seed_project(session)
    arch = await _split(session, project_id, user_id, ["TAVOLA 1", "Oggetto: Pianta piano terra", "Rev. 02"])
    struct = await _split(session, project_id, user_id, ["TAVOLA 1", "Oggetto: Carpenteria fondazioni", "Rev. 00"])

    assert struct.is_current is True
    assert struct.previous_version_id is None
    assert (await _reload(session, arch.id)).is_current is True


async def test_a_bare_number_stacks_when_the_title_matches(session: AsyncSession) -> None:
    """The same Tavola 1 with the same subject is the next revision."""
    project_id, user_id = await _seed_project(session)
    first = await _split(session, project_id, user_id, ["TAVOLA 1", "Oggetto: Pianta piano terra", "Rev. 01"])
    second = await _split(session, project_id, user_id, ["TAVOLA 01", "Oggetto: PIANTA  piano terra", "Rev. 02"])

    assert second.previous_version_id == first.id
    assert (await _reload(session, first.id)).is_current is False


async def test_correcting_a_misread_number_moves_the_sheet_into_its_stack_and_back(session: AsyncSession) -> None:
    """A PATCH that changes the number re-runs the stacking, and undoing it leaves no cycle."""
    project_id, user_id = await _seed_project(session)
    first = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV A"])
    misread = await _split(session, project_id, user_id, ["SHEET NO: X-999", "REV B"])
    assert misread.previous_version_id is None

    service = SheetService(session)
    moved = await service.update_sheet(misread.id, SheetUpdate(sheet_number="A-101"))
    assert moved.is_current is True
    assert moved.previous_version_id == first.id
    assert (await _reload(session, first.id)).is_current is False

    back = await service.update_sheet(misread.id, SheetUpdate(sheet_number="X-999"))
    assert back.is_current is True
    assert back.previous_version_id is None
    restored = await _reload(session, first.id)
    assert restored.is_current is True
    assert restored.previous_version_id is None

    # Walking either chain terminates and finds only its own sheet.
    assert [s.id for s in await service.repo.get_version_chain(first.id)] == [first.id]
    assert [s.id for s in await service.repo.get_version_chain(misread.id)] == [misread.id]


async def test_correcting_a_revision_reorders_the_stack(session: AsyncSession) -> None:
    """The later upload misread as "ole" is corrected to 00, below the 01 already held."""
    project_id, user_id = await _seed_project(session)
    rev01 = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV 01"])
    # An upload whose revision was read wrongly. It is the latest, so it is current.
    wrong = await _split(session, project_id, user_id, ["SHEET NO: A-101", "REV X9Z"])
    assert wrong.is_current is True

    corrected = await SheetService(session).update_sheet(wrong.id, SheetUpdate(revision="00"))
    assert corrected.is_current is False
    assert (corrected.metadata_ or {}).get("revision_order_unclear") is None
    head = await _reload(session, rev01.id)
    assert head.is_current is True
    assert head.previous_version_id == corrected.id


async def test_a_date_only_value_from_the_edit_form_is_stored(session: AsyncSession) -> None:
    """The drawer sends the date input's value, a bare YYYY-MM-DD; the column takes it."""
    project_id, user_id = await _seed_project(session)
    sheet = await _split(session, project_id, user_id, ["SHEET NO: A-101"])

    payload = SheetUpdate.model_validate(
        {"revision_date": "2025-03-12", "sheet_title": "Pianta piano terra", "scale": "", "revision": "  "}
    )
    updated = await SheetService(session).update_sheet(sheet.id, payload)
    assert updated.revision_date is not None
    assert updated.revision_date.date().isoformat() == "2025-03-12"
    assert updated.sheet_title == "Pianta piano terra"
    # A cleared field is stored as unset, never as an empty string a stack could key on.
    assert updated.scale is None
    assert updated.revision is None


async def test_the_italian_title_block_reaches_the_stored_row(session: AsyncSession) -> None:
    """Every field of the cartiglio fixture lands on the row the register shows."""
    project_id, user_id = await _seed_project(session)
    sheet = await _split(
        session,
        project_id,
        user_id,
        ["TAVOLA: ARC-03", "Oggetto: Pianta piano terra", "Data 12/03/2025", "Scala 1:100", "Rev. 02"],
    )
    assert sheet.sheet_number == "ARC-03"
    assert sheet.sheet_title == "Pianta piano terra"
    assert sheet.discipline == "Architectural"
    assert sheet.scale == "1:100"
    assert sheet.revision == "02"
    assert sheet.revision_date is not None
    assert sheet.revision_date.date().isoformat() == "2025-03-12"


async def test_a_multi_page_set_does_not_stamp_its_file_name_on_every_page(session: AsyncSession) -> None:
    """The file name describes one drawing, so it is read only when the PDF holds one page."""
    project_id, user_id = await _seed_project(session)
    sheets = await SheetService(session).split_pdf_to_sheets(
        project_id, _upload(_pdf([["Pianta"], ["Sezione"]]), "ARC_PT_01_R03.pdf"), user_id
    )
    assert [s.sheet_number for s in sheets] == [None, None]
    assert [s.revision for s in sheets] == [None, None]


async def test_two_bare_numbers_are_joined_by_giving_them_the_same_title(session: AsyncSession) -> None:
    """Kept apart for want of a title, they stack once the edit form gives both the same one."""
    project_id, user_id = await _seed_project(session)
    first = await _split(session, project_id, user_id, ["TAVOLA 1", "Rev. 01"])
    second = await _split(session, project_id, user_id, ["TAVOLA 1", "Rev. 02"])
    assert second.previous_version_id is None
    assert (await _reload(session, first.id)).is_current is True

    service = SheetService(session)
    await service.update_sheet(first.id, SheetUpdate(sheet_title="Pianta piano terra"))
    joined = await service.update_sheet(second.id, SheetUpdate(sheet_title="Pianta piano terra"))

    assert joined.is_current is True
    assert joined.previous_version_id == first.id
    assert (await _reload(session, first.id)).is_current is False
