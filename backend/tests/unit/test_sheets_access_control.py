# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project scoping of the drawing-sheet register, asserted at the route.

The register now has a screen of its own - an index, a detail drawer and an
insights band - and every number on it comes from one of the eight
``/api/v1/documents/sheets/`` endpoints. Each of those handlers calls
``verify_project_access`` in its own body rather than through a shared
dependency, so the guard is written once per route and a route can be added
without it. ``tests/modules/test_documents_security.py`` covers the rule by
calling ``verify_project_access`` itself, which is the router's logic re-typed
in the test: it cannot see whether any route wired the call. These tests drive
the real ASGI app, so a handler that forgets the guard fails here.

Two details are what make the assertions mean anything.

The attacker is a ``manager`` carrying every ``documents.*`` permission.
``RequirePermission`` runs before the handler body, so an attacker without
those permissions is turned away by RBAC with a 403 and never reaches the
project check - the refusal would look right and prove nothing about scoping.
With the permissions granted, the only thing left that can refuse is the
project guard, and every refusal is asserted as exactly 404, the shape
``verify_project_access`` raises for "missing" and "denied" alike.

Every refused URL is also requested by the project owner. A 404 from a mistyped
path is indistinguishable from a 404 from the guard, and the positive control is
what tells the two apart.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

#: Mounted by the module loader from the package directory name.
SHEETS_BASE = "/api/v1/documents/sheets"

#: Every permission the sheet routes gate on, granted to attacker and owner
#: alike so RBAC is never the reason a request below is refused.
DOCUMENT_PERMS = [
    "documents.read",
    "documents.create",
    "documents.update",
    "documents.delete",
]


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def sheets_app() -> AsyncIterator[Any]:
    """Boot the real application once for this module, schema included.

    The module routers are mounted by the module loader during startup, so the
    lifespan has to run before ``/api/v1/documents/sheets/`` resolves at all.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Session on the same database the application under test is bound to."""
    from app.database import async_session_factory

    async with async_session_factory() as session:
        yield session


# ── Helpers ───────────────────────────────────────────────────────────────


