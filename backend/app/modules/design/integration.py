"""What a revision does in the other ERP modules: drawings in Documents, a review task, notifications; and the
project overview (which modules the design feeds, and how far each one is).

Every side effect here is best effort and runs in a savepoint: a missing or failing ERP module never blocks
an upload or a decision, it only leaves its part out (logged).
"""

from __future__ import annotations

import io
import logging
import uuid
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, select

from .models import (
    DesignChangeOrder,
    DesignDraft,
    DesignEstimate,
    DesignEstimateBinding,
    DesignRevision,
    DesignSchedule,
    DesignScheduleBinding,
)
from .procurement_models import DesignProcurement, DesignTakeoffSection

log = logging.getLogger(__name__)

TASK_TYPE = "design_review"
DOC_CATEGORY = "drawing"
# Task titles are stored text, not keys: written in the reviewer's language where we have it.
TASK_TITLE = {
    "en": "Review design revision {n}",
    "de": "Entwurfsrevision {n} prüfen",
    "ru": "Проверить ревизию проекта {n}",
}


async def _best_effort(session, what: str, fn) -> Any:
    try:
        async with session.begin_nested():
            return await fn()
    except Exception:  # noqa: BLE001 - another module's failure must not undo the design's own step
        log.warning("design integration: %s skipped", what, exc_info=True)
        return None


def acceptance_url(project_id: uuid.UUID, revision_id: uuid.UUID) -> str:
    return f"/design/acceptance?project={project_id}&revision={revision_id}"


# ── Drawings: every sheet of every revision in Documents, one version chain per sheet ─────────────────────────


def sheet_name(path: str) -> str:
    return f"Design - {PurePosixPath(path).name}"


async def _sheet_docs(session, project_id: uuid.UUID) -> dict[str, Any]:
    from app.modules.documents.models import Document

    rows = (
        (
            await session.execute(
                select(Document).where(Document.project_id == project_id, Document.category == DOC_CATEGORY)
            )
        )
        .scalars()
        .all()
    )
    out: dict[str, Any] = {}
    for d in rows:
        meta = d.metadata_ or {}
        path = (meta.get("design") or {}).get("sheet") if isinstance(meta, dict) else None
        if path:
            out[path] = d
    return out


async def publish_sheets(session, rev: DesignRevision, sheets: dict[str, bytes], user_id: uuid.UUID) -> list[str]:
    """Put each sheet PDF into Documents (category drawing): first time a document, later a new version of it."""
    from starlette.datastructures import UploadFile

    from app.modules.documents.service import DocumentService

    svc = DocumentService(session)
    known = await _sheet_docs(session, rev.project_id)
    out: list[str] = []
    docs: dict[str, Any] = {}
    for path in sorted(sheets):
        upload = UploadFile(file=io.BytesIO(sheets[path]), filename=sheet_name(path))
        note = f"Design revision {rev.number}"
        doc = known.get(path)
        if doc is None:
            doc = await svc.upload_document(rev.project_id, upload, DOC_CATEGORY, str(user_id))
        else:
            doc = await svc.upload_document_revision(doc.id, upload, str(user_id), notes=note)
        doc.metadata_ = {
            **(doc.metadata_ or {}),
            "design": {"sheet": path, "revision_id": str(rev.id), "revision_number": rev.number, "status": rev.status},
        }
        doc.description = note
        out.append(str(doc.id))
        docs[path] = doc
    await session.flush()
    await _best_effort(session, "sheet register", lambda: register_sheets(session, rev, docs))
    return out


# ── Drawing register: the ERP's own sheet list (/sheets), one row per sheet and revision ──────────────────────


async def _design_sheets(session, project_id: uuid.UUID) -> list[Any]:
    from app.modules.documents.models import Sheet

    rows = (await session.execute(select(Sheet).where(Sheet.project_id == project_id))).scalars().all()
    return [s for s in rows if isinstance(s.metadata_, dict) and (s.metadata_.get("design") or {}).get("sheet")]


