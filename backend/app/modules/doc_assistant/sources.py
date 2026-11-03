# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Collect the passages one user may read in one project.

Permission scope is applied here, before ranking, so a passage the caller
may not read never enters the index and cannot surface in an answer, a
snippet or a confidence score:

* the caller must own or belong to the project (checked by the router);
* each source family is gated on its module read permission
  (``documents.read``, ``rfi.read``, ``submittals.read``,
  ``correspondence.read``, ``meetings.read``, ``contracts.read``);
* a document with a confidential security classification is readable by
  managers and administrators, and by the person who uploaded it.

Document text comes from the existing file-search index (one row per file,
pages separated by form feeds); sheet numbers and revisions come from the
documents module's sheet register. Reads are bounded per family so a huge
project cannot pull an unbounded set into memory.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import ROLE_HIERARCHY, Role, _resolve_role, permission_registry
from app.modules.doc_assistant.core import Passage, chunk_document, record_passages

logger = logging.getLogger(__name__)

MAX_DOCUMENTS = 400
MAX_RECORDS = 500
MAX_PASSAGES = 20_000

RESTRICTED_CLASSIFICATIONS = frozenset({"confidential", "restricted", "secret", "strictly_confidential", "commercial"})
_CATEGORY_KIND = {
    "specification": "specification",
    "specifications": "specification",
    "spec": "specification",
    "drawing": "drawing",
    "drawings": "drawing",
    "contract": "contract",
    "contracts": "contract",
}


def can_read(role: str | None, permission: str) -> bool:
    """True when *role* holds *permission*; an unregistered permission falls back to viewer access."""
    if not role:
        return False
    if permission_registry.has(permission):
        return permission_registry.role_has_permission(role, permission)
    resolved = _resolve_role(role)
    return resolved is not None and ROLE_HIERARCHY.get(resolved, -1) >= ROLE_HIERARCHY[Role.VIEWER]


def can_read_classified(role: str | None, classification: str | None, uploaded_by: str, user_id: str) -> bool:
    """Confidential documents: managers, administrators and the uploader only."""
    if (classification or "").strip().lower() not in RESTRICTED_CLASSIFICATIONS:
        return True
    if uploaded_by and uploaded_by == user_id:
        return True
    resolved = _resolve_role(role or "")
    return resolved is not None and ROLE_HIERARCHY.get(resolved, -1) >= ROLE_HIERARCHY[Role.MANAGER]


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(f"{k}: {_flatten(v)}" for k, v in value.items() if v not in (None, "", [], {}))
    if isinstance(value, list):
        return "\n".join(_flatten(v) for v in value)
    return "" if value is None else str(value)


def document_link(document_id: str, page: int | None) -> str:
    """Deep link that opens a document in the viewer at *page*."""
    return f"/plan-room?doc={document_id}&page={page or 1}"


async def _document_passages(session: AsyncSession, project_id: uuid.UUID, role: str, user_id: str) -> list[Passage]:
    from app.modules.documents.models import Document, Sheet
    from app.modules.file_search.models import FileSearchIndex

    index_rows = (
        (
            await session.execute(
                select(FileSearchIndex)
                .where(FileSearchIndex.project_id == project_id, FileSearchIndex.file_kind == "document")
                .limit(MAX_DOCUMENTS)
            )
        )
        .scalars()
        .all()
    )
    ids: dict[uuid.UUID, Any] = {}
    for row in index_rows:
        try:
            ids[uuid.UUID(row.file_id)] = row
        except (ValueError, TypeError):
            continue
    if not ids:
        return []
    # file_id is a string column and Document.id a UUID, so resolve in Python rather than join across types.
    docs = (await session.execute(select(Document).where(Document.id.in_(list(ids))))).scalars().all()
    rows = [(ids[d.id], d) for d in docs if d.project_id == project_id]
    sheet_rows = (await session.execute(select(Sheet).where(Sheet.project_id == project_id))).scalars().all()
    sheets: dict[str, dict[int, dict[str, Any]]] = {}
    for sheet in sheet_rows:
        sheets.setdefault(str(sheet.document_id), {})[int(sheet.page_number)] = {
            "sheet_number": sheet.sheet_number,
            "sheet_title": sheet.sheet_title,
            "revision": sheet.revision,
        }
    out: list[Passage] = []
    for index_row, doc in rows:
        if not can_read_classified(role, doc.security_classification, doc.uploaded_by or "", user_id):
            continue
        doc_id = str(doc.id)
        kind = _CATEGORY_KIND.get((doc.category or "").lower(), "document")
        out += chunk_document(
            source_kind=kind,
            source_id=doc_id,
            title=doc.name,
            content_text=index_row.content_text or "",
            document_id=doc_id,
            revision=doc.revision_code or (f"v{doc.version}" if doc.version else None),
            is_current=doc.is_current_revision is not False,
            sheets_by_page=sheets.get(doc_id),
            link_for_page=lambda page, _d=doc_id: document_link(_d, page),
        )
    return out


