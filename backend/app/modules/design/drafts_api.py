"""Drafts of the browser editor (contract README §11): every edit autosaves a ``.ddcrev`` package as the person's
draft; its quantities and estimate are computed at once from the project's rules; one action turns the draft into a
revision through the same intake as the desktop editor. Who may edit is a per-project choice; accepting stays with
managers. Also the editor's own AI choice (default: the person's ERP AI settings)."""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from fastapi import BackgroundTasks, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.dependencies import SessionDep

from . import rules
from .auth import PrincipalDep, require_project
from .estimate import _rule_rows, dstr, q4, summary
from .intake import Limits, PackageRejected, verify_package
from .models import DesignAiChoice, DesignDraft, DesignEditRights
from .revisions import element_properties, element_quantities
from .settings import get_design_settings

EditRight = Literal["members", "managers"]


def _limits() -> Limits:
    s = get_design_settings()
    return Limits(
        max_unpacked=s.revision_max_unpacked_bytes,
        max_json=s.revision_max_json_bytes,
        max_glb_json=s.revision_max_glb_json_bytes,
        max_rows=s.revision_max_rows,
    )


def draft_elements(pkg) -> list[rules.Element]:
    return [
        rules.Element(r["element_key"], r["element_type"], r["storey"], element_properties(r), element_quantities(r))
        for r in pkg.rows()
    ]


def draft_estimate(elements: list[rules.Element], rule_rows: list, current: dict[str, Any]) -> dict[str, Any]:
    """Model-rule quantities of the draft beside the estimate's current ones, priced at the current unit rates.

    Nothing is guessed: a rule the draft cannot evaluate here (a formula quantity) or a position without a rate is
    listed with its flag and left out of the total."""
    positions = {p["rule"]: p for p in current.get("positions", [])} if current.get("estimate") else {}
    lines: list[dict[str, Any]] = []
    total = Decimal(0)
    for r in rule_rows:
        if r.kind != "model":
            continue
        body = r.body
        q = body.get("quantity") or {}
        pos = positions.get(r.code)
        sel = rules.select(elements, body["select"])
        flags: list[str] = []
        if q.get("formula"):
            qty = None
            flags.append("formula_not_in_draft")
        else:
            vals = [v for v in (rules.read_field(e, q.get("field") or "") for e in sel) if v is not None]
            qty = rules.aggregate(vals, q.get("aggregation", "sum")) if sel else Decimal(0)
            if sel and len(vals) < len(sel):
                flags.append("elements_without_quantity")
        rate = q4(pos["unit_rate"]) if pos else Decimal(0)
        if pos is None:
            flags.append("no_position")
        elif rate == 0:
            flags.append("rate_missing")
        line_total = q4(qty * rate) if qty is not None and rate else None
        if line_total is not None:
            total += line_total
        lines.append(
            {
                "rule": r.code,
                "unit": body.get("unit"),
                "elements": len(sel),
                "element_keys": [e.key for e in sel][:5000],
                "quantity": dstr(q4(qty)) if qty is not None else None,
                "current_quantity": pos["quantity"] if pos else None,
                "unit_rate": dstr(rate) if pos else None,
                "total": dstr(line_total) if line_total is not None else None,
                "current_total": pos["total"] if pos else None,
                "position_id": pos["position_id"] if pos else None,
                "description": pos["description"] if pos else r.code,
                "flags": flags,
            }
        )
    return {"estimate": bool(positions), "lines": lines, "model_total": dstr(q4(total))}


class DraftView(BaseModel):
    project_id: str
    revision_id: str
    parent_revision_id: str | None
    package_sha256: str
    package_bytes: int
    element_count: int
    updated_at: str
    estimate: dict[str, Any]

    @classmethod
    def of(cls, d: DesignDraft) -> DraftView:
        return cls(
            project_id=str(d.project_id),
            revision_id=d.revision_id,
            parent_revision_id=d.parent_revision_id,
            package_sha256=d.package_sha256,
            package_bytes=d.package_bytes,
            element_count=d.element_count,
            updated_at=d.updated_at.isoformat() if d.updated_at else "",
            estimate=d.estimate,
        )


