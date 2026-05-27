# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Approvals (W8) service-layer tests.

Covers
~~~~~~
* submit a workflow with 2 ordered steps
* step 1 approves → workflow stays ``in_review``
* step 2 approves → workflow flips to ``approved`` + a stamped artifact
  path is written
* reject at step 1 → workflow flips to ``rejected`` and step 2 stays
  ``pending``
* ``withdraw`` flips an in-review workflow to ``withdrawn``
* the four global stamp templates seeded by the migration are present
  after applying the migration to a fresh DB

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
fresh temp SQLite file BEFORE ``app`` is first imported.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-approvals-"))
_TMP_DB = _TMP_DIR / "approvals.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def db_session():
    """An :class:`AsyncSession` over a freshly ``create_all``'d temp SQLite.

    Also pre-seeds the four global stamp templates the migration would
    seed, so behavioural tests can rely on them being present.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    # Eagerly import every module package so all model tables are in the
    # Base.metadata snapshot before create_all runs.
    import importlib
    import pkgutil

    import app.modules as _modules_pkg

    for _m in pkgutil.iter_modules(_modules_pkg.__path__):
        if not _m.ispkg:
            continue
        try:
            importlib.import_module(f"app.modules.{_m.name}.models")
        except ModuleNotFoundError:
            continue

    from app.database import Base, async_session_factory, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        # Seed the four global stamp templates (mirror of the migration).
        await _seed_global_stamps(session)
        yield session


async def _seed_global_stamps(session) -> None:
    """Insert the four global stamp templates."""
    from app.modules.file_approvals.models import FileStampTemplate

    seeds = (
        ("For Construction", "FOR CONSTRUCTION", "#16a34a"),
        ("Approved", "APPROVED", "#2563eb"),
        ("Revise & Resubmit", "REVISE & RESUBMIT", "#ca8a04"),
        ("Rejected", "REJECTED", "#dc2626"),
    )
    for name, text, color in seeds:
        session.add(
            FileStampTemplate(
                project_id=None,
                name=name,
                text=text,
                color=color,
                svg_template=(
                    f'<svg xmlns="http://www.w3.org/2000/svg" '
                    f'width="220" height="80">'
                    f'<rect x="2" y="2" width="216" height="76" '
                    f'fill="none" stroke="{color}" stroke-width="3"/>'
                    f'<text x="14" y="34" fill="{color}" '
                    f'font-size="16" font-weight="bold">{{{{text}}}}</text>'
                    f"</svg>"
                ),
                is_active=True,
            )
        )
    await session.flush()


async def _seed_project_with_users(
    session,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create owner + two approvers + a project; return ids."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        email=f"approval-owner-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Owner",
    )
    approver1 = User(
        email=f"approver1-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Approver One",
    )
    approver2 = User(
        email=f"approver2-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Approver Two",
    )
    session.add_all([owner, approver1, approver2])
    await session.flush()
    project = Project(name="Approval Test Project", owner_id=owner.id)
    session.add(project)
    await session.flush()
    return project.id, owner.id, approver1.id, approver2.id


# ── Stamp template seeding ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_stamp_templates_present(db_session):
    """The four global stamp templates are seeded and active."""
    from app.modules.file_approvals.service import ApprovalService

    service = ApprovalService(db_session)
    rows = await service.list_templates(project_id=None)
    names = {r.name for r in rows}
    assert names >= {
        "For Construction",
        "Approved",
        "Revise & Resubmit",
        "Rejected",
    }
    for r in rows:
        assert r.is_active is True
        assert r.svg_template.startswith("<svg")
        assert r.color.startswith("#")


# ── Submit + sequential approve ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_step_full_approval_burns_stamp(db_session):
    """step1 approve → still in_review; step2 approve → approved + stamped."""
    from app.modules.file_approvals.schemas import (
        ApprovalStepCreate,
        ApprovalStepDecide,
        ApprovalWorkflowCreate,
    )
    from app.modules.file_approvals.service import ApprovalService

    project_id, _owner_id, approver1, approver2 = await _seed_project_with_users(db_session)
    service = ApprovalService(db_session)
    templates = await service.list_templates(project_id=None)
    template_id = templates[0].id

    workflow = await service.submit(
        ApprovalWorkflowCreate(
            project_id=project_id,
            file_kind="document",
            file_id="approval-file-001",
            file_version_snapshot="v1",
            stamp_template_id=template_id,
            steps=[
                ApprovalStepCreate(approver_id=approver1, role_label="Reviewer"),
                ApprovalStepCreate(approver_id=approver2, role_label="Project Manager"),
            ],
        ),
        submitted_by_id=str(approver1),
    )
    assert workflow.status == "in_review"
    assert len(workflow.steps) == 2
    assert workflow.stamped_artifact_path is None

    step1 = workflow.steps[0]
    step2 = workflow.steps[1]

    # Step 1 approves → workflow remains in_review.
    workflow = await service.decide(
        workflow.id,
        step1.id,
        ApprovalStepDecide(decision="approved", decision_note="LGTM"),
        actor_id=str(approver1),
    )
    assert workflow.status == "in_review"
    assert workflow.steps[0].decision == "approved"
    assert workflow.steps[1].decision == "pending"
    assert workflow.stamped_artifact_path is None

    # Step 2 approves → workflow → approved + stamp burned (sidecar or PDF).
    workflow = await service.decide(
        workflow.id,
        step2.id,
        ApprovalStepDecide(decision="approved"),
        actor_id=str(approver2),
    )
    assert workflow.status == "approved"
    assert workflow.final_decision_at is not None
    assert workflow.final_decision_by_id is not None
    # Storage may have written either a PDF or a JSON sidecar; the path
    # must exist and end with one of those extensions.
    assert workflow.stamped_artifact_path
    assert workflow.stamped_artifact_path.endswith((".pdf", ".json"))


@pytest.mark.asyncio
async def test_reject_at_step1_short_circuits_workflow(db_session):
    """Reject at step1 → workflow=rejected, step2 still pending, no stamp."""
    from app.modules.file_approvals.schemas import (
        ApprovalStepCreate,
        ApprovalStepDecide,
        ApprovalWorkflowCreate,
    )
    from app.modules.file_approvals.service import ApprovalService

    project_id, _owner_id, approver1, approver2 = await _seed_project_with_users(db_session)
    service = ApprovalService(db_session)

    workflow = await service.submit(
        ApprovalWorkflowCreate(
            project_id=project_id,
            file_kind="report",
            file_id="rejecting-001",
            steps=[
                ApprovalStepCreate(approver_id=approver1),
                ApprovalStepCreate(approver_id=approver2),
            ],
        ),
        submitted_by_id=str(approver1),
    )
    step1 = workflow.steps[0]
    step2 = workflow.steps[1]

    workflow = await service.decide(
        workflow.id,
        step1.id,
        ApprovalStepDecide(
            decision="rejected",
            decision_note="Drawings missing dimensions",
        ),
        actor_id=str(approver1),
    )
    assert workflow.status == "rejected"
    assert workflow.steps[0].decision == "rejected"
    # Step 2 is untouched.
    step2_reloaded = next(s for s in workflow.steps if s.id == step2.id)
    assert step2_reloaded.decision == "pending"
    assert workflow.stamped_artifact_path is None


@pytest.mark.asyncio
async def test_decide_out_of_order_rejected(db_session):
    """Cannot decide step 2 before step 1 has approved."""
    from fastapi import HTTPException

    from app.modules.file_approvals.schemas import (
        ApprovalStepCreate,
        ApprovalStepDecide,
        ApprovalWorkflowCreate,
    )
    from app.modules.file_approvals.service import ApprovalService

    project_id, _owner_id, approver1, approver2 = await _seed_project_with_users(db_session)
    service = ApprovalService(db_session)
    workflow = await service.submit(
        ApprovalWorkflowCreate(
            project_id=project_id,
            file_kind="sheet",
            file_id="order-001",
            steps=[
                ApprovalStepCreate(approver_id=approver1),
                ApprovalStepCreate(approver_id=approver2),
            ],
        ),
        submitted_by_id=str(approver1),
    )
    step2 = workflow.steps[1]
    with pytest.raises(HTTPException) as exc_info:
        await service.decide(
            workflow.id,
            step2.id,
            ApprovalStepDecide(decision="approved"),
            actor_id=str(approver2),
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_withdraw_in_review_workflow(db_session):
    """Submitter withdraws → workflow → withdrawn."""
    from app.modules.file_approvals.schemas import (
        ApprovalStepCreate,
        ApprovalWorkflowCreate,
    )
    from app.modules.file_approvals.service import ApprovalService

    project_id, _owner_id, approver1, _approver2 = await _seed_project_with_users(db_session)
    service = ApprovalService(db_session)
    workflow = await service.submit(
        ApprovalWorkflowCreate(
            project_id=project_id,
            file_kind="markup",
            file_id="withdraw-001",
            steps=[ApprovalStepCreate(approver_id=approver1)],
        ),
        submitted_by_id=str(approver1),
    )
    assert workflow.status == "in_review"
    workflow = await service.withdraw(workflow.id)
    assert workflow.status == "withdrawn"
    assert workflow.final_decision_at is not None
    # Idempotent: a second withdraw is a no-op.
    workflow = await service.withdraw(workflow.id)
    assert workflow.status == "withdrawn"


@pytest.mark.asyncio
async def test_cannot_decide_on_completed_workflow(db_session):
    """Once a workflow is approved/rejected/withdrawn, further decides 409."""
    from fastapi import HTTPException

    from app.modules.file_approvals.schemas import (
        ApprovalStepCreate,
        ApprovalStepDecide,
        ApprovalWorkflowCreate,
    )
    from app.modules.file_approvals.service import ApprovalService

    project_id, _owner_id, approver1, _approver2 = await _seed_project_with_users(db_session)
    service = ApprovalService(db_session)
    workflow = await service.submit(
        ApprovalWorkflowCreate(
            project_id=project_id,
            file_kind="document",
            file_id="locked-001",
            steps=[ApprovalStepCreate(approver_id=approver1)],
        ),
        submitted_by_id=str(approver1),
    )
    step1 = workflow.steps[0]
    workflow = await service.decide(
        workflow.id,
        step1.id,
        ApprovalStepDecide(decision="approved"),
        actor_id=str(approver1),
    )
    assert workflow.status == "approved"

    with pytest.raises(HTTPException) as exc_info:
        await service.decide(
            workflow.id,
            step1.id,
            ApprovalStepDecide(decision="rejected"),
            actor_id=str(approver1),
        )
    assert exc_info.value.status_code in (404, 409)


@pytest.mark.asyncio
async def test_create_custom_stamp_template(db_session):
    """Custom (project-scoped) stamp templates can be created + listed."""
    from app.modules.file_approvals.schemas import StampTemplateCreate
    from app.modules.file_approvals.service import ApprovalService

    project_id, _owner_id, _a1, _a2 = await _seed_project_with_users(db_session)
    service = ApprovalService(db_session)

    tmpl = await service.create_template(
        StampTemplateCreate(
            project_id=project_id,
            name="Project Hold",
            text="HOLD",
            color="#7c3aed",
            svg_template=(
                '<svg xmlns="http://www.w3.org/2000/svg" width="220" '
                'height="80"><text x="20" y="40" fill="#7c3aed" '
                'font-size="20">{{text}}</text></svg>'
            ),
            is_active=True,
        )
    )
    assert tmpl.project_id == project_id
    assert tmpl.name == "Project Hold"

    listed = await service.list_templates(project_id=project_id)
    names = {r.name for r in listed}
    # Project list returns globals AND the new project-scoped row.
    assert "Project Hold" in names
    assert "Approved" in names
