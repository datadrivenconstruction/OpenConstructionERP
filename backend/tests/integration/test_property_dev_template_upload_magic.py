"""Magic-byte gate for the Property-Dev custom-template upload endpoint.

Mirrors the v4.2.x defense-in-depth pattern used by Punchlist photos,
correspondence attachments and submittal attachments: the upload route
must reject files whose content does not match their declared extension,
even if extension + Content-Type say otherwise.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-propdev-tpl-magic-"))
_TMP_DB = _TMP_DIR / "propdev_tpl_magic.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import io  # noqa: E402
import zipfile  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.property_dev import models as _m  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


@pytest_asyncio.fixture(scope="module")
async def tenant(http_client):
    email = f"tpl-magic-{uuid.uuid4().hex[:6]}@propdev.io"
    password = f"TplMagic{uuid.uuid4().hex[:6]}9!"
    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "TplMagic"},
    )
    assert reg.status_code in (200, 201), reg.text
    await _set_role(email, "admin")

    res = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

    proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"TplMagic {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return {
        "headers": headers,
        "project_id": proj.json()["id"],
    }


def _zip_bytes() -> bytes:
    """Minimal but valid OOXML-shaped zip (PK\\x03\\x04 header)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
        zf.writestr("word/document.xml", "<?xml version='1.0'?><doc/>")
    return buf.getvalue()


def _common_form(name: str) -> dict[str, str]:
    return {
        "name": name,
        "doc_type": "custom",
        "entity": "custom",
        "trigger": "manual",
        "description": "",
    }


async def _upload(
    client: AsyncClient,
    tenant: dict,
    *,
    filename: str,
    content: bytes,
    content_type: str,
):
    return await client.post(
        "/api/v1/property-dev/document-templates/upload",
        params={**_common_form(f"Tpl {filename}"), "project_id": tenant["project_id"]},
        files={"file": (filename, content, content_type)},
        headers=tenant["headers"],
    )


@pytest.mark.asyncio
async def test_docx_with_valid_zip_magic_accepted(http_client, tenant):
    res = await _upload(
        http_client,
        tenant,
        filename="kyc.docx",
        content=_zip_bytes(),
        content_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_xlsx_with_valid_zip_magic_accepted(http_client, tenant):
    res = await _upload(
        http_client,
        tenant,
        filename="rate-card.xlsx",
        content=_zip_bytes(),
        content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_pdf_with_valid_magic_accepted(http_client, tenant):
    pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    res = await _upload(
        http_client,
        tenant,
        filename="receipt.pdf",
        content=pdf_body,
        content_type="application/pdf",
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_html_with_html_root_accepted(http_client, tenant):
    body = b"<!DOCTYPE html>\n<html><body><h1>{{buyer.full_name}}</h1></body></html>"
    res = await _upload(
        http_client,
        tenant,
        filename="cover.html",
        content=body,
        content_type="text/html",
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_md_plain_text_accepted(http_client, tenant):
    res = await _upload(
        http_client,
        tenant,
        filename="notes.md",
        content=b"# Notes\n\nHello {{buyer.full_name}}\n",
        content_type="text/markdown",
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_docx_with_jpeg_payload_rejected(http_client, tenant):
    jpeg_body = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 32
    res = await _upload(
        http_client,
        tenant,
        filename="evil.docx",
        content=jpeg_body,
        content_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    )
    assert res.status_code == 415, res.text


@pytest.mark.asyncio
async def test_exe_renamed_to_docx_rejected(http_client, tenant):
    mz_body = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 64
    res = await _upload(
        http_client,
        tenant,
        filename="totally-not-malware.docx",
        content=mz_body,
        content_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    )
    assert res.status_code == 415, res.text


@pytest.mark.asyncio
async def test_pdf_with_wrong_magic_rejected(http_client, tenant):
    res = await _upload(
        http_client,
        tenant,
        filename="receipt.pdf",
        content=b"not a pdf at all just some random text",
        content_type="application/pdf",
    )
    assert res.status_code == 415, res.text


@pytest.mark.asyncio
async def test_md_with_null_bytes_rejected(http_client, tenant):
    res = await _upload(
        http_client,
        tenant,
        filename="binary.md",
        content=b"# Title\n\nText\x00binary payload\xff\xfe",
        content_type="text/markdown",
    )
    assert res.status_code == 415, res.text


@pytest.mark.asyncio
async def test_unknown_extension_rejected(http_client, tenant):
    res = await _upload(
        http_client,
        tenant,
        filename="payload.exe",
        content=b"MZ\x90\x00",
        content_type="application/octet-stream",
    )
    assert res.status_code == 415, res.text
