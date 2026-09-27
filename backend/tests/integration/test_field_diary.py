# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Integration tests for the Field Diary MVP (task #113 / Epic F).

End-to-end exercises:
    * PIN-gated magic-link request → consume → session-bearer flow.
    * Diary FSM (draft → submit; can't edit after submit; idempotent submit).
    * Attachment size cap (read from the enforcing constant, not remembered).
    * PIN header is required on every field endpoint (magic-link alone is not enough).
    * Wrong PIN returns 401.
    * Mocked SMS provider records the payload for assertion.
"""

from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

os.environ["EXPOSE_DEV_AUTH_SECRETS"] = "true"  # so request-magic-link returns dev_token/dev_pin

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.dependencies import get_session  # noqa: E402
from app.modules.field_diary import models as fd_models  # noqa: E402,F401
from app.modules.field_diary.models import DiaryEntry  # noqa: E402
from app.modules.field_diary.router import router as fd_router  # noqa: E402
from app.modules.field_diary.service import (  # noqa: E402
    FieldDiaryService,
    clear_sms_log,
    get_sms_log,
)
from app.modules.projects.models import Project  # noqa: E402
from app.modules.users.models import User  # noqa: E402
from tests._pg import isolated_engine  # noqa: E402

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def engine_and_session():
    # PostgreSQL isolation: a throwaway database cloned from the full-schema
    # template. The app opens its OWN independent sessions per request from this
    # engine and relies on data committed in the test's seeding sessions being
    # visible across those separate connections, so a real engine (not a
    # rolled-back transactional session) is required here.
    async with isolated_engine() as engine:
        SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
        yield engine, SessionFactory


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
    assert body["dev_token"] is not None  # EXPOSE_DEV_AUTH_SECRETS=true
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
    # EXPOSE_DEV_AUTH_SECRETS=true → plaintext exposed in body for test convenience.
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
async def test_diary_attachment_upload_size_limit(app_and_client, monkeypatch) -> None:
    """An attachment over the cap is rejected with 413, whatever the cap is."""
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

    # Read the cap rather than remembering it. This test asserted a hard 26 MB
    # against a remembered 25 MB limit, and the enforced constant had been
    # raised to 200 MB without it: the upload was accepted, and the failure said
    # the cap was broken when what had actually broken was the test's memory of
    # it. A number worth enforcing is worth reading from the thing enforcing it.
    from app.modules.field_diary import router as diary_router

    cap = diary_router.MAX_ATTACHMENT_BYTES
    monkeypatch.setattr(diary_router, "MAX_ATTACHMENT_BYTES", 1024 * 1024)

    oversized = b"\x00" * (1024 * 1024 + 1)
    files = {"file": ("big.bin", oversized, "application/octet-stream")}
    r = await client.post(
        f"/v1/field-diary/entries/{entry_id}/attachments/",
        headers=headers,
        files=files,
    )
    assert r.status_code == 413
    # The refusal has to quote the cap it is actually enforcing. A message
    # naming a different number sends somebody to shrink a file that would
    # have been accepted, or to give up on one that would not.
    assert "1 MB" in r.json()["detail"]

    # And the real cap is a sane one. A phone on site uploads photos and short
    # video over a connection that may be a bar of signal, so this is a number
    # somebody chose, not a default to drift.
    assert cap == 200 * 1024 * 1024


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


@pytest.mark.asyncio
async def test_offline_activity_replay_is_idempotent(app_and_client) -> None:
    """A queued activity replayed twice (same client_op_id) creates ONE row.

    This is the durable-sync-ledger guarantee for TOP-30 #14: the offline field
    shell drains at-least-once (a reconnect that fires twice, or a write whose
    response was lost), re-sending the same op. Without the server-side ledger
    the by-date activity append inserted a duplicate row each time - duplicate
    logged hours feeding duplicate payroll labour. The ledger keyed on
    client_op_id must collapse the replay to a single activity.
    """
    from sqlalchemy import func, select

    from app.modules.field_diary.models import DiaryActivity, FieldSyncLedger

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

    date = "2026-05-25"
    op_id = "11111111-2222-3333-4444-555555555555"
    body = {
        "activity_type": "work",
        "description": "Poured slab zone A",
        "hours": "8",
        "started_at": f"{date}T07:00:00",
        "ended_at": f"{date}T15:00:00",
        "metadata": {"task": "concrete"},
        "client_op_id": op_id,
    }

    # First replay: applies, returns 201 with the new activity id.
    r1 = await client.post(
        f"/v1/field-diary/entries/by-date/{date}/activities/",
        headers=headers,
        json=body,
    )
    assert r1.status_code == 201, r1.text
    first_id = r1.json()["id"]

    # Second replay of the SAME op_id (the "reconnect fired twice" case).
    r2 = await client.post(
        f"/v1/field-diary/entries/by-date/{date}/activities/",
        headers=headers,
        json=body,
    )
    assert r2.status_code == 201, r2.text
    # The server returned the ORIGINAL row, not a fresh one.
    assert r2.json()["id"] == first_id

    # Exactly one activity row and one ledger row exist.
    async with SessionFactory() as s:
        act_count = (await s.execute(select(func.count()).select_from(DiaryActivity))).scalar_one()
        assert act_count == 1
        ledger = (
            await s.execute(
                select(FieldSyncLedger).where(FieldSyncLedger.client_op_id == op_id),
            )
        ).scalar_one()
        assert str(ledger.result_id) == str(first_id)
        assert ledger.op_kind == "field.diary.activity"


@pytest.mark.asyncio
async def test_online_activity_without_op_id_not_deduplicated(app_and_client) -> None:
    """Two direct (online) appends with no client_op_id are two distinct rows.

    Dedup is opt-in on the device-supplied key; an online caller that omits it
    gets normal append-only behaviour (no accidental collapse of two real
    distinct activities).
    """
    from sqlalchemy import func, select

    from app.modules.field_diary.models import DiaryActivity

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

    date = "2026-05-26"
    body = {"activity_type": "work", "description": "shift", "hours": "4"}

    for _ in range(2):
        r = await client.post(
            f"/v1/field-diary/entries/by-date/{date}/activities/",
            headers=headers,
            json=body,
        )
        assert r.status_code == 201, r.text

    async with SessionFactory() as s:
        act_count = (await s.execute(select(func.count()).select_from(DiaryActivity))).scalar_one()
        assert act_count == 2


# ── Approval is what costs the hours ──────────────────────────────────────


async def _submitted_entry_with_hours(client, SessionFactory, headers, date: str) -> uuid.UUID:  # noqa: N803
    """An entry carrying four payable hours, submitted and awaiting approval."""
    r = await client.post(
        f"/v1/field-diary/entries/by-date/{date}/activities/",
        headers=headers,
        json={"activity_type": "work", "description": "shift", "hours": "4"},
    )
    assert r.status_code == 201, r.text

    async with SessionFactory() as s:
        entry_id = (await s.execute(select(DiaryEntry.id).where(DiaryEntry.entry_date == date))).scalar_one()

    r = await client.post(f"/v1/field-diary/entries/{entry_id}/submit/", headers=headers)
    assert r.status_code == 200, r.text
    return entry_id


@pytest.mark.asyncio
async def test_submitting_no_longer_costs_the_hours(app_and_client, monkeypatch) -> None:
    """Submitting says the worker finished writing, not that anyone checked it.

    These hours land on a budget line's actuals, and the person submitting is
    the person the hours pay. The desktop timesheet has always needed a
    manager; the same hours captured on site now need one too.
    """
    _app, client, SessionFactory = app_and_client
    _owner_id, project_id = await _seed_user_and_project(SessionFactory)
    token, pin, _uid = await _request_link_and_grant(client, SessionFactory, project_id=project_id)
    session_token = await _open_session(client, token, pin)
    headers = {"Authorization": f"Bearer {session_token}", "X-Field-PIN": pin}

    published: list[dict] = []
    monkeypatch.setattr(
        "app.modules.field_diary.events.publish_diary_labour",
        lambda **kwargs: published.append(kwargs),
    )

    await _submitted_entry_with_hours(client, SessionFactory, headers, "2026-06-01")

    assert published == [], "submitting must not reach the cost model"

    async with SessionFactory() as s:
        stamped = (
            await s.execute(select(DiaryEntry.labour_published_at).where(DiaryEntry.entry_date == "2026-06-01"))
        ).scalar_one()
    assert stamped is None


@pytest.mark.asyncio
async def test_approving_costs_the_hours_exactly_once(app_and_client, monkeypatch) -> None:
    _app, client, SessionFactory = app_and_client
    _owner_id, project_id = await _seed_user_and_project(SessionFactory)
    token, pin, _uid = await _request_link_and_grant(client, SessionFactory, project_id=project_id)
    session_token = await _open_session(client, token, pin)
    headers = {"Authorization": f"Bearer {session_token}", "X-Field-PIN": pin}

    published: list[dict] = []
    monkeypatch.setattr(
        "app.modules.field_diary.events.publish_diary_labour",
        lambda **kwargs: published.append(kwargs),
    )

    entry_id = await _submitted_entry_with_hours(client, SessionFactory, headers, "2026-06-02")

    from app.modules.field_diary.service import FieldDiaryService as _Svc

    async with SessionFactory() as s:
        service = _Svc(s)
        await service.approve_diary_entry(entry_id, approver_id=_owner_id)
        await s.commit()

    assert len(published) == 1, "approval is what costs the hours"
    assert published[0]["entry_id"] == str(entry_id)

    # Approving again must not cost them a second time. The FSM returns early
    # on an already-approved entry, and the mark backs that up independently.
    async with SessionFactory() as s:
        service = _Svc(s)
        await service.approve_diary_entry(entry_id, approver_id=_owner_id)
        await s.commit()

    assert len(published) == 1


@pytest.mark.asyncio
async def test_an_entry_already_costed_on_submit_is_not_costed_again(app_and_client, monkeypatch) -> None:
    """The upgrade case, which is the one that would break a live project.

    Every entry submitted before this change had its hours costed on submit.
    The migration marks them, and approving one of them afterwards must not
    post the same hours a second time.
    """
    _app, client, SessionFactory = app_and_client
    _owner_id, project_id = await _seed_user_and_project(SessionFactory)
    token, pin, _uid = await _request_link_and_grant(client, SessionFactory, project_id=project_id)
    session_token = await _open_session(client, token, pin)
    headers = {"Authorization": f"Bearer {session_token}", "X-Field-PIN": pin}

    published: list[dict] = []
    monkeypatch.setattr(
        "app.modules.field_diary.events.publish_diary_labour",
        lambda **kwargs: published.append(kwargs),
    )

    entry_id = await _submitted_entry_with_hours(client, SessionFactory, headers, "2026-06-03")

    # Stand in for what the migration writes on an install that was running
    # the old behaviour.
    from datetime import UTC, datetime

    from sqlalchemy import update as sa_update

    async with SessionFactory() as s:
        await s.execute(
            sa_update(DiaryEntry).where(DiaryEntry.id == entry_id).values(labour_published_at=datetime.now(UTC))
        )
        await s.commit()

    from app.modules.field_diary.service import FieldDiaryService as _Svc

    async with SessionFactory() as s:
        service = _Svc(s)
        entry = await service.approve_diary_entry(entry_id, approver_id=_owner_id)
        await s.commit()
        assert entry.status == "approved", "the approval itself still goes through"

    assert published == []


@pytest.mark.asyncio
async def test_a_field_worker_cannot_approve_their_own_entry(app_and_client) -> None:
    """The approve route is on standard RBAC, not the field grant.

    Every other route in this module authenticates the worker through the PIN
    and magic link. That is right for capture and wrong for sign-off: the
    session belongs to the person the hours pay.
    """
    _app, client, SessionFactory = app_and_client
    _owner_id, project_id = await _seed_user_and_project(SessionFactory)
    token, pin, _uid = await _request_link_and_grant(client, SessionFactory, project_id=project_id)
    session_token = await _open_session(client, token, pin)
    headers = {"Authorization": f"Bearer {session_token}", "X-Field-PIN": pin}

    entry_id = await _submitted_entry_with_hours(client, SessionFactory, headers, "2026-06-04")

    r = await client.post(f"/v1/field-diary/entries/{entry_id}/approve/", headers=headers)
    assert r.status_code in (401, 403), r.text

    async with SessionFactory() as s:
        status_now = (await s.execute(select(DiaryEntry.status).where(DiaryEntry.id == entry_id))).scalar_one()
    assert status_now == "submitted"


# ── Project roster ────────────────────────────────────────────────────────


async def _add_resource(
    SessionFactory,  # noqa: N803
    *,
    name: str,
    home_project_id: uuid.UUID | None = None,
    resource_type: str = "person",
    status: str = "active",
) -> uuid.UUID:
    from app.modules.resources.models import Resource

    async with SessionFactory() as s:
        row = Resource(
            code=f"R-{uuid.uuid4().hex[:8]}",
            name=name,
            resource_type=resource_type,
            status=status,
            home_project_id=home_project_id,
        )
        s.add(row)
        await s.flush()
        rid = row.id
        await s.commit()
    return rid


async def _assign(SessionFactory, resource_id: uuid.UUID, project_id: uuid.UUID) -> None:  # noqa: N803
    import datetime as _dt

    from app.modules.resources.models import Assignment

    async with SessionFactory() as s:
        s.add(
            Assignment(
                resource_id=resource_id,
                project_id=project_id,
                start_at=_dt.datetime(2026, 6, 1, tzinfo=_dt.UTC),
                end_at=_dt.datetime(2026, 6, 30, tzinfo=_dt.UTC),
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_roster_offers_the_people_who_work_this_project(app_and_client) -> None:
    """Both ways a project staffs itself, and no third project's people.

    A resource homed on the project is site labour. A resource from the shared
    pool with an assignment here is somebody lent for the month. A foreman on
    site sees no difference between the two and would not accept "not on the
    list" for either.
    """
    _app, client, SessionFactory = app_and_client
    _owner_id, project_id = await _seed_user_and_project(SessionFactory)
    _other_owner, other_project = await _seed_user_and_project(SessionFactory)

    await _add_resource(SessionFactory, name="Homed Here", home_project_id=project_id)
    lent = await _add_resource(SessionFactory, name="Lent From Pool")
    await _assign(SessionFactory, lent, project_id)
    await _add_resource(SessionFactory, name="Somebody Else", home_project_id=other_project)
    await _add_resource(SessionFactory, name="Unassigned Pool Person")

    token, pin, _uid = await _request_link_and_grant(client, SessionFactory, project_id=project_id)
    session_token = await _open_session(client, token, pin)
    headers = {"Authorization": f"Bearer {session_token}", "X-Field-PIN": pin}

    r = await client.get("/v1/field-diary/roster/", headers=headers)
    assert r.status_code == 200, r.text
    names = {row["name"] for row in r.json()}
    assert "Homed Here" in names
    assert "Lent From Pool" in names
    assert "Somebody Else" not in names
    assert "Unassigned Pool Person" not in names


@pytest.mark.asyncio
async def test_roster_carries_the_id_the_timesheet_matches_on(app_and_client) -> None:
    """The whole point of the list: the row has the resource id on it.

    A name is not a key. Hours captured against a typed name cannot be
    reconciled with the desktop timesheet, so the same person is counted from
    both sides and neither screen says so.
    """
    _app, client, SessionFactory = app_and_client
    _owner_id, project_id = await _seed_user_and_project(SessionFactory)
    rid = await _add_resource(SessionFactory, name="Marta Nowak", home_project_id=project_id)

    token, pin, _uid = await _request_link_and_grant(client, SessionFactory, project_id=project_id)
    session_token = await _open_session(client, token, pin)
    headers = {"Authorization": f"Bearer {session_token}", "X-Field-PIN": pin}

    r = await client.get("/v1/field-diary/roster/", headers=headers)
    assert r.status_code == 200, r.text
    row = next(item for item in r.json() if item["name"] == "Marta Nowak")
    assert row["id"] == str(rid)
    assert row["code"]
    assert row["resource_type"] == "person"
    # A phone is not a payroll screen. It gets who somebody is, not what they cost.
    assert "default_cost_rate" not in row
    assert "currency" not in row


@pytest.mark.asyncio
async def test_roster_leaves_out_what_a_punch_clock_is_not_for(app_and_client) -> None:
    """An excavator does not punch in, and a leaver is not on site."""
    _app, client, SessionFactory = app_and_client
    _owner_id, project_id = await _seed_user_and_project(SessionFactory)

    await _add_resource(SessionFactory, name="Gang One", home_project_id=project_id, resource_type="crew")
    await _add_resource(SessionFactory, name="CAT 320", home_project_id=project_id, resource_type="equipment")
    await _add_resource(
        SessionFactory,
        name="Left In March",
        home_project_id=project_id,
        status="inactive",
    )

    token, pin, _uid = await _request_link_and_grant(client, SessionFactory, project_id=project_id)
    session_token = await _open_session(client, token, pin)
    headers = {"Authorization": f"Bearer {session_token}", "X-Field-PIN": pin}

    r = await client.get("/v1/field-diary/roster/", headers=headers)
    assert r.status_code == 200, r.text
    names = {row["name"] for row in r.json()}
    assert "Gang One" in names
    assert "CAT 320" not in names
    assert "Left In March" not in names


@pytest.mark.asyncio
async def test_roster_needs_a_field_session(app_and_client) -> None:
    """A workforce list is not public. Same gate as every other field route."""
    _app, client, SessionFactory = app_and_client
    _owner_id, project_id = await _seed_user_and_project(SessionFactory)
    await _add_resource(SessionFactory, name="Homed Here", home_project_id=project_id)

    r = await client.get("/v1/field-diary/roster/")
    assert r.status_code in (401, 403), r.text

    token, pin, _uid = await _request_link_and_grant(client, SessionFactory, project_id=project_id)
    session_token = await _open_session(client, token, pin)
    # Session token without the PIN header is not a session.
    r = await client.get("/v1/field-diary/roster/", headers={"Authorization": f"Bearer {session_token}"})
    assert r.status_code in (401, 403), r.text
