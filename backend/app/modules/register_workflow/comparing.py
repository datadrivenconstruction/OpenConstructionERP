# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The quotes themselves, gathered per supplier so they can be read side by side.

Comparing prices from a table of numbers is not comparing quotes. The
number is a summary somebody (or something) made of a document, and the
question that decides an award - did they price the whole scope, what did
they exclude, is the lead time real - is only answerable by looking at
what they actually sent.

So this collects, for each supplier asked: their reply, its readable
body, and every document that came with it. The compare screen then puts
one column per supplier on the glass with the document IN it, which is
what makes an award justifiable from a single screen.

Serving is deliberately narrow. A path is only ever resolved from the
record it belongs to and must land inside a known uploads root; a
filename from an email is treated as hostile, because it is.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.register_workflow.models import RegisterItem

logger = logging.getLogger(__name__)

#: Everywhere a served document may legitimately live. Anything resolving
#: outside all of these is refused regardless of what the record says.
ALLOWED_ROOTS = (
    Path("uploads/register_workflow"),
    Path("uploads/outlook_bridge"),
    Path("uploads/correspondence"),
)

#: Rendered in the browser rather than downloaded. Everything else is
#: served as octet-stream so a hostile name cannot execute.
INLINE_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain",
}

#: A real quote document. Signature logos are not quotes - counting them
#: once let a supplier's one-line question look like a priced response.
DOCLIKE = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".csv", ".rtf"}


class CompareError(Exception):
    pass


def _under_allowed_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:  # pragma: no cover
        return False
    for root in ALLOWED_ROOTS:
        base = root.resolve()
        if base == resolved or base in resolved.parents:
            return True
    return False


def resolve_stored(raw: str) -> tuple[Path, str, bool]:
    """(path, media type, inline?) for a path recorded against a message.

    The stored value is trusted only as far as "it names a file we saved":
    it must resolve inside an uploads root and exist. That is what stops a
    forged attachment entry turning this into an arbitrary file read.
    """
    if not raw:
        raise CompareError("No document named")
    path = Path(str(raw))
    if not _under_allowed_root(path):
        raise CompareError("Outside the document store")
    if not path.is_file():
        raise CompareError("Not found")
    media = INLINE_TYPES.get(path.suffix.lower())
    return path, media or "application/octet-stream", media is not None


def _docs_from(record: Any) -> list[dict[str, Any]]:
    """Attachment entries on a correspondence or swept-message row."""
    out: list[dict[str, Any]] = []
    for att in getattr(record, "attachments", None) or []:
        if isinstance(att, str):
            name, stored = Path(att).name, att
        elif isinstance(att, dict):
            name = str(att.get("filename") or att.get("name") or "")
            stored = str(att.get("path") or att.get("stored_path") or att.get("filename") or "")
        else:
            continue
        if not name:
            continue
        suffix = Path(name).suffix.lower()
        out.append(
            {
                "filename": name,
                "stored": stored,
                "is_quote_document": suffix in DOCLIKE,
                "inline": suffix in INLINE_TYPES,
            }
        )
    return out


async def quotes_side_by_side(session: AsyncSession, item: RegisterItem) -> dict[str, Any]:
    """One column per supplier: their reply, its body, and their documents.

    Ordered so the columns read the way a decision is made - anybody who
    actually priced it first, then repliers, then the silent.
    """
    from app.modules.register_workflow import suggestions, tracking

    columns: list[dict[str, Any]] = []
    figures: dict[str, Any] = {}
    try:
        found = await suggestions.suggestions_for(session, item)
        figures = found.get("by_supplier") or {}
    except Exception:  # noqa: BLE001
        logger.debug("Figures unavailable for %s", item.reference, exc_info=True)

    state = await tracking.tracking_for(session, item)

    # Their replies, so the body can be read without leaving the screen.
    replies_by_supplier: dict[str, list[Any]] = {}
    roll = [(r["contact_id"] or r["name"], r["name"]) for r in state["rows"] if r.get("name")]
    for reply in await tracking._replies_for(session, item):
        text = " ".join(str(x or "") for x in (reply.subject, reply.notes))
        from_id = str(getattr(reply, "from_contact_id", "") or "")
        key = from_id if from_id else suggestions.match_supplier(text, roll)
        if key:
            replies_by_supplier.setdefault(str(key), []).append(reply)

    for row in state["rows"]:
        key = str(row.get("contact_id") or row.get("name") or "")
        theirs = replies_by_supplier.get(key, [])
        docs: list[dict[str, Any]] = []
        body_html = ""
        body_text = ""
        for reply in theirs:
            for d in _docs_from(reply):
                docs.append({**d, "correspondence_id": str(reply.id)})
            if not body_text:
                body_text = str(getattr(reply, "notes", "") or "")
            if not body_html:
                # The formatted original, kept by the inbox sweep under
                # metadata_["source_html"] - ALREADY sanitised on write
                # (register allowlist), so it is safe to hand straight to
                # the column for rendering.
                meta = getattr(reply, "metadata_", None) or {}
                body_html = str(meta.get("source_html") or "")

        fig = figures.get(key) or {}
        columns.append(
            {
                "contact_id": row.get("contact_id"),
                "name": row["name"],
                "email": row.get("email", ""),
                "state": row["state"],
                "days_waiting": row.get("days_waiting"),
                "sent_count": row.get("sent_count", 0),
                "replied_at": row.get("replied_at"),
                # The figure, and the words it was read out of - a price
                # with no evidence behind it is not usable in an award.
                "amount": fig.get("amount") or row.get("quoted_amount") or "",
                "basis": fig.get("basis") or "",
                "lead_time": fig.get("lead_time") or "",
                "quote_number": fig.get("quote_number") or "",
                "evidence": fig.get("evidence") or "",
                "warnings": fig.get("warnings") or [],
                "reply_subject": row.get("reply_subject"),
                "reply_body": body_text[:4000],
                "reply_html": body_html,
                "documents": docs,
                "has_quote_document": any(d["is_quote_document"] for d in docs),
            }
        )

    order = {"quoted": 0, "replied": 1, "overdue": 2, "chase": 3, "waiting": 4, "not_asked": 5}
    columns.sort(key=lambda c: (order.get(c["state"], 9), c["name"]))
    return {
        "item_id": str(item.id),
        "reference": item.reference,
        "kind": item.kind,
        "title": item.title,
        "columns": columns,
        "totals": state["totals"],
    }


