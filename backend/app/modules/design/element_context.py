"""Model quantities, documents and open remarks the ERP holds for selected design elements (the editor's selection panel).

Documents come from the ERP's document-to-element links (sheets of a shared revision link to their storey; a person can
link any document). Remarks are tasks whose element list names one of the elements and punch-list items whose element
reference does. Elements are matched in the model of the newest shared revision and by their design key, so a remark
written against the key itself is found too. Reads only.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from .field_links import published
from .revisions import QUANTITY_KEYS

MAX_ITEMS = 50
CLOSED = {"done", "completed", "closed", "cancelled", "canceled", "verified", "resolved", "archived"}


async def _elements(session, project_id: uuid.UUID, keys: list[str]) -> list[Any]:
    from app.modules.bim_hub.models import BIMElement

    rev = await published(session, project_id)
    if rev is None or rev.bim_model_id is None or not keys:
        return []
    return list(
        (
            await session.execute(
                select(BIMElement).where(BIMElement.model_id == rev.bim_model_id, BIMElement.stable_id.in_(keys))
            )
        ).scalars()
    )


def quantities(elements: list[Any]) -> list[dict[str, Any]]:
    """The model's own quantities of the selection, summed per kind (what a take-off would count)."""
    total: dict[str, Decimal] = {}
    for e in elements:
        for k in QUANTITY_KEYS:
            v = (e.quantities or {}).get(k)
            try:
                total[k] = total.get(k, Decimal(0)) + Decimal(str(v))
            except (InvalidOperation, TypeError, ValueError):
                continue
    return [{"kind": k, "value": str(total[k].quantize(Decimal("0.0001")))} for k in QUANTITY_KEYS if k in total]


async def documents(session, project_id: uuid.UUID, ids: dict[uuid.UUID, str]) -> list[dict[str, Any]]:
    from app.modules.documents.models import Document, DocumentBIMLink

    if not ids:
        return []
    rows = (
        await session.execute(
            select(DocumentBIMLink, Document)
            .join(Document, Document.id == DocumentBIMLink.document_id)
            .where(DocumentBIMLink.bim_element_id.in_(list(ids)), Document.project_id == project_id)
        )
    ).all()
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for link, doc in rows:
        d = out.setdefault(
            doc.id,
            {
                "document_id": str(doc.id),
                "name": doc.name,
                "category": doc.category,
                "version": doc.version,
                "link_type": link.link_type,
                "revision": ((doc.metadata_ or {}).get("design") or {}).get("revision_number"),
                "elements": [],
                "url": f"/documents?id={doc.id}",
            },
        )
        if ids[link.bim_element_id] not in d["elements"]:
            d["elements"].append(ids[link.bim_element_id])
    return sorted(out.values(), key=lambda d: (d["link_type"] != "design_sheet", d["name"]))[:MAX_ITEMS]


async def remarks(session, project_id: uuid.UUID, keys: list[str], ids: dict[uuid.UUID, str]) -> list[dict[str, Any]]:
    """Open tasks and punch items about these elements; closed ones are history and stay in their modules."""
    from app.modules.qms.models import QMSPunchItem
    from app.modules.tasks.models import Task

    by_ref = {str(i): k for i, k in ids.items()} | {k: k for k in keys}
    out: list[dict[str, Any]] = []
    for t in (await session.execute(select(Task).where(Task.project_id == project_id))).scalars():
        hit = sorted({by_ref[str(x)] for x in (t.bim_element_ids or []) if str(x) in by_ref})
        if hit and (t.status or "").lower() not in CLOSED:
            out.append(
                {
                    "kind": "task",
                    "id": str(t.id),
                    "title": t.title,
                    "status": t.status,
                    "due": t.due_date,
                    "elements": hit,
                    "url": f"/tasks?id={t.id}",
                }
            )
    refs = list(by_ref)
    if refs:
        for p in (
            await session.execute(
                select(QMSPunchItem).where(
                    QMSPunchItem.project_id == project_id, QMSPunchItem.bim_element_ref.in_(refs)
                )
            )
        ).scalars():
            if (p.status or "").lower() not in CLOSED:
                out.append(
                    {
                        "kind": "punch",
                        "id": str(p.id),
                        "title": p.title,
                        "status": p.status,
                        "due": getattr(p, "due_date", None),
                        "elements": [by_ref[p.bim_element_ref]],
                        "url": f"/punchlist?highlight={p.id}",
                    }
                )
    out.sort(key=lambda r: (str(r["due"] or "9999"), r["title"]))
    return out[:MAX_ITEMS]


async def context(session, project_id: uuid.UUID, keys: list[str]) -> dict[str, Any]:
    elements = await _elements(session, project_id, keys)
    ids = {e.id: e.stable_id for e in elements}
    return {
        "keys": sorted(set(keys)),
        "found": len(elements),
        "quantities": quantities(elements),
        "documents": await documents(session, project_id, ids),
        "remarks": await remarks(session, project_id, keys, ids),
    }
