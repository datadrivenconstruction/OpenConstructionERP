"""Magic-byte hardening for ``POST /api/v1/fieldreports/reports/import/file/``.

The import route used to trust the uploader-supplied filename extension
(``.xlsx`` / ``.xls`` / ``.csv``) for both routing and validation. Any
authenticated caller could rename a Windows ``.exe`` (or, more
realistically, an arbitrary attacker-crafted blob) to ``foo.xlsx`` and
ship it past the filename gate — openpyxl would then attempt to parse
the bytes and either crash the worker or trigger memory growth.

The fix:

* Cap the request body at 25 MB before any parser is touched.
* Verify the magic bytes of ``.xlsx`` (must be ZIP container) and
  ``.xls`` (must be OLE compound doc) against the project's pure-stdlib
  signature detector.

CSV stays best-effort — it has no magic bytes — but the size cap
above still applies.
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-fr-import-magic-"))
_TMP_DB = _TMP_DIR / "fr_import_magic.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

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
        from app.modules.fieldreports import models as _fr_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate_user(email: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()


async def _promote_admin(email: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()


@pytest_asyncio.fixture(scope="module")
async def owner_project(http_client):
    email = f"importer-{uuid.uuid4().hex[:8]}@fr-import-magic.io"
    password = f"FrImportMagic{uuid.uuid4().hex[:6]}9"

    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "import"},
    )
    assert reg.status_code in (200, 201), reg.text

    await _promote_admin(email)
    await _activate_user(email)

    login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"FR-import {uuid.uuid4().hex[:6]}",
            "description": "fr-import-magic-byte tests",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return {"headers": headers, "project_id": proj.json()["id"]}


def _real_xlsx_bytes() -> bytes:
    """Build a minimal but valid xlsx via openpyxl so the happy-path check
    actually exercises the magic-byte detector + openpyxl reader."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Field Reports"
    ws.append(["Date", "Weather", "Description"])
    ws.append(["2026-05-22", "clear", "smoke-test row"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ── Rejection cases ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_executable_renamed_xlsx_is_rejected(http_client, owner_project):
    """An MZ-header .exe blob renamed to .xlsx must 400 before openpyxl."""
    fake_exe = b"MZ" + b"\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00" + b"\x00" * 200

    resp = await http_client.post(
        f"/api/v1/fieldreports/reports/import/file/?project_id={owner_project['project_id']}",
        headers=owner_project["headers"],
        files={"file": ("malicious.xlsx", fake_exe, "application/octet-stream")},
    )
    assert resp.status_code == 400, f"executable accepted as xlsx: {resp.status_code} {resp.text!r}"
    assert "content does not match" in resp.text.lower() or "signature" in resp.text.lower()


@pytest.mark.asyncio
async def test_random_blob_renamed_xlsx_is_rejected(http_client, owner_project):
    """Random bytes pretending to be xlsx → rejected on magic byte mismatch."""
    blob = b"NOT-A-REAL-XLSX-this-is-just-random-text" * 4
    resp = await http_client.post(
        f"/api/v1/fieldreports/reports/import/file/?project_id={owner_project['project_id']}",
        headers=owner_project["headers"],
        files={"file": ("plain.xlsx", blob, "application/octet-stream")},
    )
    assert resp.status_code == 400, f"random blob accepted as xlsx: {resp.status_code} {resp.text!r}"


@pytest.mark.asyncio
async def test_oversize_upload_rejected(http_client, owner_project):
    """A 26 MB upload must 400 before any parser allocates."""
    big = b"," * (26 * 1024 * 1024)
    resp = await http_client.post(
        f"/api/v1/fieldreports/reports/import/file/?project_id={owner_project['project_id']}",
        headers=owner_project["headers"],
        files={"file": ("big.csv", big, "text/csv")},
    )
    assert resp.status_code == 400, f"oversize upload accepted: {resp.status_code} {resp.text!r}"
    assert "maximum size" in resp.text.lower() or "exceed" in resp.text.lower()


# ── Happy path ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_real_xlsx_is_accepted(http_client, owner_project):
    """A genuine openpyxl-produced xlsx passes the magic-byte check."""
    xlsx_bytes = _real_xlsx_bytes()
    resp = await http_client.post(
        f"/api/v1/fieldreports/reports/import/file/?project_id={owner_project['project_id']}",
        headers=owner_project["headers"],
        files={
            "file": (
                "good.xlsx",
                xlsx_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # We sent one data row → imported should be 1.
    assert body["imported"] == 1, body


@pytest.mark.asyncio
async def test_csv_is_accepted(http_client, owner_project):
    """CSV has no magic byte; size cap is the only guard but a small
    payload must still pass through end-to-end."""
    csv_body = b"Date,Weather,Description\n2026-05-23,clear,csv-smoke\n"
    resp = await http_client.post(
        f"/api/v1/fieldreports/reports/import/file/?project_id={owner_project['project_id']}",
        headers=owner_project["headers"],
        files={"file": ("good.csv", csv_body, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 1, body
