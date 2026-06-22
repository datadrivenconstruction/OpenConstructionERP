# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Folder-permission write gate on ``upload_document_revision`` (Finding #25).

Background
----------
``upload_document`` and ``delete_document`` both resolve the document's
folder scope via ``folder_access_for`` and reject a caller who holds only a
``viewer`` grant on a restricted/managed folder (even when they carry the
project-wide ``documents.update`` permission). ``upload_document_revision``
previously skipped that check entirely - it only ran ``RequirePermission``
+ ``verify_project_access`` - so a read-only folder member could replace
the served file bytes of any document in that folder by POSTing a revision,
defeating the whole folder write gate.

These tests call the router handler directly (no ASGI / DB) with the
``DocumentService`` stubbed and ``verify_project_access`` patched to a
no-op (a project MEMBER already clears that gate). They assert that:

    1. a ``viewer`` folder grant is rejected with 404 BEFORE the service
       is asked to write any bytes (this FAILS on the pre-fix code, where
       the revision was uploaded unconditionally),
    2. an ``editor`` grant is accepted (the fix must not over-block
       legitimate writers),
    3. the project-OWNER role ("owner" from ``folder_access_for``) is
       accepted.

Mirrors the patch-style of ``test_dms_folder_permissions.py`` (patching
``folder_permissions_service`` helpers) and the source guard in
``test_idor_router_guards.py``.
"""

from __future__ import annotations

import ast
import io
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.modules.documents import router as documents_router


def _dummy_upload() -> UploadFile:
    """A minimal UploadFile - never read before the gate rejects."""
    return UploadFile(filename="rev.pdf", file=io.BytesIO(b"%PDF-1.4\n"))


def _fake_doc(project_id: uuid.UUID) -> SimpleNamespace:
    """A Document-shaped stub with the attributes the handler touches."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        category="drawing",
    )


def _make_service(doc: SimpleNamespace) -> AsyncMock:
    """Stub DocumentService: ``get_document`` returns ``doc``; the revision
    writer is a tracked mock so we can assert it is (not) called."""
    service = AsyncMock()
    service.get_document = AsyncMock(return_value=doc)
    service.upload_document_revision = AsyncMock(return_value=doc)
    return service


@pytest.mark.asyncio
async def test_viewer_grant_is_rejected_before_writing_bytes() -> None:
    """A read-only (viewer) folder member is 404'd and no revision is written."""
    project_id = uuid.uuid4()
    user_id = str(uuid.uuid4())
    doc = _fake_doc(project_id)
    service = _make_service(doc)

    with (
        patch.object(documents_router, "verify_project_access", new=AsyncMock(return_value=None)),
        patch(
            "app.modules.documents.folder_permissions_service.folder_access_for",
            new=AsyncMock(return_value="viewer"),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await documents_router.upload_document_revision(
                document_id=doc.id,
                session=AsyncMock(),
                file=_dummy_upload(),
                notes=None,
                user_id=user_id,
                _perm=None,
                service=service,
            )

    assert exc.value.status_code == 404, "viewer-grant member must be 404'd (folder write gate)"
    service.upload_document_revision.assert_not_called()


@pytest.mark.asyncio
async def test_editor_grant_is_accepted() -> None:
    """An editor folder grant clears the gate and the revision is written."""
    project_id = uuid.uuid4()
    user_id = str(uuid.uuid4())
    doc = _fake_doc(project_id)
    service = _make_service(doc)

    with (
        patch.object(documents_router, "verify_project_access", new=AsyncMock(return_value=None)),
        patch(
            "app.modules.documents.folder_permissions_service.folder_access_for",
            new=AsyncMock(return_value="editor"),
        ),
    ):
        result = await documents_router.upload_document_revision(
            document_id=doc.id,
            session=AsyncMock(),
            file=_dummy_upload(),
            notes="rev B",
            user_id=user_id,
            _perm=None,
            service=service,
        )

    assert result.id == doc.id
    service.upload_document_revision.assert_awaited_once()


@pytest.mark.asyncio
async def test_project_owner_role_is_accepted() -> None:
    """The project owner ('owner' from folder_access_for) bypasses can_write."""
    project_id = uuid.uuid4()
    user_id = str(uuid.uuid4())
    doc = _fake_doc(project_id)
    service = _make_service(doc)

    with (
        patch.object(documents_router, "verify_project_access", new=AsyncMock(return_value=None)),
        patch(
            "app.modules.documents.folder_permissions_service.folder_access_for",
            new=AsyncMock(return_value="owner"),
        ),
    ):
        result = await documents_router.upload_document_revision(
            document_id=doc.id,
            session=AsyncMock(),
            file=_dummy_upload(),
            notes=None,
            user_id=user_id,
            _perm=None,
            service=service,
        )

    assert result.id == doc.id
    service.upload_document_revision.assert_awaited_once()


# ── Source guard: keep the folder write gate grep-able ──────────────────────


def _upload_revision_ast() -> ast.AsyncFunctionDef:
    here = Path(__file__).resolve()
    repo = here.parents[2]  # tests/unit/<file> -> backend/
    router = repo / "app" / "modules" / "documents" / "router.py"
    tree = ast.parse(router.read_text(encoding="utf-8"), filename=str(router))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "upload_document_revision":
            return node
    raise AssertionError("upload_document_revision handler not found in documents/router.py")


def test_revision_handler_enforces_folder_write_gate() -> None:
    """Static guard: ``upload_document_revision`` must call ``folder_access_for``
    and ``can_write`` so a future refactor can't silently drop the gate while
    still passing the happy-path tests (legit editors/owners still 201)."""
    fn = _upload_revision_ast()
    called = {node.func.id for node in ast.walk(fn) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "folder_access_for" in called, "revision upload must resolve the folder role (folder_access_for)"
    assert "can_write" in called, "revision upload must enforce can_write on the folder role"
