# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What the sheet register actually holds after a drawing set is split.

The register's new screen displays exactly what ``split_pdf_to_sheets`` wrote,
so these tests pin the split's output rather than its plumbing: one row per
page, the page order, what happens to a page whose title block cannot be read,
and what a second split of the same file does. ``test_epic_c_versioning``
already covers the ``FileVersion`` chain the split writes; it asserts the sheet
count and nothing else about the rows.

The PDFs are real, rendered with reportlab, so ``detect_sheet_info`` runs
against text pdfplumber genuinely extracted. Tests that need one skip where
reportlab is unavailable; the two aggregation tests seed rows directly and
always run.

Storage is redirected at the test's tmp dir. Without that the split writes the
PDF and its thumbnails under ``~/.openestimator`` on the machine running the
suite, which is where the application keeps real uploads.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents import service as documents_service
from app.modules.documents.models import Document, Sheet
from app.modules.documents.repository import SheetRepository
from app.modules.documents.service import SheetService, detect_sheet_info
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session inside an outer transaction.

    The shared ``oe_test_unit`` database already carries the full schema, and
    the transaction is rolled back on teardown, so each test starts empty.
    """
    async with transactional_session() as sess:
        yield sess


@pytest.fixture(autouse=True)
def _isolated_sheet_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the split's PDF and thumbnail writes inside the test's tmp dir."""
    monkeypatch.setattr(documents_service, "UPLOAD_BASE", tmp_path / "uploads")
    monkeypatch.setattr(documents_service, "SHEET_THUMB_BASE", tmp_path / "sheets")


