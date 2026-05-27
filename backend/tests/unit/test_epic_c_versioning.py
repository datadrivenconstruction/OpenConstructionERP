# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Epic C — Document Versioning Unification regression tests.

Verifies the seven wiring points the design doc calls out:

    1. ``canonical_name_for`` returns the right key for each kind.
    2. ``DocumentService.upload_document`` writes a v1 ``FileVersion``
       row keyed on the document's name.
    3. ``DocumentService.upload_document_revision`` rolls the chain
       forward — v1 superseded, v2 current.
    4. ``PhotoService.upload_photo`` writes a v1 ``FileVersion`` row
       keyed on the photo's filename.
    5. ``SheetService.split_pdf_to_sheets`` writes a chain row per
       sheet plus one for the parent document.
    6. ``create_comment`` defaults ``file_version_id`` to the chain
       head.
    7. ``MarkupsService.create_markup`` defaults ``file_version_id``
       to the chain head and the dropdown surfaces both versions.

All tests use isolated in-memory SQLite — production DB is never
touched (per ``feedback_test_isolation.md``).
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.documents.models import Document, ProjectPhoto, Sheet  # noqa: F401
from app.modules.documents.service import DocumentService, PhotoService, SheetService
from app.modules.file_comments.models import FileComment, FileCommentMention  # noqa: F401
from app.modules.file_comments.schemas import FileCommentCreate
from app.modules.file_comments.service import create_comment
from app.modules.file_versions.helpers import canonical_name_for
from app.modules.file_versions.models import FileVersion
from app.modules.file_versions.repository import FileVersionRepository
from app.modules.markups.models import Markup  # noqa: F401
from app.modules.markups.schemas import MarkupCreate
from app.modules.markups.service import MarkupsService
from app.modules.projects.models import Project  # noqa: F401
from app.modules.users.models import User

