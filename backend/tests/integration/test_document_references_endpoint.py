# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠End-to-end cover for ``GET /api/v1/documents/{id}/references``.

The endpoint answers "what still points at this document" so the delete
confirmation can say what it costs. Thirty-four columns across twenty-one
modules hold a document id that no foreign key constrains, and until now the
delete path removed the row without asking any of them.

What this exercises, and why each case is here rather than a cheaper one:

``Sheet`` and ``ScaleConfig``
    ``String`` columns that are NOT NULL, so they are classified ``strands``:
    the row cannot even record that the document went away.
``PunchItem``
    ``String(36)``, nullable, so ``unlinks``.
``TemporaryWorksItem.design_document_id``
    A ``GUID`` column. Included because GUID is a TypeDecorator and the
    predicate binds a plain string to it; a GUID that silently failed to match
    would leave the ten GUID columns among the thirty-four reporting zero forever.
``Meeting.document_ids``
    A JSON array. Containment there cannot use ``@>`` - the six array columns
    are ``JSON`` and not ``JSONB`` - so the predicate matches the quoted id in
    the serialised text instead.
``PortalDocumentAccessLog``
    Polymorphic, and the reason the registry is curated rather than derived
    from column names. Its ``document_id`` is qualified by ``document_type``,
    a free-form ``String(64)`` the API accepts from the caller, and only the
    value ``document`` means a documents-module row.

Two decoys are seeded deliberately, and they are the point of the test rather
than trimming: a portal access row carrying the same id under a different
``document_type``, and a meeting whose array holds a different id. A
name-matching implementation passes every positive case above and still counts
both decoys, so a test without them would go green on the wrong code.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

#: ``Meeting.meeting_date`` is a ``String(40)``, not a date column.
_MEETING_DATE = "2026-09-19"


@pytest_asyncio.fixture
async def client():
    """FastAPI test client with full app lifespan (modules + DDL)."""
    from contextlib import asynccontextmanager

    app = create_app()

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
    email = f"docrefs-{unique}@smoke.io"
    password = f"DocRefs{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Doc Refs Tester"},
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
            "name": "Document References Test",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