async def register_sheets(session, rev: DesignRevision, docs: dict[str, Any]) -> int:
    """One register row per sheet and revision, chained to the previous one; the file is the Documents entry.

    Number is the sheet's file name (the manifest carries nothing else); discipline, title and scale are left empty
    rather than guessed. A sheet whose name equals a storey of the model is linked to that storey's elements.
    """
    from app.modules.documents.models import Sheet
    from app.modules.documents.service import SheetService

    repo = SheetService(session).repo
    existing = await _design_sheets(session, rev.project_id)
    made = 0
    for path, doc in docs.items():
        mine = [s for s in existing if s.metadata_["design"]["sheet"] == path]
        if any(s.metadata_["design"].get("revision_id") == str(rev.id) for s in mine):
            continue
        prev = next(
            (
                s
                for s in sorted(mine, key=lambda s: s.metadata_["design"].get("revision_number", 0), reverse=True)
                if s.is_current
            ),
            None,
        )
        row = Sheet(
            project_id=rev.project_id,
            document_id=str(doc.id),
            page_number=1,
            sheet_number=PurePosixPath(path).stem,
            revision=str(rev.number),
            revision_date=getattr(rev, "created_at", None),
            is_current=True,
            previous_version_id=prev.id if prev else None,
            created_by=str(rev.author_user_id or ""),
            metadata_={
                "design": {
                    "sheet": path,
                    "revision_id": str(rev.id),
                    "revision_number": rev.number,
                    "status": rev.status,
                    "model_id": str(rev.bim_model_id) if rev.bim_model_id else None,
                }
            },
        )
        if prev is not None:
            prev.is_current = False
        await repo.create_many([row])
        await _link_sheet_to_storey(session, rev, doc, path)
        made += 1
    return made


async def _link_sheet_to_storey(session, rev: DesignRevision, doc: Any, path: str) -> int:
    from sqlalchemy import func as f

    from app.modules.bim_hub.models import BIMElement
    from app.modules.documents.schemas import DocumentBIMLinkCreate
    from app.modules.documents.service import DocumentBIMLinkService

    if rev.bim_model_id is None:
        return 0
    stem = PurePosixPath(path).stem.lower()
    ids = (
        (
            await session.execute(
                select(BIMElement.id).where(BIMElement.model_id == rev.bim_model_id, f.lower(BIMElement.storey) == stem)
            )
        )
        .scalars()
        .all()
    )
    svc = DocumentBIMLinkService(session)
    have = {x.bim_element_id for x in await svc.list_links_for_document(doc.id)}
    n = 0
    for eid in ids:
        if eid not in have:
            await svc.create_link(
                DocumentBIMLinkCreate(
                    document_id=doc.id,
                    bim_element_id=eid,
                    link_type="design_sheet",
                    metadata={"revision_id": str(rev.id), "match": "storey name"},
                )
            )
            n += 1
    return n


# ── People: who hears about a revision ───────────────────────────────────────────────────────────────────────


async def _project(session, project_id: uuid.UUID):
    from app.modules.projects.models import Project

    return await session.get(Project, project_id)


async def _notify(session, users: list[uuid.UUID], kind: str, rev: DesignRevision, **ctx: Any) -> int:
    from app.modules.notifications.service import NotificationService

    users = list(dict.fromkeys(u for u in users if u is not None))
    if not users:
        return 0
    project = await _project(session, rev.project_id)
    await NotificationService(session).notify_users(
        users,
        f"design_{kind}",
        f"design.notify.{kind}.title",
        entity_type="design_revision",
        entity_id=str(rev.id),
        body_key=f"design.notify.{kind}.body",
        body_context={"number": rev.number, "project": getattr(project, "name", ""), **ctx},
        action_url=acceptance_url(rev.project_id, rev.id),
        metadata={"project_id": str(rev.project_id)},
    )
    return len(users)


async def _open_review_tasks(session, project_id: uuid.UUID, revision_id: uuid.UUID | None = None) -> list:
    from app.modules.tasks.models import Task

    rows = (
        (
            await session.execute(
                select(Task).where(
                    Task.project_id == project_id, Task.task_type == TASK_TYPE, Task.status != "completed"
                )
            )
        )
        .scalars()
        .all()
    )
    if revision_id is None:
        return list(rows)
    return [t for t in rows if (t.metadata_ or {}).get("design_revision_id") == str(revision_id)]


