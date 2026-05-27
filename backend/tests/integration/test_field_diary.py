# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Integration tests for the Field Diary MVP (task #113 / Epic F).

End-to-end exercises:
    * PIN-gated magic-link request → consume → session-bearer flow.
    * Diary FSM (draft → submit; can't edit after submit; idempotent submit).
    * Attachment size cap (25 MB).
    * PIN header is required on every field endpoint (magic-link alone is not enough).
    * Wrong PIN returns 401.
    * Mocked SMS provider records the payload for assertion.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import AsyncIterator

# ── Per-module SQLite isolation (must run BEFORE app imports) ─────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-field-diary-"))
_TMP_DB = _TMP_DIR / "field_diary.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"
os.environ["APP_DEBUG"] = "true"  # so request-magic-link returns dev_token/dev_pin

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.database import Base  # noqa: E402
from app.dependencies import get_session  # noqa: E402
from app.modules.field_diary import models as fd_models  # noqa: E402,F401
from app.modules.field_diary.router import router as fd_router  # noqa: E402
from app.modules.field_diary.service import (  # noqa: E402
    FieldDiaryService,
    clear_sms_log,
    get_sms_log,
)
from app.modules.projects.models import Project, ProjectMilestone, ProjectWBS  # noqa: E402
from app.modules.users.models import APIKey, User  # noqa: E402

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def engine_and_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                APIKey.__table__,
                Project.__table__,
                ProjectWBS.__table__,
                ProjectMilestone.__table__,
                fd_models.DiaryEntry.__table__,
                fd_models.DiaryActivity.__table__,
                fd_models.DiaryAttachment.__table__,
                fd_models.FieldModuleGrant.__table__,
                fd_models.FieldMagicLink.__table__,
                fd_models.FieldSession.__table__,
            ],
        )
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    yield engine, SessionFactory
    await engine.dispose()


@pytest_asyncio.fixture
async def app_and_client(engine_and_session) -> AsyncIterator[tuple]:
    _engine, SessionFactory = engine_and_session

    app = FastAPI()
    app.include_router(fd_router, prefix="/v1/field-diary")

    async def _session_override():
        async with SessionFactory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = _session_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield app, client, SessionFactory


async def _seed_user_and_project(SessionFactory) -> tuple[uuid.UUID, uuid.UUID]:  # noqa: N803
    async with SessionFactory() as s:
        owner = User(
            email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="x",
            role="admin",
        )
        s.add(owner)
        await s.flush()
        proj = Project(
            name=f"P-{uuid.uuid4().hex[:6]}",
            owner_id=owner.id,
        )
        s.add(proj)
        await s.flush()
        owner_id = owner.id
        proj_id = proj.id
        await s.commit()
    return owner_id, proj_id


