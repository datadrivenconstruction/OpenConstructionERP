# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ addenda and Q&A on one seeded tender package.

Two published addenda (the second changes the BOQ and extends the deadline),
three bidders of which one never acknowledged the second addendum, and four
questions in different states. Day offsets come from the project country's
tender rules, so a German and a French demo show their own defaults.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.tender_rules import rules_for
from app.modules.tendering.addenda import closing_date
from app.modules.tendering.models import TenderClarification

#: Demo projects that carry the addenda story, and the jurisdiction they show.
DEMO_ADDENDA_COUNTRIES: dict[str, str] = {"residential-berlin": "DE", "school-paris": "FR"}

_QUESTIONS = (
    ("Is the concrete grade for the slabs C30/37 or C35/45?", "C30/37 as in the specification; see addendum 1."),
    ("May bidders offer an equivalent waterproofing system?", "Yes, with the data sheet attached to the bid."),
    ("Is the site crane provided by the main contractor?", "Yes, the crane is provided until the shell is complete."),
    ("Can the submission deadline be extended by one week?", ""),
)


def seed_package_addenda(
    meta: dict[str, Any],
    deadline: str,
    bids: list[Any],
    package_id: uuid.UUID,
    country_code: str,
    first_position_ids: list[str],
) -> tuple[dict[str, Any], str, list[TenderClarification]]:
    """Return ``(metadata, new deadline, clarification rows)`` for the package."""
    rules = rules_for(country_code)
    close = closing_date(deadline) or datetime.now(UTC).date() + timedelta(days=21)
    new_close = close + timedelta(days=7)
    issued = datetime.now(UTC) - timedelta(days=20)
    recipients = [r for r in meta.get("recipients") or [] if isinstance(r, dict)]
    by_email = {str(r.get("email")): str(r.get("id")) for r in recipients}
    for bid in bids:
        rid = by_email.get(bid.contact_email)
        if rid:
            bid.metadata_ = {**(bid.metadata_ or {}), "recipient_id": rid}
    bidder_ids = [str((b.metadata_ or {}).get("recipient_id") or b.id) for b in bids[:3]]

    def ack(ids: list[str], at: datetime) -> list[dict]:
        return [{"bidder_id": i, "acknowledged_at": at.isoformat(), "user_id": None} for i in ids]

    a1_at = issued + timedelta(days=4)
    a2_at = datetime.combine(
        close - timedelta(days=rules.addendum_min_days_before_closing + 2), datetime.min.time(), UTC
    )
    pid = first_position_ids[0] if first_position_ids else None
    changes = [
        {
            "op": "change",
            "position_id": pid,
            "ordinal": "",
            "description": "Quantity corrected after drawing revision B",
            "unit": "",
            "quantity_before": "100",
            "quantity_after": "112",
            "description_before": None,
        }
    ]
    addenda = [
        {
            "id": str(uuid.uuid4()),
            "revision_no": 1,
            "title": "Concrete grade clarification",
            "body": "Slabs are C30/37 throughout; the general notes on the drawings are superseded.",
            "published_at": a1_at.isoformat(),
            "published_by_user_id": None,
            "acknowledged_by": ack(bidder_ids, a1_at + timedelta(days=1)),
            "created_at": a1_at.isoformat(),
            "updated_at": a1_at.isoformat(),
            "document_changes": [{"title": "General arrangement", "drawing_number": "A-101", "revision": "B"}],
            "boq_changes": [],
            "new_deadline": None,
        },
        {
            "id": str(uuid.uuid4()),
            "revision_no": 2,
            "title": "Revised quantities and deadline extension",
            "body": "One bill line changes and the submission deadline moves by one week.",
            "published_at": a2_at.isoformat(),
            "published_by_user_id": None,
            # The third bidder never acknowledged this addendum.
            "acknowledged_by": ack(bidder_ids[:2], a2_at + timedelta(days=1)),
            "created_at": a2_at.isoformat(),
            "updated_at": a2_at.isoformat(),
            "document_changes": [],
            "boq_changes": changes if pid else [],
            "boq_revision_no": 1 if pid else None,
            "previous_deadline": deadline,
            "new_deadline": new_close.isoformat(),
        },
    ]
    meta = {
        **meta,
        "addenda": addenda,
        "tender_rules_country": rules.country_code,
    }
    if pid:
        meta["boq_revision_no"] = 1
        meta["boq_revisions"] = [
            {
                "revision_no": 1,
                "addendum_id": addenda[1]["id"],
                "addendum_revision_no": 2,
                "changes": changes,
                "created_at": a2_at.isoformat(),
            }
        ]
        # Two bidders repriced on revision 1; the third is still on the bill as issued.
        for i, bid in enumerate(bids[:3]):
            bid.metadata_ = {**(bid.metadata_ or {}), "boq_revision_no": 1 if i < 2 else 0}
    rows: list[TenderClarification] = []
    for n, (question, answer) in enumerate(_QUESTIONS, start=1):
        asked = issued + timedelta(days=n * 2)
        rid = bidder_ids[(n - 1) % len(bidder_ids)] if bidder_ids else None
        rows.append(
            TenderClarification(
                id=uuid.uuid4(),
                package_id=package_id,
                number=n,
                recipient_id=rid,
                asked_by_email="",
                question=question,
                asked_at=asked,
                answer=answer,
                answered_at=asked + timedelta(days=1) if answer else None,
                published_at=asked + timedelta(days=1) if answer and n != 3 else None,
                status=("published" if n != 3 else "answered") if answer else "open",
                addendum_id=addenda[0]["id"] if n == 1 else None,
            )
        )
    return meta, new_close.isoformat(), rows
