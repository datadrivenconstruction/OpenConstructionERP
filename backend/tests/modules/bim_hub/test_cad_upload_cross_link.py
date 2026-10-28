# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A failed documents cross-link must not lose the uploaded CAD model.

READ THIS BEFORE WRITING ANY TRANSACTION-ISOLATION TEST IN THIS CODEBASE.

A mocked ``flush`` that merely raises does not set the session's rollback-only
flag. Only a real database failure does. So a test that patches ``flush`` to
raise, and then asserts the request still finishes, passes identically with and
without the SAVEPOINT it claims to guard - before the fix and after it. It is
not a weak test, it is a test of nothing, and it looks exactly like a strong one
because the code under test really does contain the isolation it is asserting.
The trap is not that mocks are imprecise. It is that this particular flag lives
in SQLAlchemy's session state and is set by the failure path a mock replaces.

The consequence is general. Any test here that asks "does the rest of the
request survive a failed write" has to make the write fail the way the database
fails, and the only proof that it does is running it against the code from
before the fix and watching it go red. If you have only ever seen it pass, you
do not yet know what it tests.

``POST /upload-cad/`` saves the model row, streams the file into storage, and
then writes a ``Document`` row so the file also appears in the documents hub.
That last step is convenience work. The model is already saved by the time it
runs, and the comment above it has always said a failure there is non-fatal.

Saying so takes more than an ``except``. A failed ``flush()`` marks the whole
session for rollback, and on PostgreSQL the transaction goes to aborted
server-side at the same moment. The endpoint then reaches
``await service.session.commit()`` twenty lines further down - the commit that
makes the model durable before the background converter goes looking for it -
and that raises ``PendingRollbackError`` instead. The upload dies describing a
transaction problem rather than a cross-link problem, the user gets a 500, and
the model they just uploaded is gone even though it was written and stored
successfully. This product has paid for that class of bug before, most visibly
when deadline notifications went dark because one bad row poisoned a session
that a caught exception could not revive.

The endpoint therefore runs the cross-link inside ``session.begin_nested()``,
and these tests are about that SAVEPOINT rather than about the ``except``. "No
exception escaped" cannot tell the two apart. What separates them is whether the
request can still finish, so that is what is asserted.

Remove the ``async with service.session.begin_nested():`` line from
``upload_cad_file`` and ``test_a_failed_cross_link_still_returns_the_model``
fails with ``PendingRollbackError`` raised from the endpoint's own commit.

The failure is injected by pointing the cross-link row at a project that does
not exist. ``Document.project_id`` carries a foreign key, so the flush fails the
way a database really fails, with an ``IntegrityError`` raised by PostgreSQL and
the transaction aborted server-side too. Nothing else about the upload changes;
the model row still names the real project.

The endpoint is called directly rather than over HTTP. It is an ordinary async
function whose auth and permission arguments are ``Depends`` defaults, so a
direct call exercises every line of the upload body - the access check, the
magic-byte gate, the storage write, the cross-link and the commit - without
standing up a client and a login for a code path no other test reaches.
``BackgroundTasks`` collects the conversion task and never runs it, which is
what we want: the DDC conversion is not what is under test here.
"""

from __future__ import annotations

import io
import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks, UploadFile
from sqlalchemy import func, select
from starlette.datastructures import Headers

from app.core.storage import LocalStorageBackend
from app.modules.bim_hub import file_storage as bim_file_storage
from app.modules.bim_hub.models import BIMModel
from app.modules.bim_hub.router import upload_cad_file
from app.modules.bim_hub.service import BIMHubService
from app.modules.documents import models as documents_models
from app.modules.documents.models import Document
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

OWNER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()

# A STEP file the magic-byte gate recognises: ``detect`` reads the first 64
# bytes and returns "ifc" for anything starting with ISO-10303-21. IFC is
# deliberately not in the needs-a-converter set, so the upload runs the whole
# body instead of short-circuiting to 202.
MINIMAL_IFC = b"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('minimal.ifc','2026-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
"""


def _upload(filename: str = "minimal.ifc") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(MINIMAL_IFC),
        filename=filename,
        headers=Headers({"content-type": "application/octet-stream"}),
    )


@pytest.fixture(autouse=True)
def cad_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stream the uploaded CAD file into the test's tmp dir, not the data dir."""
    backend = LocalStorageBackend(tmp_path)
    monkeypatch.setattr(bim_file_storage, "_backend", lambda: backend)
    return tmp_path


@pytest_asyncio.fixture
async def session():
    """One transactional session with a project the uploader may write to."""
    async with transactional_session() as s:
        s.add(
            User(
                id=OWNER_ID,
                email="owner@bim-crosslink.io",
                hashed_password="x",
                full_name="Owner",
                role="admin",
            )
        )
        await s.flush()
        s.add(Project(id=PROJECT_ID, name="BIM cross-link", owner_id=OWNER_ID, currency="EUR"))
        await s.flush()
        yield s


async def _upload_cad(session: AsyncSession, filename: str = "minimal.ifc", *, model_name: str = "") -> dict:
    """Run the endpoint body the way a request would, minus the transport.

    ``model_name`` is the ``name`` query parameter. Left empty the endpoint
    derives the model's name from the filename, which is what the upload form
    does; the overlong-filename test below sets it so the model row is not
    overflowing the same limit the cross-link is being measured against.
    """
    return await upload_cad_file(
        background_tasks=BackgroundTasks(),
        project_id=str(PROJECT_ID),
        name=model_name,
        discipline="architecture",
        conversion_depth="standard",
        file=_upload(filename),
        user_id=str(OWNER_ID),
        _perm=None,
        service=BIMHubService(session),
    )


