# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The generated sheets PDF has to reach the documents hub. It never once did.

``_generate_pdf_in_background`` runs the DDC PDF-only export for a model that
is already converted and then writes a ``Document`` row so the sheets turn up
in the documents hub next to everything else on the project. The row was built
with a ``created_by`` keyword. ``Document`` has no such column - ``Base``
carries id, created_at and updated_at and nothing else - so SQLAlchemy's
declarative constructor answered with ``TypeError`` and the INSERT was never
attempted. Not refused: never attempted. The surrounding ``except Exception``
logged "PDF sheets -> Document linkage failed", which reads like the database
declining a row, so every install with a converter reported a database hiccup
on every export and nobody had a reason to look at the constructor.

That makes this a different animal from a write that fails under a condition.
It is a feature that has never existed on any install since the code was
written, described in the logs as an intermittent storage problem.

This test exercises the worker. It does not assert what keywords the call site
passes - a test that reads the call site would have agreed with the defect for
its whole life, because the call site was self-consistent and simply named the
wrong model's field. The row has to arrive in PostgreSQL or this test fails.

What is stubbed and why it is not the mocked-flush trap
------------------------------------------------------
Two things stand in for the outside world: ``find_converter`` and
``subprocess.run``. Both are the DDC converter binary, which is not installed
on a test machine and is not what is under test - the module deliberately does
not test DDC conversion anywhere. Everything from that point on is real: the
real ``save_geometry`` writes a real file through the real storage backend, the
real ``Document`` is constructed by the real declarative constructor, and the
real INSERT is committed to a real PostgreSQL through a session the worker
opens for itself.

Nothing about the database is simulated, which matters here more than usual.
See the trap named at the top of ``test_cad_upload_cross_link.py``: a mocked
``flush`` that merely raises does not set the session's rollback-only flag, so
a test built on one passes before and after the fix it claims to guard. The
line between a stub and a lie is whether the thing you are measuring is on the
real side of it. Here the write is.

The project is committed rather than created in a test transaction, because the
worker opens ``async_session_factory`` instead of taking the request's session
and cannot see a row nobody has committed. Without that the INSERT fails on the
foreign key, which is a failure, but not the one being measured.
"""

from __future__ import annotations

import logging
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core import storage as core_storage
from app.core.storage import LocalStorageBackend
from app.database import async_session_factory
from app.modules.bim_hub import file_storage as bim_file_storage
from app.modules.bim_hub.router import _generate_pdf_in_background
from app.modules.boq import cad_import
from app.modules.documents.models import Document
from app.modules.projects.models import Project
from app.modules.users.models import User

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Whatever the converter is handed, it is never read: the stub writes the PDF.
MINIMAL_CAD = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"

# The worker discards anything under 1000 bytes as a failed export, so the
# stand-in PDF has to clear that floor to reach the cross-link at all.
MINIMAL_PDF = b"%PDF-1.4\n" + (b"% padding so the export clears the size floor\n" * 40) + b"%%EOF\n"


@pytest_asyncio.fixture(autouse=True)
async def _schema_on_the_app_engine() -> None:
    """Give the worker's own database a schema.

    ``tests/_pg`` hands each test a throwaway database cloned from a template
    and binds the fixture session to it. The worker does not use that session -
    it opens ``async_session_factory``, which is bound to the application
    engine and the database ``DATABASE_URL`` names, and that one is never
    schema-loaded by the module lane. Without this the INSERT fails on
    ``relation "oe_users_user" does not exist``, which is a real failure of a
    real database and tells you nothing about the cross-link. Idempotent, and
    the same thing ``tests/modules/users/test_tour_state.py`` does for the same
    reason.
    """
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest_asyncio.fixture
async def committed_project() -> AsyncIterator[tuple[uuid.UUID, uuid.UUID]]:
    """An owner and project the worker's own session can see, then removed.

    Committed on purpose, and therefore cleaned up on purpose: this lands in a
    cluster other tests are using, and a leaked project would come back as
    somebody else's flake rather than as a failure here. Deleting the project
    takes the cross-linked document with it through the FK's ON DELETE CASCADE,
    which the teardown then verifies rather than assumes.
    """
    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    async with async_session_factory() as session:
        session.add(
            User(
                id=owner_id,
                email=f"owner-{owner_id}@sheets-crosslink.io",
                hashed_password="x",
                full_name="Owner",
                role="admin",
            )
        )
        await session.flush()
        session.add(Project(id=project_id, name="Sheets cross-link", owner_id=owner_id, currency="EUR"))
        await session.commit()

    yield owner_id, project_id

    async with async_session_factory() as session:
        project = await session.get(Project, project_id)
        if project is not None:
            await session.delete(project)
        owner = await session.get(User, owner_id)
        if owner is not None:
            await session.delete(owner)
        await session.commit()

    async with async_session_factory() as session:
        left = await session.scalar(select(func.count()).select_from(Document).where(Document.project_id == project_id))
    assert left == 0, f"{left} document row(s) outlived the project and are now loose in the cluster"


@pytest.fixture
def converter_and_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalStorageBackend:
    """Stand in for the DDC binary; keep every write real and inside tmp_path.

    ``find_converter`` and ``subprocess.run`` are the converter. Patching them
    is what lets a machine with no DDC install reach the cross-link, which is
    the whole reason this defect survived: the block is unreachable without a
    converter, so no test on a clean machine ever ran the constructor.
    """
    backend = LocalStorageBackend(tmp_path)
    monkeypatch.setattr(bim_file_storage, "_backend", lambda: backend)
    monkeypatch.setattr(core_storage, "get_storage_backend", lambda: backend)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: tmp_path / "ddc-converter")

    def _write_the_pdf_instead_of_converting(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        # The worker invokes the converter as ``<binary> <input> <output>``.
        Path(cmd[2]).write_bytes(MINIMAL_PDF)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _write_the_pdf_instead_of_converting)
    return backend


async def _run_the_worker(
    backend: LocalStorageBackend,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    *,
    model_name: str = "Tower A",
) -> uuid.UUID:
    """Put a CAD blob where the worker looks for it and run the worker."""
    model_id = uuid.uuid4()
    cad_key = f"bim/{project_id}/{model_id}/original.ifc"
    await backend.put(cad_key, MINIMAL_CAD)

    await _generate_pdf_in_background(
        project_id=str(project_id),
        model_id=str(model_id),
        cad_storage_key=cad_key,
        ext=".ifc",
        model_name=model_name,
        user_id=str(owner_id),
    )
    return model_id


async def test_the_generated_sheets_pdf_arrives_in_the_documents_hub(
    committed_project: tuple[uuid.UUID, uuid.UUID],
    converter_and_storage: LocalStorageBackend,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The row lands. Before the fix nothing did, on any install, ever."""
    owner_id, project_id = committed_project

    with caplog.at_level("WARNING", logger="app.modules.bim_hub.router"):
        await _run_the_worker(converter_and_storage, project_id, owner_id)

    async with async_session_factory() as session:
        doc = await session.scalar(select(Document).where(Document.project_id == project_id))

    # The worker swallows everything, so a bare "is not None" would report the
    # absence and hide the reason. Hand over what it wrote down instead.
    complaints = "\n".join(r.getMessage() for r in caplog.records)
    assert doc is not None, f"the sheets PDF never reached the documents hub. Worker log:\n{complaints}"

    assert doc.name == "Tower A - Sheets (PDF)"
    assert doc.category == "drawing"
    assert doc.mime_type == "application/pdf"
    assert doc.uploaded_by == str(owner_id)
    assert doc.file_path.endswith(".pdf")
    assert doc.file_size == len(MINIMAL_PDF)
    assert "bim" in doc.tags and "sheets" in doc.tags


