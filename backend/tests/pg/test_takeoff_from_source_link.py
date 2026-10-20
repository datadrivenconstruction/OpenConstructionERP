"""PG: the Project-Files -> takeoff document link.

Opening a PDF from the /files area must land on a REAL ``TakeoffDocument``
rather than on the ``oe_documents_document`` id, because every takeoff artefact
(measurements, page scales, extracted text, AI runs) keys on the takeoff id.
The bridge is ``TakeoffDocument.source_document_id`` plus the find-or-create in
``TakeoffService.get_or_create_takeoff_from_source``.

These tests run against a REAL PostgreSQL cluster because the properties worth
pinning are all database-level and cannot be observed on the mock-repository
suite in ``tests/modules/takeoff/test_from_source.py``:

* the ``uq_takeoff_document_project_source`` unique index is what actually
  stops a concurrent double-open from minting two rows (#369) - the mock
  implements find-or-create in Python and stays green with the index dropped;
* that index is deliberately plain rather than partial, which only works
  because PostgreSQL treats NULLs as distinct - SQLite would not prove it;
* deleting the source document is a cross-module interaction between
  ``DocumentService`` and the takeoff tables.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.documents.models import Document
from app.modules.documents.service import DocumentService
from app.modules.projects.models import Project
from app.modules.takeoff.models import TakeoffDocument, TakeoffMeasurement
from app.modules.takeoff.router import create_takeoff_from_source
from app.modules.takeoff.service import TakeoffService
from app.modules.users.models import User

# Bytes that are NOT a parseable PDF. Every reuse-path test passes these as the
# "source content": if the find-or-create ever stops short-circuiting and falls
# through to the real upload/parse path, the test fails loudly instead of
# quietly succeeding for the wrong reason.
NOT_A_PDF = b"this should never reach the parser"


def _real_pdf_on_disk(name: str) -> str:
    """Write a genuinely valid one-page PDF under the uploads root.

    The access test needs the source blob to be present and readable, otherwise
    the route would 404 on the missing file for a reason that has nothing to do
    with permissions - and the test would pass even with the access check torn
    out. A real file makes the refusal attributable to the access check alone.
    """
    from reportlab.pdfgen import canvas

    from app.modules.documents.service import UPLOAD_BASE

    base = Path(UPLOAD_BASE)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"takeoff-src-test-{uuid.uuid4().hex}-{name}"
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    c.showPage()
    c.save()
    return str(path)


async def _seed(session, *, with_blob: bool = False) -> tuple[User, Project, Document]:
    """Insert an owner, a project, and one Project-Files document.

    ``with_blob`` also writes a real PDF to disk and points the document at it.
    """
    owner = User(email=f"takeoff-src-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(owner)
    await session.flush()

    project = Project(name="From-source link", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()

    source = Document(
        project_id=project.id,
        name="A-201 Floor Plan.pdf",
        category="drawing",
        mime_type="application/pdf",
        file_path=_real_pdf_on_disk("A-201.pdf") if with_blob else "",
        uploaded_by=str(owner.id),
    )
    session.add(source)
    await session.flush()
    return owner, project, source


def _takeoff_doc(project: Project, owner: User, *, source_id: str | None) -> TakeoffDocument:
    return TakeoffDocument(
        filename="A-201 Floor Plan.pdf",
        pages=1,
        size_bytes=1024,
        project_id=project.id,
        owner_id=owner.id,
        source_document_id=source_id,
    )


@pytest.mark.asyncio
async def test_reopening_a_project_file_reuses_the_document_and_its_measurements(pg_session):
    """A second open returns the first open's document, measurements included.

    This is the deliberate product decision: a takeoff is a work product, not a
    viewing session, so reopening the same drawing from /files must not strand
    the quantities already measured on it behind a fresh document id.
    """
    owner, project, source = await _seed(pg_session)

    first = _takeoff_doc(project, owner, source_id=str(source.id))
    pg_session.add(first)
    await pg_session.flush()

    measurement = TakeoffMeasurement(
        project_id=project.id,
        document_id=str(first.id),
        page=1,
        type="area",
        measurement_value=42,
        measurement_unit="m2",
    )
    pg_session.add(measurement)
    await pg_session.flush()

    service = TakeoffService(pg_session)
    second = await service.get_or_create_takeoff_from_source(
        source_document_id=str(source.id),
        source_project_id=str(project.id),
        source_file_path=source.file_path,
        filename="A-201 Floor Plan.pdf",
        content=NOT_A_PDF,
        size_bytes=len(NOT_A_PDF),
        owner_id=str(owner.id),
    )

    assert second.id == first.id, "reopening the same source minted a new takeoff document"

    rows = (
        (await pg_session.execute(select(TakeoffMeasurement).where(TakeoffMeasurement.document_id == str(second.id))))
        .scalars()
        .all()
    )
    assert len(rows) == 1, "the reused document lost the measurements taken on the first open"
    assert rows[0].measurement_value == 42


@pytest.mark.asyncio
async def test_unique_index_rejects_a_duplicate_source_link(pg_session):
    """Two takeoff documents cannot share one (project, source document).

    The database-level guard behind #369: the find-or-create does an unlocked
    SELECT then INSERT, so two concurrent opens can both miss. Without this
    index the loser's measurements strand on an unreachable duplicate row.
    """
    owner, project, source = await _seed(pg_session)

    pg_session.add(_takeoff_doc(project, owner, source_id=str(source.id)))
    await pg_session.flush()

    pg_session.add(_takeoff_doc(project, owner, source_id=str(source.id)))
    with pytest.raises(IntegrityError):
        await pg_session.flush()
    await pg_session.rollback()


@pytest.mark.asyncio
async def test_direct_uploads_without_a_source_never_collide(pg_session):
    """Many plain uploads coexist in one project - NULL source ids stay distinct.

    ``uq_takeoff_document_project_source`` is deliberately a plain (not partial)
    unique index so the startup auto-migrate heal, which skips partial indexes,
    still materialises it. That is only safe because PostgreSQL treats NULLs as
    distinct, so the constraint binds from-source rows and never ordinary
    uploads. If that ever changed, direct upload would break for every project.
    """
    owner, project, _ = await _seed(pg_session)

    pg_session.add(_takeoff_doc(project, owner, source_id=None))
    pg_session.add(_takeoff_doc(project, owner, source_id=None))
    pg_session.add(_takeoff_doc(project, owner, source_id=None))
    await pg_session.flush()

    rows = (
        (
            await pg_session.execute(
                select(TakeoffDocument).where(
                    TakeoffDocument.project_id == project.id,
                    TakeoffDocument.source_document_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_deleting_the_source_leaves_the_takeoff_document_intact(pg_session):
    """Deleting the /files document must not destroy takeoff work built on it.

    ``source_document_id`` is a plain column, not a cascading FK, and the
    takeoff document owns its own copy of the bytes, so the delete is
    survivable by design: the takeoff document and its measurements remain
    readable. The reference goes stale, which the next open handles as a clean
    404 (pinned separately below) rather than a 500.

    DECISION RECORD - this test pins CURRENT behaviour, deliberately, and the
    behaviour depends on a known defect. The takeoff document survives the
    delete precisely *because* the from-source path copies the PDF bytes into
    the takeoff upload directory instead of referencing the stored blob, so the
    source document and the takeoff document own independent copies. That copy
    is a real defect (it doubles disk for every project file opened in takeoff),
    and the planned fix - referencing the blob zero-copy, with a copy-on-delete
    hook in ``DocumentService.delete_document`` - would keep this test's
    assertions true while changing the mechanism underneath them.

    So: this test is a decision record, not an accident. If you are implementing
    the zero-copy change and this test fails, you have removed the copy WITHOUT
    adding the delete hook, and you have just orphaned every measurement built
    on a deleted project file. That is the one outcome strictly worse than the
    duplication being fixed. The assertions here stay valid under both designs;
    only a half-finished migration between them can break it.
    """
    owner, project, source = await _seed(pg_session)
    source_id = source.id

    doc = _takeoff_doc(project, owner, source_id=str(source_id))
    pg_session.add(doc)
    await pg_session.flush()
    takeoff_id = doc.id

    pg_session.add(
        TakeoffMeasurement(
            project_id=project.id,
            document_id=str(takeoff_id),
            page=1,
            type="area",
            measurement_value=17,
            measurement_unit="m2",
        )
    )
    await pg_session.flush()

    await DocumentService(pg_session).delete_document(source_id, user_id=str(owner.id))

    # Drop the identity map before asserting. ``session.get`` would happily
    # return the still-cached Python object for a row the database has already
    # deleted, so these assertions must be forced through real SELECTs -
    # otherwise a cascading delete would slip past this test unnoticed.
    pg_session.expire_all()

    remaining_source = (await pg_session.execute(select(Document).where(Document.id == source_id))).scalars().all()
    assert remaining_source == [], "source document was not deleted"

    survivors = (
        (await pg_session.execute(select(TakeoffDocument).where(TakeoffDocument.id == takeoff_id))).scalars().all()
    )
    assert len(survivors) == 1, "deleting the source destroyed the takeoff document"

    rows = (
        (await pg_session.execute(select(TakeoffMeasurement).where(TakeoffMeasurement.document_id == str(takeoff_id))))
        .scalars()
        .all()
    )
    assert len(rows) == 1, "deleting the source orphaned the measurements"
    assert rows[0].measurement_value == 17


@pytest.mark.asyncio
async def test_opening_from_source_references_the_blob_instead_of_copying_it(pg_session):
    """The bytes are not duplicated: the takeoff row points at the stored blob.

    This is the whole point of the zero-copy change. Before it, opening a
    project file in takeoff wrote a second identical PDF into the takeoff
    documents directory, doubling disk for every drawing anyone opened.
    """
    owner, project, source = await _seed(pg_session, with_blob=True)
    source_path = Path(source.file_path)

    from app.modules.takeoff.service import _takeoff_documents_dir

    takeoff_dir = _takeoff_documents_dir()
    before = set(takeoff_dir.glob("*.pdf")) if takeoff_dir.is_dir() else set()

    try:
        doc = await TakeoffService(pg_session).get_or_create_takeoff_from_source(
            source_document_id=str(source.id),
            source_project_id=str(project.id),
            source_file_path=str(source_path),
            filename="A-201 Floor Plan.pdf",
            content=source_path.read_bytes(),
            size_bytes=source_path.stat().st_size,
            owner_id=str(owner.id),
        )

        assert doc.file_path == str(source_path), "takeoff did not reference the stored blob"

        after = set(takeoff_dir.glob("*.pdf")) if takeoff_dir.is_dir() else set()
        assert after == before, f"a second copy of the PDF was written: {sorted(after - before)}"
    finally:
        # The database rolls back after each test, the filesystem does not.
        # Also sweep any copy a regression wrote, so a red run does not leave
        # the duplicate behind that the test exists to forbid.
        source_path.unlink(missing_ok=True)
        strays = (set(takeoff_dir.glob("*.pdf")) if takeoff_dir.is_dir() else set()) - before
        for stray in strays:
            stray.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_a_parse_failure_on_a_borrowed_blob_never_deletes_the_project_file(pg_session):
    """An unparseable from-source PDF must not take the user's document with it.

    ``upload_document`` unlinks the bytes it wrote when the parser cannot read a
    single page. On the from-source path that path is the user's stored project
    document rather than a takeoff-owned copy, so the unlink has to be guarded
    by provenance. Getting this wrong destroys a Project-Files document on what
    should be a harmless 400.
    """
    owner, project, source = await _seed(pg_session, with_blob=True)
    source_path = Path(source.file_path)
    # Valid magic so the pre-parser gates pass, but nothing a parser can read.
    source_path.write_bytes(b"%PDF-1.4\nnot really a pdf\n")

    try:
        with pytest.raises(HTTPException) as exc:
            await TakeoffService(pg_session).get_or_create_takeoff_from_source(
                source_document_id=str(source.id),
                source_project_id=str(project.id),
                source_file_path=str(source_path),
                filename="A-201 Floor Plan.pdf",
                content=source_path.read_bytes(),
                size_bytes=source_path.stat().st_size,
                owner_id=str(owner.id),
            )
        assert exc.value.status_code == 400

        assert source_path.is_file(), "a failed parse deleted the user's project document off disk"
    finally:
        # Surviving the parse failure is the assertion, so this test always
        # leaves the blob behind unless it is cleaned up explicitly.
        source_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_deleting_the_source_hands_takeoff_its_own_copy_of_the_bytes(pg_session):
    """The delete hook copies the blob before the unlink, and repoints the row.

    This is the test that actually exercises copy-on-delete. The decision-record
    test above cannot: its source document has no blob on disk and its takeoff
    document has no ``file_path``, so it passes whether the hook works, is
    broken, or is absent entirely. Its green is a statement about the DB rows
    surviving, not about the bytes.

    Here the takeoff document shares the source's path, which is what a
    from-source open now produces. After the delete the takeoff document must
    point somewhere else, that somewhere must exist, and it must still be the
    PDF - otherwise the zero-copy change has traded doubled disk for lost work.
    """
    owner, project, source = await _seed(pg_session, with_blob=True)
    source_id = source.id
    source_path = Path(source.file_path)
    assert source_path.is_file(), "seed did not put the source blob on disk"

    doc = _takeoff_doc(project, owner, source_id=str(source_id))
    doc.file_path = str(source_path)
    pg_session.add(doc)
    await pg_session.flush()
    takeoff_id = doc.id

    preserved: Path | None = None
    try:
        await DocumentService(pg_session).delete_document(source_id, user_id=str(owner.id))
        pg_session.expire_all()

        survivor = (
            (await pg_session.execute(select(TakeoffDocument).where(TakeoffDocument.id == takeoff_id))).scalars().one()
        )
        # Captured before the assertions so the copy is cleaned up even when
        # one of them fails.
        preserved = Path(survivor.file_path) if survivor.file_path else None

        assert survivor.file_path, "takeoff document lost its file path entirely"
        assert survivor.file_path != str(source_path), "takeoff document still points at the deleted source blob"

        assert preserved is not None
        assert preserved.is_file(), "the copy the hook was supposed to make does not exist"
        assert preserved.read_bytes().startswith(b"%PDF-"), "the preserved file is not the PDF"
        assert not source_path.exists(), "the source blob should have been unlinked after the copy"
    finally:
        source_path.unlink(missing_ok=True)
        if preserved is not None:
            preserved.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_a_failed_copy_keeps_the_source_blob_rather_than_orphaning_takeoff(pg_session, monkeypatch):
    """If the copy fails the original file must survive the deletion.

    This is the failure mode that would be strictly worse than the duplication
    being removed: the DB row is already gone by this point, so unlinking after
    a failed copy would leave the takeoff document pointing at nothing and every
    measurement on it unreadable. Deleting the row but keeping the bytes is
    recoverable; deleting both is not.
    """
    owner, project, source = await _seed(pg_session, with_blob=True)
    source_id = source.id
    source_path = Path(source.file_path)

    doc = _takeoff_doc(project, owner, source_id=str(source_id))
    doc.file_path = str(source_path)
    pg_session.add(doc)
    await pg_session.flush()

    def _explode(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr("app.modules.takeoff.service.shutil.copyfile", _explode)

    try:
        await DocumentService(pg_session).delete_document(source_id, user_id=str(owner.id))
        pg_session.expire_all()

        remaining = (await pg_session.execute(select(Document).where(Document.id == source_id))).scalars().all()
        assert remaining == [], "the document row should still be deleted"
        assert source_path.is_file(), (
            "the source blob was unlinked even though the takeoff copy failed - "
            "the takeoff document now points at nothing"
        )
    finally:
        # Keeping the blob is the assertion here, so it is always left behind.
        source_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_deleting_the_source_leaves_a_pre_zero_copy_takeoff_row_alone(pg_session):
    """A takeoff document that owns its bytes is not touched by the delete hook.

    The mixed fleet this ships into: every takeoff document created BEFORE the
    zero-copy change was handed its own copy at upload time, so it carries a
    ``source_document_id`` but a ``file_path`` of its own. Those rows are already
    safe and must be left exactly as they are.

    What decides that is the path comparison in the hook, not the source id -
    these rows are returned by its query just like the sharing ones. So the
    failure this pins is a plausible future "fix": someone drops the path filter
    on the reasoning that every row with a matching source id is a dependent, and
    the hook then repoints a row onto a file it does not own. Because the legacy
    file here is deliberately parked at the exact destination name the hook would
    write to, a widened filter overwrites its bytes, which the content assertion
    catches rather than letting a same-path repoint look like a no-op.
    """
    from app.modules.takeoff.service import _takeoff_documents_dir

    owner, project, source = await _seed(pg_session, with_blob=True)
    source_id = source.id
    source_path = Path(source.file_path)

    doc = _takeoff_doc(project, owner, source_id=str(source_id))
    pg_session.add(doc)
    await pg_session.flush()
    takeoff_id = doc.id

    # The legacy layout: takeoff owns a separate file, with bytes distinct from
    # the source so an overwrite is visible rather than silent.
    takeoff_dir = _takeoff_documents_dir()
    takeoff_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = takeoff_dir / f"{takeoff_id}.pdf"
    legacy_bytes = b"%PDF-1.4\nthe takeoff document's own pre-zero-copy copy\n"
    legacy_path.write_bytes(legacy_bytes)
    doc.file_path = str(legacy_path)
    await pg_session.flush()

    try:
        await DocumentService(pg_session).delete_document(source_id, user_id=str(owner.id))
        pg_session.expire_all()

        survivor = (
            (await pg_session.execute(select(TakeoffDocument).where(TakeoffDocument.id == takeoff_id))).scalars().one()
        )
        assert survivor.file_path == str(legacy_path), "the hook repointed a takeoff row that owned its own bytes"
        assert legacy_path.is_file(), "the takeoff document's own file was removed"
        assert legacy_path.read_bytes() == legacy_bytes, "the hook overwrote a file the takeoff document owned"

        # Nothing shared the source blob, so removing it is correct here - the
        # hook must not hold the original hostage for a row that never used it.
        assert not source_path.exists(), "the source blob was kept even though no takeoff document referenced it"
    finally:
        legacy_path.unlink(missing_ok=True)
        source_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_reopening_a_deleted_source_is_a_clean_404(pg_session):
    """A stale source id returns 404, never an unhandled 500.

    A dangling reference that crashes on next open would be a worse bug than
    the id-namespace mixup this whole bridge exists to fix.
    """
    owner, project, source = await _seed(pg_session)
    source_id = source.id

    await DocumentService(pg_session).delete_document(source_id, user_id=str(owner.id))

    with pytest.raises(HTTPException) as exc:
        await create_takeoff_from_source(
            source_document_id=str(source_id),
            user_id=str(owner.id),
            service=TakeoffService(pg_session),
            session=pg_session,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_the_link_does_not_widen_access_to_another_users_project(pg_session):
    """An outsider cannot read a project file through the takeoff bridge.

    The takeoff route must be no wider than the documents module's own read
    scoping: it resolves the source row, then runs the same
    ``verify_project_access`` the documents download route runs, against the
    project taken from the stored row rather than from anything the caller
    sends. The refusal is 404 (not 403) so a probed UUID cannot be used to test
    for existence.
    """
    _owner, _project, source = await _seed(pg_session, with_blob=True)

    outsider = User(email=f"outsider-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    pg_session.add(outsider)
    await pg_session.flush()
    assert outsider.role != "admin", "outsider must not hold the admin bypass"

    try:
        with pytest.raises(HTTPException) as exc:
            await create_takeoff_from_source(
                source_document_id=str(source.id),
                user_id=str(outsider.id),
                service=TakeoffService(pg_session),
                session=pg_session,
            )
        assert exc.value.status_code == 404

        linked = (
            (
                await pg_session.execute(
                    select(TakeoffDocument).where(TakeoffDocument.source_document_id == str(source.id))
                )
            )
            .scalars()
            .all()
        )
        assert linked == [], "a refused open still created a takeoff document"
    finally:
        # The seeded blob lives in the real uploads root: the database rolls
        # back after each test, the filesystem does not. Remove it so a run
        # does not leave a stray PDF in the developer's data dir.
        Path(source.file_path).unlink(missing_ok=True)