def _break_the_cross_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the cross-link row, and only that row, one the database rejects.

    The endpoint imports ``Document`` from ``documents.models`` inside the block
    itself, so the name is replaced at its source with a factory that builds the
    same row against a project id nothing points at. The model row is untouched
    and still names the real project, so the only thing that can fail is the
    insert the SAVEPOINT exists to contain.
    """

    def _document_for_a_project_that_does_not_exist(**fields: object) -> Document:
        return Document(**{**fields, "project_id": uuid.uuid4()})

    monkeypatch.setattr(documents_models, "Document", _document_for_a_project_that_does_not_exist)


def _documents_for(model_id: str):
    """Cross-link rows for a model, found by a column the injection never touches.

    Deliberately not filtered by project: the injected failure works by changing
    the row's ``project_id``, so a query narrowed to the real project would come
    back empty whether the row landed or not, and the "nothing was written"
    assertion below would prove nothing. ``file_path`` is the storage key, which
    carries the model id.
    """
    return select(Document).where(Document.file_path.like(f"%{model_id}%"))


async def test_an_uploaded_cad_model_reaches_the_documents_hub(session: AsyncSession) -> None:
    """The cross-link lands: one Document row carrying the model back to it."""
    result = await _upload_cad(session)

    assert result["status"] == "processing"
    doc = await session.scalar(_documents_for(result["model_id"]))

    assert doc is not None, "the model never reached the documents hub"
    assert doc.project_id == PROJECT_ID
    assert doc.category == "drawing"
    assert doc.metadata_["source_id"] == result["model_id"]


async def test_a_failed_cross_link_still_returns_the_model(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The savepoint test. Without ``begin_nested`` the endpoint's own commit raises.

    The upload has to finish. It reaches ``service.session.commit()`` after the
    cross-link, and on a poisoned session that commit is where the request dies
    - taking with it a model row that was already written and a CAD file that
    was already stored.
    """
    _break_the_cross_link(monkeypatch)

    result = await _upload_cad(session, "cad-whose-crosslink-fails.ifc")

    assert result["status"] == "processing"

    # The model survived, which is the whole point: it was saved before the
    # convenience work ran and must not be undone by it.
    model = await session.get(BIMModel, uuid.UUID(result["model_id"]))
    assert model is not None, "the model was lost to a failure in convenience work"
    assert model.project_id == PROJECT_ID

    # The cross-link was rolled back to the savepoint, so the hub holds no
    # half-written row for a model it could not describe.
    orphans = await session.scalar(select(func.count()).select_from(_documents_for(result["model_id"]).subquery()))
    assert orphans == 0


async def test_an_overlong_filename_reaches_the_same_failure_with_nothing_injected(
    session: AsyncSession,
) -> None:
    """The same failure, arrived at by an ordinary upload instead of a patch.

    Every test above injects the cross-link failure. This one does not need to.
    ``Document.name`` is ``String(255)`` and takes the uploaded filename
    verbatim, while the model row takes the ``name`` parameter, so a file with a
    long enough name is a request PostgreSQL refuses on the cross-link and on
    nothing else. It matters because an injected failure only says what would
    happen if an insert ever failed. This says one can, from the outside, today,
    with no privileges and no unusual state - which is what makes the SAVEPOINT
    load-bearing rather than defensive.
    """
    filename = f"{'s' * 300}.ifc"
    assert len(filename) > 255, "the filename has to overflow Document.name or this proves nothing"

    result = await _upload_cad(session, filename, model_name="Long file name")

    assert result["status"] == "processing"
    model = await session.get(BIMModel, uuid.UUID(result["model_id"]))
    assert model is not None, "an overlong filename took the whole upload down with the cross-link"
    assert model.name == "Long file name"

    # Rolled back to the savepoint, so the hub holds nothing for it either.
    orphans = await session.scalar(select(func.count()).select_from(_documents_for(result["model_id"]).subquery()))
    assert orphans == 0


async def test_a_failed_cross_link_says_which_model_it_lost(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Swallowed is not silent: the log names the model and the project.

    A cross-link that fails leaves a model the documents hub cannot see. That is
    only recoverable if somebody can find out which one, so both ids belong in
    the record.
    """
    from app.modules.bim_hub import router as bim_router

    _break_the_cross_link(monkeypatch)

    with caplog.at_level("ERROR", logger=bim_router.logger.name):
        result = await _upload_cad(session, "cad-that-should-be-logged.ifc")

    complaints = [r for r in caplog.records if "cross-link" in r.getMessage().lower()]
    assert complaints, "the cross-link failed and nothing was written down"
    reported = complaints[-1].getMessage()
    assert result["model_id"] in reported
    assert str(PROJECT_ID) in reported


async def test_a_defect_in_the_cross_link_block_is_not_swallowed(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``except SQLAlchemyError``, not ``except Exception``.

    A TypeError here is a defect in the block, not the database declining, and
    widening back to a bare ``except`` is exactly how this stayed invisible for
    as long as it did. Nothing catches it, so the upload fails loudly and
    somebody goes and fixes the block.
    """

    def _document_built_wrong(**fields: object) -> Document:
        raise TypeError("Document() got an unexpected keyword argument")

    monkeypatch.setattr(documents_models, "Document", _document_built_wrong)

    with pytest.raises(TypeError):
        await _upload_cad(session, "cad-with-a-broken-crosslink.ifc")