async def _record_passages(session: AsyncSession, project_id: uuid.UUID, role: str) -> list[Passage]:
    out: list[Passage] = []
    if can_read(role, "rfi.read"):
        from app.modules.rfi.models import RFI

        for r in (await session.execute(select(RFI).where(RFI.project_id == project_id).limit(MAX_RECORDS))).scalars():
            text = f"{r.subject}\n{r.question}\n{r.official_response or ''}"
            out += record_passages(
                source_kind="rfi",
                source_id=str(r.id),
                title=f"{r.rfi_number} {r.subject}",
                text=text,
                deep_link=f"/rfi/{r.id}",
            )
    if can_read(role, "submittals.read"):
        from app.modules.submittals.models import Submittal

        stmt = select(Submittal).where(Submittal.project_id == project_id).limit(MAX_RECORDS)
        for s in (await session.execute(stmt)).scalars():
            text = _flatten(
                {
                    "title": s.title,
                    "spec_section": s.spec_section,
                    "type": s.submittal_type,
                    "manufacturer": s.manufacturer,
                    "model": s.model_reference,
                    "outcome": s.review_outcome,
                    "history": s.review_history,
                }
            )
            out += record_passages(
                source_kind="submittal",
                source_id=str(s.id),
                title=f"{s.submittal_number} {s.title}",
                text=text,
                deep_link=f"/submittals?id={s.id}",
                revision=str(s.current_revision),
                section=s.spec_section,
            )
    if can_read(role, "correspondence.read"):
        from app.modules.correspondence.models import Correspondence

        stmt = select(Correspondence).where(Correspondence.project_id == project_id).limit(MAX_RECORDS)
        for c in (await session.execute(stmt)).scalars():
            out += record_passages(
                source_kind="correspondence",
                source_id=str(c.id),
                title=f"{c.reference_number} {c.subject}",
                text=f"{c.subject}\n{c.notes or ''}",
                deep_link=f"/correspondence?id={c.id}",
                section=c.contract_clause_ref,
            )
    if can_read(role, "meetings.read"):
        from app.modules.meetings.models import Meeting, MeetingMinutes

        stmt = (
            select(MeetingMinutes, Meeting)
            .join(Meeting, Meeting.id == MeetingMinutes.meeting_id)
            .where(MeetingMinutes.project_id == project_id)
            .limit(MAX_RECORDS)
        )
        for minutes, meeting in (await session.execute(stmt)).all():
            out += record_passages(
                source_kind="minutes",
                source_id=str(minutes.id),
                title=f"{meeting.meeting_number} {meeting.title}",
                text=_flatten(minutes.content),
                deep_link=f"/meetings?id={meeting.id}",
            )
    if can_read(role, "contracts.read"):
        from app.modules.contracts.models import Contract

        stmt = select(Contract).where(Contract.project_id == project_id).limit(MAX_RECORDS)
        for k in (await session.execute(stmt)).scalars():
            terms = _flatten(k.terms) if k.terms else ""
            if not terms.strip():
                continue
            out += record_passages(
                source_kind="contract",
                source_id=str(k.id),
                title=f"{k.code} {k.title}",
                text=terms,
                deep_link=f"/contracts?id={k.id}",
            )
    return out


async def collect_passages(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    role: str,
    user_id: str,
    kinds: set[str] | None = None,
) -> list[Passage]:
    """All passages *user_id* (with *role*) may read in *project_id*, optionally filtered by source kind."""
    passages: list[Passage] = []
    if can_read(role, "documents.read"):
        try:
            passages += await _document_passages(session, project_id, role, user_id)
        except Exception:  # noqa: BLE001 - an unreadable index must not hide the other sources
            logger.warning("Document passages unavailable for project %s", project_id, exc_info=True)
    try:
        passages += await _record_passages(session, project_id, role)
    except Exception:  # noqa: BLE001
        logger.warning("Record passages unavailable for project %s", project_id, exc_info=True)
    if kinds:
        passages = [p for p in passages if p.source_kind in kinds]
    return passages[:MAX_PASSAGES]


def passages_digest(passages: list[Passage]) -> str:
    """Small stable fingerprint of a passage set, for logging and tests."""
    return json.dumps(sorted({p.source_id for p in passages}))[:200]
