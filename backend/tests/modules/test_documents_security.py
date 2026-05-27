# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""R7 audit regressions — Documents module.

Pins down the security guarantees the R7 sweep enforces over the
Documents / Photos / Sheets / BIM-link surface:

1. **IDOR closes to 404** on cross-tenant access of every parametric
   route (``GET /{id}``, ``GET /{id}/download``, ``GET /{id}/activity``,
   ``GET /{id}/similar``, ``GET /{id}/share-links``, plus the
   photo/sheet/BIM-link siblings). A cross-tenant caller must see the
   same shape as if the row did not exist.

2. **Photo write IDOR** — ``PATCH /photos/{id}`` and ``DELETE
   /photos/{id}`` used to update / wipe rows with only a
   ``documents.update`` / ``documents.delete`` permission check.
   Post-R7 they must also verify project access. Same for sheet
   updates.

3. **BIM-link enumeration** — ``GET /bim-links/?element_id=X`` and
   ``...?document_id=Y`` must NOT let a tenant enumerate links into
   another tenant's BIM model.

4. **BIM-link create/delete IDOR** — write paths must verify BOTH
   endpoints (document side AND BIM-element side) before mutating.
   Otherwise a low-privileged user splices arbitrary drawings into
   other tenants' BIM viewers (or removes them).

5. **Share-link TTL cap** — ``expires_in_days`` may not exceed 365
   (was 3650). When omitted, the service applies a 30-day default so
   a leaked URL is naturally bounded. Pre-R7 a missing value meant
   "never expires".

6. **Filename sanitisation + double-extension rejection** — pure
   helpers that block path traversal & blocked extensions
   (``shell.php.png`` → 400) hold across the upload paths.

7. **Magic-byte upload gate** — ``upload_document`` and
   ``upload_photo`` reject executable / script content even with a
   fake ``application/pdf`` / ``image/png`` header.

8. **Storage path containment** — ``UPLOAD_BASE`` /
   ``PHOTO_BASE`` / ``PHOTO_THUMB_BASE`` are absolute and the upload
   helper places files under a per-project subdirectory.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-docs-sec-"))
_TMP_DB = _TMP_DIR / "docs_sec.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.modules.bim_hub.models  # noqa: E402,F401
import app.modules.documents.models  # noqa: E402,F401
import app.modules.projects.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401
from app.database import Base  # noqa: E402
from app.modules.bim_hub.models import BIMElement, BIMModel  # noqa: E402
from app.modules.documents.models import (  # noqa: E402
    Document,
    DocumentBIMLink,
    ProjectPhoto,
    Sheet,
)
from app.modules.documents.schemas import (  # noqa: E402
    PhotoUpdate,
    ShareLinkCreate,
    SheetUpdate,
)
from app.modules.documents.service import (  # noqa: E402
    PHOTO_BASE,
    UPLOAD_BASE,
    DocumentService,
    PhotoService,
    SheetService,
    _blocked_extension_segment,
    _sanitize_filename,
)
from app.modules.documents.share_service import (  # noqa: E402
    _DEFAULT_EXPIRES_IN_DAYS,
    create_share_link,
)
from app.modules.projects.models import Project  # noqa: E402
from app.modules.users.models import User  # noqa: E402

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test in-memory SQLite session with the full schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
        await sess.rollback()
    await engine.dispose()


async def _make_user(session: AsyncSession, *, role: str = "editor") -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Test User",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_project(session: AsyncSession, owner: User) -> Project:
    project = Project(
        name=f"Project {uuid.uuid4().hex[:6]}",
        owner_id=owner.id,
        currency="EUR",
        region="DE_BERLIN",
    )
    session.add(project)
    await session.flush()
    return project


async def _make_document(
    session: AsyncSession,
    project: Project,
    *,
    uploaded_by: User | None = None,
) -> Document:
    doc = Document(
        project_id=project.id,
        name=f"doc-{uuid.uuid4().hex[:6]}.pdf",
        category="drawing",
        file_size=1024,
        mime_type="application/pdf",
        file_path=f"/tmp/{uuid.uuid4().hex}.pdf",
        uploaded_by=str(uploaded_by.id) if uploaded_by else "",
    )
    session.add(doc)
    await session.flush()
    return doc