async def _request_link_and_grant(
    client,
    SessionFactory,  # noqa: N803 — sqlalchemy convention is PascalCase here
    *,
    project_id: uuid.UUID,
    phone: str = "+491701234567",
) -> tuple[str, str, uuid.UUID]:
    """Drive the auth flow + admin grant to a usable ``(token, pin, user_id)``."""
    clear_sms_log()

    # 1) Request magic link (no auth required) — provisions a field user.
    r = await client.post(
        "/v1/field-diary/auth/request-magic-link/",
        json={
            "phone": phone,
            "project_id": str(project_id),
            "module_key": "field_diary",
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["accepted"] is True
    assert body["dev_token"] is not None  # APP_DEBUG=true
    assert body["dev_pin"] is not None
    assert len(body["dev_pin"]) == 6

    # Confirm SMS sink captured the payload.
    sms = get_sms_log()
    assert len(sms) == 1
    assert sms[0]["phone"] == phone
    assert "PIN" in sms[0]["body"]
    assert body["dev_pin"] in sms[0]["body"]

    # Resolve the provisioned user_id.
    from sqlalchemy import select

    synth = f"field+{phone.lstrip('+')}@field.local"
    async with SessionFactory() as s:
        row = (await s.execute(select(User).where(User.email == synth))).scalar_one()
        user_id = row.id

    # 2) Operator grants the module (raw service call — admin RBAC path
    #    isn't wired in this isolated FastAPI test app).
    async with SessionFactory() as s:
        svc = FieldDiaryService(s)
        from app.modules.field_diary.schemas import FieldModuleGrantCreate

        await svc.create_grant(
            FieldModuleGrantCreate(
                user_id=user_id,
                project_id=project_id,
                module_key="field_diary",
            ),
            granted_by=user_id,
        )
        await s.commit()

    return body["dev_token"], body["dev_pin"], user_id


async def _open_session(client, token: str, pin: str) -> str:
    r = await client.post(
        "/v1/field-diary/auth/consume/",
        json={"token": token, "pin": pin},
    )
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_magic_link_logs_sms(app_and_client) -> None:
    """The mocked SMS sender records the dispatched payload."""
    _app, client, SessionFactory = app_and_client
    _owner, project_id = await _seed_user_and_project(SessionFactory)
    clear_sms_log()

    r = await client.post(
        "/v1/field-diary/auth/request-magic-link/",
        json={
            "phone": "+491701234567",
            "project_id": str(project_id),
            "module_key": "field_diary",
        },
    )
    assert r.status_code == 202
    body = r.json()
    # APP_DEBUG=true → plaintext exposed in body for test convenience.
    assert body["dev_token"]
    assert body["dev_pin"]

    sms = get_sms_log()
    assert len(sms) == 1
    assert sms[0]["phone"] == "+491701234567"
    assert body["dev_pin"] in sms[0]["body"]
    assert body["dev_token"] in sms[0]["body"]


@pytest.mark.asyncio
async def test_pin_required_on_field_endpoints(app_and_client) -> None:
    """Bearer session-token alone is not enough — X-Field-PIN must be present."""
    _app, client, SessionFactory = app_and_client
    _owner, project_id = await _seed_user_and_project(SessionFactory)
    token, pin, _user_id = await _request_link_and_grant(
        client,
        SessionFactory,
        project_id=project_id,
    )
    session_token = await _open_session(client, token, pin)

    # Hitting an endpoint WITHOUT the PIN header → 401.
    r = await client.get(
        "/v1/field-diary/entries/",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert r.status_code == 401
    assert "PIN" in r.json()["detail"]

    # With the PIN header → 200 (empty list).
    r = await client.get(
        "/v1/field-diary/entries/",
        headers={
            "Authorization": f"Bearer {session_token}",
            "X-Field-PIN": pin,
        },
    )
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_pin_wrong_returns_401(app_and_client) -> None:
    """A correct token paired with a wrong PIN is 401."""
    _app, client, SessionFactory = app_and_client
    _owner, project_id = await _seed_user_and_project(SessionFactory)
    token, pin, _user_id = await _request_link_and_grant(
        client,
        SessionFactory,
        project_id=project_id,
    )
    session_token = await _open_session(client, token, pin)

    bad_pin = "000000" if pin != "000000" else "999999"
    r = await client.get(
        "/v1/field-diary/entries/",
        headers={
            "Authorization": f"Bearer {session_token}",
            "X-Field-PIN": bad_pin,
        },
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_diary_entry_lifecycle(app_and_client) -> None:
    """draft → submit; submit is idempotent; can't edit after submit."""
    _app, client, SessionFactory = app_and_client
    _owner, project_id = await _seed_user_and_project(SessionFactory)
    token, pin, _user_id = await _request_link_and_grant(
        client,
        SessionFactory,
        project_id=project_id,
    )
    session_token = await _open_session(client, token, pin)
    headers = {
        "Authorization": f"Bearer {session_token}",
        "X-Field-PIN": pin,
    }

    # Create draft.
    r = await client.post(
        "/v1/field-diary/entries/",
        headers=headers,
        json={
            "project_id": str(project_id),
            "entry_date": "2026-05-25",
            "weather": "Sunny",
            "headcount": 5,
            "notes_md": "Poured slab in zone A.",
        },
    )
    assert r.status_code == 201, r.text
    entry = r.json()
    entry_id = entry["id"]
    assert entry["status"] == "draft"

    # PATCH draft — succeeds.
    r = await client.patch(
        f"/v1/field-diary/entries/{entry_id}/",
        headers=headers,
        json={"headcount": 7},
    )
    assert r.status_code == 200
    assert r.json()["headcount"] == 7

    # Submit.
    r = await client.post(
        f"/v1/field-diary/entries/{entry_id}/submit/",
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "submitted"

    # Submit again — idempotent (still 200, still submitted).
    r = await client.post(
        f"/v1/field-diary/entries/{entry_id}/submit/",
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "submitted"

    # PATCH after submit — rejected (409).
    r = await client.patch(
        f"/v1/field-diary/entries/{entry_id}/",
        headers=headers,
        json={"headcount": 99},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_diary_attachment_upload_size_limit(app_and_client) -> None:
    """An attachment > 25 MB is rejected with 413."""
    _app, client, SessionFactory = app_and_client
    _owner, project_id = await _seed_user_and_project(SessionFactory)
    token, pin, _user_id = await _request_link_and_grant(
        client,
        SessionFactory,
        project_id=project_id,
    )
    session_token = await _open_session(client, token, pin)
    headers = {
        "Authorization": f"Bearer {session_token}",
        "X-Field-PIN": pin,
    }

    # Create a draft to attach to.
    r = await client.post(
        "/v1/field-diary/entries/",
        headers=headers,
        json={
            "project_id": str(project_id),
            "entry_date": "2026-05-25",
            "notes_md": "Initial.",
        },
    )
    assert r.status_code == 201
    entry_id = r.json()["id"]

    # Build a 26 MB payload — over the 25 MB cap.
    oversized = b"\x00" * (26 * 1024 * 1024)
    files = {"file": ("big.bin", oversized, "application/octet-stream")}
    r = await client.post(
        f"/v1/field-diary/entries/{entry_id}/attachments/",
        headers=headers,
        files=files,
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_diary_endpoint_blocked_without_grant(app_and_client) -> None:
    """A valid session for a project the user has NO grant on returns 403."""
    _app, client, SessionFactory = app_and_client
    _owner, project_id = await _seed_user_and_project(SessionFactory)

    # Run the auth flow but DO NOT grant the module.
    from sqlalchemy import select

    clear_sms_log()
    phone = "+491709999000"
    r = await client.post(
        "/v1/field-diary/auth/request-magic-link/",
        json={
            "phone": phone,
            "project_id": str(project_id),
            "module_key": "field_diary",
        },
    )
    assert r.status_code == 202
    body = r.json()

    session_token = await _open_session(client, body["dev_token"], body["dev_pin"])

    r = await client.get(
        "/v1/field-diary/entries/",
        headers={
            "Authorization": f"Bearer {session_token}",
            "X-Field-PIN": body["dev_pin"],
        },
    )
    assert r.status_code == 403
    assert "grant" in r.json()["detail"].lower()

    # Sanity check: the user was provisioned, just without a grant.
    synth = f"field+{phone.lstrip('+')}@field.local"
    async with SessionFactory() as s:
        u = (await s.execute(select(User).where(User.email == synth))).scalar_one_or_none()
        assert u is not None


@pytest.mark.asyncio
async def test_diary_entry_unique_per_author_date(app_and_client) -> None:
    """Same author can't create two entries on the same date."""
    _app, client, SessionFactory = app_and_client
    _owner, project_id = await _seed_user_and_project(SessionFactory)
    token, pin, _user_id = await _request_link_and_grant(
        client,
        SessionFactory,
        project_id=project_id,
    )
    session_token = await _open_session(client, token, pin)
    headers = {
        "Authorization": f"Bearer {session_token}",
        "X-Field-PIN": pin,
    }

    payload = {
        "project_id": str(project_id),
        "entry_date": "2026-05-25",
        "notes_md": "first",
    }
    r = await client.post(
        "/v1/field-diary/entries/",
        headers=headers,
        json=payload,
    )
    assert r.status_code == 201

    # Same author + date → 409.
    r = await client.post(
        "/v1/field-diary/entries/",
        headers=headers,
        json=payload,
    )
    assert r.status_code == 409
