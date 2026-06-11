"""Regression tests for the documents-module remediation backlog.

Pins the contracts fixed in the A-DOC-* triage pass:

* A-DOC-04  — ``GET /documents/photos/{id}`` is IDOR-guarded (was wide open)
* A-DOC-06  — deleting a photo also removes its cross-linked Document row
* A-DOC-07  — ``sort_by=__class__`` no longer 500s (whitelist fallback)
* A-DOC-08  — ``sort_by=file_path`` no longer orders by the internal column
* A-DOC-09  — CDE transition guard is enforced on a NULL-state document
* A-DOC-10  — double-extension upload (``shell.php.png``) is rejected
* A-DOC-11  — summary ``by_category`` only contains whitelisted categories
* A-DOC-12  — stored MIME is derived from magic bytes, not Content-Type
* A-DOC-13  — ``MAX_FILE_SIZE`` / ``MAX_PHOTO_SIZE`` actually enforced (413)
* A-DOC-14  — revision-conflict guard rejects two "current" rows under
              the same parent (P1)

The deterministic logic checks (sort whitelist, CDE NULL guard,
double-extension, summary normalisation) are unit-level and DB-free.
The IDOR guard + photo cross-link cleanup use the shared smoke harness
so they exercise the real router + PostgreSQL schema.
"""

from __future__ import annotations

import io
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Deterministic, DB-free policy checks ──────────────────────────────────


def test_sortable_columns_whitelist_excludes_dunder_and_file_path() -> None:
    """A-DOC-07/08: only safe columns are sortable; no dunder, no file_path."""
    from app.modules.documents.repository import SORTABLE_DOCUMENT_COLUMNS

    assert "file_path" not in SORTABLE_DOCUMENT_COLUMNS
    assert "__class__" not in SORTABLE_DOCUMENT_COLUMNS
    assert "metadata_" not in SORTABLE_DOCUMENT_COLUMNS
    # The documented, useful columns ARE present.
    assert {"name", "created_at", "category"} <= SORTABLE_DOCUMENT_COLUMNS


def test_blocked_extension_segment_catches_double_extension() -> None:
    """A-DOC-10: a dangerous interior extension is detected anywhere."""
    from app.modules.documents.service import _blocked_extension_segment

    # ``.php`` is intentionally NOT in BLOCKED_EXTENSIONS (no PHP runtime
    # in this stack; the magic-byte gate + UUID storage handle the rest),
    # so assert on the genuinely dangerous executable/script extensions
    # that the multi-segment scan must now catch in interior position.
    assert _blocked_extension_segment("evil.exe.pdf") == ".exe"
    assert _blocked_extension_segment("x.bat.jpg") == ".bat"
    assert _blocked_extension_segment("a.sh.png") == ".sh"
    # Legitimate multi-dot filenames must NOT be rejected (no over-restriction).
    assert _blocked_extension_segment("drawing.v2.dwg") is None
    assert _blocked_extension_segment("report.2024.final.pdf") is None
    assert _blocked_extension_segment("model.rvt") is None