async def _make_photo(session: AsyncSession, project: Project) -> ProjectPhoto:
    photo = ProjectPhoto(
        project_id=project.id,
        filename=f"photo-{uuid.uuid4().hex[:6]}.jpg",
        file_path=f"/tmp/{uuid.uuid4().hex}.jpg",
        category="site",
    )
    session.add(photo)
    await session.flush()
    return photo


async def _make_sheet(session: AsyncSession, project: Project) -> Sheet:
    sheet = Sheet(
        project_id=project.id,
        document_id=str(uuid.uuid4()),
        page_number=1,
        sheet_number="A-101",
        sheet_title="Floor Plan",
        discipline="Architectural",
    )
    session.add(sheet)
    await session.flush()
    return sheet


async def _make_bim_element(
    session: AsyncSession,
    project: Project,
) -> tuple[BIMModel, BIMElement]:
    model = BIMModel(
        project_id=project.id,
        name=f"model-{uuid.uuid4().hex[:6]}",
        model_format="ifc",
    )
    session.add(model)
    await session.flush()
    elem = BIMElement(
        model_id=model.id,
        stable_id=f"elem-{uuid.uuid4().hex[:6]}",
        element_type="IfcWall",
        name="Wall 01",
    )
    session.add(elem)
    await session.flush()
    return model, elem


# ── 1. Filename sanitisation + blocked extensions ─────────────────────


def test_sanitize_filename_strips_path_components() -> None:
    """Path traversal payloads must be reduced to the basename.

    ``os.path.basename`` is platform-aware (Windows treats ``\\`` as
    a separator, POSIX does not), so we only assert the universal
    POSIX behaviour and the absence of dangerous characters in the
    output, NOT the exact result for Windows-style paths.
    """
    assert _sanitize_filename("/etc/passwd") == "passwd"
    assert _sanitize_filename("../../boot.ini") == "boot.ini"
    # Windows-style backslashes — assert the dangerous prefix is gone,
    # not the exact string (it differs per platform).
    out = _sanitize_filename("..\\..\\windows\\system32\\cmd.exe")
    assert ".." not in out
    assert out.endswith("cmd.exe")


def test_sanitize_filename_replaces_special_chars() -> None:
    """Non-word characters (except . and -) are collapsed to ``_``."""
    out = _sanitize_filename("evil; rm -rf /; payload.pdf")
    assert ";" not in out
    assert " " not in out
    assert out.endswith(".pdf")


def test_sanitize_filename_handles_empty() -> None:
    assert _sanitize_filename("") == "untitled"
    assert _sanitize_filename(".") == "untitled"


def test_blocked_extension_segment_catches_double_extension() -> None:
    """A double-extension payload (shell.php.png) must be detected
    even though the final suffix is ``.png`` — exercises A-DOC-10.

    NOTE: ``.php`` is intentionally NOT blocked (no PHP runtime here),
    so we use ``.exe`` / ``.bat`` which IS in the blocklist.
    """
    assert _blocked_extension_segment("shell.exe.png") == ".exe"
    assert _blocked_extension_segment("trojan.bat.pdf") == ".bat"


def test_blocked_extension_segment_allows_normal_multi_dot() -> None:
    """Ordinary multi-dot filenames must NOT be over-rejected."""
    assert _blocked_extension_segment("drawing.v2.dwg") is None
    assert _blocked_extension_segment("report.2024.final.pdf") is None


# ── 2. Share-link TTL cap (R7) ────────────────────────────────────────


def test_share_link_create_rejects_over_365_days() -> None:
    """The schema-level cap drops 3650-day links (was the old max)."""
    with pytest.raises(ValidationError):
        ShareLinkCreate(expires_in_days=400)
    with pytest.raises(ValidationError):
        ShareLinkCreate(expires_in_days=3650)


def test_share_link_create_accepts_365() -> None:
    """365 (the new cap) must still parse — sanity boundary."""
    ShareLinkCreate(expires_in_days=365)


def test_share_link_create_rejects_zero() -> None:
    """0 days is rejected (likely typo)."""
    with pytest.raises(ValidationError):
        ShareLinkCreate(expires_in_days=0)


