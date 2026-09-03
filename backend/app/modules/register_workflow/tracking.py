# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Where every email stands: who was asked, who answered, who is silent.

The send log answered "how many were drafted" and nothing else, which is
the wrong question on a live job. What a PM needs at 7am is the other
three:

* Who have I asked, how many times, and when was the last one?
* Who has come back, with what, and how long did they take?
* Who is silent, and how long have they been silent for?

That last one is the whole point. A supplier who never replies costs the
same as one who replies "no" - but only one of them shows up anywhere,
and it is the wrong one. Silence has to be a visible state with an age
against it, or it is invisible until the package is late.

Nothing here writes: it joins what was sent (the item's send log) to what
came back (incoming correspondence matched to this item's suppliers) and
states the position. Every figure is traceable to the record it came
from, same rule as the extraction.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.register_workflow.models import RegisterItem

logger = logging.getLogger(__name__)

#: How long a supplier may sit on an ask before it is called out. Kept
#: deliberately short for quotes - a package cannot be compared until the
#: prices are in, and "I emailed them last week" is not a position.
CHASE_AFTER_DAYS = 3
OVERDUE_AFTER_DAYS = 7


def _parse(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _days_since(when: datetime | None, now: datetime) -> int | None:
    return None if when is None else max(0, (now - when).days)


def _like(value: str) -> str:
    """LIKE-safe. These refs are server-minted, but a register reference
    is exactly the kind of thing that becomes user-editable later."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _replies_for(session: AsyncSession, item: RegisterItem) -> list[Any]:
    """Incoming correspondence that names this item or its native record."""
    try:
        from app.modules.correspondence.models import Correspondence
    except ImportError:  # pragma: no cover
        return []

    refs = {item.reference}
    # Every email this item has sent has its own REG-MSG-###### - a reply
    # quoting only THAT still belongs here.
    for entry in (item.fields or {}).get("_send_log") or []:
        if isinstance(entry, dict) and entry.get("email_ref"):
            refs.add(str(entry["email_ref"]))
    if item.linked_entity_type == "rfq" and item.linked_entity_id:
        try:
            from app.modules.rfq_bidding.models import RFQ

            number = (
                await session.execute(select(RFQ.rfq_number).where(RFQ.id == uuid.UUID(str(item.linked_entity_id))))
            ).scalar_one_or_none()
            if number:
                refs.add(str(number))
        except Exception:  # noqa: BLE001
            logger.debug("Native number unavailable for %s", item.reference, exc_info=True)

    conds = []
    for ref in refs:
        pattern = "%" + _like(str(ref)) + "%"
        conds.append(Correspondence.subject.ilike(pattern, escape="\\"))
        conds.append(Correspondence.notes.ilike(pattern, escape="\\"))
    if not conds:
        return []
    return list(
        (
            await session.execute(
                select(Correspondence)
                .where(Correspondence.project_id == item.project_id)
                .where(Correspondence.direction == "incoming")
                .where(or_(*conds))
                .order_by(Correspondence.created_at.asc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )


async def tracking_for(session: AsyncSession, item: RegisterItem) -> dict[str, Any]:
    """One row per person asked, with the position stated plainly."""
    from app.modules.register_workflow import suggestions

    now = datetime.now(UTC)
    sends = [s for s in (item.fields or {}).get("_send_log") or [] if isinstance(s, dict)]

    # Who was asked. The recipient list is the roll call; the send log
    # says which of them have actually been written to, because an item
    # can name five suppliers and have gone out to two.
    people: dict[str, dict[str, Any]] = {}
    names: dict[str, str] = {}
    try:
        from app.modules.contacts.models import Contact

        ids = [uuid.UUID(str(c)) for c in (item.recipient_contact_ids or []) if str(c)]
        if ids:
            for c in (await session.execute(select(Contact).where(Contact.id.in_(ids)))).scalars():
                label = c.company_name or " ".join(x for x in [c.first_name, c.last_name] if x) or ""
                names[str(c.id)] = label
                people[str(c.id)] = {
                    "contact_id": str(c.id),
                    "name": label,
                    "email": c.primary_email or "",
                }
    except Exception:  # noqa: BLE001
        logger.debug("Contact list unavailable for %s", item.reference, exc_info=True)

    # A send to somebody not on the recipient list still happened - an
    # ad-hoc "email anyone" send is a real email and belongs on the trail.
    for s in sends:
        cid = str(s.get("contact_id") or "")
        key = cid or f"name:{s.get('contact_name') or 'unknown'}"
        if key not in people:
            people[key] = {
                "contact_id": cid or None,
                "name": str(s.get("contact_name") or "Someone not in the book"),
                "email": "",
                "ad_hoc": True,
            }

    for key, row in people.items():
        mine = [
            s for s in sends if (str(s.get("contact_id") or "") or f"name:{s.get('contact_name') or 'unknown'}") == key
        ]
        stamps = sorted(x for x in (_parse(s.get("at")) for s in mine) if x is not None)
        row["sent_count"] = len(mine)
        row["first_sent_at"] = stamps[0].isoformat() if stamps else None
        row["last_sent_at"] = stamps[-1].isoformat() if stamps else None
        row["channels"] = sorted({str(s.get("channel") or "") for s in mine if s.get("channel")})
        row["last_subject"] = mine[-1].get("subject") if mine else None
        # Every send after the first IS a chase - that is what a chaser is.
        row["chases"] = max(0, len(mine) - 1)

    # What came back, attributed to a supplier by the same matcher the
    # compare panel uses - so the two screens can never disagree.
    roll = [(k, str(v.get("name") or "")) for k, v in people.items() if v.get("name")]
    for reply in await _replies_for(session, item):
        text = " ".join(str(x or "") for x in (reply.subject, reply.notes, getattr(reply, "from_contact_id", "")))
        key = None
        from_id = str(getattr(reply, "from_contact_id", "") or "")
        if from_id and from_id in people:
            key = from_id  # the address is better evidence than the words
        else:
            key = suggestions.match_supplier(text, roll)
        if key is None or key not in people:
            continue
        row = people[key]
        at = _parse(getattr(reply, "date_received", None)) or _parse(getattr(reply, "created_at", None))
        # The FIRST reply is the one that stops the clock.
        if row.get("replied_at") is None:
            row["replied_at"] = at.isoformat() if at else None
            row["reply_subject"] = reply.subject
            row["correspondence_id"] = str(reply.id)
            row["reply_reference"] = getattr(reply, "reference_number", None)
        row["reply_count"] = int(row.get("reply_count") or 0) + 1

    # A price is the reply that actually matters on a quote package.
    if item.kind == "rfq":
        try:
            found = await suggestions.suggestions_for(session, item)
            for cid, data in (found.get("by_supplier") or {}).items():
                if cid in people and (data or {}).get("amount"):
                    people[cid]["quoted_amount"] = data["amount"]
                    people[cid]["quoted_basis"] = data.get("basis") or ""
        except Exception:  # noqa: BLE001
            logger.debug("Quote figures unavailable for %s", item.reference, exc_info=True)

    rows: list[dict[str, Any]] = []
    for row in people.values():
        sent_at = _parse(row.get("last_sent_at"))
        replied_at = _parse(row.get("replied_at"))
        waiting = None if replied_at is not None else _days_since(sent_at, now)
        row["days_waiting"] = waiting
        row["days_to_reply"] = (
            None
            if replied_at is None or sent_at is None
            else max(0, (replied_at - _parse(row.get("first_sent_at")) or replied_at - sent_at).days)
        )
        if row.get("quoted_amount"):
            row["state"] = "quoted"
        elif replied_at is not None:
            row["state"] = "replied"
        elif not row.get("sent_count"):
            row["state"] = "not_asked"
        elif waiting is not None and waiting >= OVERDUE_AFTER_DAYS:
            row["state"] = "overdue"
        elif waiting is not None and waiting >= CHASE_AFTER_DAYS:
            row["state"] = "chase"
        else:
            row["state"] = "waiting"
        rows.append(row)

    # Worst first: the longest silence is the thing to act on.
    order = {"overdue": 0, "chase": 1, "waiting": 2, "not_asked": 3, "replied": 4, "quoted": 5}
    rows.sort(key=lambda r: (order.get(r["state"], 9), -(r.get("days_waiting") or 0), r["name"]))

    return {
        "reference": item.reference,
        "kind": item.kind,
        "title": item.title,
        "rows": rows,
        "totals": {
            "asked": sum(1 for r in rows if r.get("sent_count")),
            "on_the_list": len(rows),
            "replied": sum(1 for r in rows if r["state"] in ("replied", "quoted")),
            "quoted": sum(1 for r in rows if r["state"] == "quoted"),
            "silent": sum(1 for r in rows if r["state"] in ("waiting", "chase", "overdue")),
            "overdue": sum(1 for r in rows if r["state"] == "overdue"),
            "never_asked": sum(1 for r in rows if r["state"] == "not_asked"),
        },
    }


async def project_tracking(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    """Every outstanding ask on the job, longest silence first.

    The morning screen: one list of everybody who owes an answer, across
    all six registers, so chasing is a five-minute job rather than a
    trawl through each item.
    """
    from app.modules.register_workflow import service

    items = await service.list_items(session, project_id)
    outstanding: list[dict[str, Any]] = []
    sent_total = 0
    for item in items:
        if item.status != "open":
            continue
        detail = await tracking_for(session, item)
        sent_total += sum(int(r.get("sent_count") or 0) for r in detail["rows"])
        for row in detail["rows"]:
            if row["state"] not in ("waiting", "chase", "overdue"):
                continue
            outstanding.append(
                {
                    **row,
                    "item_id": str(item.id),
                    "reference": item.reference,
                    "kind": item.kind,
                    "title": item.title,
                    "due_date": item.due_date,
                }
            )
    outstanding.sort(key=lambda r: -(r.get("days_waiting") or 0))
    return {
        "outstanding": outstanding,
        "totals": {
            "emails_sent": sent_total,
            "awaiting_reply": len(outstanding),
            "to_chase": sum(1 for r in outstanding if r["state"] in ("chase", "overdue")),
            "overdue": sum(1 for r in outstanding if r["state"] == "overdue"),
        },
    }
