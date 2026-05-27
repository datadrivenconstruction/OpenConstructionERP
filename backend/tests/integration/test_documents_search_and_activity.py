"""Integration tests for documents module — search broadening + activity log.

Two slices live here:

1. ``test_documents_search_ocr_and_sheet`` — verifies that the search
   parameter on ``GET /v1/documents/`` matches not just ``Document.name``
   but also ``Document.metadata_["ocr_text"]`` and ``Sheet.sheet_title``
   / ``Sheet.sheet_number`` joined on ``Sheet.document_id``.

2. ``test_documents_activity_rename_event`` — uploads a document, PATCHes
   it to rename, GETs the activity timeline, and asserts the ``renamed``
   event is present with ``{old, new}`` payload.

Both tests reuse the smoke-test fixtures (``client``, ``auth_headers``)
so the in-memory SQLite + lifespan plumbing is set up once at session
scope.
"""

from __future__ import annotations

import io
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    """FastAPI test client with full app lifespan (modules + DDL)."""
    app = create_app()
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Register a fresh admin and return Bearer headers."""
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"docs-{unique}@smoke.io"
    password = f"DocsTest{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Docs Tester"},
    )
    assert reg.status_code == 201, reg.text

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = resp.json().get("access_token", "")
    assert token, resp.text
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def project_id(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    """Create a project to host the test documents."""
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "Docs Search Test",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


# ── Slice 1: content search broadening ─────────────────────────────────────


@pytest.mark.asyncio
async def test_documents_search_ocr_and_sheet(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: str,
) -> None:
    """Seed two documents and a sheet, then assert search matches each
    via its own field.

    Doc A: name="ground_plan.pdf", ocr_text="concrete foundation slab"
    Doc B: name="electrical_layout.pdf", ocr_text="cable tray riser"
           + Sheet (sheet_title="Penthouse roof", sheet_number="E-401")

    Expected:
        ?search=foundation     → only Doc A (OCR match)
        ?search=electrical     → only Doc B (name match)
        ?search=penthouse      → only Doc B (sheet title match)
        ?search=E-401          → only Doc B (sheet number match)
    """
    from app.database import async_session_factory
    from app.modules.documents.models import Document, Sheet

    # Seed two documents with distinct ocr_text payloads. We bypass the
    # upload pipeline (which would also write files to disk) and write
    # rows directly — the search path under test is repo-level, so a
    # purely in-DB seed is the cheaper / more deterministic fixture.
    pid = uuid.UUID(project_id)
    async with async_session_factory() as session:
        doc_a = Document(
            project_id=pid,
            name="ground_plan.pdf",
            category="drawing",
            file_path="/tmp/a.pdf",
            mime_type="application/pdf",
            uploaded_by="seed",
            metadata_={"ocr_text": "concrete foundation slab pile cap"},
        )
        doc_b = Document(
            project_id=pid,
            name="electrical_layout.pdf",
            category="drawing",
            file_path="/tmp/b.pdf",
            mime_type="application/pdf",
            uploaded_by="seed",
            metadata_={"ocr_text": "cable tray riser conduit"},
        )
        session.add_all([doc_a, doc_b])
        await session.flush()

        sheet = Sheet(
            project_id=pid,
            document_id=str(doc_b.id),
            page_number=1,
            sheet_number="E-401",
            sheet_title="Penthouse roof electrical",
            discipline="Electrical",
            is_current=True,
            created_by="seed",
        )
        session.add(sheet)
        await session.commit()
        doc_a_id = str(doc_a.id)
        doc_b_id = str(doc_b.id)

    async def search(q: str) -> list[str]:
        r = await client.get(
            f"/api/v1/documents/?project_id={project_id}&search={q}",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        return [row["id"] for row in r.json()]

    # name match — should still work after our extension.
    ids = await search("electrical")
    assert doc_b_id in ids
    assert doc_a_id not in ids

    # OCR match — only Doc A.
    ids = await search("foundation")
    assert doc_a_id in ids, "OCR-text search must match the seeded ocr_text key"
    assert doc_b_id not in ids

    # Sheet title — only Doc B (joined via Sheet.document_id).
    ids = await search("penthouse")
    assert doc_b_id in ids, "Sheet.sheet_title must contribute to the OR clause"
    assert doc_a_id not in ids

    # Sheet number.
    ids = await search("E-401")
    assert doc_b_id in ids
    assert doc_a_id not in ids

    # No duplicates — Doc B has 1 sheet but a search that matches both
    # name and sheet (e.g. via overlapping word) must return a single row.
    # Seed a second sheet referencing doc_b to force the outer join to
    # produce 2 rows before DISTINCT collapses them.
    async with async_session_factory() as session:
        session.add(
            Sheet(
                project_id=pid,
                document_id=doc_b_id,
                page_number=2,
                sheet_number="E-402",
                sheet_title="Penthouse roof electrical part 2",
                discipline="Electrical",
                is_current=True,
                created_by="seed",
            )
        )
        await session.commit()

    ids = await search("penthouse")
    assert ids.count(doc_b_id) == 1, "DISTINCT must dedupe multi-sheet matches"


# ── Slice 2: activity log ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_documents_activity_rename_event(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: str,
) -> None:
    """Upload a document, PATCH to rename, then GET activity.

    The rename path must produce a ``renamed`` row with the old/new
    names in ``meta``. The upload path must also produce an
    ``uploaded`` row — both should appear newest-first.
    """
    # Upload via the API so the upload-side audit row is also exercised.
    pdf_bytes = b"%PDF-1.4\n%fake\n%%EOF"
    files = {"file": ("orig_name.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    resp = await client.post(
        f"/api/v1/documents/upload/?project_id={project_id}",
        files=files,
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    doc_id = resp.json()["id"]

    # Rename via PATCH.
    resp = await client.patch(
        f"/api/v1/documents/{doc_id}",
        json={"name": "renamed_doc.pdf"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "renamed_doc.pdf"

    # GET activity.
    resp = await client.get(
        f"/api/v1/documents/{doc_id}/activity/",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    actions = [r["action"] for r in rows]

    assert "uploaded" in actions, f"expected 'uploaded' in {actions}"
    assert "renamed" in actions, f"expected 'renamed' in {actions}"

    rename_row = next(r for r in rows if r["action"] == "renamed")
    assert rename_row["meta"]["old"] == "orig_name.pdf"
    assert rename_row["meta"]["new"] == "renamed_doc.pdf"

    # Newest-first ordering: renamed must appear before uploaded.
    rename_idx = actions.index("renamed")
    upload_idx = actions.index("uploaded")
    assert rename_idx < upload_idx, (
        f"rename (later) must come before upload (earlier) in newest-first ordering: actions={actions}"
    )


@pytest.mark.asyncio
async def test_documents_activity_dedupe_within_1s(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: str,
) -> None:
    """Two identical PATCH calls inside the 1-s dedupe window must
    produce a single ``renamed`` row in the timeline.

    Issuing the same rename twice in a row (e.g. duplicate-fired event
    handler on retry) must not double-write the timeline. We hit this
    via two PATCH calls back-to-back — the second sets name to a value
    that equals the just-committed value, so the service's "skip if
    fields didn't change" branch handles one half; we exercise the
    dedupe helper itself by issuing TWO renames inside the 1-s window
    that toggle then re-toggle the name.
    """
    pdf_bytes = b"%PDF-1.4\n%fake\n%%EOF"
    files = {"file": ("dedupe.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    resp = await client.post(
        f"/api/v1/documents/upload/?project_id={project_id}",
        files=files,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    # PATCH twice in fast succession. Both calls write a "renamed" audit
    # event for the same (doc, user, action) triple — the dedupe helper
    # must collapse them into a single row.
    r1 = await client.patch(
        f"/api/v1/documents/{doc_id}",
        json={"name": "rename_one.pdf"},
        headers=auth_headers,
    )
    assert r1.status_code == 200
    r2 = await client.patch(
        f"/api/v1/documents/{doc_id}",
        json={"name": "rename_two.pdf"},
        headers=auth_headers,
    )
    assert r2.status_code == 200

    resp = await client.get(
        f"/api/v1/documents/{doc_id}/activity/",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    rows = resp.json()
    rename_rows = [r for r in rows if r["action"] == "renamed"]
    assert len(rename_rows) == 1, (
        f"Two PATCHes within 1 s must collapse to a single 'renamed' "
        f"activity row, got {len(rename_rows)}: {rename_rows}"
    )