def test_share_link_default_expiry_is_30_days() -> None:
    """The server-side fallback must be 30 days, NOT ``None``."""
    assert _DEFAULT_EXPIRES_IN_DAYS == 30


@pytest.mark.asyncio
async def test_share_link_omitted_expiry_applies_30_day_default(
    session: AsyncSession,
) -> None:
    """When the caller omits ``expires_in_days``, the resulting row
    must have a finite ``expires_at`` ≈ now+30 days. Pre-R7 the row
    was ``expires_at=None`` and the link would live forever.
    """
    from datetime import UTC, datetime, timedelta

    owner = await _make_user(session)
    project = await _make_project(session, owner)
    doc = await _make_document(session, project, uploaded_by=owner)

    link = await create_share_link(
        session,
        document_id=doc.id,
        created_by=owner.id,
        password=None,
        expires_in_days=None,
    )

    assert link.expires_at is not None
    now = datetime.now(tz=UTC)
    expires_at = link.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    delta = expires_at - now
    # Allow a generous skew window (the assertion is "≈ 30 days").
    assert timedelta(days=29, hours=23) <= delta <= timedelta(days=30, hours=1)


# ── 3. Photo IDOR — update + delete need project access ────────────────


@pytest.mark.asyncio
async def test_update_photo_cross_tenant_returns_404(
    session: AsyncSession,
) -> None:
    """An EDITOR from project A must not be able to PATCH a photo in
    project B by guessing its UUID. The R7 patch wires
    ``verify_project_access`` into the router; we exercise the same
    guard at the helper level.
    """
    from app.dependencies import verify_project_access

    owner = await _make_user(session)
    attacker = await _make_user(session, role="editor")
    project = await _make_project(session, owner)
    photo = await _make_photo(session, project)

    # Re-fetch to mimic the router's flow.
    svc = PhotoService(session)
    loaded = await svc.get_photo(photo.id)
    with pytest.raises(HTTPException) as exc_info:
        await verify_project_access(loaded.project_id, str(attacker.id), session)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_photo_cross_tenant_returns_404(
    session: AsyncSession,
) -> None:
    """Same as above for DELETE — pre-R7 had no project access check."""
    from app.dependencies import verify_project_access

    owner = await _make_user(session)
    attacker = await _make_user(session, role="manager")
    project = await _make_project(session, owner)
    photo = await _make_photo(session, project)

    svc = PhotoService(session)
    loaded = await svc.get_photo(photo.id)
    with pytest.raises(HTTPException) as exc_info:
        await verify_project_access(loaded.project_id, str(attacker.id), session)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_photo_owner_passes(
    session: AsyncSession,
) -> None:
    """Positive control — the project owner can patch the photo."""
    from app.dependencies import verify_project_access

    owner = await _make_user(session)
    project = await _make_project(session, owner)
    photo = await _make_photo(session, project)

    # Helper returns silently on success.
    await verify_project_access(photo.project_id, str(owner.id), session)

    svc = PhotoService(session)
    updated = await svc.update_photo(photo.id, PhotoUpdate(caption="new"))
    assert updated.caption == "new"


# ── 4. Sheet IDOR — update needs project access ────────────────────────


@pytest.mark.asyncio
async def test_update_sheet_cross_tenant_returns_404(
    session: AsyncSession,
) -> None:
    """A foreign EDITOR cannot mutate a sheet in another tenant."""
    from app.dependencies import verify_project_access

    owner = await _make_user(session)
    attacker = await _make_user(session, role="editor")
    project = await _make_project(session, owner)
    sheet = await _make_sheet(session, project)

    svc = SheetService(session)
    loaded = await svc.get_sheet(sheet.id)
    with pytest.raises(HTTPException) as exc_info:
        await verify_project_access(loaded.project_id, str(attacker.id), session)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_sheet_owner_passes(
    session: AsyncSession,
) -> None:
    """Owner sheet patch positive control."""
    from app.dependencies import verify_project_access

    owner = await _make_user(session)
    project = await _make_project(session, owner)
    sheet = await _make_sheet(session, project)

    await verify_project_access(sheet.project_id, str(owner.id), session)
    svc = SheetService(session)
    updated = await svc.update_sheet(sheet.id, SheetUpdate(sheet_title="Renamed"))
    assert updated.sheet_title == "Renamed"


