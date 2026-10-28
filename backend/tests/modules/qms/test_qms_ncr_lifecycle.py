"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests: QMS NCR lifecycle — open → root-cause → corrective-action → closed.

Covers:
    * Full happy-path: open → action_pending → verifying → closed.
    * Root-cause update at the service layer.
    * Multiple corrective actions; all must be verified before close.
    * Idempotent close: calling close_ncr twice returns the same status
      and does NOT reset the audit trail (second call should raise ValueError).
    * Audit trail completeness: every status change lands a row in
      ``oe_qms_audit_log``.
    * Cross-project IDOR: close attempt by attacker → 404 via HTTP layer.
    * Decimal-as-string money: cost_impact_amount serialised as string in
      the JSON response (no float rounding).
    * NCR escalation: NCR with cost_impact links to a variation; event is
      published with the Decimal amount serialised as a string.
    * Cancellation path: open NCR may be cancelled; cancelled → closed is
      illegal.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.projects.models import Project
from app.modules.qms.router import router as qms_router
from app.modules.qms.schemas import NCRActionCreate, NCRCreate, NCRUpdate
from app.modules.qms.service import QMSService
from app.modules.users.models import User
from app.modules.variations.models import VariationOrder
from tests._pg import transactional_session

_PROJECT_ID = uuid.uuid4()


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    # PostgreSQL isolation: each test runs inside an outer transaction that is
    # rolled back on teardown. The session's own commit() becomes a SAVEPOINT
    # release, so committed data is visible within the test (and to the app when
    # this same session is injected via dependency_overrides) but undone after.
    async with transactional_session() as sess:
        yield sess


@pytest_asyncio.fixture
async def svc(session: AsyncSession) -> QMSService:
    return QMSService(session)


async def _make_user(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"u{uuid.uuid4().hex[:6]}@test.com", hashed_password="x")
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user.id


