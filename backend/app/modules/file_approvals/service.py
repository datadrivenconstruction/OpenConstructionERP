# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Approvals (W8) service layer.

Holds the submit / decide / withdraw lifecycle and the
stamp-burning logic that runs when the final step approves.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.file_approvals.models import (
    FileApprovalStep,
    FileApprovalWorkflow,
    FileStampTemplate,
)
from app.modules.file_approvals.schemas import (
    ApprovalStepDecide,
    ApprovalWorkflowCreate,
    StampTemplateCreate,
)

logger = logging.getLogger(__name__)

_STAMP_KEY_PREFIX = "approvals"


# ── Stamp burning ─────────────────────────────────────────────────────────


def _expand_svg_placeholders(svg: str, *, text: str, approver: str, decision_date: str) -> str:
    """Expand the canonical ``{{text}}``/``{{date}}``/``{{approver}}``
    placeholders inside the SVG template.

    Unknown placeholders are left untouched so future template authors
    can use raw curly-braces in their SVG content.
    """
    out = svg
    out = out.replace("{{text}}", text)
    out = out.replace("{{date}}", decision_date)
    out = out.replace("{{approver}}", approver)
    return out


def _burn_pdf_stamp(
    pdf_bytes: bytes,
    *,
    template_text: str,
    template_color: str,
    approver: str,
    decision_date: str,
) -> bytes | None:
    """Overlay a stamp page onto a PDF via ``pypdf`` + ``reportlab``.

    Returns the stamped bytes, or ``None`` when the dependency stack is
    not importable / a failure occurs (callers then fall back to a
    JSON sidecar).
    """
    try:
        from io import BytesIO

        from pypdf import PdfReader, PdfWriter
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfgen import canvas
    except Exception:  # noqa: BLE001 — optional deps
        logger.debug(
            "pypdf / reportlab unavailable; sidecar fallback for stamp",
            exc_info=True,
        )
        return None

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        # Build a single-page overlay sized to the first page so the
        # stamp lands consistently regardless of orientation.
        if reader.pages:
            mb = reader.pages[0].mediabox
            try:
                page_w = float(mb.width)
                page_h = float(mb.height)
            except Exception:  # noqa: BLE001
                page_w, page_h = LETTER
        else:
            page_w, page_h = LETTER

        overlay_buf = BytesIO()
        c = canvas.Canvas(overlay_buf, pagesize=(page_w, page_h))
        try:
            stroke = HexColor(template_color)
        except Exception:  # noqa: BLE001 — invalid hex → fall back
            stroke = HexColor("#16a34a")
        c.setStrokeColor(stroke)
        c.setFillColor(stroke)
        c.setLineWidth(3)
        # Stamp box: top-right corner with margin.
        stamp_w = 220
        stamp_h = 80
        x0 = max(page_w - stamp_w - 36, 24)
        y0 = max(page_h - stamp_h - 36, 24)
        c.rect(x0, y0, stamp_w, stamp_h, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(x0 + 12, y0 + stamp_h - 22, template_text[:40])
        c.setFont("Helvetica", 9)
        c.drawString(x0 + 12, y0 + stamp_h - 42, f"Approved by {approver[:32]}")
        c.drawString(x0 + 12, y0 + stamp_h - 58, decision_date)
        c.showPage()
        c.save()

        overlay_reader = PdfReader(BytesIO(overlay_buf.getvalue()))
        overlay_page = overlay_reader.pages[0]

        writer = PdfWriter()
        for page in reader.pages:
            page.merge_page(overlay_page)
            writer.add_page(page)
        out = BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:  # noqa: BLE001 — never let stamp-burn crash final approve
        logger.exception("PDF stamp overlay failed; sidecar fallback")
        return None


def _build_sidecar_json(
    *,
    workflow: FileApprovalWorkflow,
    template: FileStampTemplate | None,
    approver: str,
    decision_date: str,
) -> bytes:
    """Compose the ``__stamped.json`` sidecar payload for non-PDF artifacts."""
    if template is not None:
        svg = _expand_svg_placeholders(
            template.svg_template,
            text=template.text,
            approver=approver,
            decision_date=decision_date,
        )
        payload = {
            "workflow_id": str(workflow.id),
            "file_kind": workflow.file_kind,
            "file_id": workflow.file_id,
            "file_version_snapshot": workflow.file_version_snapshot,
            "stamp": {
                "template_id": str(template.id),
                "name": template.name,
                "text": template.text,
                "color": template.color,
                "svg": svg,
                "position": {"anchor": "top-right", "margin_pt": 36},
            },
            "approver": approver,
            "decision_date": decision_date,
        }
    else:
        payload = {
            "workflow_id": str(workflow.id),
            "file_kind": workflow.file_kind,
            "file_id": workflow.file_id,
            "file_version_snapshot": workflow.file_version_snapshot,
            "stamp": None,
            "approver": approver,
            "decision_date": decision_date,
        }
    return json.dumps(payload, indent=2).encode("utf-8")


# ── Service ───────────────────────────────────────────────────────────────


class ApprovalService:
    """Stateless business logic for ``oe_file_approval_*``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Read ───────────────────────────────────────────────────────────

    async def list_workflows(
        self,
        project_id: uuid.UUID,
        *,
        status_filter: str | None = None,
    ) -> list[FileApprovalWorkflow]:
        stmt = (
            select(FileApprovalWorkflow)
            .where(FileApprovalWorkflow.project_id == project_id)
            .options(selectinload(FileApprovalWorkflow.steps))
            .order_by(FileApprovalWorkflow.submitted_at.desc())
        )
        if status_filter:
            stmt = stmt.where(FileApprovalWorkflow.status == status_filter)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_workflow(self, workflow_id: uuid.UUID) -> FileApprovalWorkflow:
        stmt = (
            select(FileApprovalWorkflow)
            .where(FileApprovalWorkflow.id == workflow_id)
            .options(selectinload(FileApprovalWorkflow.steps))
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow {workflow_id} not found",
            )
        return row

    # ── Create ─────────────────────────────────────────────────────────

    async def submit(self, data: ApprovalWorkflowCreate, submitted_by_id: str | None) -> FileApprovalWorkflow:
        """Create a new workflow with N ordered steps in ``in_review``."""
        # Validate stamp template (if provided) is global or in this project.
        if data.stamp_template_id is not None:
            tmpl = await self.session.get(FileStampTemplate, data.stamp_template_id)
            if tmpl is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Unknown stamp template",
                )
            if tmpl.project_id is not None and tmpl.project_id != data.project_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Stamp template not available for this project",
                )

        submitter_uuid: uuid.UUID | None = None
        if submitted_by_id:
            try:
                submitter_uuid = uuid.UUID(str(submitted_by_id))
            except (TypeError, ValueError):
                submitter_uuid = None

        workflow = FileApprovalWorkflow(
            project_id=data.project_id,
            file_kind=data.file_kind,
            file_id=data.file_id,
            file_version_snapshot=data.file_version_snapshot,
            submitted_by_id=submitter_uuid,
            submitted_at=datetime.now(UTC),
            status="in_review",
            stamp_template_id=data.stamp_template_id,
            notes=data.notes,
        )
        self.session.add(workflow)
        await self.session.flush()

        for idx, step in enumerate(data.steps):
            self.session.add(
                FileApprovalStep(
                    workflow_id=workflow.id,
                    sort_order=idx,
                    approver_id=step.approver_id,
                    role_label=step.role_label,
                    decision="pending",
                )
            )
        await self.session.flush()
        return await self.get_workflow(workflow.id)

    # ── Decide ─────────────────────────────────────────────────────────

    async def decide(
        self,
        workflow_id: uuid.UUID,
        step_id: uuid.UUID,
        decision_data: ApprovalStepDecide,
        actor_id: str,
    ) -> FileApprovalWorkflow:
        """Record a decision on one step and roll the workflow forward."""
        workflow = await self.get_workflow(workflow_id)
        if workflow.status != "in_review":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Workflow is {workflow.status}; cannot decide",
            )
        step = next((s for s in workflow.steps if s.id == step_id), None)
        if step is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Step {step_id} not found in workflow {workflow_id}",
            )
        if step.decision != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Step already decided: {step.decision}",
            )

        # Enforce strict ordering: every prior step must be approved.
        for prior in workflow.steps:
            if prior.sort_order < step.sort_order and prior.decision != "approved":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Previous step (#{prior.sort_order}) is '{prior.decision}'; current step is not yet actionable"
                    ),
                )

        # Restrict who can decide (the approver themselves, or admin).
        # Admins bypass via the router-level RequirePermission; here we
        # enforce the per-step approver identity.
        try:
            actor_uuid = uuid.UUID(str(actor_id))
        except (TypeError, ValueError):
            actor_uuid = None
        if actor_uuid is not None and step.approver_id != actor_uuid:
            # Allow project admins via the RBAC layer; the per-step check
            # is best-effort. We let the call proceed but the router has
            # already filtered on ``file_approvals.decide``.
            from app.modules.users.repository import UserRepository

            actor = await UserRepository(self.session).get_by_id(actor_uuid)
            actor_role = getattr(actor, "role", "")
            if actor_role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not the approver for this step",
                )

        now = datetime.now(UTC)
        step.decision = decision_data.decision
        step.decision_at = now
        step.decision_note = decision_data.decision_note

        # Roll workflow status.
        if decision_data.decision == "rejected":
            workflow.status = "rejected"
            workflow.final_decision_at = now
            workflow.final_decision_by_id = actor_uuid
        elif decision_data.decision == "approved":
            # Approved final step? Roll to ``approved`` and burn stamp.
            remaining = [s for s in workflow.steps if s.id != step.id and s.decision != "approved"]
            if not remaining:
                workflow.status = "approved"
                workflow.final_decision_at = now
                workflow.final_decision_by_id = actor_uuid
                await self._burn_stamp(workflow, actor_id, now)
        # ``delegated`` is a soft no-op at the workflow level; the workflow
        # stays ``in_review`` and the next approver in the chain can act.

        await self.session.flush()
        return await self.get_workflow(workflow.id)

    async def withdraw(self, workflow_id: uuid.UUID) -> FileApprovalWorkflow:
        """Submitter (or admin) abandons the workflow."""
        workflow = await self.get_workflow(workflow_id)
        if workflow.status in ("approved", "rejected", "withdrawn"):
            return workflow
        workflow.status = "withdrawn"
        workflow.final_decision_at = datetime.now(UTC)
        await self.session.flush()
        return await self.get_workflow(workflow.id)

    # ── Stamp templates ────────────────────────────────────────────────

    async def list_templates(self, project_id: uuid.UUID | None) -> list[FileStampTemplate]:
        """List globals + project-scoped templates (project first if given)."""
        from sqlalchemy import or_

        stmt = select(FileStampTemplate).where(FileStampTemplate.is_active.is_(True))
        if project_id is not None:
            stmt = stmt.where(
                or_(
                    FileStampTemplate.project_id.is_(None),
                    FileStampTemplate.project_id == project_id,
                )
            )
        else:
            stmt = stmt.where(FileStampTemplate.project_id.is_(None))
        stmt = stmt.order_by(
            FileStampTemplate.project_id.is_(None).desc(),
            FileStampTemplate.name.asc(),
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def create_template(self, data: StampTemplateCreate) -> FileStampTemplate:
        """Persist a new stamp template (project-scoped or global)."""
        row = FileStampTemplate(
            project_id=data.project_id,
            name=data.name,
            text=data.text,
            color=data.color,
            svg_template=data.svg_template,
            is_active=data.is_active,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    # ── Stamp burning ─────────────────────────────────────────────────

    async def _burn_stamp(
        self,
        workflow: FileApprovalWorkflow,
        approver_id: str,
        decision_at: datetime,
    ) -> None:
        """Generate + persist the stamped artifact for a finally-approved workflow.

        The original source file is NEVER overwritten. The stamped copy
        lives in storage under ``approvals/{workflow_id}/`` so the audit
        trail is preserved and the un-stamped source can still be
        retrieved by anyone with read access to the source module.
        """
        from app.core.storage import get_storage_backend

        template: FileStampTemplate | None = None
        if workflow.stamp_template_id is not None:
            template = await self.session.get(FileStampTemplate, workflow.stamp_template_id)

        approver_label = await self._resolve_approver_label(approver_id)
        decision_date = decision_at.date().isoformat()

        source_bytes = await self._read_source_file(workflow)
        is_pdf = workflow.file_kind in ("document", "report", "takeoff") or (
            source_bytes is not None and source_bytes.startswith(b"%PDF-")
        )

        backend = get_storage_backend()
        stamped: bytes | None = None
        if is_pdf and source_bytes and template is not None:
            stamped = _burn_pdf_stamp(
                source_bytes,
                template_text=template.text,
                template_color=template.color,
                approver=approver_label,
                decision_date=decision_date,
            )

        try:
            if stamped is not None:
                key = f"{_STAMP_KEY_PREFIX}/{workflow.id}/{workflow.file_id}__stamped.pdf"
                await backend.put(key, stamped)
                workflow.stamped_artifact_path = key
            else:
                # Sidecar JSON for non-PDF or no-pypdf fallback.
                sidecar = _build_sidecar_json(
                    workflow=workflow,
                    template=template,
                    approver=approver_label,
                    decision_date=decision_date,
                )
                key = f"{_STAMP_KEY_PREFIX}/{workflow.id}/{workflow.file_id}__stamped.json"
                await backend.put(key, sidecar)
                workflow.stamped_artifact_path = key
        except Exception:  # noqa: BLE001 — never crash final approval
            logger.exception(
                "Failed to persist stamped artifact for workflow %s",
                workflow.id,
            )
            workflow.stamped_artifact_path = None

    async def _read_source_file(self, workflow: FileApprovalWorkflow) -> bytes | None:
        """Best-effort read of the source file bytes via the storage backend.

        Different file kinds live in different storage prefixes; we probe
        the conventional layout used elsewhere in the codebase
        (``documents/{project_id}/{file_id}``, etc.). On any miss we
        return ``None`` and the caller writes a sidecar describing the
        stamp instead.
        """
        from app.core.storage import get_storage_backend

        backend = get_storage_backend()
        # The 8 file kinds may persist under many different keys depending
        # on the originating module. We try a small, well-known set; if
        # all miss we degrade gracefully to "no source bytes" → sidecar.
        candidate_keys = [
            f"{workflow.file_kind}s/{workflow.project_id}/{workflow.file_id}",
            f"{workflow.file_kind}/{workflow.project_id}/{workflow.file_id}",
            f"uploads/{workflow.project_id}/{workflow.file_id}",
            f"documents/{workflow.project_id}/{workflow.file_id}",
        ]
        for key in candidate_keys:
            try:
                data = await backend.get(key)
                if data:
                    return data
            except Exception:  # noqa: BLE001 — probe-style, keep looking
                continue
        return None

    async def _resolve_approver_label(self, approver_id: str) -> str:
        """Best-effort human label for the stamp's "Approved by" line."""
        try:
            from app.modules.users.repository import UserRepository

            user = await UserRepository(self.session).get_by_id(uuid.UUID(str(approver_id)))
            if user is not None:
                if user.full_name:
                    return user.full_name
                return user.email
        except Exception:  # noqa: BLE001 — fall through
            pass
        return str(approver_id)

    async def read_stamped(self, workflow_id: uuid.UUID) -> tuple[bytes, str]:
        """Return ``(bytes, media_type)`` for the stamped artifact."""
        from app.core.storage import get_storage_backend

        workflow = await self.get_workflow(workflow_id)
        if not workflow.stamped_artifact_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No stamped artifact for this workflow",
            )
        data = await get_storage_backend().get(workflow.stamped_artifact_path)
        if workflow.stamped_artifact_path.endswith(".pdf"):
            return data, "application/pdf"
        return data, "application/json"