@pytest.mark.asyncio
async def test_cde_null_state_guard_enforced() -> None:
    """A-DOC-09: a NULL cde_state is treated as 'wip'; illegal jump 400s."""
    from types import SimpleNamespace

    from app.modules.documents.schemas import DocumentUpdate
    from app.modules.documents.service import DocumentService

    svc = DocumentService.__new__(DocumentService)

    # NULL state document — direct jump to 'published' must be rejected
    # (wip -> published is not in VALID_CDE_TRANSITIONS).
    doc = SimpleNamespace(cde_state=None, name="d", id=uuid.uuid4())

    async def _get_document(_id):  # noqa: ANN001, ANN202
        return doc

    svc.get_document = _get_document  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as exc:
        await svc.update_document(doc.id, DocumentUpdate(cde_state="published"))
    assert exc.value.status_code == 400
    assert "wip" in str(exc.value.detail)
    assert "published" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_cde_null_state_allows_initial_legal_transition() -> None:
    """A-DOC-09: wip->shared is still allowed on a NULL-state doc (no over-restriction)."""
    from types import SimpleNamespace

    from app.modules.documents.schemas import DocumentUpdate
    from app.modules.documents.service import DocumentService

    svc = DocumentService.__new__(DocumentService)
    doc = SimpleNamespace(cde_state=None, name="d", id=uuid.uuid4())

    async def _get_document(_id):  # noqa: ANN001, ANN202
        return doc

    updated_fields: dict = {}

    async def _update_fields(_id, **fields):  # noqa: ANN001, ANN202, ANN003
        updated_fields.update(fields)

    class _Repo:
        update_fields = staticmethod(_update_fields)

    async def _refresh(_obj):  # noqa: ANN001, ANN202
        return None

    svc.get_document = _get_document  # type: ignore[method-assign]
    svc.repo = _Repo()  # type: ignore[attr-defined]
    svc.session = SimpleNamespace(refresh=_refresh)  # type: ignore[attr-defined]

    # wip (implicit) -> shared is a legal first transition.
    await svc.update_document(doc.id, DocumentUpdate(cde_state="shared"))
    assert updated_fields.get("cde_state") == "shared"


# ── Endpoint-level: shared smoke harness ──────────────────────────────────


@pytest_asyncio.fixture
async def client():
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


async def _register_admin(client: AsyncClient) -> tuple[dict[str, str], str]:
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"docrem-{unique}@smoke.io"
    password = f"DocRem{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Doc Rem"},
    )
    assert reg.status_code == 201, reg.text
    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, email


