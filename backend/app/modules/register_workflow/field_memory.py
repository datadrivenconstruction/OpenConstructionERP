# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""What this job has said before, offered back on the next form.

The raise form used to open blank every time. On a job that runs for
eight months that means retyping the same delivery address, the same
site contact and the same site hours onto every RFQ, every order and
every delay notice - and a retyped address is a mistyped address, which
is a delivery to the wrong gate.

So: for each field, two things.

    default  - what it should be pre-filled with when the form opens.
               The delivery address starts as the PROJECT's address; a
               date-raised field starts today; a response-required field
               starts a week out.
    recent   - what this job has actually used in that field before,
               most recently first, offered as a pick-list.

``recent`` is drawn from this project only. A delivery address from
another job is not a helpful suggestion, it is a way to send switchboards
to the wrong site.

Nothing here is a rail. It is a convenience, so every lookup degrades to
"no suggestion" rather than to an error - a blank suggestion list must
never stop somebody raising an RFQ.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.register_workflow import templates
from app.modules.register_workflow.models import RegisterItem

logger = logging.getLogger(__name__)

#: How many past answers to offer per field. Long enough to cover the
#: two or three addresses a job really uses, short enough that the list
#: stays a pick rather than a search.
MAX_RECENT = 8

#: Fields whose default is the project's own address.
_SITE_ADDRESS_LABELS = ("Delivery to", "Site address", "Location")

#: Fields that mean "today" when the form opens.
_TODAY_LABELS = ("Date raised", "Date of talk", "Date noticed", "Date")

#: Fields that mean "a week from today" - the response-required default
#: the old app used, so a request always carries a date to chase against.
_PLUS_7_LABELS = ("Response required by", "Quotes due", "Reply by")
DEFAULT_RESPONSE_DAYS = 7


def _project_address(project: Any) -> str:
    """The project's address as one line, however it happens to be stored.

    ``Project.address`` is a free-shape JSON blob - different importers
    have filled it differently - so this reads the keys that actually
    appear rather than assuming a schema, and falls back to nothing.
    """
    raw = getattr(project, "address", None)
    if isinstance(raw, str):
        return raw.strip()
    if not isinstance(raw, dict):
        return ""
    for single in ("formatted", "full", "line", "address", "text"):
        value = str(raw.get(single) or "").strip()
        if value:
            return value
    parts = [
        str(raw.get(k) or "").strip()
        for k in ("street", "line1", "address_line_1", "suburb", "city", "state", "postcode", "postal_code")
    ]
    return ", ".join(p for p in parts if p)


def _iso(d: date) -> str:
    return d.isoformat()


async def suggestions_for(session: AsyncSession, *, project_id: uuid.UUID, kind: str) -> dict[str, Any]:
    """``{label: {"default": str, "recent": [str, ...]}}`` for one kind's form."""
    # MONEY IS NEVER REMEMBERED. The estimated value is what the quote
    # gate tiers off - carry last package's figure onto this one and a
    # $40k job silently inherits a $2k package's one-quote rule. A price
    # is the one field that must be typed every time, on purpose.
    labels = [label for label, ftype, _due, _internal in templates.FIELDS.get(kind, []) if ftype != "money"]
    if not labels:
        return {"kind": kind, "fields": {}}

    # Every item on THIS project, newest first, whatever kind - a delivery
    # address typed on an order is just as good a suggestion on an RFQ.
    items: list[RegisterItem] = []
    try:
        items = list(
            (
                await session.execute(
                    select(RegisterItem)
                    .where(RegisterItem.project_id == project_id)
                    .order_by(RegisterItem.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
    except Exception:  # noqa: BLE001 - a suggestion list is never a gate
        logger.debug("Could not read this project's history", exc_info=True)

    project = None
    try:
        from app.modules.projects.models import Project

        project = (await session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        logger.debug("Could not read the project", exc_info=True)

    site_address = _project_address(project) if project is not None else ""
    today = datetime.now(UTC).date()

    out: dict[str, dict[str, Any]] = {}
    for label in labels:
        recent: list[str] = []
        seen: set[str] = set()
        for item in items:
            value = str((item.fields or {}).get(label) or "").strip()
            # Multi-line values are pasted tables, not addresses. Offering
            # one back as a one-click suggestion would paste a whole
            # materials list into a site-contact box.
            if not value or "\n" in value or "\t" in value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            recent.append(value)
            if len(recent) >= MAX_RECENT:
                break

        default = ""
        if label in _SITE_ADDRESS_LABELS:
            # The job's OWN address leads; what was actually typed last
            # time wins only if the project has no address recorded.
            default = site_address or (recent[0] if recent else "")
        elif label in _TODAY_LABELS:
            default = _iso(today)
        elif label in _PLUS_7_LABELS:
            default = _iso(today + timedelta(days=DEFAULT_RESPONSE_DAYS))
        elif recent:
            # Anything else this job has answered the same way before -
            # site hours, the site contact, the cost centre.
            default = recent[0]

        if default or recent:
            out[label] = {"default": default, "recent": recent}

    return {"kind": kind, "fields": out, "project_address": site_address}
