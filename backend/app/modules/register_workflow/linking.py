# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Cross-links: what an item is CONNECTED to, on the record.

An RFQ is rarely an island: it exists because an RFI's answer changed
the scope, it charges a cost centre, it delivers a piece of the job. The
provenance chain (``raised_from_id``) already records how an item came
to exist; these links record what it is ABOUT, and they are added by a
person, after the fact, both ways.

Four link kinds:

    item         - another register item, by reference. Stored with the
                   target's id AND a RECIPROCAL link on the target, so
                   standing on either end shows the other. The reciprocal
                   is removed with the link - a one-way "linked" is a
                   broken promise on the far end.
    cost_centre  - a cost centre code/name (text; the ERP has no single
                   cost-centre registry to point into).
    deliverable  - a job deliverable, named.
    url          - anything with an address (a SharePoint folder, a
                   drawing set). http(s) only.

Stored under the server-owned ``_links`` key: a client that could write
it directly could fabricate "linked to VO-000012" on an item the VO
never saw.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.register_workflow.models import RegisterItem
from app.modules.register_workflow.service import WorkflowError, single_line

logger = logging.getLogger(__name__)

LINKS_KEY = "_links"
LINK_TYPES = ("item", "cost_centre", "deliverable", "url")

#: Enough for a busy item, bounded so the JSON column stays a record
#: rather than a dumping ground.
MAX_LINKS = 40


def links_of(item: RegisterItem) -> list[dict[str, Any]]:
    raw = (item.fields or {}).get(LINKS_KEY) or []
    return [dict(x) for x in raw if isinstance(x, dict)]


def _write(item: RegisterItem, links: list[dict[str, Any]]) -> None:
    fields = dict(item.fields or {})
    fields[LINKS_KEY] = links
    item.fields = fields


def _entry(link_type: str, label: str, target_id: str = "", reference: str = "") -> dict[str, str]:
    return {
        "type": link_type,
        "label": single_line(label)[:160].strip(),
        "target_id": target_id,
        "reference": reference,
    }


async def add_link(session: AsyncSession, item: RegisterItem, *, link_type: str, value: str) -> list[dict[str, Any]]:
    """Attach one link; item links attach their reciprocal too."""
    if link_type not in LINK_TYPES:
        raise WorkflowError("A link is an item, a cost centre, a deliverable or a URL")
    value = single_line(value)[:200].strip()
    if not value:
        raise WorkflowError("The link needs a value")

    links = links_of(item)
    if len(links) >= MAX_LINKS:
        raise WorkflowError(f"An item carries at most {MAX_LINKS} links")

    if link_type == "url":
        if not (value.startswith("https://") or value.startswith("http://")):
            # A javascript: URL stored here renders as a clickable link on
            # everyone's screen - refuse anything that is not plainly web.
            raise WorkflowError("A link URL must start with http:// or https://")
        entry = _entry("url", value)
    elif link_type == "item":
        # BY REFERENCE, WITHIN THIS PROJECT. A reference is what a person
        # actually knows ("link it to REG-RFI-000004"); an id is not. And
        # scoping to the project keeps a typo from linking two clients'
        # jobs together.
        target = (
            await session.execute(
                select(RegisterItem)
                .where(RegisterItem.project_id == item.project_id)
                .where(RegisterItem.reference.ilike(value))
            )
        ).scalar_one_or_none()
        if target is None:
            raise WorkflowError(f"No item on this job carries the reference {value!r} - check the register.")
        if target.id == item.id:
            raise WorkflowError("An item cannot be linked to itself")
        if any(x.get("target_id") == str(target.id) for x in links if x.get("type") == "item"):
            raise WorkflowError(f"Already linked to {target.reference}")
        entry = _entry("item", f"{target.reference} — {target.title}", str(target.id), target.reference)
        # The reciprocal, so the far end shows this one.
        back = links_of(target)
        if len(back) < MAX_LINKS and not any(
            x.get("target_id") == str(item.id) for x in back if x.get("type") == "item"
        ):
            back.append(_entry("item", f"{item.reference} — {item.title}", str(item.id), item.reference))
            _write(target, back)
    else:
        entry = _entry(link_type, value)

    links.append(entry)
    _write(item, links)
    await session.flush()
    return links_of(item)


async def remove_link(session: AsyncSession, item: RegisterItem, *, index: int) -> list[dict[str, Any]]:
    """Take one link off; an item link takes its reciprocal with it."""
    links = links_of(item)
    if not (0 <= index < len(links)):
        raise WorkflowError("That link is not on the item")
    gone = links.pop(index)
    _write(item, links)

    if gone.get("type") == "item" and gone.get("target_id"):
        try:
            target = await session.get(RegisterItem, uuid.UUID(str(gone["target_id"])))
        except (ValueError, TypeError):
            target = None
        if target is not None:
            back = [x for x in links_of(target) if not (x.get("type") == "item" and x.get("target_id") == str(item.id))]
            _write(target, back)
    await session.flush()
    return links_of(item)