async def test_a_successful_export_does_not_report_a_linkage_failure(
    committed_project: tuple[uuid.UUID, uuid.UUID],
    converter_and_storage: LocalStorageBackend,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The symptom, asserted directly, because the symptom is what was seen.

    The defect's whole visible surface was a log line on every single export,
    blaming the documents linkage for something the documents linkage had not
    done. So a healthy export has to be a quiet one, and quiet is asserted by
    level rather than by wording.

    Matching on wording is what this test did first, and the pre-fix run caught
    it out: it grepped for "cross-link" while the message it needed to catch
    said "linkage failed". It passed against the defect. A symptom test that
    names the string the fixed code happens to use is testing the fix's
    vocabulary, and the defect gets to keep its own.
    """
    owner_id, project_id = committed_project

    with caplog.at_level("INFO", logger="app.modules.bim_hub.router"):
        await _run_the_worker(converter_and_storage, project_id, owner_id)

    complained = [f"{r.levelname} {r.getMessage()}" for r in caplog.records if r.levelno >= logging.WARNING]
    assert not complained, f"the export worked and still complained: {complained}"


async def test_a_row_postgres_refuses_is_logged_as_the_worker_s_own_failure(
    committed_project: tuple[uuid.UUID, uuid.UUID],
    converter_and_storage: LocalStorageBackend,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The other half: when the database really does decline, say which model.

    Reached without injecting anything. ``Document.name`` is ``String(255)`` and
    the worker builds it from the model's name, so a long enough model name is
    a row PostgreSQL genuinely refuses. The worker must absorb it - it runs
    detached from any request and has nobody to raise at - and must leave behind
    both ids, because a model whose sheets are missing from the hub is only
    recoverable if somebody can find out which one it was.
    """
    owner_id, project_id = committed_project
    long_name = "T" * 300
    assert len(f"{long_name} - Sheets (PDF)") > 255, "the name has to overflow Document.name or this proves nothing"

    with caplog.at_level("ERROR", logger="app.modules.bim_hub.router"):
        model_id = await _run_the_worker(converter_and_storage, project_id, owner_id, model_name=long_name)

    async with async_session_factory() as session:
        left = await session.scalar(select(func.count()).select_from(Document).where(Document.project_id == project_id))
    assert left == 0, "a row the database refused ended up in the hub anyway"

    complaints = [r for r in caplog.records if "cross-link" in r.getMessage().lower()]
    assert complaints, "the cross-link failed for real and nothing was written down"
    reported = complaints[-1]
    assert str(model_id) in reported.getMessage()
    assert str(project_id) in reported.getMessage()
    # ``logger.exception``, not ``logger.warning``: the traceback is the part
    # that would have made the original defect findable in a single reading.
    assert reported.exc_info is not None, "the failure was logged without the traceback that names the failing line"