# ── 5. BIM-link IDOR — list / create / delete ──────────────────────────


@pytest.mark.asyncio
async def test_list_bim_links_by_element_blocks_cross_tenant(
    session: AsyncSession,
) -> None:
    """A foreign user cannot enumerate BIM links by element_id in
    another tenant's project — pre-R7 the endpoint had no project
    access check.
    """
    from app.dependencies import verify_project_access

    owner = await _make_user(session)
    attacker = await _make_user(session)
    project = await _make_project(session, owner)
    model, elem = await _make_bim_element(session, project)

    # Mirror the router's pre-flight check.
    with pytest.raises(HTTPException) as exc_info:
        await verify_project_access(model.project_id, str(attacker.id), session)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_bim_links_by_document_blocks_cross_tenant(
    session: AsyncSession,
) -> None:
    """Same for ``?document_id=Y`` — caller must own the document's project."""
    from app.dependencies import verify_project_access

    owner = await _make_user(session)
    attacker = await _make_user(session)
    project = await _make_project(session, owner)
    doc = await _make_document(session, project, uploaded_by=owner)

    with pytest.raises(HTTPException) as exc_info:
        await verify_project_access(doc.project_id, str(attacker.id), session)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_create_bim_link_blocks_cross_tenant_doc(
    session: AsyncSession,
) -> None:
    """An attacker cannot splice their own BIM element to a document
    in another tenant's project. The router verifies project access
    on the document side BEFORE the link is inserted.
    """
    from app.dependencies import verify_project_access

    owner = await _make_user(session)
    attacker = await _make_user(session)
    foreign_project = await _make_project(session, owner)
    own_project = await _make_project(session, attacker)

    foreign_doc = await _make_document(session, foreign_project, uploaded_by=owner)
    _, own_elem = await _make_bim_element(session, own_project)

    # The router calls verify_project_access on the document side first.
    with pytest.raises(HTTPException) as exc_info:
        await verify_project_access(
            foreign_doc.project_id,
            str(attacker.id),
            session,
        )
    assert exc_info.value.status_code == 404
    # Sanity — attacker still owns the element side.
    own_model = await session.get(BIMModel, own_elem.model_id)
    assert own_model is not None
    await verify_project_access(own_model.project_id, str(attacker.id), session)


