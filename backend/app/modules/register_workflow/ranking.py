# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Which suppliers to put at the top of the picker.

The directory is 434 companies. Ordered alphabetically it is a search
box you have to type into every single time - which is what the picker
was before this file existed. The old app solved it by ranking, and the
ranking is the whole feature: the people you are already working with on
THIS job float to the top and are visibly marked, so the common case is
a click rather than a search.

Four tiers, most specific first:

    0  last on this kind - who the previous RFQ (or RFI, or order) on
                           this job went to
    1  recent here       - used on this job in the last 90 days
    2  on this job       - used on this job at some point
    3  often used        - tagged as such in the DIRECTORY, which is
                           company-wide reference data rather than any
                           one client's business

Everything else is tier 4 and sorts by name. Ties inside a tier sort by
name too, so the list is stable between renders - a picker that reorders
under the cursor is worse than one that never sorted at all.

EVERY PROJECT-DERIVED TIER IS SCOPED TO THIS PROJECT. "Recent" originally
reached across all of them, on the reasoning that a supplier used last
week on another job is a better guess than one never used. That reasoning
holds for one company on one deployment and fails the moment two do not
share a client list: this function answers with contact ids and the
browser then fetches those contacts, so asking about MY job would tell me
who is on YOURS. Who a client buys from is commercially sensitive, and
the fix is the same one the reply builder uses - make the leak impossible
by construction rather than merely unlikely.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.register_workflow.models import RegisterItem

logger = logging.getLogger(__name__)

#: How far back "recent" reaches. Long enough to cover a quiet package,
#: short enough that a supplier you used once last year is not promoted
#: over one you emailed on Tuesday.
RECENT_DAYS = 90

#: The directory tag the old app's "often used" star maps onto.
OFTEN_USED_TAG = "often-used"

TIER_LAST_ON_KIND = 0
TIER_RECENT = 1
TIER_ON_PROJECT = 2
TIER_OFTEN_USED = 3
TIER_NONE = 4

TIER_LABELS = {
    TIER_LAST_ON_KIND: "last used here",
    TIER_RECENT: "recent here",
    TIER_ON_PROJECT: "on this job",
    TIER_OFTEN_USED: "often used",
}


def _ids(value: Any) -> list[str]:
    return [str(v) for v in (value or []) if str(v or "").strip()]


async def ranking_for(session: AsyncSession, *, project_id: uuid.UUID, kind: str) -> dict[str, Any]:
    """The tier of every supplier this job has any history with.

    Returns ``{contact_id: {"tier": int, "label": str}}`` plus the tier
    labels, so the browser sorts and tints without a second round trip
    and without inventing its own idea of what "recent" means.
    """
    on_project: set[str] = set()
    last_on_kind: set[str] = set()
    recent: set[str] = set()

    items = (await session.execute(select(RegisterItem).where(RegisterItem.project_id == project_id))).scalars().all()
    for item in items:
        on_project.update(_ids(item.recipient_contact_ids))

    # "Last on this kind" is the most recently CREATED item of that kind
    # that actually went to somebody - an item raised and never sent has
    # no recipients to learn from, so it must not blank the tier.
    same_kind = [i for i in items if i.kind == kind and _ids(i.recipient_contact_ids)]
    if same_kind:
        # created_at is a real datetime; comparing them as STRINGS looks
        # right and is not - str(datetime) separates the date and time
        # with a space, which sorts before the "T" an ISO cutoff uses.
        newest = max(same_kind, key=lambda i: i.created_at)
        last_on_kind.update(_ids(newest.recipient_contact_ids))

    # Recent means recent ON THIS JOB. It used to mean recent anywhere,
    # which handed the caller contact ids from projects they may not be
    # allowed to see - see the module docstring. Reading `items` again
    # rather than re-querying: they are already loaded and already scoped.
    cutoff = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
    for item in items:
        created = getattr(item, "created_at", None)
        if created is not None and created >= cutoff:
            recent.update(_ids(item.recipient_contact_ids))

    often_used: set[str] = set()
    try:
        from app.modules.contacts.models import Contact

        rows = (await session.execute(select(Contact).where(Contact.is_active.is_(True)))).scalars().all()
        for c in rows:
            tags = [str(x).strip().lower() for x in (c.module_tags or [])]
            if OFTEN_USED_TAG in tags:
                often_used.add(str(c.id))
    except Exception:  # noqa: BLE001 - as above
        logger.debug("Could not read directory tags", exc_info=True)

    tiers: dict[str, dict[str, Any]] = {}
    # Applied WORST FIRST so the best tier a supplier qualifies for is the
    # one that survives. Written the other way round, "often used" would
    # overwrite "on this job" and the picker would bury the people you are
    # actually working with.
    for group, tier in (
        (often_used, TIER_OFTEN_USED),
        (on_project, TIER_ON_PROJECT),
        (recent, TIER_RECENT),
        (last_on_kind, TIER_LAST_ON_KIND),
    ):
        for cid in group:
            tiers[cid] = {"tier": tier, "label": TIER_LABELS[tier]}
    return {
        "kind": kind,
        "tiers": tiers,
        "tier_labels": TIER_LABELS,
        "recent_days": RECENT_DAYS,
    }