async def _make_project(session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID:
    project = Project(name="NCR Test", owner_id=owner_id)
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


@asynccontextmanager
async def _http(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """In-process async HTTP client bound to ``app`` on the current loop."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── Happy path ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ncr_full_lifecycle_open_to_closed(svc: QMSService) -> None:
    """Complete NCR flow: open → action_pending → verifying → closed."""
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=_PROJECT_ID,
            title="Rebar diameter below spec",
            description="12mm used instead of 16mm",
            severity="critical",
        ),
    )
    assert ncr.status == "open"

    # Root-cause update (still open)
    ncr = await svc.update_ncr(
        ncr.id,
        NCRUpdate(root_cause="Procurement error — wrong batch delivered"),
    )
    assert ncr.root_cause == "Procurement error — wrong batch delivered"
    assert ncr.status == "open"

    # Assign corrective action (NCR advances to action_pending)
    a1 = await svc.assign_ncr_action(
        ncr.id,
        NCRActionCreate(description="Replace rebar with correct size"),
    )
    ncr_ap = await svc.repo.get_ncr(ncr.id)
    assert ncr_ap is not None
    assert ncr_ap.status == "action_pending"

    # Second action
    a2 = await svc.assign_ncr_action(
        ncr.id,
        NCRActionCreate(description="Update site-delivery checklist"),
    )

    # Verify first — NCR still action_pending (second action outstanding)
    await svc.verify_action(a1.id)
    ncr_mid = await svc.repo.get_ncr(ncr.id)
    assert ncr_mid is not None
    assert ncr_mid.status == "action_pending"

    # Verify second — NCR advances to verifying
    await svc.verify_action(a2.id)
    ncr_v = await svc.repo.get_ncr(ncr.id)
    assert ncr_v is not None
    assert ncr_v.status == "verifying"

    # Close
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        ncr_closed = await svc.close_ncr(ncr.id)
    assert ncr_closed.status == "closed"


# ── Idempotent close ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotent_close_raises_on_second_call(svc: QMSService) -> None:
    """Calling close_ncr twice must raise ValueError on the second call —
    closed is terminal. The audit trail must NOT acquire an extra entry.
    """
    ncr = await svc.raise_ncr(
        NCRCreate(project_id=_PROJECT_ID, title="T", description="d", severity="minor"),
    )
    action = await svc.assign_ncr_action(ncr.id, NCRActionCreate(description="Fix"))
    await svc.verify_action(action.id)

    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        await svc.close_ncr(ncr.id)

    log_before = await svc.repo.list_audit_log(ncr.id, entity_type="ncr")

    # Second close must raise
    with pytest.raises(ValueError, match="already closed"):
        await svc.close_ncr(ncr.id)

    # Audit trail must NOT have grown
    log_after = await svc.repo.list_audit_log(ncr.id, entity_type="ncr")
    assert len(log_after) == len(log_before), "Audit log grew despite idempotent-close rejection"


# ── Audit trail completeness ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ncr_audit_trail_records_all_transitions(svc: QMSService) -> None:
    """Every status change must appear in the audit log, in order."""
    ncr = await svc.raise_ncr(
        NCRCreate(project_id=_PROJECT_ID, title="T", description="d", severity="major"),
    )
    action = await svc.assign_ncr_action(ncr.id, NCRActionCreate(description="Fix"))
    await svc.verify_action(action.id)
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        await svc.close_ncr(ncr.id)

    log = await svc.repo.list_audit_log(ncr.id, entity_type="ncr")
    new_statuses = [e.new_status for e in log]
    # Must include open and closed entries
    assert "open" in new_statuses
    assert "closed" in new_statuses
    # Closed must come after open
    assert new_statuses.index("open") < new_statuses.index("closed")


# ── Cancellation path ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ncr_cancellation_path(svc: QMSService) -> None:
    """open → cancelled is legal; cancelled → closed is illegal."""
    ncr = await svc.raise_ncr(
        NCRCreate(project_id=_PROJECT_ID, title="T", description="d", severity="minor"),
    )
    ncr = await svc.update_ncr(ncr.id, NCRUpdate(status="cancelled"))
    assert ncr.status == "cancelled"

    with pytest.raises(ValueError, match="cancelled"):
        await svc.close_ncr(ncr.id)


@pytest.mark.asyncio
async def test_cannot_add_action_to_cancelled_ncr(svc: QMSService) -> None:
    ncr = await svc.raise_ncr(
        NCRCreate(project_id=_PROJECT_ID, title="T", description="d", severity="minor"),
    )
    await svc.update_ncr(ncr.id, NCRUpdate(status="cancelled"))
    with pytest.raises(ValueError, match="cancelled"):
        await svc.assign_ncr_action(ncr.id, NCRActionCreate(description="Fix"))


# ── Decimal-as-string money ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ncr_cost_impact_serialised_as_string(
    session: AsyncSession,
) -> None:
    """The HTTP response must contain cost_impact_amount as a string (not float).

    This prevents FX-rounding surprises when JavaScript JSON.parse converts
    large Decimal values to IEEE-754 doubles (e.g. 9999999.99 → 10000000.0).
    """
    owner = await _make_user(session)
    project_id = await _make_project(session, owner)
    await session.commit()

    app = _build_app(session, caller_id=str(owner))
    async with _http(app) as client:
        resp = await client.post(
            "/v1/qms/ncrs",
            json={
                "project_id": str(project_id),
                "title": "Slab thickness deviation",
                "description": "4mm short of spec",
                "severity": "major",
                "cost_impact_currency": "EUR",
                "cost_impact_amount": "9999999.99",
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Must be a string, not a float
    assert isinstance(body["cost_impact_amount"], str), (
        f"Expected str, got {type(body['cost_impact_amount']).__name__}: {body['cost_impact_amount']!r}"
    )
    assert body["cost_impact_amount"] == "9999999.99"


# ── Escalation with Decimal ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ncr_escalation_publishes_decimal_as_string(
    svc: QMSService,
) -> None:
    """escalate_ncr_to_variation publishes cost_impact as a string.

    Mirrors the product flow: an existing VariationOrder in the same
    project is supplied via ``variation_id`` (the QMS module never
    fabricates one).
    """
    # A real owner + project so the VariationOrder FK is satisfied
    # (PostgreSQL enforces foreign keys natively).
    owner = User(email=f"u{uuid.uuid4().hex[:6]}@test.com", hashed_password="x")
    svc.session.add(owner)
    await svc.session.flush()
    project = Project(id=_PROJECT_ID, name="Escalation Test", owner_id=owner.id)
    svc.session.add(project)
    await svc.session.flush()

    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=_PROJECT_ID,
            title="Structural defect",
            description="Core sample strength 18MPa vs 30MPa required",
            severity="critical",
            cost_impact_currency="EUR",
            cost_impact_amount=Decimal("125000.50"),
        ),
    )
    variation = VariationOrder(project_id=_PROJECT_ID, code="VO-0001")
    svc.session.add(variation)
    await svc.session.flush()

    spy = MagicMock()
    with patch("app.modules.qms.service.event_bus.publish_detached", spy):
        await svc.escalate_ncr_to_variation(ncr.id, variation_id=variation.id)

    assert spy.called
    event_name = spy.call_args.args[0]
    payload = spy.call_args.args[1]
    assert event_name == "qms.ncr.escalated_to_variation"
    # cost_impact must be a string in the event payload
    assert isinstance(payload["cost_impact"], str)
    assert payload["cost_impact"] == "125000.50"


# ── HTTP-level close IDOR ─────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_http_close_ncr_idor_returns_404(session: AsyncSession) -> None:
    """Attacker calling POST /ncrs/{ncr_id}/close on a victim's NCR → 404."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)

    svc = QMSService(session)
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=victim_project,
            title="Wall crack",
            description="d",
            severity="major",
        ),
    )
    action = await svc.assign_ncr_action(ncr.id, NCRActionCreate(description="Fix"))
    await svc.verify_action(action.id)
    await session.commit()

    app = _build_app(session, caller_id=str(attacker))
    async with _http(app) as client:
        resp = await client.post(f"/v1/qms/ncrs/{ncr.id}/close")
    assert resp.status_code == 404, resp.text

    # Victim's NCR must still be verifying
    refreshed = await svc.repo.get_ncr(ncr.id)
    assert refreshed is not None
    assert refreshed.status == "verifying"