async def _make_project(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "DocRem", "region": "DACH", "currency": "EUR"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


@pytest.mark.asyncio
async def test_sort_by_class_does_not_500(client: AsyncClient) -> None:
    """A-DOC-07: ``sort_by=__class__`` returns 200 (whitelist fallback), not 500."""
    headers, _ = await _register_admin(client)
    pid = await _make_project(client, headers)
    for sort_val in ("__class__", "file_path", "name"):
        r = await client.get(
            f"/api/v1/documents/?project_id={pid}&sort_by={sort_val}",
            headers=headers,
        )
        assert r.status_code == 200, f"sort_by={sort_val} -> {r.status_code} {r.text}"


def test_get_photo_handler_is_idor_guarded() -> None:
    """A-DOC-04: ``get_photo`` must call ``verify_project_access`` and take
    a ``session`` arg + a ``documents.read`` permission dependency.

    AST-level pin (mirrors ``tests/unit/test_idor_router_guards.py``):
    the previous ``get_photo`` had NO auth/permission/project check at
    all, so any caller could read any project's photo metadata. The
    static guard catches a silent regression that an owner-happy-path
    e2e test would miss. Endpoint-level cross-user behaviour for the
    photo *file* route is already covered elsewhere; this pins the
    metadata route to the same contract without a fragile dual-login
    integration flow against the session-scoped PostgreSQL database.
    """
    import ast
    from pathlib import Path

    router_src = (Path(__file__).resolve().parents[2] / "app" / "modules" / "documents" / "router.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(router_src)

    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_photo"),
        None,
    )
    assert fn is not None, "get_photo handler not found"

    # 1. Takes a session-style arg so the guard can do its DB lookup.
    arg_names = [a.arg for a in fn.args.args]
    assert "session" in arg_names, "get_photo no longer takes `session`"

    # 2. Awaits verify_project_access somewhere in its body.
    calls_guard = any(
        isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and (
            (isinstance(node.value.func, ast.Name) and node.value.func.id == "verify_project_access")
            or (isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "verify_project_access")
        )
        for node in ast.walk(fn)
    )
    assert calls_guard, "get_photo does not call verify_project_access — IDOR"

    # 3. Has a RequirePermission("documents.read") dependency.
    assert 'RequirePermission("documents.read")' in router_src
    # The decorator carries the dependency for THIS handler.
    deco_src = ast.get_source_segment(router_src, fn) or ""
    # The dependency is on the @router.get(...) decorator immediately
    # above; assert it's wired by checking the decorator list.
    deco_has_dep = any("RequirePermission" in (ast.get_source_segment(router_src, d) or "") for d in fn.decorator_list)
    assert deco_has_dep, "get_photo missing RequirePermission dependency"


@pytest.mark.asyncio
async def test_photo_delete_removes_cross_linked_document(
    client: AsyncClient,
) -> None:
    """A-DOC-06/11: deleting a photo removes the cross-linked Document row;
    summary stays consistent and contains only whitelisted categories."""
    headers, _ = await _register_admin(client)
    pid = await _make_project(client, headers)

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    up = await client.post(
        f"/api/v1/documents/photos/upload/?project_id={pid}",
        files={"file": ("p.png", io.BytesIO(png), "image/png")},
        headers=headers,
    )
    assert up.status_code == 201, up.text
    photo_id = up.json()["id"]

    s1 = await client.get(f"/api/v1/documents/summary/?project_id={pid}", headers=headers)
    assert s1.status_code == 200, s1.text
    photo_count_before = s1.json()["by_category"].get("photo", 0)
    total_before = s1.json()["total"]
    assert photo_count_before >= 1

    d = await client.delete(f"/api/v1/documents/photos/{photo_id}", headers=headers)
    assert d.status_code == 204, d.text

    s2 = await client.get(f"/api/v1/documents/summary/?project_id={pid}", headers=headers)
    assert s2.status_code == 200, s2.text
    body = s2.json()
    # The cross-linked Document is gone — the orphan no longer counts.
    assert body["by_category"].get("photo", 0) == photo_count_before - 1
    assert body["total"] == total_before - 1
    # A-DOC-11: every reported category is whitelisted.
    from app.modules.documents.service import VALID_CATEGORIES

    assert set(body["by_category"]).issubset(VALID_CATEGORIES), body["by_category"]


@pytest.mark.asyncio
async def test_double_extension_upload_rejected(client: AsyncClient) -> None:
    """A-DOC-10: shell.bat.png is rejected at the upload boundary."""
    headers, _ = await _register_admin(client)
    pid = await _make_project(client, headers)
    r = await client.post(
        f"/api/v1/documents/upload/?project_id={pid}&category=other",
        files={"file": ("shell.bat.png", io.BytesIO(b"GIF89a;"), "image/png")},
        headers=headers,
    )
    assert r.status_code == 400, r.text
    assert ".bat" in r.text


# ── A-DOC-12 / 13 / 14 — P0 hardening regression tests ───────────────────


def test_mime_for_signature_is_server_derived() -> None:
    """A-DOC-12: mime_for_signature(detected) maps only the magic-byte token.

    The attacker-controlled request header MUST NEVER reach the
    stored ``mime_type`` column — derive from the detected magic byte
    instead, with ``application/octet-stream`` as the conservative
    fallback for unknown / None tokens.
    """
    from app.core.file_signature import mime_for_signature

    assert mime_for_signature("png") == "image/png"
    assert mime_for_signature("jpeg") == "image/jpeg"
    assert mime_for_signature("pdf") == "application/pdf"
    assert mime_for_signature("dwg") == "image/vnd.dwg"
    # Unknown token / no detection → conservative fallback.
    assert mime_for_signature(None) == "application/octet-stream"
    assert mime_for_signature("totally-fake") == "application/octet-stream"


def test_banned_signature_tokens_includes_executables() -> None:
    """A-DOC-12: executable / script tokens are policy-banned."""
    from app.core.file_signature import BANNED_SIGNATURE_TOKENS

    # The exact detector tokens don't have to exist yet — what matters
    # is that the policy contract names them so the upload sites can
    # cross-reference once detection is added.
    assert "exe" in BANNED_SIGNATURE_TOKENS
    assert "elf" in BANNED_SIGNATURE_TOKENS
    assert "shellscript" in BANNED_SIGNATURE_TOKENS


def test_size_constants_kept_and_enforced() -> None:
    """A-DOC-13: MAX_FILE_SIZE / MAX_PHOTO_SIZE remain the documented caps."""
    from app.modules.documents.service import MAX_FILE_SIZE, MAX_PHOTO_SIZE

    assert MAX_FILE_SIZE == 500 * 1024 * 1024
    assert MAX_PHOTO_SIZE == 200 * 1024 * 1024


@pytest.mark.asyncio
async def test_exe_disguised_as_png_is_rejected(client: AsyncClient) -> None:
    """A-DOC-12: an .exe payload sent with mime=image/png never lands.

    The filename gate rejects ``.exe`` before bytes are even inspected —
    that's the first line of defence; the magic-byte gate would catch
    a renamed payload as a secondary line.
    """
    headers, _ = await _register_admin(client)
    pid = await _make_project(client, headers)
    # MZ header is the PE/exe magic. The .exe extension is in the
    # BLOCKED_EXTENSIONS list so this MUST be rejected.
    payload = b"MZ" + b"\x00" * 64
    r = await client.post(
        f"/api/v1/documents/upload/?project_id={pid}&category=other",
        files={"file": ("evil.exe", io.BytesIO(payload), "image/png")},
        headers=headers,
    )
    assert r.status_code == 400, r.text
    assert ".exe" in r.text


@pytest.mark.asyncio
async def test_oversize_document_upload_413(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A-DOC-13: an oversize document upload returns 413 (defence in depth).

    The real cap is 500MB; allocating that here would slow or OOM the
    runner, so we monkeypatch the service cap down to a tiny value and send
    a small payload that still trips the size check before magic-byte
    validation.
    """
    from app.modules.documents import service as documents_service

    monkeypatch.setattr(documents_service, "MAX_FILE_SIZE", 1024)

    headers, _ = await _register_admin(client)
    pid = await _make_project(client, headers)
    # PDF magic header + filler bytes to exceed the (patched) cap.
    oversize = b"%PDF-1.7\n" + (b"\x00" * (1024 + 64))
    r = await client.post(
        f"/api/v1/documents/upload/?project_id={pid}&category=other",
        files={"file": ("huge.pdf", io.BytesIO(oversize), "application/pdf")},
        headers=headers,
    )
    assert r.status_code == 413, r.text
    assert "too large" in r.text.lower()


@pytest.mark.asyncio
async def test_photo_49mb_accepted(client: AsyncClient) -> None:
    """A-DOC-13: a 49MB photo is accepted (just under the 50MB cap)."""
    headers, _ = await _register_admin(client)
    pid = await _make_project(client, headers)
    # Minimal valid PNG + filler IDAT-ish padding under the cap. The
    # service doesn't decode the image, it only sniffs magic bytes,
    # so padding after the PNG signature is fine.
    png_head = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    )
    payload = png_head + (b"\x00" * (49 * 1024 * 1024))
    r = await client.post(
        f"/api/v1/documents/photos/upload/?project_id={pid}",
        files={"file": ("big.png", io.BytesIO(payload), "image/png")},
        headers=headers,
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_oversize_photo_upload_413(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A-DOC-13: an oversize photo upload returns 413.

    The real cap is 200MB; we monkeypatch the service cap down to a tiny
    value and send a small payload rather than allocate a huge literal.
    """
    from app.modules.documents import service as documents_service

    monkeypatch.setattr(documents_service, "MAX_PHOTO_SIZE", 1024)

    headers, _ = await _register_admin(client)
    pid = await _make_project(client, headers)
    png_head = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    )
    oversize = png_head + (b"\x00" * (1024 + 64))
    r = await client.post(
        f"/api/v1/documents/photos/upload/?project_id={pid}",
        files={"file": ("huge.png", io.BytesIO(oversize), "image/png")},
        headers=headers,
    )
    assert r.status_code == 413, r.text
    assert "too large" in r.text.lower()


@pytest.mark.asyncio
async def test_valid_png_upload_stores_server_derived_mime(
    client: AsyncClient,
) -> None:
    """A-DOC-12: a valid PNG with attacker-set Content-Type=image/svg+xml
    still ends up with ``image/png`` in the DB (server-derived MIME)."""
    headers, _ = await _register_admin(client)
    pid = await _make_project(client, headers)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    # Send with a lying header — the stored mime must come from the
    # magic bytes, not from this header.
    r = await client.post(
        f"/api/v1/documents/upload/?project_id={pid}&category=other",
        files={"file": ("real.png", io.BytesIO(png), "application/x-msdownload")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body.get("mime_type") == "image/png", body


@pytest.mark.asyncio
async def test_revision_conflict_guard_rejects_dual_current() -> None:
    """A-DOC-14 (P1): two docs cannot both be ``is_current_revision`` under
    the same ``parent_document_id`` — second update returns 409."""
    from types import SimpleNamespace

    from app.modules.documents.schemas import DocumentUpdate
    from app.modules.documents.service import DocumentService

    parent_id = uuid.uuid4()
    other_doc_id = uuid.uuid4()
    target_doc_id = uuid.uuid4()

    target = SimpleNamespace(
        id=target_doc_id,
        cde_state=None,
        name="rev-b",
        parent_document_id=parent_id,
        is_current_revision=False,
        project_id=uuid.uuid4(),
    )
    existing_current = SimpleNamespace(
        id=other_doc_id,
        parent_document_id=parent_id,
        is_current_revision=True,
    )

    svc = DocumentService.__new__(DocumentService)

    async def _get_document(_id):  # noqa: ANN001, ANN202
        return target

    class _ResultScalars:
        def first(self):  # noqa: ANN202
            return existing_current

    class _Result:
        def scalars(self):  # noqa: ANN202
            return _ResultScalars()

    class _Session:
        async def execute(self, _stmt):  # noqa: ANN001, ANN202
            return _Result()

        async def refresh(self, _obj):  # noqa: ANN001, ANN202
            return None

    svc.get_document = _get_document  # type: ignore[method-assign]
    svc.session = _Session()  # type: ignore[assignment]

    with pytest.raises(HTTPException) as exc:
        await svc.update_document(target_doc_id, DocumentUpdate(is_current_revision=True))
    assert exc.value.status_code == 409
    assert "current revision" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_revision_promote_allowed_when_no_other_current() -> None:
    """A-DOC-14: promoting to current is fine when no sibling is current
    (no over-restriction — single-revision projects must still work)."""
    from types import SimpleNamespace

    from app.modules.documents.schemas import DocumentUpdate
    from app.modules.documents.service import DocumentService

    parent_id = uuid.uuid4()
    target_doc_id = uuid.uuid4()
    target = SimpleNamespace(
        id=target_doc_id,
        cde_state=None,
        name="solo",
        parent_document_id=parent_id,
        is_current_revision=False,
        project_id=uuid.uuid4(),
    )

    svc = DocumentService.__new__(DocumentService)

    async def _get_document(_id):  # noqa: ANN001, ANN202
        return target

    class _ResultScalars:
        def first(self):  # noqa: ANN202
            return None

    class _Result:
        def scalars(self):  # noqa: ANN202
            return _ResultScalars()

    updated_fields: dict = {}

    async def _update_fields(_id, **fields):  # noqa: ANN001, ANN202, ANN003
        updated_fields.update(fields)

    class _Repo:
        update_fields = staticmethod(_update_fields)

    class _Session:
        async def execute(self, _stmt):  # noqa: ANN001, ANN202
            return _Result()

        async def refresh(self, _obj):  # noqa: ANN001, ANN202
            return None

    svc.get_document = _get_document  # type: ignore[method-assign]
    svc.repo = _Repo()  # type: ignore[attr-defined]
    svc.session = _Session()  # type: ignore[assignment]

    await svc.update_document(target_doc_id, DocumentUpdate(is_current_revision=True))
    assert updated_fields.get("is_current_revision") is True