class RightsBody(BaseModel):
    edit: EditRight


class AiChoiceBody(BaseModel):
    preferred_model: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=200)


@dataclass
class _Upload:
    """What the intake records of an upload, for bytes already in hand."""

    path: Path
    sha256_hex: str
    size: int
    head: bytes


async def edit_right(session, project_id: uuid.UUID) -> str:
    row = (
        await session.execute(select(DesignEditRights).where(DesignEditRights.project_id == project_id))
    ).scalar_one_or_none()
    return row.edit if row else "members"


def register(router, can_accept, can_publish, acquire, holds_lock, ingest) -> None:
    async def may_edit(session, principal, project_id: uuid.UUID) -> bool:
        from app.modules.projects.models import Project

        if not await can_publish(session, principal.user_id):
            return False
        if await edit_right(session, project_id) == "members":
            return True
        return await can_accept(session, principal.user_id, await session.get(Project, project_id))

    async def require_edit(session, principal, project_id: uuid.UUID) -> None:
        await require_project(principal, project_id, session)
        if not await may_edit(session, principal, project_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role may not edit the design of this project")

    async def mine(session, project_id: uuid.UUID, user_id: uuid.UUID) -> DesignDraft | None:
        return (
            await session.execute(
                select(DesignDraft).where(DesignDraft.project_id == project_id, DesignDraft.user_id == user_id)
            )
        ).scalar_one_or_none()

    @router.get("/projects/{project_id}/design-rights")
    async def get_rights(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict[str, Any]:
        from app.modules.projects.models import Project

        await require_project(principal, project_id, session)
        project = await session.get(Project, project_id)
        return {
            "edit": await edit_right(session, project_id),
            "can_edit": await may_edit(session, principal, project_id),
            "can_accept": await can_accept(session, principal.user_id, project),
        }

    @router.put("/projects/{project_id}/design-rights")
    async def put_rights(
        project_id: uuid.UUID, body: RightsBody, principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        from app.modules.projects.models import Project

        await require_project(principal, project_id, session)
        if principal.via_link or not await can_accept(
            session, principal.user_id, await session.get(Project, project_id)
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager may change who edits the design")
        row = (
            await session.execute(select(DesignEditRights).where(DesignEditRights.project_id == project_id))
        ).scalar_one_or_none()
        if row is None:
            session.add(DesignEditRights(project_id=project_id, edit=body.edit, updated_by=principal.user_id))
        else:
            row.edit, row.updated_by = body.edit, principal.user_id
        await session.commit()
        return {"edit": body.edit}

    @router.get("/projects/{project_id}/draft", response_model=DraftView | None)
    async def get_draft(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> DraftView | None:
        # No draft yet is the normal state of a workspace, not an error: null, so browsers log nothing.
        await require_project(principal, project_id, session)
        d = await mine(session, project_id, principal.user_id)
        return None if d is None else DraftView.of(d)

    @router.get("/projects/{project_id}/draft/package")
    async def get_draft_package(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> Response:
        await require_project(principal, project_id, session)
        d = await mine(session, project_id, principal.user_id)
        if d is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No draft")
        return Response(d.package, media_type="application/zip", headers={"X-Package-SHA256": d.package_sha256})

    @router.put("/projects/{project_id}/draft", response_model=DraftView)
    async def put_draft(
        project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, package: UploadFile = File(...)
    ) -> DraftView:
        await require_edit(session, principal, project_id)
        limit = get_design_settings().draft_max_bytes
        data = await package.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"A draft may be at most {limit} bytes")
        with tempfile.TemporaryDirectory(prefix="oe-ddcdraft-") as tmp:
            src = Path(tmp) / "draft.ddcrev"
            src.write_bytes(data)
            try:
                pkg = await asyncio.to_thread(
                    verify_package, src, Path(tmp) / "pkg", project_id=str(project_id), limits=_limits()
                )
            except PackageRejected as exc:
                raise HTTPException(exc.status_code, exc.detail) from exc
            elements = await asyncio.to_thread(draft_elements, pkg)
        est = draft_estimate(elements, await _rule_rows(session, project_id), await summary(session, project_id))
        d = await mine(session, project_id, principal.user_id)
        if d is None:
            d = DesignDraft(project_id=project_id, user_id=principal.user_id)
            session.add(d)
        d.package, d.package_bytes = data, len(data)
        d.package_sha256 = hashlib.sha256(data).hexdigest()
        d.revision_id = pkg.manifest.revision_id
        d.parent_revision_id = pkg.manifest.parent_revision_id
        d.element_count, d.estimate = pkg.element_count, est
        await session.commit()
        await session.refresh(d)
        return DraftView.of(d)

    @router.delete("/projects/{project_id}/draft", status_code=status.HTTP_204_NO_CONTENT)
    async def drop_draft(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
        await require_project(principal, project_id, session)
        await session.execute(
            delete(DesignDraft).where(DesignDraft.project_id == project_id, DesignDraft.user_id == principal.user_id)
        )
        await session.commit()

    @router.post("/projects/{project_id}/draft/revision", status_code=status.HTTP_201_CREATED)
    async def draft_to_revision(
        project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, background: BackgroundTasks
    ):
        """The person's draft becomes a revision awaiting acceptance: the desktop editor's intake, under the lock."""
        from app.modules.collaboration_locks.service import CollabLockService

        from .router import LOCK_ENTITY
        from .schemas import RevisionView

        await require_edit(session, principal, project_id)
        d = await mine(session, project_id, principal.user_id)
        if d is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No draft")
        took = not await holds_lock(session, project_id, principal.user_id)
        if took:
            await acquire(project_id, principal, session)  # 409 with the holder when someone else edits
        try:
            with tempfile.TemporaryDirectory(prefix="oe-ddcdraft-") as tmp:
                src = Path(tmp) / "draft.ddcrev"
                src.write_bytes(d.package)
                try:
                    pkg = await asyncio.to_thread(
                        verify_package, src, Path(tmp) / "pkg", project_id=str(project_id), limits=_limits()
                    )
                except PackageRejected as exc:
                    raise HTTPException(exc.status_code, exc.detail) from exc
                upload = _Upload(src, d.package_sha256, d.package_bytes, d.package[:8])
                rev = await ingest(session, background, project_id, principal, pkg, upload, Path(tmp))
            await session.execute(delete(DesignDraft).where(DesignDraft.id == d.id))
            await session.commit()
            return RevisionView.of(rev)
        finally:
            if took:
                svc = CollabLockService(session)
                lock = await svc.get_for_entity(entity_type=LOCK_ENTITY, entity_id=project_id)
                if lock is not None and lock.user_id == principal.user_id:
                    await svc.release(lock_id=lock.id, user_id=principal.user_id)
                    await session.commit()

    @router.get("/ai-choice")
    async def get_ai_choice(principal: PrincipalDep, session: SessionDep) -> dict[str, Any]:
        row = (
            await session.execute(select(DesignAiChoice).where(DesignAiChoice.user_id == principal.user_id))
        ).scalar_one_or_none()
        return {
            "same_as_erp": row is None,
            "preferred_model": row.preferred_model if row else None,
            "model": row.model if row else None,
        }

    @router.put("/ai-choice")
    async def put_ai_choice(body: AiChoiceBody, principal: PrincipalDep, session: SessionDep) -> dict[str, Any]:
        if principal.via_link:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "The AI choice is made in the ERP")
        await session.execute(delete(DesignAiChoice).where(DesignAiChoice.user_id == principal.user_id))
        same = not (body.preferred_model or body.model)
        if not same:
            session.add(
                DesignAiChoice(
                    user_id=principal.user_id, preferred_model=body.preferred_model or None, model=body.model or None
                )
            )
        await session.commit()
        return {
            "same_as_erp": same,
            "preferred_model": None if same else body.preferred_model,
            "model": None if same else body.model,
        }


async def editor_ai_choice(session, user_id: uuid.UUID) -> DesignAiChoice | None:
    return (await session.execute(select(DesignAiChoice).where(DesignAiChoice.user_id == user_id))).scalar_one_or_none()