async def message_for_viewing(session: AsyncSession, item: RegisterItem, correspondence_id: str) -> dict[str, Any]:
    """One received email, safe to render: headers, body, its documents.

    The body is sanitised through the same allowlist the .eml viewer uses,
    because it is the same untrusted source - a supplier's mail rendered
    inside the buyer's session.
    """
    from app.modules.correspondence.models import Correspondence
    from app.modules.register_workflow.sanitise import sanitise_html

    try:
        cid = uuid.UUID(str(correspondence_id))
    except ValueError:
        raise CompareError("Bad message id") from None
    row = (
        await session.execute(
            select(Correspondence)
            .where(Correspondence.id == cid)
            # SCOPED TO THIS ITEM'S PROJECT. Without it the viewer is an
            # open door onto every message in the deployment.
            .where(Correspondence.project_id == item.project_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise CompareError("Message not found")

    raw_body = str(getattr(row, "notes", "") or "")
    looks_html = "<" in raw_body and ">" in raw_body
    safe_html, blocked = sanitise_html(raw_body) if looks_html else ("", False)

    # Resolve the parties to NAMES. A reader showing a row of UUIDs is a
    # database view, not an email - the whole point of opening it here
    # rather than in Outlook is that it knows who these people are.
    async def _people(ids: list[Any]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        try:
            from app.modules.contacts.models import Contact

            wanted = [uuid.UUID(str(i)) for i in ids if str(i or "").strip()]
            if not wanted:
                return out
            found = (await session.execute(select(Contact).where(Contact.id.in_(wanted)))).scalars().all()
            for c in found:
                out.append(
                    {
                        "contact_id": str(c.id),
                        "name": c.company_name
                        or " ".join(x for x in [c.first_name, c.last_name] if x)
                        or (c.primary_email or ""),
                        "email": c.primary_email or "",
                    }
                )
        except Exception:  # noqa: BLE001 - a missing contact must not blank the email
            logger.debug("Could not resolve parties on %s", row.id, exc_info=True)
        return out

    sender = await _people([getattr(row, "from_contact_id", None)])
    recipients = await _people(list(getattr(row, "to_contact_ids", None) or []))

    docs = _docs_from(row)
    for d in docs:
        # Size is what tells a reader whether the "quote" is a real
        # document or a 4KB signature image.
        try:
            d["size"] = Path(d["stored"]).stat().st_size if d.get("stored") else 0
        except OSError:
            d["size"] = 0

    return {
        "correspondence_id": str(row.id),
        "reference_number": getattr(row, "reference_number", ""),
        "subject": row.subject,
        "direction": row.direction,
        "date": getattr(row, "date_received", None) or getattr(row, "date_sent", None),
        "from_contact_id": getattr(row, "from_contact_id", None),
        "to_contact_ids": getattr(row, "to_contact_ids", None) or [],
        "from_people": sender,
        "to_people": recipients,
        "text": "" if looks_html else raw_body,
        "html": safe_html,
        "remote_content_blocked": blocked,
        "documents": docs,
        # What the scanner read out of this message, so the reader can show
        # the figure beside the words it came from rather than in a
        # different screen.
        "extracted": await _extracted_for(session, row),
    }


async def _extracted_for(session: AsyncSession, row: Any) -> dict[str, Any]:
    """The stored analysis of this message, if the scanner has seen it."""
    try:
        from app.modules.comms_intelligence.models import CommsAnalysis

        found = (
            await session.execute(
                select(CommsAnalysis)
                .where(CommsAnalysis.correspondence_id == str(row.id))
                .order_by(CommsAnalysis.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if found is None:
            return {}
        data = dict(found.extracted or {})
        price = data.get("package_price") or {}
        return {
            "amount": price.get("amount") or "",
            "basis": price.get("basis") or "",
            "evidence": price.get("evidence") or "",
            "warnings": price.get("warnings") or [],
            "lead_time": data.get("lead_time") or "",
            "quote_number": data.get("quote_number") or "",
            "category": getattr(found, "category", "") or "",
            "confidence": getattr(found, "confidence", None),
        }
    except Exception:  # noqa: BLE001
        logger.debug("No analysis available for %s", getattr(row, "id", "?"), exc_info=True)
        return {}


async def find_document(
    session: AsyncSession, item: RegisterItem, correspondence_id: str, filename: str
) -> tuple[Path, str, bool]:
    """Resolve one document named on one message belonging to this item.

    Deliberately indirect: the caller names a message and a FILENAME, and
    the path comes from the record rather than from the request, so a
    request can never point the server at a file of its choosing.
    """
    view = await message_for_viewing(session, item, correspondence_id)
    bare = Path(str(filename)).name
    for doc in view["documents"]:
        if Path(doc["filename"]).name == bare:
            return resolve_stored(doc["stored"])
    raise CompareError("That document is not on this message")