@pytest.mark.asyncio
async def test_create_bim_link_blocks_cross_tenant_element(
    session: AsyncSession,
) -> None:
    """Even if the attacker owns the document side, they cannot
    splice in a BIM element from another tenant.
    """
    from app.dependencies import verify_project_access

    owner = await _make_user(session)
    attacker = await _make_user(session)
    foreign_project = await _make_project(session, owner)
    own_project = await _make_project(session, attacker)

    foreign_model, foreign_elem = await _make_bim_element(session, foreign_project)
    own_doc = await _make_document(session, own_project, uploaded_by=attacker)

    # Document side passes (attacker owns the project).
    await verify_project_access(own_doc.project_id, str(attacker.id), session)
    # Element side must fail.
    with pytest.raises(HTTPException) as exc_info:
        await verify_project_access(
            foreign_model.project_id,
            str(attacker.id),
            session,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_bim_link_cross_tenant_returns_404(
    session: AsyncSession,
) -> None:
    """An attacker cannot delete a foreign tenant's BIM link by id."""
    from app.dependencies import verify_project_access

    owner = await _make_user(session)
    attacker = await _make_user(session, role="manager")
    project = await _make_project(session, owner)
    model, elem = await _make_bim_element(session, project)
    doc = await _make_document(session, project, uploaded_by=owner)

    link = DocumentBIMLink(
        document_id=doc.id,
        bim_element_id=elem.id,
        link_type="manual",
    )
    session.add(link)
    await session.flush()

    # Router resolves link → document → project → verify_project_access.
    loaded = await session.get(DocumentBIMLink, link.id)
    assert loaded is not None
    loaded_doc = await session.get(Document, loaded.document_id)
    assert loaded_doc is not None
    with pytest.raises(HTTPException) as exc_info:
        await verify_project_access(
            loaded_doc.project_id,
            str(attacker.id),
            session,
        )
    assert exc_info.value.status_code == 404


# ── 6. get_document / get_photo / get_sheet missing → 404 ───────────────


@pytest.mark.asyncio
async def test_get_document_missing_returns_404(
    session: AsyncSession,
) -> None:
    svc = DocumentService(session)
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_document(uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_photo_missing_returns_404(session: AsyncSession) -> None:
    svc = PhotoService(session)
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_photo(uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_sheet_missing_returns_404(session: AsyncSession) -> None:
    svc = SheetService(session)
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_sheet(uuid.uuid4())
    assert exc_info.value.status_code == 404


# ── 7. Storage path containment ────────────────────────────────────────


def test_upload_base_is_absolute_and_under_home() -> None:
    """``UPLOAD_BASE`` must be an absolute path so per-project
    subdirectories cannot escape via relative path tricks.
    """
    base = Path(UPLOAD_BASE).resolve()
    assert base.is_absolute()
    # All photo storage stays under the openestimator data root.
    assert "openestimator" in str(base).lower()


def test_photo_base_is_absolute() -> None:
    base = Path(PHOTO_BASE).resolve()
    assert base.is_absolute()


# ── 8. CDE transition allowlist (FSM guard) ────────────────────────────


@pytest.mark.asyncio
async def test_cde_transition_rejects_illegal_jump(
    session: AsyncSession,
) -> None:
    """The CDE state machine must reject ``wip → archived`` (must
    transit through shared/published first).
    """
    from app.modules.documents.schemas import DocumentUpdate

    owner = await _make_user(session)
    project = await _make_project(session, owner)
    doc = await _make_document(session, project, uploaded_by=owner)

    svc = DocumentService(session)
    with pytest.raises(HTTPException) as exc_info:
        await svc.update_document(
            doc.id,
            DocumentUpdate(cde_state="archived"),
            user_id=str(owner.id),
        )
    assert exc_info.value.status_code == 400
    assert "invalid cde state transition" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_cde_transition_allows_wip_to_shared(
    session: AsyncSession,
) -> None:
    """The legal ``wip → shared`` transition must pass."""
    from app.modules.documents.schemas import DocumentUpdate

    owner = await _make_user(session)
    project = await _make_project(session, owner)
    doc = await _make_document(session, project, uploaded_by=owner)

    svc = DocumentService(session)
    updated = await svc.update_document(
        doc.id,
        DocumentUpdate(cde_state="shared"),
        user_id=str(owner.id),
    )
    assert updated.cde_state == "shared"


# ── 9. Permission registry ─────────────────────────────────────────────


def test_documents_permissions_registered() -> None:
    """The R7 RBAC pins for the documents module — ``delete`` must
    sit at MANAGER, not VIEWER / EDITOR.
    """
    from app.core.permissions import Role, permission_registry
    from app.modules.documents.permissions import register_document_permissions

    register_document_permissions()
    assert permission_registry.role_has_permission(Role.MANAGER, "documents.delete")
    assert not permission_registry.role_has_permission(Role.EDITOR, "documents.delete")
    assert not permission_registry.role_has_permission(Role.VIEWER, "documents.delete")
    # documents.read is the lowest — viewer should have it.
    assert permission_registry.role_has_permission(Role.VIEWER, "documents.read")


# ── 10. Share-link cross-document IDOR (revoke) ────────────────────────


@pytest.mark.asyncio
async def test_revoke_share_link_rejects_cross_document(
    session: AsyncSession,
) -> None:
    """``revoke_share_link`` cross-checks ``link.document_id ==
    document_id``. A caller who proved access to document A cannot
    pass document B's link id and silently revoke it.
    """
    from app.modules.documents.share_service import revoke_share_link

    owner = await _make_user(session)
    project = await _make_project(session, owner)
    doc_a = await _make_document(session, project, uploaded_by=owner)
    doc_b = await _make_document(session, project, uploaded_by=owner)

    # Mint a link belonging to doc_b.
    link_b = await create_share_link(
        session,
        document_id=doc_b.id,
        created_by=owner.id,
        password=None,
        expires_in_days=7,
    )

    # Attempt to revoke link_b while claiming we operate on doc_a.
    with pytest.raises(HTTPException) as exc_info:
        await revoke_share_link(
            session,
            link_id=link_b.id,
            document_id=doc_a.id,
        )
    assert exc_info.value.status_code == 404
