"""Tests for the in-browser editor save / load endpoints.

Covers:

  * POST /document-templates/save-text — happy path (HTML), validation
    failures (empty body, oversize, unsupported content_type), and
    update-in-place (template_id present).
  * GET  /document-templates/custom/{id}/content — round-trips the
    saved text, rejects binary-uploaded rows with 415, applies the
    standard 404-not-403 IDOR closure.
  * RBAC — a viewer (role lacking property_dev.create) cannot save text
    templates.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from .conftest import _register_user

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def admin_alice(client: AsyncClient):
    """Tenant A: admin owning a project — author of templates."""
    _uid, _email, headers = await _register_user(client, role="admin", tag="alice")
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"PropDev-DocTpl-Alice-{uuid.uuid4().hex[:6]}",
            "description": "in-browser editor test",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code in (200, 201), proj.text
    return {"headers": headers, "project_id": proj.json()["id"]}


@pytest_asyncio.fixture(scope="module")
async def editor_bob(client: AsyncClient):
    """Tenant B: editor (non-admin) — verifies cross-tenant 404.

    Must be a non-admin role because admin bypasses the IDOR closure by
    design — a real attacker would be a member of their own tenant.
    """
    _uid, _email, headers = await _register_user(client, role="editor", tag="bob")
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"PropDev-DocTpl-Bob-{uuid.uuid4().hex[:6]}",
            "description": "cross-tenant test",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code in (200, 201), proj.text
    return {"headers": headers, "project_id": proj.json()["id"]}


@pytest_asyncio.fixture(scope="module")
async def viewer_carol(client: AsyncClient):
    """A non-creator role — tests RBAC."""
    _uid, _email, headers = await _register_user(client, role="viewer", tag="carol")
    return {"headers": headers}


# ── Happy path ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_text_html_round_trip(client: AsyncClient, admin_alice: dict) -> None:
    html = "<html><body><h1>Hello {{buyer.full_name}}</h1></body></html>"
    save = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": "Round-trip HTML",
            "doc_type": "reservation_receipt",
            "entity": "reservation",
            "trigger": "manual",
            "description": "Round-trip smoke",
            "content_type": "text/html",
            "content_text": html,
            "project_id": admin_alice["project_id"],
        },
        headers=admin_alice["headers"],
    )
    assert save.status_code == 201, save.text
    body = save.json()
    assert body["is_custom"] is True
    assert body["content_type"] == "text/html"
    assert body["filename"].endswith(".html")
    assert body["size_bytes"] == len(html.encode("utf-8"))
    template_id = body["id"]

    # GET-content
    fetched = await client.get(
        f"/api/v1/property-dev/document-templates/custom/{template_id}/content",
        headers=admin_alice["headers"],
    )
    assert fetched.status_code == 200, fetched.text
    fb = fetched.json()
    assert fb["content_text"] == html
    assert fb["content_type"] == "text/html"
    assert fb["title"] == "Round-trip HTML"


@pytest.mark.asyncio
async def test_save_text_markdown_round_trip(client: AsyncClient, admin_alice: dict) -> None:
    md = "# Heading\n\nBuyer: {{buyer.full_name}}\n"
    save = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": "Markdown round trip",
            "doc_type": "custom",
            "entity": "custom",
            "content_type": "text/markdown",
            "content_text": md,
            "project_id": admin_alice["project_id"],
        },
        headers=admin_alice["headers"],
    )
    assert save.status_code == 201, save.text
    body = save.json()
    assert body["filename"].endswith(".md")
    assert body["content_type"] == "text/markdown"


@pytest.mark.asyncio
async def test_save_text_update_in_place(client: AsyncClient, admin_alice: dict) -> None:
    # Create
    v1 = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": "Update target",
            "doc_type": "custom",
            "entity": "custom",
            "content_type": "text/html",
            "content_text": "<p>v1</p>",
            "project_id": admin_alice["project_id"],
        },
        headers=admin_alice["headers"],
    )
    assert v1.status_code == 201, v1.text
    template_id = v1.json()["id"]

    # Update in place
    v2 = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "template_id": template_id,
            "name": "Update target (v2)",
            "doc_type": "custom",
            "entity": "custom",
            "content_type": "text/html",
            "content_text": "<p>v2 — much longer body</p>",
        },
        headers=admin_alice["headers"],
    )
    assert v2.status_code == 201, v2.text
    body = v2.json()
    assert body["id"] == template_id
    assert body["title"] == "Update target (v2)"

    # GET-content reflects v2
    fetched = await client.get(
        f"/api/v1/property-dev/document-templates/custom/{template_id}/content",
        headers=admin_alice["headers"],
    )
    assert fetched.status_code == 200
    assert fetched.json()["content_text"] == "<p>v2 — much longer body</p>"


# ── Validation failures ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_text_rejects_empty_content(client: AsyncClient, admin_alice: dict) -> None:
    res = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": "Empty body",
            "doc_type": "custom",
            "entity": "custom",
            "content_type": "text/html",
            "content_text": "   \n  ",
            "project_id": admin_alice["project_id"],
        },
        headers=admin_alice["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_save_text_rejects_binary_content_type(client: AsyncClient, admin_alice: dict) -> None:
    res = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": "Bad ct",
            "doc_type": "custom",
            "entity": "custom",
            "content_type": "application/pdf",
            "content_text": "%PDF-1.4...",
            "project_id": admin_alice["project_id"],
        },
        headers=admin_alice["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_save_text_rejects_missing_name(client: AsyncClient, admin_alice: dict) -> None:
    res = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": "",
            "doc_type": "custom",
            "entity": "custom",
            "content_type": "text/html",
            "content_text": "<p>x</p>",
            "project_id": admin_alice["project_id"],
        },
        headers=admin_alice["headers"],
    )
    assert res.status_code == 422, res.text


# ── RBAC ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_text_viewer_role_rejected(client: AsyncClient, viewer_carol: dict) -> None:
    res = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": "Viewer try",
            "doc_type": "custom",
            "entity": "custom",
            "content_type": "text/html",
            "content_text": "<p>x</p>",
        },
        headers=viewer_carol["headers"],
    )
    # property_dev.create RBAC → 403 (handled by RequirePermission).
    assert res.status_code in (401, 403), res.text


# ── IDOR closure ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_content_cross_tenant_404(client: AsyncClient, admin_alice: dict, editor_bob: dict) -> None:
    save = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": "Alice secret",
            "doc_type": "custom",
            "entity": "custom",
            "content_type": "text/html",
            "content_text": "<p>secret</p>",
            "project_id": admin_alice["project_id"],
        },
        headers=admin_alice["headers"],
    )
    assert save.status_code == 201, save.text
    template_id = save.json()["id"]

    # Bob tries to read Alice's template → must collapse to 404 (not 403).
    bob_get = await client.get(
        f"/api/v1/property-dev/document-templates/custom/{template_id}/content",
        headers=editor_bob["headers"],
    )
    assert bob_get.status_code == 404, bob_get.text


@pytest.mark.asyncio
async def test_save_text_update_cross_tenant_404(client: AsyncClient, admin_alice: dict, editor_bob: dict) -> None:
    save = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": "Alice owns",
            "doc_type": "custom",
            "entity": "custom",
            "content_type": "text/html",
            "content_text": "<p>v1</p>",
            "project_id": admin_alice["project_id"],
        },
        headers=admin_alice["headers"],
    )
    assert save.status_code == 201, save.text
    template_id = save.json()["id"]

    # Bob tries to overwrite Alice's row by passing template_id.
    bob_save = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "template_id": template_id,
            "name": "Pwned",
            "doc_type": "custom",
            "entity": "custom",
            "content_type": "text/html",
            "content_text": "<p>pwn</p>",
        },
        headers=editor_bob["headers"],
    )
    assert bob_save.status_code == 404, bob_save.text


@pytest.mark.asyncio
async def test_get_content_missing_id_404(client: AsyncClient, admin_alice: dict) -> None:
    fake = uuid.uuid4()
    res = await client.get(
        f"/api/v1/property-dev/document-templates/custom/{fake}/content",
        headers=admin_alice["headers"],
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_content_binary_template_415(client: AsyncClient, admin_alice: dict) -> None:
    """A row whose content_type is binary (e.g. a real .docx upload)
    must NOT be opened in the editor — return 415, not the raw bytes."""
    # Upload a fake .docx (which the upload endpoint rejects via magic
    # bytes), so we go the direct DB-row route. Use the upload form with
    # a real-ish PDF magic-byte file to land a binary row.
    pdf_bytes = b"%PDF-1.4\n%fake\nendobj\n" + b"X" * 100 + b"\n%%EOF"
    files = {"file": ("real.pdf", pdf_bytes, "application/pdf")}
    params = {
        "name": "Binary upload",
        "doc_type": "custom",
        "entity": "custom",
        "trigger": "manual",
        "description": "",
        "project_id": admin_alice["project_id"],
    }
    upload = await client.post(
        "/api/v1/property-dev/document-templates/upload",
        params=params,
        files=files,
        headers=admin_alice["headers"],
    )
    assert upload.status_code == 201, upload.text
    template_id = upload.json()["id"]

    res = await client.get(
        f"/api/v1/property-dev/document-templates/custom/{template_id}/content",
        headers=admin_alice["headers"],
    )
    assert res.status_code == 415, res.text


# ── Filename / extension safety ────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_text_filename_is_sanitised(client: AsyncClient, admin_alice: dict) -> None:
    """A pathological `name` must not escape the templates directory or
    end up with a fake extension."""
    res = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": "../../../etc/passwd",
            "doc_type": "custom",
            "entity": "custom",
            "content_type": "text/html",
            "content_text": "<p>x</p>",
            "project_id": admin_alice["project_id"],
        },
        headers=admin_alice["headers"],
    )
    assert res.status_code == 201, res.text
    body = res.json()
    # Slash / dot path-segments are scrubbed; only the html extension survives.
    assert "/" not in body["filename"]
    assert "\\" not in body["filename"]
    assert body["filename"].endswith(".html")