# ── Helpers ───────────────────────────────────────────────────────────────


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, str]:
    """Insert a user and a project so the split has its foreign keys.

    Returns:
        ``(project_id, user_id_as_str)`` in the shape the service takes.
    """
    user = User(
        email=f"sheets-split-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x",
        full_name="Sheets Split Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Sheets Split Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id, str(user.id)


def _pdf_with_pages(pages: list[list[str]]) -> bytes:
    """Render a PDF whose pages carry the given lines of title-block text."""
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
    """Wrap raw bytes in the ``UploadFile`` the service expects."""
    return UploadFile(filename=name, file=io.BytesIO(content), headers={"content-type": "application/pdf"})


async def _seed_sheet(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    page_number: int,
    sheet_number: str | None,
    discipline: str | None,
) -> None:
    """Insert one sheet row directly, bypassing the split."""
    session.add(
        Sheet(
            project_id=project_id,
            document_id=str(uuid.uuid4()),
            page_number=page_number,
            sheet_number=sheet_number,
            discipline=discipline,
            is_current=True,
        )
    )
    await session.flush()


# ── The split ─────────────────────────────────────────────────────────────


async def test_split_creates_one_row_per_page_in_page_order(session: AsyncSession) -> None:
    """Three pages become three rows, numbered 1..3 in the order they appear.

    The order is asserted for a single split of a single file, which is all
    this test is about. It used to say that was the only case the query
    decides, because ``list_for_project`` sorted on ``page_number`` alone and
    a second document in the same project starts at page 1 again. That clause
    is stale: the query now orders on page number, then the created instant,
    then the id, so two documents no longer interleave by chance. Widening
    this test to two documents is a fair thing to want and belongs beside the
    ordering change rather than here, where a scope of one file keeps the
    subject the split rather than the register.
    """
    project_id, user_id = await _seed_project(session)
    pdf = _pdf_with_pages(
        [
            ["SHEET NO: A-201", "SHEET TITLE: Floor Plan Level 2"],
            ["SHEET NO: A-202", "SHEET TITLE: Floor Plan Level 3"],
            ["SHEET NO: S-301", "SHEET TITLE: Foundation Details"],
        ]
    )

    sheets = await SheetService(session).split_pdf_to_sheets(project_id, _upload(pdf), user_id)

    assert len(sheets) == 3
    assert [s.page_number for s in sheets] == [1, 2, 3]
    assert [s.sheet_number for s in sheets] == ["A-201", "A-202", "S-301"]
    assert [s.discipline for s in sheets] == ["Architectural", "Architectural", "Structural"]

    # Same order back out through the read path the register itself uses.
    listed, total = await SheetService(session).list_sheets(project_id)
    assert total == 3
    assert [s.page_number for s in listed] == [1, 2, 3]


async def test_split_reads_the_title_block_fields_the_drawer_shows(session: AsyncSession) -> None:
    """Number, title, scale and revision come off the page; discipline does not.

    Discipline is a lookup of the number's prefix, not anything read from the
    drawing. This page carries no issue date, so ``revision_date`` stays unset
    (a labelled date is read, see ``test_sheet_title_block_fields``), and a
    first upload has nothing to stack on, so ``previous_version_id`` is unset.
    """
    project_id, user_id = await _seed_project(session)
    pdf = _pdf_with_pages([["SHEET NO: M-401", "SHEET TITLE: Ventilation Layout", "REV C", "SCALE: 1:50"]])

    sheets = await SheetService(session).split_pdf_to_sheets(project_id, _upload(pdf), user_id)

    assert len(sheets) == 1
    sheet = sheets[0]
    assert sheet.sheet_number == "M-401"
    assert sheet.sheet_title == "Ventilation Layout"
    assert sheet.scale == "1:50"
    assert sheet.revision == "C"
    assert sheet.discipline == "Mechanical"
    assert sheet.revision_date is None
    assert sheet.previous_version_id is None
    assert sheet.is_current is True


async def test_the_scale_read_off_a_page_stops_at_the_end_of_its_line(session: AsyncSession) -> None:
    """A scale followed by another line does not swallow the newline.

    The scale pattern's character class used to include ``\\s``, which matches a
    newline, so the capture did not stop at the end of the line the label is on
    and the trailing ``\\S*`` took the first token of the next one. On a title
    block where anything follows the scale - which is the normal case, since the
    scale is rarely the last thing on a drawing - the stored value was the scale
    plus that token, and it is the stored value the detail drawer prints in its
    Scale field. This page puts REV C directly under the scale, which is the
    arrangement that produced ``"1:50\\nREV"``.
    """
    project_id, user_id = await _seed_project(session)
    pdf = _pdf_with_pages([["SHEET NO: M-401", "SCALE: 1:50", "REV C"]])

    sheets = await SheetService(session).split_pdf_to_sheets(project_id, _upload(pdf), user_id)

    assert sheets[0].scale == "1:50"
    # The revision was always read correctly; only the scale over-reached.
    assert sheets[0].revision == "C"


def test_the_scale_pattern_is_bounded_to_the_label_s_own_line() -> None:
    """The same case stated at the pattern, with no PDF toolchain involved.

    The split-level test above proves the value that reaches the stored row is
    right, but it can only do so through reportlab's layout and pdfplumber's
    line joining, either of which could change the exact text for reasons that
    have nothing to do with this pattern. This one pins the cause directly.

    Deliberately equalities, not substrings. The pre-existing scale tests all
    assert ``"1:100" in result["scale"]``, which is why a value carrying an
    extra line went unnoticed for as long as it did.
    """
    assert detect_sheet_info("SCALE: 1:50\nREV C")["scale"] == "1:50"
    assert detect_sheet_info("SCALE: 1:50\r\nREV C")["scale"] == "1:50"
    # Nothing after the label, so nothing there was ever to over-reach into.
    assert detect_sheet_info("SCALE: 1:50")["scale"] == "1:50"
    # Padding around the value belongs to the layout, not to the scale.
    assert detect_sheet_info("SCALE:   1:50   \nREV C")["scale"] == "1:50"


def test_a_scale_beside_its_neighbours_on_one_row_takes_only_its_own_cell() -> None:
    """The common real case: a title block row arrives as one joined line.

    A title block lays its fields out in columns, and the text extractor joins
    the cells sharing a visual row into a single line separated by runs of
    spaces. Bounding the capture to the line is therefore not enough on its own,
    because the line holds three fields. Both break signals are exercised here:
    the column gap, and a following label separated by only one space.
    """
    row = "SCALE: 1:50    DRAWN: AB    DATE: 2026-01-14"
    assert detect_sheet_info(row)["scale"] == "1:50"

    # A single space before the next label, so the column gap says nothing and
    # the label itself has to be what ends the value.
    assert detect_sheet_info("SCALE: 1:50 DRAWN: AB")["scale"] == "1:50"

    # The scale sitting in the middle of a row rather than at its start.
    assert detect_sheet_info("SHEET NO: A-101   SCALE: 1:100   REV: B")["scale"] == "1:100"


def test_a_scale_written_as_words_is_read_as_written() -> None:
    """Not every drawing carries a ratio, and the written forms must survive.

    NTS is the ordinary way to say a detail is not drawn to scale, so a change
    that reads only ratios would lose the field on a large share of real sheets.
    ``AS NOTED`` is the case that decides the shape of the break rule: it has a
    space inside the value, so a rule that ended the value at the first space
    would store ``AS``.
    """
    assert detect_sheet_info("SCALE: NTS")["scale"] == "NTS"
    assert detect_sheet_info("SCALE: N.T.S.")["scale"] == "N.T.S."
    assert detect_sheet_info("SCALE: VARIES")["scale"] == "VARIES"
    assert detect_sheet_info("SCALE: AS NOTED")["scale"] == "AS NOTED"
    assert detect_sheet_info("SCALE: AS NOTED   DRAWN: AB")["scale"] == "AS NOTED"
    assert detect_sheet_info("SCALE: NTS\nREV C")["scale"] == "NTS"


def test_a_sheet_title_beside_a_neighbouring_field_does_not_absorb_it() -> None:
    """The title pattern had the same fault as the scale, and keeps a wider bound.

    ``(.+?)(?:\\n|$)`` captures to the end of the joined row, so a title sharing
    a row with the drawn-by cell was stored carrying that cell, up to the 500
    character column limit.

    The title is free text, so unlike the scale it is NOT cut at a run of
    spaces: wide letter spacing inside a single cell produces the same run, and
    cutting there would truncate a real title. Only a following label ends it.
    That asymmetry is deliberate and this pins both halves of it.
    """
    joined = "SHEET TITLE: Floor Plan Level 2    DRAWN: AB"
    assert detect_sheet_info(joined)["sheet_title"] == "Floor Plan Level 2"

    # A gap inside the title itself is kept, because it is not a field boundary.
    spaced = "SHEET TITLE: Floor  Plan  Level 2\nREV C"
    assert detect_sheet_info(spaced)["sheet_title"] == "Floor  Plan  Level 2"


def test_an_imperial_scale_survives_the_labelled_pattern() -> None:
    """A labelled imperial scale is stored whole rather than cut at the equals.

    A second fault in the same pattern, found while fixing the first and not
    covered by any test. ``=`` was absent from the character class, so on
    ``SCALE: 1/4" = 1'-0"`` the class stopped at the space before the equals and
    the trailing ``\\S*`` took only the equals itself, storing ``1/4" =``. The
    third pattern in the list reads the imperial form correctly, but it never
    ran: the labelled pattern is tried first and matched, and the loop breaks on
    the first match. So the imperial form was only ever read correctly on a page
    that does not label it.
    """
    assert detect_sheet_info('SCALE: 1/4" = 1\'-0"')["scale"] == '1/4" = 1\'-0"'
    assert detect_sheet_info('SCALE: 1/4" = 1\'-0"\nREV C')["scale"] == '1/4" = 1\'-0"'
    # Unlabelled, which is the case the third pattern was carrying on its own.
    assert detect_sheet_info('1/4" = 1\'-0"')["scale"] == '1/4" = 1\'-0"'


def test_a_scale_label_with_its_value_on_the_next_line_still_reads() -> None:
    """Bounding the capture to one line must not lose a value set below the label.

    Some title blocks put the field name in one cell and the value in the cell
    under it, which reaches the text extractor as two lines. The labelled
    pattern now declines that, correctly, because what follows the label on its
    own line is nothing. The unlabelled ratio pattern picks it up instead, so
    the value still arrives; this pins that the fallback is doing that work,
    rather than the bound silently costing a page its scale.
    """
    assert detect_sheet_info("SCALE:\n1:50")["scale"] == "1:50"


async def test_a_page_with_no_readable_number_is_kept_with_a_null_number(session: AsyncSession) -> None:
    """An unreadable title block yields a row, not a refusal and not a guess.

    The page is stored with ``sheet_number`` and ``discipline`` null rather
    than dropped or given an invented number, which is why the register falls
    back to labelling such a row by its page.
    """
    project_id, user_id = await _seed_project(session)
    pdf = _pdf_with_pages(
        [
            ["SHEET NO: A-201", "SHEET TITLE: Floor Plan Level 2"],
            ["GENERAL NOTES", "SEE THE SPECIFICATION"],
        ]
    )

    sheets = await SheetService(session).split_pdf_to_sheets(project_id, _upload(pdf), user_id)

    assert len(sheets) == 2
    unreadable = sheets[1]
    assert unreadable.page_number == 2
    assert unreadable.sheet_number is None
    assert unreadable.discipline is None
    assert unreadable.sheet_title is None


async def test_a_second_split_supersedes_the_first_rather_than_doubling_it(session: AsyncSession) -> None:
    """A re-uploaded drawing set leaves one current row per sheet number.

    Every row used to be flagged current forever, so a second upload gave the
    register two A-201s, both claiming to be the current revision and
    distinguishable only by parent document. It also handed a doubled ACTUAL
    set to ``check_completeness``, which reads ``current_only=True`` and
    reconciles the project's sheets against a drawing index by number.

    Nothing is deleted. Both parent documents survive, all four rows survive,
    and the earlier pair keeps every column it had; they simply stop being
    current and the new rows point back at them.
    """
    project_id, user_id = await _seed_project(session)
    pdf = _pdf_with_pages(
        [
            ["SHEET NO: A-201", "SHEET TITLE: Floor Plan Level 2"],
            ["SHEET NO: A-202", "SHEET TITLE: Floor Plan Level 3"],
        ]
    )

    service = SheetService(session)
    first = await service.split_pdf_to_sheets(project_id, _upload(pdf), user_id)
    second = await service.split_pdf_to_sheets(project_id, _upload(pdf), user_id)

    assert len(first) == 2
    assert len(second) == 2

    rows = list((await session.execute(select(Sheet).where(Sheet.project_id == project_id))).scalars().all())
    assert len(rows) == 4
    assert len({r.document_id for r in rows}) == 2
    assert sorted(str(r.sheet_number) for r in rows) == ["A-201", "A-201", "A-202", "A-202"]

    # One current row per number, and it is the one from the second upload.
    current = [r for r in rows if r.is_current]
    assert sorted(str(r.sheet_number) for r in current) == ["A-201", "A-202"]
    assert {r.id for r in current} == {s.id for s in second}

    # The retired rows are the first upload's, and each new row names the row
    # it replaced rather than merely outranking it.
    assert {r.id for r in rows if not r.is_current} == {s.id for s in first}
    by_number_first = {s.sheet_number: s.id for s in first}
    for sheet in second:
        assert sheet.previous_version_id == by_number_first[sheet.sheet_number]

    documents = list((await session.execute(select(Document).where(Document.project_id == project_id))).scalars().all())
    assert len(documents) == 2


async def test_the_version_chain_of_a_re_uploaded_sheet_reads_oldest_first(session: AsyncSession) -> None:
    """The links the split writes are the ones the version history walks.

    Setting ``previous_version_id`` is only worth doing if the read path that
    follows it agrees, so this goes through ``get_version_chain`` rather than
    asserting the column a second time. Three uploads, so the walk has to
    traverse two hops rather than one.
    """
    project_id, user_id = await _seed_project(session)
    pdf = _pdf_with_pages([["SHEET NO: A-201", "SHEET TITLE: Floor Plan Level 2"]])

    service = SheetService(session)
    uploads = [(await service.split_pdf_to_sheets(project_id, _upload(pdf), user_id))[0] for _ in range(3)]

    chain = await service.repo.get_version_chain(uploads[-1].id)

    assert [s.id for s in chain] == [s.id for s in uploads]
    assert [s.is_current for s in chain] == [False, False, True]

    # Walking from the oldest row returns the same chain, because the walk goes
    # forwards as well as backwards.
    from_oldest = await service.repo.get_version_chain(uploads[0].id)
    assert [s.id for s in from_oldest] == [s.id for s in uploads]


async def test_a_page_with_no_number_never_joins_a_version_chain(session: AsyncSession) -> None:
    """Unreadable is not a key, so unreadable pages do not supersede each other.

    Two uploads each carrying an unreadable page must leave two current rows,
    not one retiring the other. Chaining on "no number" would collect every
    unreadable page in the project into a single bogus history, and the second
    upload's general notes page has nothing to do with the first's.
    """
    project_id, user_id = await _seed_project(session)
    pdf = _pdf_with_pages(
        [
            ["SHEET NO: A-201", "SHEET TITLE: Floor Plan Level 2"],
            ["GENERAL NOTES", "SEE THE SPECIFICATION"],
        ]
    )

    service = SheetService(session)
    await service.split_pdf_to_sheets(project_id, _upload(pdf), user_id)
    await service.split_pdf_to_sheets(project_id, _upload(pdf), user_id)

    rows = list((await session.execute(select(Sheet).where(Sheet.project_id == project_id))).scalars().all())
    unnumbered = [r for r in rows if r.sheet_number is None]

    assert len(unnumbered) == 2
    assert all(r.is_current for r in unnumbered)
    assert all(r.previous_version_id is None for r in unnumbered)

    # The numbered page in the same uploads did supersede, so the difference is
    # the missing key and not the split having skipped the step.
    numbered = [r for r in rows if r.sheet_number == "A-201"]
    assert sorted(r.is_current for r in numbered) == [False, True]


async def test_one_upload_claiming_a_number_twice_keeps_both_pages_current(session: AsyncSession) -> None:
    """A duplicate number inside one file is the file's fault, not resolved by us.

    The earlier page takes the link to the sheet it replaces and the later page
    stays current and unlinked, so the register shows two current rows for that
    number. That is the truth about the PDF that was uploaded. Retiring the
    predecessor anyway is deliberate: this upload does supersede it, and leaving
    it current would make three.
    """
    project_id, user_id = await _seed_project(session)
    original = _pdf_with_pages([["SHEET NO: A-201", "SHEET TITLE: Floor Plan Level 2"]])
    duplicated = _pdf_with_pages(
        [
            ["SHEET NO: A-201", "SHEET TITLE: Floor Plan Level 2"],
            ["SHEET NO: A-201", "SHEET TITLE: Floor Plan Level 2 Revised"],
        ]
    )

    service = SheetService(session)
    first = await service.split_pdf_to_sheets(project_id, _upload(original), user_id)
    second = await service.split_pdf_to_sheets(project_id, _upload(duplicated), user_id)

    rows = list((await session.execute(select(Sheet).where(Sheet.project_id == project_id))).scalars().all())
    assert len(rows) == 3

    current = [r for r in rows if r.is_current]
    assert {r.id for r in current} == {s.id for s in second}

    # Page 1 claims the link, page 2 stays unlinked rather than pointing at the
    # same predecessor a second time.
    by_page = {s.page_number: s for s in second}
    assert by_page[1].previous_version_id == first[0].id
    assert by_page[2].previous_version_id is None


# ── The consequence downstream of the register ────────────────────────────


async def test_completeness_compares_the_index_against_the_newest_revision(session: AsyncSession) -> None:
    """A re-issued sheet is reconciled against the revision that replaced it.

    ``check_completeness`` loads the project's sheets with ``current_only=True``
    and its own comment beside that call said this was so superseded revisions
    do not read as extra. Nothing ever marked a revision superseded, so the
    comment described an intention rather than the code.

    The consequence was NOT a pile of extras, which is worth stating because it
    is the obvious guess and it is wrong. ``reconcile`` keys both sides on the
    normalised sheet number and builds a dict, so two rows carrying A-201
    collapse into one entry and the later one in the list simply overwrites the
    earlier. Nothing is reported. What decided which of the two revisions got
    compared against the index was the order ``list_sheets`` happened to return,
    and that order sorts on page number, which both rows share. So the revision
    check could answer for the superseded sheet, and the same call could answer
    differently twice.

    Here the index asks for revision B, the first upload is revision A and the
    second is revision B. With one current row the answer is decided rather than
    raced.
    """
    project_id, user_id = await _seed_project(session)
    rev_a = _pdf_with_pages([["SHEET NO: A-201", "SHEET TITLE: Floor Plan Level 2", "REV A"]])
    rev_b = _pdf_with_pages([["SHEET NO: A-201", "SHEET TITLE: Floor Plan Level 2", "REV B"]])

    service = SheetService(session)
    first = await service.split_pdf_to_sheets(project_id, _upload(rev_a), user_id)
    second = await service.split_pdf_to_sheets(project_id, _upload(rev_b), user_id)
    assert first[0].revision == "A"
    assert second[0].revision == "B"

    report = await service.check_completeness(project_id, pasted_index="A-201 Floor Plan Level 2 Rev B")
    completeness = report["completeness"]

    assert completeness["matched"] == ["A-201"]
    assert completeness["missing"] == []
    assert completeness["extra"] == []
    # The revision compared is B, the one that replaced A, so nothing mismatches.
    assert completeness["rev_mismatch"] == []

    # Both rows are still in the table, so what changed is which sheet the
    # reconciliation reads and not whether the history survives.
    rows = list((await session.execute(select(Sheet).where(Sheet.project_id == project_id))).scalars().all())
    assert len(rows) == 2


async def test_completeness_counts_sheet_numbers_and_not_sheet_rows(session: AsyncSession) -> None:
    """``actual_count`` is a count of distinct numbers, which is easy to misread.

    Asking for every revision returns two rows for A-201, and the reconciliation
    still reports one, because it is a set difference over sheet numbers rather
    than a tally of rows. Pinned so that nobody reads ``actual_count`` as "how
    many sheets are in the project", including whoever writes the next release
    note about this feature.
    """
    project_id, user_id = await _seed_project(session)
    pdf = _pdf_with_pages([["SHEET NO: A-201", "SHEET TITLE: Floor Plan Level 2"]])

    service = SheetService(session)
    await service.split_pdf_to_sheets(project_id, _upload(pdf), user_id)
    await service.split_pdf_to_sheets(project_id, _upload(pdf), user_id)

    report = await service.check_completeness(project_id, pasted_index="A-201", current_only=False)

    assert report["completeness"]["actual_count"] == 1
    # Two rows went in, so the collapse is real and not an empty second upload.
    _listed, total = await service.list_sheets(project_id, current_only=False)
    assert total == 2


# ── Aggregation over the register ─────────────────────────────────────────


async def test_listing_reports_the_total_behind_the_page(session: AsyncSession) -> None:
    """The row count and the register's size are different numbers.

    ``list_for_project`` counts the filtered set before paginating, so a caller
    that counts the rows it received is not counting the register. The route
    returns only the rows and drops this total, and the index page asks for
    ``limit=500``, which is the schema maximum.
    """
    project_id, _user_id = await _seed_project(session)
    for page in (1, 2, 3):
        await _seed_sheet(session, project_id, page_number=page, sheet_number=f"A-10{page}", discipline="Architectural")

    listed, total = await SheetService(session).list_sheets(project_id, limit=2)

    assert len(listed) == 2
    assert total == 3


async def test_distinct_disciplines_collapses_rows_and_drops_the_unset_ones(session: AsyncSession) -> None:
    """The discipline list counts disciplines, not sheets, and skips the nulls.

    Five rows over two named disciplines return two values. The rows with no
    discipline contribute nothing here, while the insights band buckets them
    under a visible "not set" slice, so the two surfaces do not agree on how
    many groups the register has.
    """
    project_id, _user_id = await _seed_project(session)
    await _seed_sheet(session, project_id, page_number=1, sheet_number="A-101", discipline="Architectural")
    await _seed_sheet(session, project_id, page_number=2, sheet_number="A-102", discipline="Architectural")
    await _seed_sheet(session, project_id, page_number=3, sheet_number="S-201", discipline="Structural")
    await _seed_sheet(session, project_id, page_number=4, sheet_number=None, discipline=None)
    await _seed_sheet(session, project_id, page_number=5, sheet_number="X-999", discipline=None)

    disciplines = await SheetService(session).get_disciplines(project_id)

    assert disciplines == ["Architectural", "Structural"]

    _listed, total = await SheetService(session).list_sheets(project_id)
    assert total == 5


async def test_which_row_a_revision_supersedes_does_not_depend_on_insertion_order(
    session: AsyncSession,
) -> None:
    """Two current rows on one number resolve to the same one either way round.

    ``current_by_chain_key`` is what decides which row an incoming revision
    records as its predecessor: the stacker takes the last row of a key's
    group, read in ascending order. The lookup this replaced,
    ``current_by_sheet_numbers``, once ordered on ``created_at`` alone.

    That column is written per row by a Python default, so it is only as fine as
    the clock underneath it, and on a coarse one an entire import batch carries
    a single value. Duplicates in this register are produced by exactly that,
    one upload writing the same number on two pages, which is the case where the
    timestamp has nothing left to order by. What answered then was the plan.

    So the two projects here hold identical rows written in opposite orders,
    with the created instant pinned equal on purpose. Anything that resolves
    them by arrival answers differently for the two, and this asserts they
    agree. Pinning the timestamps rather than sleeping between the inserts also
    keeps the test from passing on a machine whose clock happens to be fine
    enough to separate them, which is what CI has and this box does not.

    What this does NOT cover: pinning the instants equal is what makes the id
    carry the whole assertion, so an implementation that ordered on the id alone
    and dropped ``created_at`` would pass this too. The created component is
    reasoned from what the column is for, not measured here, and a test that
    separated the two would have to rely on the clock this one deliberately
    takes out of the picture.
    """
    stamp = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
    low = uuid.UUID("00000000-0000-4000-8000-000000000001")
    high = uuid.UUID("00000000-0000-4000-8000-000000000002")

    async def _seed_pair(order: tuple[uuid.UUID, uuid.UUID]) -> uuid.UUID:
        project_id, _ = await _seed_project(session)
        for page, sheet_id in enumerate(order, start=1):
            session.add(
                Sheet(
                    id=sheet_id,
                    project_id=project_id,
                    document_id=str(uuid.uuid4()),
                    page_number=page,
                    sheet_number="A-101",
                    is_current=True,
                    created_at=stamp,
                )
            )
            await session.flush()
        return project_id

    forwards = await _seed_pair((low, high))
    # A fresh id per row is required, so the reversed project gets its own pair
    # carrying the same relative order.
    low_b = uuid.UUID("00000000-0000-4000-8000-00000000000a")
    high_b = uuid.UUID("00000000-0000-4000-8000-00000000000b")

    backwards_project, _ = await _seed_project(session)
    for page, sheet_id in enumerate((high_b, low_b), start=1):
        session.add(
            Sheet(
                id=sheet_id,
                project_id=backwards_project,
                document_id=str(uuid.uuid4()),
                page_number=page,
                sheet_number="A-101",
                is_current=True,
                created_at=stamp,
            )
        )
        await session.flush()

    repo = SheetRepository(session)
    # The stacker takes the last row of a key's group as the latest.
    picked_forwards = (await repo.current_by_chain_key(forwards))["A101"][-1]
    picked_backwards = (await repo.current_by_chain_key(backwards_project))["A101"][-1]

    # Both projects hold the same two rows. The one written second in each is a
    # different id, so a resolution that follows arrival returns the high id for
    # one project and the low id for the other. Under a total order both return
    # the later id, whichever order the rows were written in.
    assert str(picked_forwards.id) == str(high)
    assert str(picked_backwards.id) == str(high_b)