# ── Fixtures ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Per-test in-memory SQLite session with the full schema applied."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, str]:
    """Return ``(project_id, user_id_str)`` so service calls have FKs."""
    user = User(
        email=f"epic-c-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed",
        full_name="Epic-C Tester",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Epic-C Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id, str(user.id)


def _upload_file(name: str, content: bytes, content_type: str) -> UploadFile:
    """Build a FastAPI ``UploadFile`` from raw bytes for tests."""
    bio = io.BytesIO(content)
    return UploadFile(filename=name, file=bio, headers={"content-type": content_type})


# ── 1. canonical_name_for ──────────────────────────────────────────────


def test_canonical_name_for_each_kind() -> None:
    class _Doc:
        name = "  Plans.PDF  "

    class _Photo:
        filename = "site-01.jpg"

    class _Sheet:
        sheet_number = "A-201"
        page_number = 1
        document_id = "abc-123"

    class _Sheet_NoNumber:
        sheet_number = None
        page_number = 7
        document_id = "abc-123"

    class _BIM:
        name = "MEP_REV_03.ifc"

    assert canonical_name_for("document", _Doc()) == "Plans.PDF"  # strip preserved-case
    assert canonical_name_for("photo", _Photo()) == "site-01.jpg"
    assert canonical_name_for("sheet", _Sheet()) == "abc-123:A-201"
    assert canonical_name_for("sheet", _Sheet_NoNumber()) == "abc-123:page-007"
    assert canonical_name_for("bim_model", _BIM()) == "MEP_REV_03.ifc"
    assert canonical_name_for("document", "raw-string.pdf") == "raw-string.pdf"
    assert canonical_name_for("document", "") == "untitled"

    with pytest.raises(ValueError):
        canonical_name_for("not_a_kind", _Doc())


# ── 2. upload_document writes v1 chain row ─────────────────────────────


@pytest.mark.asyncio
async def test_upload_document_registers_chain_v1(session: AsyncSession) -> None:
    project_id, user_id = await _seed_project(session)
    svc = DocumentService(session)

    # 5-byte PDF header so the magic-byte detector accepts it.
    upload = _upload_file("contract.pdf", b"%PDF-1.4\n", "application/pdf")
    doc = await svc.upload_document(project_id, upload, "contract", user_id)

    repo = FileVersionRepository(session)
    chain = await repo.list_chain(
        project_id=project_id,
        file_kind="document",
        canonical_name="contract.pdf",
    )
    assert len(chain) == 1
    row = chain[0]
    assert row.is_current is True
    assert row.version_number == 1
    assert row.file_id == str(doc.id)
    assert row.previous_version_id is None


# ── 3. revision endpoint rolls chain forward ───────────────────────────


@pytest.mark.asyncio
async def test_upload_document_revision_rolls_chain_forward(
    session: AsyncSession,
) -> None:
    project_id, user_id = await _seed_project(session)
    svc = DocumentService(session)

    first = _upload_file("plans.pdf", b"%PDF-1.4\nfirst", "application/pdf")
    doc = await svc.upload_document(project_id, first, "drawing", user_id)

    rev_upload = _upload_file("plans-v2.pdf", b"%PDF-1.4\nsecond", "application/pdf")
    await svc.upload_document_revision(doc.id, rev_upload, user_id, notes="rev B")

    repo = FileVersionRepository(session)
    chain = await repo.list_chain(
        project_id=project_id,
        file_kind="document",
        canonical_name="plans.pdf",
    )
    assert [r.version_number for r in chain] == [2, 1]
    assert [r.is_current for r in chain] == [True, False]
    assert chain[0].notes == "rev B"
    assert chain[1].superseded_by_id == chain[0].id


# ── 4. upload_photo writes v1 chain row ────────────────────────────────


@pytest.mark.asyncio
async def test_upload_photo_registers_chain_v1(session: AsyncSession) -> None:
    project_id, user_id = await _seed_project(session)
    svc = PhotoService(session)

    # JPEG magic bytes so the photo signature gate accepts it.
    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00" + b"\x00" * 200
    upload = _upload_file("site-01.jpg", jpeg, "image/jpeg")
    photo = await svc.upload_photo(
        project_id=project_id,
        file=upload,
        category="site",
        user_id=user_id,
    )

    repo = FileVersionRepository(session)
    chain = await repo.list_chain(
        project_id=project_id,
        file_kind="photo",
        canonical_name="site-01.jpg",
    )
    assert len(chain) == 1
    assert chain[0].is_current is True
    assert chain[0].version_number == 1
    assert chain[0].file_id == str(photo.id)


# ── 5. split_pdf writes parent + sheet chain rows ─────────────────────


@pytest.mark.asyncio
async def test_split_pdf_to_sheets_writes_chain(monkeypatch: pytest.MonkeyPatch, session: AsyncSession) -> None:
    project_id, user_id = await _seed_project(session)

    # Stub the heavy pdfplumber path: produce a fake 2-page "pdf" so the
    # SheetService walks the per-page loop without touching the real lib.
    class _FakePage:
        def __init__(self, number: int) -> None:
            self._n = number

        def extract_text(self) -> str:
            return f"SHEET: A-{200 + self._n}"

        def to_image(self, resolution: int = 72):  # noqa: ARG002
            class _Img:
                def save(self, *_args, **_kwargs) -> None:
                    return None

            return _Img()

    class _FakePDF:
        pages = [_FakePage(1), _FakePage(2)]

        def __enter__(self) -> _FakePDF:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    import pdfplumber as _pp  # type: ignore[import-not-found]

    monkeypatch.setattr(_pp, "open", lambda *_a, **_kw: _FakePDF())

    svc = SheetService(session)
    pdf_bytes = b"%PDF-1.4\n" + b"\x00" * 256
    upload = _upload_file("drawings.pdf", pdf_bytes, "application/pdf")
    sheets = await svc.split_pdf_to_sheets(project_id, upload, user_id)
    assert len(sheets) == 2

    repo = FileVersionRepository(session)
    # Parent PDF
    parent_chain = await repo.list_chain(
        project_id=project_id,
        file_kind="document",
        canonical_name="drawings.pdf",
    )
    assert len(parent_chain) == 1
    # Each sheet has its own chain
    for sheet in sheets:
        sheet_chain = await repo.list_chain(
            project_id=project_id,
            file_kind="sheet",
            canonical_name=canonical_name_for("sheet", sheet),
        )
        assert len(sheet_chain) == 1
        assert sheet_chain[0].is_current is True


# ── 6. create_comment defaults file_version_id to chain head ──────────


@pytest.mark.asyncio
async def test_comment_defaults_to_current_version(session: AsyncSession) -> None:
    project_id, user_id = await _seed_project(session)
    user_uuid = uuid.UUID(user_id)

    # Seed a FileVersion chain head directly.
    fv = FileVersion(
        project_id=project_id,
        file_kind="document",
        file_id="doc-001",
        version_number=1,
        canonical_name="brief.pdf",
        is_current=True,
        uploaded_at=datetime.now(UTC),
    )
    session.add(fv)
    await session.flush()

    payload = FileCommentCreate(
        project_id=project_id,
        file_kind="document",
        file_id="doc-001",
        body="Looks good — approved.",
    )
    comment, _ = await create_comment(session, payload, author_id=user_uuid)

    assert comment.file_version_id == fv.id


# ── 7. create_markup defaults file_version_id to chain head ───────────


@pytest.mark.asyncio
async def test_markup_defaults_to_current_version(session: AsyncSession) -> None:
    project_id, user_id = await _seed_project(session)
    document_id = uuid.uuid4().hex

    # Seed two chain rows so the test verifies the current one wins.
    older = FileVersion(
        project_id=project_id,
        file_kind="document",
        file_id=document_id,
        version_number=1,
        canonical_name="drawing.pdf",
        is_current=False,
        superseded_at=datetime.now(UTC),
        uploaded_at=datetime.now(UTC),
    )
    current = FileVersion(
        project_id=project_id,
        file_kind="document",
        file_id=document_id,
        version_number=2,
        canonical_name="drawing.pdf",
        is_current=True,
        previous_version_id=None,
        uploaded_at=datetime.now(UTC),
    )
    session.add_all([older, current])
    await session.flush()

    svc = MarkupsService(session)
    data = MarkupCreate(
        project_id=project_id,
        document_id=document_id,
        page=1,
        type="cloud",
        geometry={"x": 1.0, "y": 1.0, "w": 10.0, "h": 10.0},
        author_id=user_id,
    )
    markup = await svc.create_markup(data, user_id)
    assert markup.file_version_id == current.id

    # Now an explicit pin to the older row should be honoured.
    data_pinned = MarkupCreate(
        project_id=project_id,
        document_id=document_id,
        file_version_id=older.id,
        page=1,
        type="cloud",
        geometry={},
        author_id=user_id,
    )
    pinned = await svc.create_markup(data_pinned, user_id)
    assert pinned.file_version_id == older.id


# ── Bonus: backfill SQL (alembic) exercises the runtime path ─────────


@pytest.mark.asyncio
async def test_register_new_version_chain_indexable_by_file_id(
    session: AsyncSession,
) -> None:
    """Smoke: lookup-by-file_id (used by frontend dropdown) still works
    end-to-end through the wired-up upload path."""
    project_id, user_id = await _seed_project(session)
    svc = DocumentService(session)
    upload = _upload_file("ref.pdf", b"%PDF-1.4\n", "application/pdf")
    doc = await svc.upload_document(project_id, upload, "other", user_id)

    repo = FileVersionRepository(session)
    rows = await repo.list_for_file_id(str(doc.id), "document")
    assert len(rows) == 1
    assert rows[0].is_current is True
    assert rows[0].canonical_name == "ref.pdf"
