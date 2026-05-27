"""Unit tests for the Enterprise Workflows module — hardening contract lock.

Covers the 2026-05-21 hardening sweep:

* EW-001  Step-count cap (MAX_STEPS) rejects runaway / infinite-loop
          workflows at create.
* EW-002  action_type whitelist rejects unknown / templated values
          (sandbox-escape vector for would-be code-exec steps).
* EW-003  Bad role string on a step is rejected at create.
* EW-004  Happy path: create workflow → submit request → approve at
          each step → status flips to "approved" on the final step.
* EW-005  Per-step audit_log entries are appended to request metadata
          on every approve / reject / cancel transition (forensic trail
          across multi-step workflows).
* EW-006  Runtime max-step guard: a request whose current_step has
          somehow exceeded MAX_STEPS is rejected loudly (defence in
          depth against corrupted / loop-edited workflows).

Per ``feedback_test_isolation.md`` every test uses an isolated temp
SQLite — never ``backend/openestimate.db``.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.enterprise_workflows.schemas import (
    ApprovalRequestCreate,
    WorkflowCreate,
)
from app.modules.enterprise_workflows.service import (
    ALLOWED_ACTION_TYPES,
    MAX_STEPS,
    WorkflowService,
)


def _register_models() -> None:
    """Import every model the test touches so Base.metadata is complete."""
    import app.modules.enterprise_workflows.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session():
    tmp_db = Path(tempfile.mkdtemp()) / "enterprise_workflows.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)
    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


async def _make_user(session: AsyncSession, *, role: str = "admin") -> uuid.UUID:
    from app.modules.users.models import User

    uid = uuid.uuid4()
    session.add(
        User(
            id=uid,
            email=f"u-{uid.hex[:6]}@test.io",
            hashed_password="x",
            full_name="U",
            role=role,
        )
    )
    await session.flush()
    return uid


# ── EW-001 — step-count cap ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_workflow_rejects_over_max_steps(session: AsyncSession) -> None:
    """A workflow definition past MAX_STEPS must be rejected at create."""
    service = WorkflowService(session)
    too_many = [{"name": f"step-{i}", "role": "editor"} for i in range(MAX_STEPS + 1)]
    with pytest.raises(HTTPException) as exc:
        await service.create_workflow(
            WorkflowCreate(
                entity_type="invoice",
                name="bad",
                steps=too_many,
            )
        )
    assert exc.value.status_code == 400
    assert "maximum" in exc.value.detail.lower()


# ── EW-002 — action_type whitelist ───────────────────────────────────────


@pytest.mark.asyncio
async def test_create_workflow_rejects_unknown_action_type(session: AsyncSession) -> None:
    """A templated / unknown action_type is rejected (sandbox-escape guard)."""
    service = WorkflowService(session)
    bad_step = [{"name": "exec", "action_type": "exec_python", "role": "admin"}]
    with pytest.raises(HTTPException) as exc:
        await service.create_workflow(WorkflowCreate(entity_type="invoice", name="bad", steps=bad_step))
    assert exc.value.status_code == 400
    assert "action_type" in exc.value.detail


@pytest.mark.asyncio
async def test_allowed_action_types_accepted(session: AsyncSession) -> None:
    """Every allowed action_type round-trips cleanly through create."""
    service = WorkflowService(session)
    steps = [{"name": at, "action_type": at, "role": "admin"} for at in ALLOWED_ACTION_TYPES]
    wf = await service.create_workflow(WorkflowCreate(entity_type="invoice", name="ok", steps=steps))
    assert len(wf.steps) == len(ALLOWED_ACTION_TYPES)


# ── EW-003 — bad role string ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_workflow_rejects_unknown_role(session: AsyncSession) -> None:
    service = WorkflowService(session)
    with pytest.raises(HTTPException) as exc:
        await service.create_workflow(
            WorkflowCreate(
                entity_type="invoice",
                name="bad-role",
                steps=[{"name": "x", "role": "<script>alert(1)</script>"}],
            )
        )
    assert exc.value.status_code == 400
    assert "role" in exc.value.detail


# ── EW-004 / EW-005 — happy path + audit log ─────────────────────────────


@pytest.mark.asyncio
async def test_two_step_workflow_approve_flow(session: AsyncSession) -> None:
    """Create → submit → approve step 1 → approve step 2 → status='approved'.

    Also verifies each approve appends an audit_log entry (EW-005).
    """
    admin_id = await _make_user(session, role="admin")
    service = WorkflowService(session)

    wf = await service.create_workflow(
        WorkflowCreate(
            entity_type="invoice",
            name="two-step",
            steps=[
                {"name": "review", "action_type": "review", "role": "manager"},
                {"name": "sign-off", "action_type": "sign_off", "role": "admin"},
            ],
        )
    )

    req = await service.submit_request(
        ApprovalRequestCreate(
            workflow_id=wf.id,
            entity_type="invoice",
            entity_id=str(uuid.uuid4()),
        ),
        user_id=str(admin_id),
    )
    assert req.current_step == 1
    assert req.status == "pending"

    # Step 1 — should advance, NOT mark approved yet.
    req = await service.approve_request(req.id, user_id=str(admin_id), decision_notes="ok1")
    assert req.current_step == 2
    assert req.status == "pending"
    audit = (req.metadata_ or {}).get("audit_log") or []
    assert len(audit) == 1
    assert audit[0]["action"] == "approve"
    assert audit[0]["step"] == 1
    assert audit[0]["actor"] == str(admin_id)
    assert audit[0]["notes"] == "ok1"

    # Step 2 — final → approved.
    req = await service.approve_request(req.id, user_id=str(admin_id), decision_notes="ok2")
    assert req.status == "approved"
    audit = (req.metadata_ or {}).get("audit_log") or []
    assert len(audit) == 2
    assert audit[1]["step"] == 2
    assert audit[1]["notes"] == "ok2"


# ── EW-006 — runtime infinite-loop guard ─────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_step_overflow_rejected(session: AsyncSession) -> None:
    """A request whose current_step has drifted past MAX_STEPS is rejected.

    Simulates a corrupted row or a workflow whose steps were trimmed
    after the request was already past the new tail. The engine must
    not silently spin or crash — it must raise loudly.
    """
    admin_id = await _make_user(session, role="admin")
    service = WorkflowService(session)

    wf = await service.create_workflow(
        WorkflowCreate(
            entity_type="invoice",
            name="loop-guard",
            steps=[{"name": "s1", "action_type": "approve", "role": "admin"}],
        )
    )
    req = await service.submit_request(
        ApprovalRequestCreate(
            workflow_id=wf.id,
            entity_type="invoice",
            entity_id=str(uuid.uuid4()),
        ),
        user_id=str(admin_id),
    )

    # Forcibly push current_step past the cap (simulates corruption).
    # Use a raw UPDATE so we don't expire the live session — the
    # repository helper calls session.expire_all() which leaves the
    # ORM identity map in a state that lazy-loads on the next attribute
    # access (a known pattern in this codebase — see feedback re
    # repository expire_all + MissingGreenlet).
    from sqlalchemy import update as sa_update

    from app.modules.enterprise_workflows.models import ApprovalRequest

    request_id = req.id
    await session.execute(
        sa_update(ApprovalRequest).where(ApprovalRequest.id == request_id).values(current_step=MAX_STEPS + 1)
    )
    await session.flush()

    with pytest.raises(HTTPException) as exc:
        await service.approve_request(request_id, user_id=str(admin_id))
    assert exc.value.status_code == 400
    assert "maximum step" in exc.value.detail.lower()
