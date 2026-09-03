# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Read the analysed replies and suggest each supplier's figures.

Comms Intelligence already mines every captured reply for a package
price, a lead time and a quote number, with the verbatim words it read
them from. This module carries those findings across to the RFQ they
belong to, matched to the supplier who sent them, so the compare panel
opens with the numbers already in it.

Two rails, both learned the expensive way:

- Extracted figures are SUGGESTIONS. They are never written to a bid on
  their own; a person confirms each one, and a typed figure always wins.
- A document that cannot be placed with confidence goes to an explicit
  ``unmatched`` bucket rather than being guessed onto the nearest name -
  a price on the wrong supplier's column is worse than a price nobody
  claimed.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.register_workflow.models import RegisterItem

logger = logging.getLogger(__name__)

#: Words that carry no identity - two suppliers both being "Pty Ltd" is
#: not a match (ported stop-word list).
_STOP = {
    "pty",
    "ltd",
    "limited",
    "the",
    "and",
    "group",
    "australia",
    "australian",
    "co",
    "company",
    "services",
    "service",
    "supplies",
    "supply",
    "electrical",
    "electric",
    "industries",
    "industrial",
    # TRADE AND PLACE WORDS. These are the words that appear in a
    # supplier's name AND in the body of any quote about the work, so
    # matching on them filed a switchboard quote on whichever supplier
    # happened to have "switchboard" in its trading name. They carry no
    # identity in this industry - half a supplier directory contains them.
    "switchboard",
    "switchboards",
    "cable",
    "cables",
    "cabling",
    "lighting",
    "lights",
    "power",
    "energy",
    "solar",
    "solutions",
    "systems",
    "system",
    "products",
    "equipment",
    "engineering",
    "engineers",
    "contracting",
    "contractors",
    "distribution",
    "distributors",
    "wholesale",
    "wholesalers",
    "trading",
    "national",
    "international",
    "holdings",
    "enterprises",
    "technologies",
    "technology",
    "sydney",
    "melbourne",
    "brisbane",
    "adelaide",
    "perth",
    "canberra",
    "newcastle",
    "wollongong",
    "queensland",
    "victoria",
    "tasmania",
    "north",
    "south",
    "east",
    "west",
    "northern",
    "southern",
    "eastern",
    "western",
    "central",
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", str(name or "").lower())


def tokens(name: str) -> list[str]:
    """Distinctive words in a company name, longest first."""
    words = [w for w in _norm(name).split() if len(w) >= 5 and w not in _STOP]
    return sorted(set(words), key=len, reverse=True)


def match_supplier(text: str, suppliers: list[tuple[str, str]]) -> str | None:
    """Which supplier does this text belong to? None when unsure.

    ``suppliers`` is [(contact_id, display name)]. Strongest signal
    first: the whole normalised name, then a distinctive token of five
    characters or more. TWO different suppliers matching means the answer
    is unknowable from the words - say nothing.
    """
    low = _norm(text)
    if not low.strip():
        return None

    # Gather every supplier the text points at, by EITHER signal. Both
    # passes count towards ambiguity: a forward reading "Coastal
    # Fasteners to Acme Electrical" names one in full and the other by
    # its distinctive token, and filing that price on either of them is a
    # coin flip. One supplier or nobody - never a guess between two.
    full: dict[str, str] = {}
    weak: dict[str, list[str]] = {}
    for cid, name in suppliers:
        norm = " ".join(_norm(name).split())
        # The whole trading name, on word boundaries at BOTH ends. Without
        # the trailing one a token like "acme" matched inside
        # "acmeville" and filed a price on the wrong company.
        if len(norm) >= 4 and re.search(r"\b" + re.escape(norm) + r"\b", low):
            full[cid] = norm
            continue
        matched = [t for t in tokens(name) if re.search(r"\b" + re.escape(t) + r"\b", low)]
        if matched:
            weak[cid] = matched

    # ONE SUPPLIER, OR NOBODY. Two named in one message means the right
    # one is unknowable from the words, and filing that price on either is
    # a coin flip. Two narrow exceptions, both of which are one supplier
    # appearing twice rather than two suppliers appearing once:
    #
    # 1. A registered name that CONTAINS another registered name.
    #    "Acme Electrical Services Group" necessarily also matches
    #    "Acme Electrical"; the longer, more specific one is meant.
    if len(full) > 1:
        full = {
            cid: norm
            for cid, norm in full.items()
            if not any(other != norm and f" {norm} " in f" {other} " for other in full.values())
        }
    # 2. A token hit whose every matching word already sits inside a name
    #    that matched IN FULL. "Acme Electrical" matches b outright and
    #    drags in "Acme Electrical Services Group" on the token
    #    "acme" - but that token is entirely explained by b's own name,
    #    so it is not independent evidence of a second supplier.
    if full:
        full_words = {w for norm in full.values() for w in norm.split()}
        weak = {cid: toks for cid, toks in weak.items() if not set(toks) <= full_words}

    hits = list(full) + [c for c in weak if c not in full]
    return hits[0] if len(hits) == 1 else None


async def suggestions_for(session: AsyncSession, item: RegisterItem) -> dict[str, Any]:
    """Per-supplier figures read out of the captured replies.

    Returns ``{"by_supplier": {contact_id: {...}}, "unmatched": [...]}``
    where each entry carries the amount, basis, lead time, quote number,
    the reply it came from and the VERBATIM evidence - because an
    extracted figure is only worth as much as the words behind it.
    """
    out: dict[str, Any] = {"by_supplier": {}, "unmatched": []}
    if item.kind != "rfq":
        return out
    try:
        from app.modules.comms_intelligence.models import CommsAnalysis
        from app.modules.correspondence.models import Correspondence
    except ImportError:  # pragma: no cover
        return out

    # Who was asked - the only columns a figure may land in.
    suppliers: list[tuple[str, str]] = []
    try:
        from app.modules.contacts.models import Contact

        ids = [uuid.UUID(str(c)) for c in (item.recipient_contact_ids or []) if str(c)]
        if ids:
            rows = (await session.execute(select(Contact).where(Contact.id.in_(ids)))).scalars().all()
            suppliers = [
                (
                    str(c.id),
                    c.company_name or " ".join(x for x in [c.first_name, c.last_name] if x) or "",
                )
                for c in rows
            ]
    except Exception:  # noqa: BLE001
        logger.debug("Supplier list unavailable for %s", item.reference, exc_info=True)
    if not suppliers:
        return out

    # Incoming correspondence on this project that mentions the item or
    # its native RFQ number.
    refs = {item.reference}
    if item.linked_entity_type == "rfq" and item.linked_entity_id:
        try:
            from app.modules.rfq_bidding.models import RFQ

            number = (
                await session.execute(select(RFQ.rfq_number).where(RFQ.id == uuid.UUID(item.linked_entity_id)))
            ).scalar_one_or_none()
            if number:
                refs.add(str(number))
        except Exception:  # noqa: BLE001
            pass

    conds = []
    for ref in refs:
        conds.append(Correspondence.subject.ilike(f"%{ref}%"))
        conds.append(Correspondence.notes.ilike(f"%{ref}%"))
    if not conds:
        return out
    replies = (
        (
            await session.execute(
                select(Correspondence)
                .where(Correspondence.project_id == item.project_id)
                .where(Correspondence.direction == "incoming")
                .where(or_(*conds))
                .order_by(Correspondence.created_at.desc())
                .limit(60)
            )
        )
        .scalars()
        .all()
    )

    for reply in replies:
        analysis = (
            await session.execute(select(CommsAnalysis).where(CommsAnalysis.correspondence_id == str(reply.id)))
        ).scalar_one_or_none()
        if analysis is None:
            continue
        facts = analysis.extracted or {}
        package = facts.get("package_price") or {}
        if not package.get("amount") and not facts.get("quote_number"):
            continue  # a question, not a quote - never a suggestion

        haystack = f"{reply.subject}\n{reply.notes or ''}"
        cid = match_supplier(haystack, suppliers)
        entry = {
            "correspondence_id": str(reply.id),
            "reference": reply.reference_number,
            "subject": reply.subject,
            "received": reply.date_received or (reply.created_at.isoformat() if reply.created_at else None),
            "amount": package.get("amount"),
            "basis": package.get("basis"),
            "evidence": package.get("evidence"),
            "lead_time": facts.get("lead_time") or "",
            "quote_number": facts.get("quote_number"),
            "reply_kind": facts.get("reply_kind"),
            "confidence": analysis.confidence,
        }
        if cid is None:
            out["unmatched"].append(entry)
            continue
        # Newest priced reply per supplier wins; the older ones are kept
        # so a revised quote is visibly a revision, not a silent replace.
        bucket = out["by_supplier"].setdefault(cid, {"latest": None, "superseded": []})
        if bucket["latest"] is None:
            bucket["latest"] = entry
        else:
            bucket["superseded"].append(entry)
    return out