async def _review_task(session, rev: DesignRevision, reviewer: uuid.UUID) -> str:
    from app.modules.tasks.schemas import TaskCreate
    from app.modules.tasks.service import TaskService
    from app.modules.users.models import User

    if await _open_review_tasks(session, rev.project_id, rev.id):
        return ""
    user = await session.get(User, reviewer)
    lang = (getattr(user, "locale", "") or "en").split("-")[0]
    task = await TaskService(session).create_task(
        TaskCreate(
            project_id=rev.project_id,
            task_type=TASK_TYPE,
            status="open",
            priority="normal",
            title=TASK_TITLE.get(lang, TASK_TITLE["en"]).format(n=rev.number),
            description=(rev.message or "")[:4000] or None,
            responsible_id=str(reviewer),
            metadata={"design_revision_id": str(rev.id), "action_url": acceptance_url(rev.project_id, rev.id)},
        ),
        user_id=str(rev.author_user_id) if rev.author_user_id else None,
    )
    return str(task.id)


async def on_shared(session, rev: DesignRevision, sheets: dict[str, bytes]) -> dict[str, Any]:
    """A revision waits for acceptance: drawings to Documents, a review task and a notification for the manager."""
    out: dict[str, Any] = {}
    if sheets:
        out["documents"] = await _best_effort(
            session, "sheets to documents", lambda: publish_sheets(session, rev, sheets, rev.author_user_id)
        )
    project = await _project(session, rev.project_id)
    reviewer = getattr(project, "owner_id", None)
    if reviewer is not None:
        out["task"] = await _best_effort(session, "review task", lambda: _review_task(session, rev, reviewer))
        if reviewer != rev.author_user_id:
            out["notified"] = await _best_effort(
                session, "notify reviewer", lambda: _notify(session, [reviewer], "revision_shared", rev)
            )
    return out


async def on_decided(session, rev: DesignRevision, decision: str, user_id: uuid.UUID) -> dict[str, Any]:
    """Accepted or rejected: the review task closes, the author hears, drawings carry the decision."""
    from app.modules.tasks.service import TaskService

    async def close() -> int:
        tasks = await _open_review_tasks(session, rev.project_id, rev.id)
        svc = TaskService(session)
        for t in tasks:
            if t.status == "draft":
                t.status = "open"
            await svc.complete_task(t.id, result=decision, current_user_id=str(user_id))
        return len(tasks)

    async def mark_docs() -> int:
        n = 0
        for d in (await _sheet_docs(session, rev.project_id)).values():
            meta = dict(d.metadata_ or {})
            if (meta.get("design") or {}).get("revision_id") == str(rev.id):
                meta["design"] = {**meta["design"], "status": "published" if decision == "accepted" else "rejected"}
                d.metadata_ = meta
                n += 1
        await session.flush()
        return n

    async def mark_register() -> int:
        n = 0
        rows = await _design_sheets(session, rev.project_id)
        for s in rows:
            meta = dict(s.metadata_)
            if meta["design"].get("revision_id") != str(rev.id):
                continue
            meta["design"] = {**meta["design"], "status": "published" if decision == "accepted" else "rejected"}
            s.metadata_ = meta
            if decision != "accepted":  # a rejected sheet is not the drawing in force: the one before it is again
                s.is_current = False
                prev = next((p for p in rows if p.id == s.previous_version_id), None)
                if prev is not None:
                    prev.is_current = True
            n += 1
        await session.flush()
        return n

    out = {
        "tasks_closed": await _best_effort(session, "close review task", close),
        "documents": await _best_effort(session, "mark documents", mark_docs),
        "sheets": await _best_effort(session, "mark sheet register", mark_register),
    }
    if decision == "accepted":
        from .validators import record

        report = await _best_effort(
            session, "validation report", lambda: record(session, rev.project_id, user_id, "design_accept")
        )
        out["validation_report"] = str(report.id) if report is not None else None
    if rev.author_user_id and rev.author_user_id != user_id:
        out["notified"] = await _best_effort(
            session, "notify author", lambda: _notify(session, [rev.author_user_id], f"revision_{decision}", rev)
        )
    return out


# ── Overview: the project, module by module ──────────────────────────────────────────────────────────────────


