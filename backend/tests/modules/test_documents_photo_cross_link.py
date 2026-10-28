# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The photo cross-link must not take the upload down with it.

Uploading a site photo writes two rows: the photo itself, and a ``Document`` row
so the photo also shows up in the documents hub. The second one is convenience
work, and the comment above it has always said a failure there is non-fatal.

Saying so takes more than an ``except``. A failed ``flush()`` marks the whole
session for rollback, and on PostgreSQL the transaction goes to aborted
server-side at the same moment, so catching the error and carrying on leaves
every later statement raising about a transaction that cannot continue. The
upload then dies several frames away, describing something other than what went
wrong, and the photo the user just uploaded is gone. This product has paid for
that class of bug before, most visibly when deadline notifications went dark
across the product because one bad row poisoned a session that a caught
exception could not revive.

``PhotoService.upload_photo`` therefore runs the cross-link inside
``session.begin_nested()``, and these tests are about that SAVEPOINT rather than
about the ``except``. "No exception escaped" cannot tell the two apart: it is
true whether the guard is present or missing. What separates them is what the
session can still do afterwards, so that is what is asserted here.

Remove the ``async with self.session.begin_nested():`` line from
``upload_photo`` and ``test_a_failed_cross_link_leaves_the_session_usable``
fails with ``PendingRollbackError``, which is the whole reason it exists.

The failure is injected by pointing the cross-link row at a project that does
not exist. ``Document.project_id`` carries a foreign key, so the flush fails the
way a database really fails, with an ``IntegrityError`` raised by PostgreSQL and
the transaction aborted server-side too. Nothing else about the upload changes;
the photo row still names the real project.

The upload also registers a version-chain row two lines BEFORE the cross-link,
and that call had no savepoint of its own. A failure there poisoned the session
first, so the cross-link below could no longer open its savepoint at all and
the guard the tests above certify was disarmed by the line above it - a test
that passes while the property it describes is false. The last three tests are
about that ordering, which is why one of them makes the registration fail and
then asserts that the cross-link still worked.
"""

from __future__ import annotations

import io
import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from fastapi import UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import Headers

from app.modules.documents import service as documents_service
from app.modules.documents.models import Document, ProjectPhoto
from app.modules.documents.service import PhotoService
from app.modules.file_distribution import service as file_distribution_service
from app.modules.file_versions import service as file_versions_service
from app.modules.file_versions.models import FileVersion
from app.modules.file_versions.schemas import FileVersionCreate
from app.modules.file_versions.service import FileVersionService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

OWNER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


def _png_bytes() -> bytes:
    """A real 8x8 PNG. The upload path sniffs magic bytes and decodes pixels."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (120, 140, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(filename: str = "site-photo.png") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(_png_bytes()),
        filename=filename,
        headers=Headers({"content-type": "image/png"}),
    )


@pytest.fixture(autouse=True)
def photo_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write uploaded photos under the test's own tmp dir, not the user's home."""
    monkeypatch.setattr(documents_service, "PHOTO_BASE", tmp_path / "photos")
    monkeypatch.setattr(documents_service, "PHOTO_THUMB_BASE", tmp_path / "photos" / "thumbs")
    return tmp_path


@pytest_asyncio.fixture
async def session():
    """One transactional session with a project for the photo to belong to."""
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email="owner@photo-crosslink.io", hashed_password="x", full_name="Owner"))
        await s.flush()
        s.add(Project(id=PROJECT_ID, name="Photo cross-link", owner_id=OWNER_ID, currency="EUR"))
        await s.flush()
        yield s


def _break_the_cross_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the cross-link row, and only that row, one the database rejects.

    The ``Document`` name the service holds is replaced with a factory building
    the same row against a project id nothing points at. The photo row is
    untouched and still names the real project, so the only thing that can fail
    is the insert the SAVEPOINT exists to contain.
    """

    def _document_for_a_project_that_does_not_exist(**fields: object) -> Document:
        return Document(**{**fields, "project_id": uuid.uuid4()})

    monkeypatch.setattr(documents_service, "Document", _document_for_a_project_that_does_not_exist)