@pytest.mark.asyncio
async def test_references_counts_every_shape_and_ignores_the_decoys(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: str,
) -> None:
    """Seed one referenced document, one untouched one, and two decoys."""
    from app.database import async_session_factory
    from app.modules.documents.models import Document, Sheet
    from app.modules.markups.models import ScaleConfig
    from app.modules.meetings.models import Meeting
    from app.modules.portal.models import PortalDocumentAccessLog, PortalUser
    from app.modules.punchlist.models import PunchItem
    from app.modules.temporary_works.models import TemporaryWorksItem

    pid = uuid.UUID(project_id)
    async with async_session_factory() as session:
        target = Document(
            project_id=pid,
            name="referenced.pdf",
            category="drawing",
            file_path="/tmp/referenced.pdf",
            mime_type="application/pdf",
            uploaded_by="seed",
        )
        lonely = Document(
            project_id=pid,
            name="lonely.pdf",
            category="drawing",
            file_path="/tmp/lonely.pdf",
            mime_type="application/pdf",
            uploaded_by="seed",
        )
        session.add_all([target, lonely])
        await session.flush()

        doc_id = target.id
        other_id = uuid.uuid4()

        portal_user = PortalUser(email=f"portal-{uuid.uuid4().hex[:8]}@test.io", portal_role="client")
        session.add(portal_user)
        await session.flush()

        session.add_all(
            [
                # strands: NOT NULL String columns.
                Sheet(project_id=pid, document_id=str(doc_id), page_number=1),
                Sheet(project_id=pid, document_id=str(doc_id), page_number=2),
                ScaleConfig(document_id=str(doc_id), pixels_per_unit=10.0, real_distance=1.0),
                # unlinks: nullable String(36).
                PunchItem(project_id=pid, title="Cracked screed", document_id=str(doc_id)),
                # unlinks: GUID column, bound from a plain string.
                TemporaryWorksItem(
                    project_id=pid,
                    reference="TW-001",
                    title="Propping to slab",
                    tw_type="propping",
                    design_document_id=doc_id,
                ),
                # unlinks: JSON array membership.
                Meeting(
                    project_id=pid,
                    meeting_number="M-001",
                    meeting_type="progress",
                    title="Weekly progress",
                    meeting_date=_MEETING_DATE,
                    document_ids=[str(doc_id)],
                ),
                # retains: append-only audit, qualified by document_type.
                PortalDocumentAccessLog(
                    portal_user_id=portal_user.id,
                    document_type="document",
                    document_id=doc_id,
                    action="view",
                ),
                # DECOY 1: same id, different document_type. Must not count.
                PortalDocumentAccessLog(
                    portal_user_id=portal_user.id,
                    document_type="invoice",
                    document_id=doc_id,
                    action="view",
                ),
                # DECOY 2: an array holding somebody else's id. Must not count.
                Meeting(
                    project_id=pid,
                    meeting_number="M-002",
                    meeting_type="progress",
                    title="Unrelated meeting",
                    meeting_date=_MEETING_DATE,
                    document_ids=[str(other_id)],
                ),
            ]
        )
        await session.commit()
        lonely_id = lonely.id

    resp = await client.get(f"/api/v1/documents/{doc_id}/references", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    counts = {item["key"]: item["count"] for item in body["references"]}
    impacts = {item["key"]: item["impact"] for item in body["references"]}

    assert counts["Sheet.document_id"] == 2
    assert counts["ScaleConfig.document_id"] == 1
    assert counts["PunchItem.document_id"] == 1
    assert counts["TemporaryWorksItem.design_document_id"] == 1
    assert counts["Meeting.document_ids"] == 1, "the decoy meeting must not be counted"
    assert counts["PortalDocumentAccessLog.document_id"] == 1, "the decoy access row must not be counted"

    assert impacts["Sheet.document_id"] == "strands"
    assert impacts["ScaleConfig.document_id"] == "strands"
    assert impacts["PunchItem.document_id"] == "unlinks"
    assert impacts["PortalDocumentAccessLog.document_id"] == "retains"

    # 3 stranded (two sheets, one scale), 3 unlinked (punch item, temporary
    # works, meeting), 1 retained (the portal access row).
    assert body["strands"] == 3
    assert body["unlinks"] == 3
    assert body["retains"] == 1
    assert body["total"] == 7

    # Only the six referrers seeded above report anything.
    assert len(body["references"]) == 6

    # Heaviest consequence first, so the prompt leads with what cannot be
    # repaired and ends with what is kept on purpose. Two entries are
    # ``strands`` even though three rows are stranded: Sheet contributes two
    # rows under one key.
    ordering = [item["impact"] for item in body["references"]]
    assert ordering == ["strands", "strands", "unlinks", "unlinks", "unlinks", "retains"], ordering

    # A document nothing points at must come back empty, which is what proves
    # the counts above are matching the id rather than counting rows.
    resp = await client.get(f"/api/v1/documents/{lonely_id}/references", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    empty = resp.json()
    assert empty["total"] == 0
    assert empty["references"] == []


@pytest.mark.asyncio
async def test_references_are_readable_wherever_the_document_is(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: str,
) -> None:
    """The endpoint is guarded like reading the document, and 404s the same.

    It reports nothing the document's own GET does not already imply, so it
    carries the same guard rather than the delete endpoint's stricter one. An
    id that does not exist must not be distinguishable from one the caller
    cannot see.
    """
    from app.database import async_session_factory
    from app.modules.documents.models import Document

    pid = uuid.UUID(project_id)
    async with async_session_factory() as session:
        doc = Document(
            project_id=pid,
            name="readable.pdf",
            category="drawing",
            file_path="/tmp/readable.pdf",
            mime_type="application/pdf",
            uploaded_by="seed",
        )
        session.add(doc)
        await session.commit()
        doc_id = doc.id

    resp = await client.get(f"/api/v1/documents/{doc_id}/references", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["document_id"] == str(doc_id)

    missing = await client.get(f"/api/v1/documents/{uuid.uuid4()}/references", headers=auth_headers)
    assert missing.status_code == 404, missing.text

    unauthenticated = await client.get(f"/api/v1/documents/{doc_id}/references")
    assert unauthenticated.status_code in (401, 403), unauthenticated.text