async def overview(session, project_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    """One row per ERP module the design feeds: set up or not, what it holds, where to open it. Counts only."""
    from app.modules.bim_hub.models import BOQElementLink

    from . import links
    from .brief_models import DesignBrief

    revs = (
        (
            await session.execute(
                select(DesignRevision).where(DesignRevision.project_id == project_id).order_by(DesignRevision.number)
            )
        )
        .scalars()
        .all()
    )
    published = next((r for r in reversed(revs) if r.status == "published"), None)
    waiting = [r for r in revs if r.status == "shared"]
    brief = (
        await session.execute(select(DesignBrief).where(DesignBrief.project_id == project_id))
    ).scalar_one_or_none()
    drafts = (
        await session.execute(select(func.count()).select_from(DesignDraft).where(DesignDraft.project_id == project_id))
    ).scalar_one()
    est = (
        await session.execute(select(DesignEstimate).where(DesignEstimate.project_id == project_id))
    ).scalar_one_or_none()
    est_n = (
        await session.execute(
            select(func.count())
            .select_from(DesignEstimateBinding)
            .where(DesignEstimateBinding.project_id == project_id)
        )
    ).scalar_one()
    sched = (
        await session.execute(select(DesignSchedule).where(DesignSchedule.project_id == project_id))
    ).scalar_one_or_none()
    act_n = (
        await session.execute(
            select(func.count())
            .select_from(DesignScheduleBinding)
            .where(DesignScheduleBinding.project_id == project_id)
        )
    ).scalar_one()
    proc = (
        await session.execute(select(DesignProcurement).where(DesignProcurement.project_id == project_id))
    ).scalar_one_or_none()
    pkg_n = (
        await session.execute(
            select(func.count())
            .select_from(DesignTakeoffSection)
            .where(DesignTakeoffSection.project_id == project_id, DesignTakeoffSection.package_id.is_not(None))
        )
    ).scalar_one()
    co_n = (
        await session.execute(
            select(func.count())
            .select_from(DesignChangeOrder)
            .where(DesignChangeOrder.project_id == project_id, DesignChangeOrder.change_order_id.is_not(None))
        )
    ).scalar_one()

    async def docs() -> int:
        return len(await _sheet_docs(session, project_id))

    async def tasks() -> int:
        return len(await _open_review_tasks(session, project_id))

    async def linked() -> int:
        g = await links.build(session, project_id)
        if not g.positions:
            return 0
        return (
            await session.execute(
                select(func.count(func.distinct(BOQElementLink.bim_element_id))).where(
                    BOQElementLink.boq_position_id.in_(list(g.positions)), BOQElementLink.link_type == links.LINK_TYPE
                )
            )
        ).scalar_one()

    doc_n = await _best_effort(session, "count documents", docs)
    task_n = await _best_effort(session, "count tasks", tasks)
    link_n = await _best_effort(session, "count element links", linked)
    model_id = published.bim_model_id if published else None
    pid = str(project_id)
    return {
        "project_id": pid,
        "steps": [
            {"id": "brief", "done": brief is not None, "count": None, "url": "/design/brief"},
            {
                "id": "model",
                "done": published is not None,
                "count": len(revs),
                "waiting": len(waiting),
                "drafts": drafts,
                "current": published.number if published else None,
                "url": "/design/revisions",
            },
            {
                "id": "estimate",
                "done": est is not None,
                "count": est_n,
                "url": f"/boq/{est.boq_id}" if est else "/design/estimate",
            },
            {
                "id": "schedule",
                "done": sched is not None,
                "count": act_n,
                "url": f"/schedule/{sched.schedule_id}/cpm" if sched else "/design/acceptance",
            },
            {
                "id": "procurement",
                "done": proc is not None,
                "count": pkg_n,
                "url": "/tendering" if proc else "/design/acceptance",
            },
            {"id": "documents", "done": bool(doc_n), "count": doc_n, "url": f"/projects/{pid}/files"},
            {
                "id": "bim",
                "done": model_id is not None,
                "count": link_n,
                "url": f"/projects/{pid}/bim/{model_id}" if model_id else f"/projects/{pid}/bim",
            },
            {"id": "change_orders", "done": co_n > 0, "count": co_n, "url": "/changeorders"},
            {
                "id": "tasks",
                "done": task_n == 0 if task_n is not None else False,
                "count": task_n,
                "url": f"/projects/{pid}/tasks",
            },
        ],
        "waiting_revision_id": str(waiting[-1].id) if waiting else None,
    }