async def _documents_at(session: AsyncSession, file_path: str) -> int:
    return await session.scalar(select(func.count()).select_from(Document).where(Document.file_path == file_path))


async def test_an_uploaded_photo_reaches_the_documents_hub(session: AsyncSession) -> None:
    """The cross-link lands: one Document row, naming the stored photo file."""
    photo = await PhotoService(session).upload_photo(
        project_id=PROJECT_ID,
        file=_upload(),
        category="site",
        user_id=str(OWNER_ID),
        caption="North elevation",
    )
    await session.commit()

    doc = await session.scalar(select(Document).where(Document.file_path == photo.file_path))

    assert doc is not None, "the photo never reached the documents hub"
    assert doc.project_id == PROJECT_ID
    assert doc.category == "photo"
    assert doc.name == photo.filename


async def test_a_failed_cross_link_leaves_the_session_usable(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The savepoint test. Without ``begin_nested`` this raises PendingRollbackError.

    Every statement after the failed cross-link is issued on a session a bare
    ``except`` would have left unusable: a read, a commit, and a re-read. The
    photo is what the user came to save, and it is still there.
    """
    _break_the_cross_link(monkeypatch)

    photo = await PhotoService(session).upload_photo(
        project_id=PROJECT_ID,
        file=_upload("photo-whose-crosslink-fails.png"),
        category="site",
        user_id=str(OWNER_ID),
    )

    # The assertion this test exists for. A poisoned session raises
    # PendingRollbackError here instead of answering.
    still_there = await session.scalar(
        select(func.count()).select_from(ProjectPhoto).where(ProjectPhoto.id == photo.id)
    )
    assert still_there == 1

    # The cross-link was rolled back to the savepoint, so the hub holds no
    # half-written row for a photo it could not describe.
    assert await _documents_at(session, photo.file_path) == 0

    await session.commit()

    committed = await session.scalar(select(ProjectPhoto).where(ProjectPhoto.id == photo.id))
    assert committed is not None, "the photo was lost to a failure in convenience work"
    assert committed.project_id == PROJECT_ID


async def test_a_failed_cross_link_says_which_photo_it_lost(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Swallowed is not silent: the log names the photo and the project.

    A cross-link that fails leaves a photo the documents hub cannot see. That is
    only recoverable if somebody can find out which one, so both ids belong in
    the record.
    """
    _break_the_cross_link(monkeypatch)

    with caplog.at_level("ERROR", logger=documents_service.logger.name):
        photo = await PhotoService(session).upload_photo(
            project_id=PROJECT_ID,
            file=_upload("photo-that-should-be-logged.png"),
            category="site",
            user_id=str(OWNER_ID),
        )
        await session.commit()

    complaints = [r for r in caplog.records if "cross-link" in r.getMessage().lower()]
    assert complaints, "the cross-link failed and nothing was written down"
    reported = complaints[-1].getMessage()
    assert str(photo.id) in reported
    assert str(PROJECT_ID) in reported


async def test_a_defect_in_the_cross_link_block_is_not_swallowed(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``except SQLAlchemyError``, not ``except Exception``.

    A TypeError here is a defect in the block, not the database declining, and
    widening back to a bare ``except`` is exactly how the previous bug in this
    code stayed invisible for as long as it did. Nothing catches it, so the
    upload fails loudly and somebody goes and fixes the block.
    """

    def _document_built_wrong(**fields: object) -> Document:
        raise TypeError("Document() got an unexpected keyword argument")

    monkeypatch.setattr(documents_service, "Document", _document_built_wrong)

    with pytest.raises(TypeError):
        await PhotoService(session).upload_photo(
            project_id=PROJECT_ID,
            file=_upload("photo-with-a-broken-crosslink.png"),
            category="site",
            user_id=str(OWNER_ID),
        )


# ── The write that runs before the cross-link ──────────────────────────────


async def _versions_for(session: AsyncSession, file_id: str) -> int:
    """Chain rows for one uploaded file.

    Counted by ``file_id`` rather than by project on purpose. The injection
    below works by changing the row's ``project_id``, so a query narrowed to
    the real project would come back empty whether the row landed or not, and
    "nothing was left behind" would prove nothing at all.
    """
    return await session.scalar(select(func.count()).select_from(FileVersion).where(FileVersion.file_id == file_id))


def _break_the_version_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the chain row, and only that row, one the database rejects.

    Same lever as the cross-link injection above, one table across:
    ``FileVersion.project_id`` carries a foreign key, so pointing it at a
    project nothing created makes the flush fail the way a real database
    fails, aborting the transaction server-side rather than only upsetting the
    ORM. The name is replaced on the module that builds the row, because the
    upload path imports the service lazily and never holds this name itself.
    """

    def _version_for_a_project_that_does_not_exist(**fields: object) -> FileVersion:
        return FileVersion(**{**fields, "project_id": uuid.uuid4()})

    monkeypatch.setattr(file_versions_service, "FileVersion", _version_for_a_project_that_does_not_exist)


async def test_an_uploaded_photo_gets_a_version_chain_row(session: AsyncSession) -> None:
    """Control for the two tests below, and it has to come first.

    "No chain row was left behind" would pass just as happily on a build where
    the registration never wrote one to begin with. This is what makes the
    absence in the next test mean something.
    """
    photo = await PhotoService(session).upload_photo(
        project_id=PROJECT_ID,
        file=_upload("photo-with-a-version-chain.png"),
        category="site",
        user_id=str(OWNER_ID),
    )
    await session.commit()

    assert await _versions_for(session, str(photo.id)) == 1, "the upload registered no version-chain row"


async def test_a_failed_version_registration_does_not_disarm_the_cross_link(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordering test, and the reason the guard exists in two places now.

    The registration runs first and is allowed to fail. What must survive it is
    everything after it: the cross-link opens a savepoint of its own a few
    lines later, and a session poisoned by the earlier flush cannot open one.
    So this asserts the cross-link row is there, which is the assertion that
    goes red when the savepoint above it is taken away - not a vaguer claim
    that no exception escaped, which stays true either way.
    """
    _break_the_version_chain(monkeypatch)

    photo = await PhotoService(session).upload_photo(
        project_id=PROJECT_ID,
        file=_upload("photo-whose-version-row-fails.png"),
        category="site",
        user_id=str(OWNER_ID),
    )

    assert await _documents_at(session, photo.file_path) == 1, (
        "the cross-link was disarmed by the failed version registration above it"
    )
    assert await _versions_for(session, str(photo.id)) == 0, "a rejected chain row was left behind"

    await session.commit()

    committed = await session.scalar(select(ProjectPhoto).where(ProjectPhoto.id == photo.id))
    assert committed is not None, "the photo was lost to a failure in bookkeeping"


async def test_registering_a_version_never_poisons_its_callers_session(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The savepoint inside ``register_new_version``, on its own.

    The upload path now has one of its own too, so the end-to-end test above
    cannot say which of the two carried the property. This calls the service
    directly, the way the upload paths that are not photos do: the failure is
    still raised at the caller, and the session the caller was handed still
    works afterwards.
    """
    _break_the_version_chain(monkeypatch)

    payload = FileVersionCreate(
        project_id=PROJECT_ID,
        file_kind="photo",
        file_id=str(uuid.uuid4()),
        canonical_name="elevation.png",
        file_size=1,
    )

    with pytest.raises(SQLAlchemyError):
        await FileVersionService(session).register_new_version(payload, uploaded_by_id=None)

    # Nothing about this is exotic: it is the first statement a caller would
    # run after catching that error, and on a poisoned session it raises
    # PendingRollbackError instead of answering.
    assert await session.scalar(select(func.count()).select_from(Project).where(Project.id == PROJECT_ID)) == 1
    await session.commit()


def _break_the_version_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take the chain table away, which is the failure the code names itself.

    ``_register_version_safely`` says in as many words that it is there for the
    case where ``oe_file_version`` is missing on a misconfigured install. The
    first statement to fail in that case is the chain lookup, and that runs
    BEFORE the savepoint inside ``register_new_version`` opens - so this is the
    failure only the caller's own savepoint can contain, and the one that tells
    the two guards apart.
    """

    class _RepositoryWithoutItsTable(file_versions_service.FileVersionRepository):
        async def get_current(self, **_kwargs: object) -> None:
            await self.session.execute(text("SELECT 1 FROM oe_file_version_that_is_not_installed"))

    monkeypatch.setattr(file_versions_service, "FileVersionRepository", _RepositoryWithoutItsTable)


async def test_a_missing_version_table_does_not_take_the_upload_down(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller's savepoint, on its own.

    An install whose chain table never got created should lose its version
    history and nothing else. Before the guard, the failed lookup poisoned the
    session, the cross-link two lines down could not open its savepoint, and
    the upload the operator was actually doing died on a table they had never
    heard of.
    """
    _break_the_version_table(monkeypatch)

    photo = await PhotoService(session).upload_photo(
        project_id=PROJECT_ID,
        file=_upload("photo-on-an-install-with-no-chain-table.png"),
        category="site",
        user_id=str(OWNER_ID),
    )

    assert await _documents_at(session, photo.file_path) == 1, (
        "a missing version table took the documents cross-link down with it"
    )

    await session.commit()

    committed = await session.scalar(select(ProjectPhoto).where(ProjectPhoto.id == photo.id))
    assert committed is not None, "a missing version table cost the operator the photo"


def _break_the_revision_fanout(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Make the subscription fan-out fail the way a database fails.

    The hook is the last write inside ``register_new_version`` and it runs
    under a bare ``except`` whose comment promises that a notification failure
    "must never roll back a successful version write". A failed flush breaks
    exactly that promise, because the version row goes down with the poisoned
    session at the next commit.

    The stub records that it ran. A re-upload that never reached the fan-out
    would otherwise make this test pass while proving nothing.
    """
    reached = {"hook": False}

    async def _a_notification_the_database_rejects(session: AsyncSession, **_kwargs: object) -> None:
        reached["hook"] = True
        session.add(
            Document(
                project_id=uuid.uuid4(),
                name="a notification nobody can store",
                description="",
                category="notification",
                file_size=0,
                mime_type="text/plain",
                file_path="notifications/rejected",
                version=1,
                uploaded_by="",
                tags=[],
                metadata_={},
            )
        )
        await session.flush()

    monkeypatch.setattr(file_distribution_service, "on_file_new_revision", _a_notification_the_database_rejects)
    return reached


async def test_a_failed_revision_notification_does_not_roll_back_the_version(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fan-out savepoint, which is the one that could disarm the other two.

    A re-upload registers version 2, then tells whoever subscribed to the file.
    The telling is allowed to fail. What must survive it is the version row it
    was announcing, the cross-link after it, and the photo itself - none of
    which survive a session the notification poisoned on its way out.
    """
    reached = _break_the_revision_fanout(monkeypatch)

    await PhotoService(session).upload_photo(
        project_id=PROJECT_ID,
        file=_upload("north-elevation.png"),
        category="site",
        user_id=str(OWNER_ID),
    )
    second = await PhotoService(session).upload_photo(
        project_id=PROJECT_ID,
        file=_upload("north-elevation.png"),
        category="site",
        user_id=str(OWNER_ID),
    )

    assert reached["hook"], "the re-upload never reached the fan-out, so this test proves nothing"

    assert await _versions_for(session, str(second.id)) == 1, (
        "a failed notification rolled back the version write it was announcing"
    )
    assert await _documents_at(session, second.file_path) == 1, "the cross-link after the fan-out was disarmed"

    await session.commit()

    committed = await session.scalar(select(ProjectPhoto).where(ProjectPhoto.id == second.id))
    assert committed is not None, "a failed notification cost the operator the photo"
