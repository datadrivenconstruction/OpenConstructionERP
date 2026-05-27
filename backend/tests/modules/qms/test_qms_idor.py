"""Integration tests: QMS IDOR ownership enforcement.

Each test seeds two users (victim / attacker), creates a resource under
the victim's project, then attempts to read / mutate / delete it as the
attacker. Every such attempt must return HTTP 404 — not 403 and not 200.
Returning 404 avoids leaking the existence of the UUID (the same behaviour
used across every R6/R7-audited module).

Router is mounted against a live in-memory SQLite session so the real
``verify_project_access`` runs against persisted ``Project.owner_id`` rows.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

# ── Per-module SQLite isolation — MUST run before app imports ────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-qms-idor-"))
_TMP_DB = _TMP_DIR / "qms_idor.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"


import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base  # noqa: E402
from app.dependencies import (  # noqa: E402
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.projects.models import Project, ProjectMilestone, ProjectWBS  # noqa: E402
from app.modules.qms.models import (  # noqa: E402
    QMSNCR,
    ITPItem,
    ITPPlan,
    ITPTemplate,
    QMSAudit,
    QMSAuditFinding,
    QMSAuditLog,
    QMSCalibration,
    QMSInspection,
    QMSInspectionSignature,
    QMSNCRAction,
    QMSPunchItem,
)
from app.modules.qms.router import router as qms_router  # noqa: E402
from app.modules.qms.schemas import (  # noqa: E402
    InspectionCreate,
    NCRCreate,
)
from app.modules.qms.service import QMSService  # noqa: E402
from app.modules.users.models import APIKey, User  # noqa: E402

_ALL_TABLES = [
    User.__table__,
    APIKey.__table__,
    Project.__table__,
    ProjectWBS.__table__,
    ProjectMilestone.__table__,
    ITPPlan.__table__,
    ITPItem.__table__,
    ITPTemplate.__table__,
    QMSInspection.__table__,
    QMSInspectionSignature.__table__,
    QMSNCR.__table__,
    QMSNCRAction.__table__,
    QMSPunchItem.__table__,
    QMSAudit.__table__,
    QMSAuditFinding.__table__,
    QMSAuditLog.__table__,
    QMSCalibration.__table__,
]


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_ALL_TABLES)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
        await sess.rollback()
    await engine.dispose()


async def _make_user(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"u{uuid.uuid4().hex[:6]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user.id


async def _make_project(session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID:
    project = Project(name="Test", owner_id=owner_id)
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project.id


def _build_app(db_session: AsyncSession, *, caller_id: str) -> FastAPI:
    app = FastAPI()
    app.include_router(qms_router, prefix="/v1/qms")

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _payload_override() -> dict[str, Any]:
        return {"sub": caller_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


# ── IDOR: GET /inspections/{id} ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_inspection_idor_404_for_attacker(
    session: AsyncSession,
) -> None:
    """Attacker guessing victim's inspection UUID must receive 404."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)

    svc = QMSService(session)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=victim_project),
    )
    await session.commit()

    app = _build_app(session, caller_id=str(attacker))
    client = TestClient(app)
    resp = client.get(f"/v1/qms/inspections/{insp.id}")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_get_inspection_200_for_owner(session: AsyncSession) -> None:
    """Project owner can retrieve their own inspection."""
    owner = await _make_user(session)
    project_id = await _make_project(session, owner)
    svc = QMSService(session)
    insp = await svc.schedule_inspection(InspectionCreate(project_id=project_id))
    await session.commit()

    app = _build_app(session, caller_id=str(owner))
    client = TestClient(app)
    resp = client.get(f"/v1/qms/inspections/{insp.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(insp.id)


# ── IDOR: GET /ncrs/{id} ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_ncr_idor_404_for_attacker(session: AsyncSession) -> None:
    """Attacker cannot read victim's NCR by UUID."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)

    svc = QMSService(session)
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=victim_project,
            title="Structural crack",
            description="Crack at joint",
            severity="major",
        ),
    )
    await session.commit()

    app = _build_app(session, caller_id=str(attacker))
    client = TestClient(app)
    resp = client.get(f"/v1/qms/ncrs/{ncr.id}")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_get_ncr_200_for_owner(session: AsyncSession) -> None:
    """Project owner can retrieve their own NCR."""
    owner = await _make_user(session)
    project_id = await _make_project(session, owner)
    svc = QMSService(session)
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=project_id,
            title="Minor gap",
            description="d",
            severity="minor",
        ),
    )
    await session.commit()

    app = _build_app(session, caller_id=str(owner))
    client = TestClient(app)
    resp = client.get(f"/v1/qms/ncrs/{ncr.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(ncr.id)


# ── IDOR: PATCH /ncrs/{id} for cross-project ─────────────────────────────


@pytest.mark.asyncio
async def test_patch_ncr_idor_404_for_attacker(session: AsyncSession) -> None:
    """Attacker cannot update victim's NCR via PATCH."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)

    svc = QMSService(session)
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=victim_project,
            title="Structural issue",
            description="d",
            severity="critical",
        ),
    )
    await session.commit()

    app = _build_app(session, caller_id=str(attacker))
    client = TestClient(app)
    resp = client.patch(
        f"/v1/qms/ncrs/{ncr.id}",
        json={"title": "Injected title"},
    )
    assert resp.status_code == 404, resp.text

    # Confirm victim's NCR was not mutated
    original = await svc.repo.get_ncr(ncr.id)
    assert original is not None
    assert original.title == "Structural issue"


# ── IDOR: POST /ncrs/{id}/close for cross-project ─────────────────────────


@pytest.mark.asyncio
async def test_close_ncr_idor_404_for_attacker(session: AsyncSession) -> None:
    """Attacker cannot close victim's NCR."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)

    svc = QMSService(session)
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=victim_project,
            title="T",
            description="d",
            severity="minor",
        ),
    )
    # Assign + verify an action so close_ncr wouldn't fail on validation
    action = await svc.assign_ncr_action(
        ncr.id,
        __import__("app.modules.qms.schemas", fromlist=["NCRActionCreate"]).NCRActionCreate(
            description="Fix",
        ),
    )
    await svc.verify_action(action.id)
    await session.commit()

    app = _build_app(session, caller_id=str(attacker))
    client = TestClient(app)
    resp = client.post(f"/v1/qms/ncrs/{ncr.id}/close")
    assert resp.status_code == 404, resp.text

    # Confirm victim's NCR is still verifying, not closed
    refreshed = await svc.repo.get_ncr(ncr.id)
    assert refreshed is not None
    assert refreshed.status == "verifying"


# ── IDOR: PATCH /inspections/{id} for cross-project ──────────────────────


@pytest.mark.asyncio
async def test_patch_inspection_idor_404_for_attacker(
    session: AsyncSession,
) -> None:
    """Attacker cannot mutate victim's inspection."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)

    svc = QMSService(session)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=victim_project, notes="original"),
    )
    await session.commit()

    app = _build_app(session, caller_id=str(attacker))
    client = TestClient(app)
    resp = client.patch(
        f"/v1/qms/inspections/{insp.id}",
        json={"notes": "hacked"},
    )
    assert resp.status_code == 404, resp.text

    # Confirm original notes unchanged
    original = await svc.repo.get_inspection(insp.id)
    assert original is not None
    assert original.notes == "original"
