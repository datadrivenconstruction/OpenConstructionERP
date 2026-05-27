"""Round 5 + R7 audit tests for the QMS module.

Scope (closes Round 5 audit findings):
    * IDOR closure on calibration GET / PATCH / DELETE / LIST / EXPIRING:
      a caller with an unrelated project must not be able to read,
      update, delete, or enumerate another project's calibration
      certificates by guessing UUIDs (or by passing ``project_id=None``).
    * Cross-project list defence: list endpoints reject ``project_id=None``
      with a 400 rather than silently leaking the whole tenant.
    * Currency consistency on NCR raise: a non-zero ``cost_impact_amount``
      with an empty ``cost_impact_currency`` is rejected at the service
      boundary so COPQ aggregates stay currency-coherent.
    * Project-default currency fallback on COPQ reports: when the caller
      passes an empty ``currency`` query param the response substitutes
      the project's configured currency (no silent EUR/USD hardcode).
    * Duplicate-signer guard: the same ``(user_id, role)`` cannot be
      recorded twice against one inspection (defends a malicious or
      misbehaving client from inflating the signature count toward the
      ``signatories_required`` invariant).
    * Filter allowlist on ``GET /ncrs``: an out-of-spec ``severity=`` or
      ``status=`` value is rejected by the Pydantic ``pattern=`` guard
      with 422 instead of silently returning an empty page.

The tests reuse the same in-memory-SQLite fixture style as
``backend/tests/unit/test_qms.py`` so the QMS-only models can be
created without dragging the full module graph in. Router-layer tests
mount a focused FastAPI app with dependency overrides for
``verify_project_access`` / ``RequirePermission`` — the same pattern
``test_correspondence.py`` uses for the magic-byte gate.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.projects.models import Project, ProjectMilestone, ProjectWBS
from app.modules.qms.models import (
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
from app.modules.qms.router import router as qms_router
from app.modules.qms.schemas import (
    CalibrationCreate,
    InspectionCreate,
    InspectionSignatureCreate,
    NCRCreate,
)
from app.modules.qms.service import QMSService
from app.modules.users.models import APIKey, User

# ── Shared fixtures (mirror test_qms.py) ──────────────────────────────────


_QMS_TABLES = [
    # Project + User tables are needed so the real
    # ``verify_project_access`` (used by the calibration IDOR tests) can
    # resolve ownership against a live row instead of returning a stub
    # 404 from a dependency override (the calibration handlers call the
    # function directly inside the route body, so ``dependency_overrides``
    # would not intercept it).
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


async def _make_user(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"u{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user.id


async def _make_project(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    currency: str = "EUR",
) -> uuid.UUID:
    project = Project(name="Test Project", owner_id=owner_id, currency=currency)
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project.id


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test in-memory SQLite session with QMS tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_QMS_TABLES)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
        await sess.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def svc(session: AsyncSession) -> QMSService:
    return QMSService(session)


# ── Service-level: NCR currency consistency ─────────────────────────────


@pytest.mark.asyncio
async def test_raise_ncr_rejects_amount_without_currency(svc: QMSService) -> None:
    """An NCR with a positive ``cost_impact_amount`` and an empty
    ``cost_impact_currency`` is rejected — COPQ aggregates would
    otherwise silently roll up currency-less monetary values.
    """
    project_id = uuid.uuid4()
    with pytest.raises(ValueError, match="cost_impact_currency"):
        await svc.raise_ncr(
            NCRCreate(
                project_id=project_id,
                title="Concrete crack",
                description="Spalling at slab edge",
                severity="major",
                cost_impact_amount=Decimal("15000.00"),
                cost_impact_currency="",
            ),
            user_id=str(uuid.uuid4()),
        )


@pytest.mark.asyncio
async def test_raise_ncr_allows_zero_amount_without_currency(
    svc: QMSService,
) -> None:
    """Zero / null amounts are still legal — the guard only fires when
    a real monetary value would be stored without a currency tag.
    """
    project_id = uuid.uuid4()
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=project_id,
            title="Documentation gap",
            description="Missing inspection record",
            severity="minor",
        ),
        user_id=str(uuid.uuid4()),
    )
    assert ncr.cost_impact_currency == ""
    assert ncr.cost_impact_amount is None


# ── Service-level: duplicate signer guard ────────────────────────────────


@pytest.mark.asyncio
async def test_signature_dedup_same_user_same_role(svc: QMSService) -> None:
    """The same ``(user, role)`` cannot sign the same inspection twice.

    Defends the ``signatories_required`` invariant: without this the
    inspector could inflate the signature count by replaying the same
    payload N times to meet the threshold.
    """
    project_id = uuid.uuid4()
    insp = await svc.schedule_inspection(InspectionCreate(project_id=project_id))
    signer = uuid.uuid4()
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(
            signer_user_id=signer,
            signer_role="GC",
        ),
    )
    with pytest.raises(ValueError, match="already signed"):
        await svc.add_signature(
            insp.id,
            InspectionSignatureCreate(
                signer_user_id=signer,
                signer_role="GC",
            ),
        )


@pytest.mark.asyncio
async def test_signature_same_user_different_role_allowed(
    svc: QMSService,
) -> None:
    """One person wearing two hats (GC + designer reviewer) can still
    sign in both roles — only ``(user, role)`` pairs are deduplicated.
    """
    project_id = uuid.uuid4()
    insp = await svc.schedule_inspection(InspectionCreate(project_id=project_id))
    signer = uuid.uuid4()
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(
            signer_user_id=signer,
            signer_role="GC",
        ),
    )
    sig = await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(
            signer_user_id=signer,
            signer_role="designer",
        ),
    )
    assert sig.signer_role == "designer"


# ── Service-level: project-default currency fallback ─────────────────────


@pytest.mark.asyncio
async def test_copq_falls_back_to_project_currency(svc: QMSService) -> None:
    """If the caller passes ``currency=""`` and a Project row exists with
    a configured ``currency`` we surface that instead of the empty
    string — no hardcoded EUR / USD.
    """
    project_id = uuid.uuid4()

    # Stub a ProjectRepository.get_by_id returning a fake project. We use
    # ``patch`` to avoid pulling in the full ``projects`` module + its
    # migrations into the minimal-fixture session.
    fake_project = type("FakeProject", (), {"currency": "BRL"})()
    fake_repo = MagicMock()
    fake_repo.get_by_id = AsyncMock(return_value=fake_project)
    with patch(
        "app.modules.projects.repository.ProjectRepository",
        return_value=fake_repo,
    ):
        data = await svc.compute_copq(project_id, currency="")
    assert data["currency"] == "BRL"


@pytest.mark.asyncio
async def test_copq_explicit_currency_wins(svc: QMSService) -> None:
    """An explicit ``currency=USD`` query param overrides the
    project default — the caller has presumably already FX-converted
    figures so we must not silently relabel them.
    """
    project_id = uuid.uuid4()
    fake_project = type("FakeProject", (), {"currency": "BRL"})()
    fake_repo = MagicMock()
    fake_repo.get_by_id = AsyncMock(return_value=fake_project)
    with patch(
        "app.modules.projects.repository.ProjectRepository",
        return_value=fake_repo,
    ):
        data = await svc.compute_copq(project_id, currency="USD")
    assert data["currency"] == "USD"


@pytest.mark.asyncio
async def test_copq_currency_unknown_when_lookup_fails(svc: QMSService) -> None:
    """When the Project lookup itself raises (e.g. no projects table in a
    minimal install) the report degrades to currency="" rather than
    substituting a hardcoded default — the caller is then expected to
    surface a "currency unknown" indicator.
    """
    project_id = uuid.uuid4()
    fake_repo = MagicMock()
    fake_repo.get_by_id = AsyncMock(side_effect=RuntimeError("no projects table"))
    with patch(
        "app.modules.projects.repository.ProjectRepository",
        return_value=fake_repo,
    ):
        data = await svc.compute_copq(project_id, currency="")
    assert data["currency"] == ""


# ── Router-level: calibration IDOR + list discipline ─────────────────────


def _build_qms_app(
    db_session: AsyncSession,
    *,
    caller_id: str,
) -> FastAPI:
    """Mount the QMS router against a live in-memory DB.

    Ownership is resolved by the real ``verify_project_access`` against
    the seeded ``Project.owner_id`` so the IDOR gate is exercised end
    to end (rather than via a dependency override, which the
    calibration handlers bypass by calling the function directly).
    """
    app = FastAPI()
    app.include_router(qms_router, prefix="/v1/qms")

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _payload_override() -> dict[str, Any]:
        # ``role=admin`` short-circuits ``RequirePermission`` for every
        # QMS permission — we're not testing RBAC here, only the
        # ownership-based IDOR / allowlist guards. ``verify_project_access``
        # ALSO has an admin bypass based on the persisted ``User.role``
        # column; the IDOR tests seed callers with the default
        # (non-admin) user row so the access check actually runs against
        # ``Project.owner_id`` and not the admin shortcut.
        return {"sub": caller_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


@pytest.mark.asyncio
async def test_get_calibration_idor_returns_404_for_foreign_project(
    session: AsyncSession,
) -> None:
    """Caller can only ``GET /calibrations/{id}`` for calibrations whose
    project the caller owns. A foreign-project calibration surfaces as
    404 (the same way a missing one does) so we don't leak the
    existence of the UUID.
    """
    victim = await _make_user(session)
    attacker = await _make_user(session)
    foreign_project = await _make_project(session, victim)

    svc = QMSService(session)
    cal = await svc.create_calibration(
        CalibrationCreate(
            project_id=foreign_project,
            instrument_id="INST-001",
            instrument_name="Total station X",
            instrument_type="survey",
            calibration_date=__import__("datetime").date(2026, 1, 1),
            valid_until=__import__("datetime").date(2026, 7, 1),
        ),
    )
    await session.commit()

    app = _build_qms_app(session, caller_id=str(attacker))
    client = TestClient(app)
    resp = client.get(f"/v1/qms/calibrations/{cal.id}")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_patch_calibration_idor_returns_404_for_foreign_project(
    session: AsyncSession,
) -> None:
    victim = await _make_user(session)
    attacker = await _make_user(session)
    foreign_project = await _make_project(session, victim)

    svc = QMSService(session)
    cal = await svc.create_calibration(
        CalibrationCreate(
            project_id=foreign_project,
            instrument_id="INST-001",
            instrument_name="Pull tester",
            instrument_type="rebar",
            calibration_date=__import__("datetime").date(2026, 1, 1),
            valid_until=__import__("datetime").date(2026, 7, 1),
        ),
    )
    await session.commit()

    app = _build_qms_app(session, caller_id=str(attacker))
    client = TestClient(app)
    resp = client.patch(
        f"/v1/qms/calibrations/{cal.id}",
        json={"manufacturer": "Pwned Inc."},
    )
    assert resp.status_code == 404, resp.text

    # And the foreign row was not mutated.
    untouched = await svc.repo.get_calibration(cal.id)
    assert untouched is not None
    assert (untouched.manufacturer or "") != "Pwned Inc."


@pytest.mark.asyncio
async def test_delete_calibration_idor_returns_404_for_foreign_project(
    session: AsyncSession,
) -> None:
    victim = await _make_user(session)
    attacker = await _make_user(session)
    foreign_project = await _make_project(session, victim)

    svc = QMSService(session)
    cal = await svc.create_calibration(
        CalibrationCreate(
            project_id=foreign_project,
            instrument_id="INST-001",
            instrument_name="Cube press",
            instrument_type="concrete",
            calibration_date=__import__("datetime").date(2026, 1, 1),
            valid_until=__import__("datetime").date(2026, 7, 1),
        ),
    )
    await session.commit()

    app = _build_qms_app(session, caller_id=str(attacker))
    client = TestClient(app)
    resp = client.delete(f"/v1/qms/calibrations/{cal.id}")
    assert resp.status_code == 404, resp.text

    # And the row is still there — the foreign caller did not delete it.
    still_there = await svc.repo.get_calibration(cal.id)
    assert still_there is not None


@pytest.mark.asyncio
async def test_list_calibrations_rejects_missing_project_id(
    session: AsyncSession,
) -> None:
    """The list endpoint must require ``project_id``. Without it we
    cannot gate the response by tenant — Round-4 IDOR convention.
    """
    caller = await _make_user(session)
    await session.commit()
    app = _build_qms_app(session, caller_id=str(caller))
    client = TestClient(app)
    resp = client.get("/v1/qms/calibrations")
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_list_expiring_calibrations_rejects_missing_project_id(
    session: AsyncSession,
) -> None:
    caller = await _make_user(session)
    await session.commit()
    app = _build_qms_app(session, caller_id=str(caller))
    client = TestClient(app)
    resp = client.get("/v1/qms/calibrations/expiring")
    assert resp.status_code == 400, resp.text


# ── Router-level: severity / status allowlist ────────────────────────────


@pytest.mark.asyncio
async def test_list_ncrs_rejects_unknown_severity(
    session: AsyncSession,
) -> None:
    """Bad ``severity=`` value is rejected with 422 by the FastAPI
    pattern guard rather than being passed through to SQL where it
    would silently return an empty page (with no signal that the
    filter was bogus).
    """
    owner = await _make_user(session)
    project_id = await _make_project(session, owner)
    await session.commit()
    app = _build_qms_app(session, caller_id=str(owner))
    client = TestClient(app)
    resp = client.get(
        "/v1/qms/ncrs",
        params={"project_id": str(project_id), "severity": "BOGUS"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_list_ncrs_rejects_unknown_status(
    session: AsyncSession,
) -> None:
    owner = await _make_user(session)
    project_id = await _make_project(session, owner)
    await session.commit()
    app = _build_qms_app(session, caller_id=str(owner))
    client = TestClient(app)
    resp = client.get(
        "/v1/qms/ncrs",
        params={"project_id": str(project_id), "status": "exploded"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_list_ncrs_accepts_known_severity(
    session: AsyncSession,
) -> None:
    """Sanity: legal severity values still pass through and return 200."""
    owner = await _make_user(session)
    project_id = await _make_project(session, owner)
    await session.commit()
    app = _build_qms_app(session, caller_id=str(owner))
    client = TestClient(app)
    resp = client.get(
        "/v1/qms/ncrs",
        params={"project_id": str(project_id), "severity": "major"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


# ── R7 additions: magic-byte upload gate ─────────────────────────────────


@pytest.mark.asyncio
async def test_inspection_attachment_upload_rejects_bad_magic_bytes(
    session: AsyncSession,
) -> None:
    """A file with an unknown/disallowed magic-byte signature is rejected
    with HTTP 415 — the content-type header is never trusted.
    """
    owner = await _make_user(session)
    project_id = await _make_project(session, owner)
    await session.commit()

    svc = QMSService(session)
    insp = await svc.schedule_inspection(InspectionCreate(project_id=project_id))
    await session.commit()

    app = _build_qms_app(session, caller_id=str(owner))
    client = TestClient(app)
    # Craft a payload whose magic bytes are not in the allowed set
    # (16 null bytes followed by arbitrary content — not pdf/png/jpeg/…)
    bad_content = b"\x00" * 16 + b"<script>alert(1)</script>"
    resp = client.post(
        f"/v1/qms/inspections/{insp.id}/attachments",
        files={"file": ("evil.html", bad_content, "text/html")},
    )
    assert resp.status_code == 415, resp.text


@pytest.mark.asyncio
async def test_inspection_attachment_upload_accepts_pdf(
    session: AsyncSession,
) -> None:
    """A valid PDF magic bytes payload is accepted (HTTP 201)."""
    owner = await _make_user(session)
    project_id = await _make_project(session, owner)
    await session.commit()

    svc = QMSService(session)
    insp = await svc.schedule_inspection(InspectionCreate(project_id=project_id))
    await session.commit()

    app = _build_qms_app(session, caller_id=str(owner))
    client = TestClient(app)
    # Minimal PDF magic bytes
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n%%EOF"
    resp = client.post(
        f"/v1/qms/inspections/{insp.id}/attachments",
        files={"file": ("report.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "filename" in body
    assert body["size_bytes"] == len(pdf_bytes)


@pytest.mark.asyncio
async def test_ncr_attachment_upload_rejects_empty_file(
    session: AsyncSession,
) -> None:
    """An empty upload body is rejected with HTTP 400 (not 500)."""
    owner = await _make_user(session)
    project_id = await _make_project(session, owner)
    await session.commit()

    svc = QMSService(session)
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=project_id,
            title="Rebar crack",
            description="d",
            severity="minor",
        ),
    )
    await session.commit()

    app = _build_qms_app(session, caller_id=str(owner))
    client = TestClient(app)
    resp = client.post(
        f"/v1/qms/ncrs/{ncr.id}/attachments",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_ncr_attachment_upload_idor_404_for_attacker(
    session: AsyncSession,
) -> None:
    """Attacker cannot upload to a victim's NCR — must get 404."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)
    await session.commit()

    svc = QMSService(session)
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=victim_project,
            title="Crack",
            description="d",
            severity="minor",
        ),
    )
    await session.commit()

    app = _build_qms_app(session, caller_id=str(attacker))
    client = TestClient(app)
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n%%EOF"
    resp = client.post(
        f"/v1/qms/ncrs/{ncr.id}/attachments",
        files={"file": ("report.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 404, resp.text


# ── R7 additions: GET single endpoints ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_inspection_idor_attacker_gets_404(
    session: AsyncSession,
) -> None:
    """GET /inspections/{id} must return 404 for a foreign-project caller."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)
    await session.commit()

    svc = QMSService(session)
    insp = await svc.schedule_inspection(InspectionCreate(project_id=victim_project))
    await session.commit()

    app = _build_qms_app(session, caller_id=str(attacker))
    client = TestClient(app)
    resp = client.get(f"/v1/qms/inspections/{insp.id}")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_get_ncr_idor_attacker_gets_404(session: AsyncSession) -> None:
    """GET /ncrs/{id} must return 404 for a foreign-project caller."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)
    await session.commit()

    svc = QMSService(session)
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=victim_project,
            title="T",
            description="d",
            severity="minor",
        ),
    )
    await session.commit()

    app = _build_qms_app(session, caller_id=str(attacker))
    client = TestClient(app)
    resp = client.get(f"/v1/qms/ncrs/{ncr.id}")
    assert resp.status_code == 404, resp.text


# ── R7 additions: Decimal-as-string serialisation ─────────────────────────


@pytest.mark.asyncio
async def test_ncr_read_cost_impact_is_string_not_float(
    session: AsyncSession,
) -> None:
    """NCR response must serialise cost_impact_amount as a JSON string."""
    owner = await _make_user(session)
    project_id = await _make_project(session, owner)
    await session.commit()

    app = _build_qms_app(session, caller_id=str(owner))
    client = TestClient(app)

    resp = client.post(
        "/v1/qms/ncrs",
        json={
            "project_id": str(project_id),
            "title": "Concrete strength below spec",
            "description": "Cube test 23MPa vs 30MPa",
            "severity": "critical",
            "cost_impact_currency": "EUR",
            "cost_impact_amount": "12345.67",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert isinstance(body["cost_impact_amount"], str), (
        f"cost_impact_amount must be a string, got {type(body['cost_impact_amount'])}"
    )
    assert body["cost_impact_amount"] == "12345.67"