async def _seed_user(session: AsyncSession, *, role: str) -> uuid.UUID:
    """Insert an active user and return its id.

    The role is stored on the row as well as claimed in the token, because
    ``verify_project_access`` reads the persisted role for its admin bypass.
    """
    from app.modules.users.models import User

    user = User(
        email=f"sheets-acl-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Sheets ACL Tester",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user.id


async def _seed_project(session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID:
    """Insert a project owned by ``owner_id`` and return its id."""
    from app.modules.projects.models import Project

    project = Project(name=f"Sheets ACL {uuid.uuid4().hex[:6]}", owner_id=owner_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project.id


async def _seed_sheet(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID:
    """Insert one sheet in ``project_id`` and return its id."""
    from app.modules.documents.models import Sheet

    sheet = Sheet(
        project_id=project_id,
        document_id=str(uuid.uuid4()),
        page_number=1,
        sheet_number="A-101",
        sheet_title="Floor Plan Level 1",
        discipline="Architectural",
        is_current=True,
    )
    session.add(sheet)
    await session.commit()
    await session.refresh(sheet)
    return sheet.id


async def _seed_document(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID:
    """Insert one document in ``project_id`` and return its id."""
    from app.modules.documents.models import Document

    document = Document(
        project_id=project_id,
        name=f"index-{uuid.uuid4().hex[:6]}.pdf",
        category="drawing",
        file_size=1024,
        mime_type="application/pdf",
        file_path=f"/nonexistent/{uuid.uuid4().hex}.pdf",
        uploaded_by="",
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    return document.id


async def _seed_victim_and_attacker(
    session: AsyncSession,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Set up a foreign register and a legitimate user with no route to it.

    The attacker owns a project of their own, so they are an ordinary tenant
    rather than an unknown id, which is the case the guard actually has to
    refuse.

    Returns:
        ``(victim_project_id, victim_sheet_id, attacker_user_id)``.
    """
    victim_id = await _seed_user(session, role="manager")
    victim_project = await _seed_project(session, victim_id)
    victim_sheet = await _seed_sheet(session, victim_project)

    attacker_id = await _seed_user(session, role="manager")
    await _seed_project(session, attacker_id)
    return victim_project, victim_sheet, attacker_id


@asynccontextmanager
async def _as_user(app: Any, user_id: uuid.UUID) -> AsyncIterator[AsyncClient]:
    """Drive the app as ``user_id``, a manager holding every documents permission.

    Clears the dependency override on the way out so one test cannot leave the
    module-scoped app authenticated as somebody else.
    """
    from app.dependencies import get_current_user_payload

    async def _payload() -> dict[str, Any]:
        return {"sub": str(user_id), "role": "manager", "permissions": list(DOCUMENT_PERMS)}

    app.dependency_overrides[get_current_user_payload] = _payload
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _count_sheets(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Count sheet rows in a project, straight from the database."""
    from app.modules.documents.models import Sheet

    stmt = select(func.count()).select_from(Sheet).where(Sheet.project_id == project_id)
    return int((await session.execute(stmt)).scalar_one())


async def _count_documents(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Count document rows in a project, straight from the database."""
    from app.modules.documents.models import Document

    stmt = select(func.count()).select_from(Document).where(Document.project_id == project_id)
    return int((await session.execute(stmt)).scalar_one())


def _one_page_pdf() -> bytes:
    """Render a single-page PDF carrying a readable title block."""
    canvas = pytest.importorskip("reportlab.pdfgen.canvas", reason="reportlab is not installed")
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(60, 760, "SHEET NO: A-201")
    pdf.drawString(60, 740, "SHEET TITLE: Floor Plan Level 2")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


# ── Read routes ───────────────────────────────────────────────────────────


async def test_listing_a_foreign_register_is_404(sheets_app: Any, db_session: AsyncSession) -> None:
    """``GET /sheets/`` must not list a project the caller cannot reach."""
    project_id, _sheet_id, attacker_id = await _seed_victim_and_attacker(db_session)

    async with _as_user(sheets_app, attacker_id) as client:
        resp = await client.get(f"{SHEETS_BASE}/", params={"project_id": str(project_id)})

    assert resp.status_code == 404, resp.text


async def test_the_owner_can_list_the_same_register(sheets_app: Any, db_session: AsyncSession) -> None:
    """Positive control: the refusal above is the guard, not a wrong URL."""
    owner_id = await _seed_user(db_session, role="manager")
    project_id = await _seed_project(db_session, owner_id)
    await _seed_sheet(db_session, project_id)

    async with _as_user(sheets_app, owner_id) as client:
        resp = await client.get(f"{SHEETS_BASE}/", params={"project_id": str(project_id)})

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1


async def test_reading_a_foreign_sheet_is_404(sheets_app: Any, db_session: AsyncSession) -> None:
    """``GET /sheets/{id}`` resolves the row first, then checks its project."""
    _project_id, sheet_id, attacker_id = await _seed_victim_and_attacker(db_session)

    async with _as_user(sheets_app, attacker_id) as client:
        resp = await client.get(f"{SHEETS_BASE}/{sheet_id}")

    assert resp.status_code == 404, resp.text


async def test_the_owner_can_read_the_same_sheet(sheets_app: Any, db_session: AsyncSession) -> None:
    """Positive control for the parametric sheet URL."""
    owner_id = await _seed_user(db_session, role="manager")
    project_id = await _seed_project(db_session, owner_id)
    sheet_id = await _seed_sheet(db_session, project_id)

    async with _as_user(sheets_app, owner_id) as client:
        resp = await client.get(f"{SHEETS_BASE}/{sheet_id}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["sheet_number"] == "A-101"


async def test_reading_a_foreign_sheets_version_history_is_404(
    sheets_app: Any,
    db_session: AsyncSession,
) -> None:
    """The drawer's version history is behind the same guard as the row."""
    _project_id, sheet_id, attacker_id = await _seed_victim_and_attacker(db_session)

    async with _as_user(sheets_app, attacker_id) as client:
        resp = await client.get(f"{SHEETS_BASE}/{sheet_id}/versions/")

    assert resp.status_code == 404, resp.text


async def test_the_owner_can_read_the_same_version_history(
    sheets_app: Any,
    db_session: AsyncSession,
) -> None:
    """Positive control for the version-history URL."""
    owner_id = await _seed_user(db_session, role="manager")
    project_id = await _seed_project(db_session, owner_id)
    sheet_id = await _seed_sheet(db_session, project_id)

    async with _as_user(sheets_app, owner_id) as client:
        resp = await client.get(f"{SHEETS_BASE}/{sheet_id}/versions/")

    assert resp.status_code == 200, resp.text


async def test_listing_a_foreign_projects_disciplines_is_404(
    sheets_app: Any,
    db_session: AsyncSession,
) -> None:
    """The discipline filter is a distinct-value read of the same register."""
    project_id, _sheet_id, attacker_id = await _seed_victim_and_attacker(db_session)

    async with _as_user(sheets_app, attacker_id) as client:
        resp = await client.get(f"{SHEETS_BASE}/disciplines/", params={"project_id": str(project_id)})

    assert resp.status_code == 404, resp.text


async def test_the_owner_can_list_the_same_disciplines(sheets_app: Any, db_session: AsyncSession) -> None:
    """Positive control for the disciplines URL."""
    owner_id = await _seed_user(db_session, role="manager")
    project_id = await _seed_project(db_session, owner_id)
    await _seed_sheet(db_session, project_id)

    async with _as_user(sheets_app, owner_id) as client:
        resp = await client.get(f"{SHEETS_BASE}/disciplines/", params={"project_id": str(project_id)})

    assert resp.status_code == 200, resp.text
    assert resp.json() == ["Architectural"]


# ── Write routes ──────────────────────────────────────────────────────────


async def test_splitting_a_pdf_into_a_foreign_project_is_404_and_writes_nothing(
    sheets_app: Any,
    db_session: AsyncSession,
) -> None:
    """The split refuses before it reads the upload, and leaves no rows behind.

    A refusal that had already created the parent ``Document`` row would put a
    foreign file in the victim's document hub even though the sheets never
    appeared, so the row counts matter as much as the status code.
    """
    project_id, _sheet_id, attacker_id = await _seed_victim_and_attacker(db_session)

    async with _as_user(sheets_app, attacker_id) as client:
        resp = await client.post(
            f"{SHEETS_BASE}/split-pdf/",
            params={"project_id": str(project_id)},
            files={"file": ("drawings.pdf", b"%PDF-1.4\n", "application/pdf")},
        )

    assert resp.status_code == 404, resp.text
    assert await _count_sheets(db_session, project_id) == 1  # only the seeded one
    assert await _count_documents(db_session, project_id) == 0


async def test_the_owner_can_split_into_their_own_project(
    sheets_app: Any,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Positive control for the split URL, with storage redirected at a tmp dir."""
    from app.modules.documents import service as documents_service

    monkeypatch.setattr(documents_service, "UPLOAD_BASE", tmp_path / "uploads")
    monkeypatch.setattr(documents_service, "SHEET_THUMB_BASE", tmp_path / "sheets")

    owner_id = await _seed_user(db_session, role="manager")
    project_id = await _seed_project(db_session, owner_id)

    async with _as_user(sheets_app, owner_id) as client:
        resp = await client.post(
            f"{SHEETS_BASE}/split-pdf/",
            params={"project_id": str(project_id)},
            files={"file": ("drawings.pdf", _one_page_pdf(), "application/pdf")},
        )

    assert resp.status_code == 201, resp.text
    assert len(resp.json()) == 1


async def test_patching_a_foreign_sheet_is_404(sheets_app: Any, db_session: AsyncSession) -> None:
    """The drawer's edit path must not rewrite another project's metadata."""
    _project_id, sheet_id, attacker_id = await _seed_victim_and_attacker(db_session)

    async with _as_user(sheets_app, attacker_id) as client:
        resp = await client.patch(f"{SHEETS_BASE}/{sheet_id}", json={"sheet_title": "Owned"})

    assert resp.status_code == 404, resp.text


async def test_the_owner_can_patch_the_same_sheet(sheets_app: Any, db_session: AsyncSession) -> None:
    """Positive control for the sheet PATCH URL."""
    owner_id = await _seed_user(db_session, role="manager")
    project_id = await _seed_project(db_session, owner_id)
    sheet_id = await _seed_sheet(db_session, project_id)

    async with _as_user(sheets_app, owner_id) as client:
        resp = await client.patch(f"{SHEETS_BASE}/{sheet_id}", json={"sheet_title": "Renamed"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["sheet_title"] == "Renamed"


async def test_deleting_a_foreign_sheet_is_404_and_leaves_the_row(
    sheets_app: Any,
    db_session: AsyncSession,
) -> None:
    """A refused delete must not have deleted anything on the way to the 404."""
    project_id, sheet_id, attacker_id = await _seed_victim_and_attacker(db_session)

    async with _as_user(sheets_app, attacker_id) as client:
        resp = await client.delete(f"{SHEETS_BASE}/{sheet_id}")

    assert resp.status_code == 404, resp.text
    assert await _count_sheets(db_session, project_id) == 1


async def test_checking_completeness_of_a_foreign_project_is_404(
    sheets_app: Any,
    db_session: AsyncSession,
) -> None:
    """Reconciliation reads the whole register, so it is guarded like a list."""
    project_id, _sheet_id, attacker_id = await _seed_victim_and_attacker(db_session)

    async with _as_user(sheets_app, attacker_id) as client:
        resp = await client.post(
            f"{SHEETS_BASE}/check-completeness/",
            json={"project_id": str(project_id), "pasted_index": "A-101, Floor Plan, A"},
        )

    assert resp.status_code == 404, resp.text


async def test_reconciling_against_a_foreign_index_document_is_404(
    sheets_app: Any,
    db_session: AsyncSession,
) -> None:
    """The index document is scoped separately from the project being checked.

    A caller who legitimately reaches their own project can still name any
    document id as the index. That is a second guard, written once inside
    ``check_completeness`` rather than at the route, and it is the one this
    test covers: the outer project check passes here by design.

    The detail string is asserted, not just the status, because the outer guard
    and a mistyped route both answer 404 as well. Only this guard says "Index
    document not found".
    """
    victim_project, _sheet_id, attacker_id = await _seed_victim_and_attacker(db_session)
    foreign_index = await _seed_document(db_session, victim_project)
    attacker_project = await _seed_project(db_session, attacker_id)

    async with _as_user(sheets_app, attacker_id) as client:
        resp = await client.post(
            f"{SHEETS_BASE}/check-completeness/",
            json={"project_id": str(attacker_project), "index_document_id": str(foreign_index)},
        )

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Index document not found"


async def test_the_owner_can_check_completeness_of_their_own_project(
    sheets_app: Any,
    db_session: AsyncSession,
) -> None:
    """Positive control for the completeness URL."""
    owner_id = await _seed_user(db_session, role="manager")
    project_id = await _seed_project(db_session, owner_id)
    await _seed_sheet(db_session, project_id)

    async with _as_user(sheets_app, owner_id) as client:
        resp = await client.post(
            f"{SHEETS_BASE}/check-completeness/",
            json={"project_id": str(project_id), "pasted_index": "A-101, Floor Plan Level 1"},
        )

    assert resp.status_code == 200, resp.text


# ── Re-read title blocks ──────────────────────────────────────────────────


async def test_rereading_a_foreign_registers_title_blocks_is_404_and_changes_nothing(
    sheets_app: Any,
    db_session: AsyncSession,
) -> None:
    """The re-read rewrites a whole project's sheets, so it is scoped like the split."""
    from app.modules.documents.models import Sheet

    project_id, sheet_id, attacker_id = await _seed_victim_and_attacker(db_session)

    async with _as_user(sheets_app, attacker_id) as client:
        resp = await client.post(f"{SHEETS_BASE}/reread-title-blocks/?project_id={project_id}")

    assert resp.status_code == 404, resp.text
    db_session.expire_all()
    row = (await db_session.execute(select(Sheet).where(Sheet.id == sheet_id))).scalar_one()
    assert row.sheet_title == "Floor Plan Level 1"


async def test_the_owner_can_reread_their_own_title_blocks(sheets_app: Any, db_session: AsyncSession) -> None:
    """Positive control for the re-read URL. The seeded sheet has no stored file."""
    owner_id = await _seed_user(db_session, role="manager")
    project_id = await _seed_project(db_session, owner_id)
    await _seed_sheet(db_session, project_id)

    async with _as_user(sheets_app, owner_id) as client:
        resp = await client.post(f"{SHEETS_BASE}/reread-title-blocks/?project_id={project_id}")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "sheets_checked": 1,
        "sheets_updated": 0,
        "fields_updated": 0,
        "files_missing": 1,
        "current_conflicts": [],
    }
