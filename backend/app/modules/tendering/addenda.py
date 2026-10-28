# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tender​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ addenda in depth: BOQ revisions, deadline extensions, Q&A, compliance.

Addenda themselves stay in the package ``metadata_`` store (see
``TenderingService``). This module adds what an addendum does once it is
published and what the buyer needs to judge bids against it:

* a BOQ change starts a new tender BOQ revision (``metadata.boq_revisions``);
  a bid records the revision it priced (``bid.metadata.boq_revision_no``);
* a new deadline moves the package deadline and records the old one;
* published addenda and answers are mailed to every invited firm in the
  project's language;
* bidder questions (``TenderClarification``) are answered and published to all
  bidders without the asker's name, and can be promoted into an addendum;
* per-bid compliance (acknowledged every addendum, priced the current
  revision) for the comparison, a dated timeline and the validation payload.

Day thresholds come from ``app.core.tender_rules`` (country data), never from
code.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tender_rules import TenderRules, rules_for
from app.modules.tendering.models import TenderBid, TenderClarification, TenderPackage

logger = logging.getLogger(__name__)

#: Guarantee statuses that no longer secure anything.
_SPENT_BOND_STATUSES = frozenset({"released", "cancelled", "expired", "called", "draft"})


# ── Pure helpers (unit tested without a database) ──────────────────────────


def closing_date(deadline: str | None) -> date | None:
    """The calendar day of a package deadline (``2026-11-30`` or a full ISO instant)."""
    if not deadline:
        return None
    try:
        return date.fromisoformat(str(deadline).strip()[:10])
    except ValueError:
        return None


def read_addenda(meta: dict | None) -> list[dict]:
    raw = (meta or {}).get("addenda")
    return [a for a in raw if isinstance(a, dict)] if isinstance(raw, list) else []


def published_addenda(meta: dict | None) -> list[dict]:
    """Published addenda, oldest revision first."""
    rows = [a for a in read_addenda(meta) if a.get("published_at")]
    return sorted(rows, key=lambda a: int(a.get("revision_no", 0)))


def current_boq_revision(meta: dict | None) -> int:
    """The tender BOQ revision bidders must price; 0 is the bill as first issued."""
    try:
        return int((meta or {}).get("boq_revision_no") or 0)
    except (TypeError, ValueError):
        return 0


def invited_recipient_ids(meta: dict | None) -> list[str]:
    """Recipients the package was sent to (the firms an addendum is issued to)."""
    raw = (meta or {}).get("recipients")
    if not isinstance(raw, list):
        return []
    return [str(r["id"]) for r in raw if isinstance(r, dict) and r.get("id") and r.get("status") == "sent"]


def ack_ids(entry: dict) -> set[str]:
    return {str(a.get("bidder_id")) for a in (entry.get("acknowledged_by") or []) if isinstance(a, dict)}


def bid_identities(bid: Any) -> set[str]:
    """Ids an acknowledgement may carry for this bid: the bid and its invited firm."""
    ids = {str(bid.id)}
    rid = (getattr(bid, "metadata_", None) or {}).get("recipient_id")
    if rid:
        ids.add(str(rid))
    return ids


def bid_revision(bid: Any) -> int:
    try:
        return int((getattr(bid, "metadata_", None) or {}).get("boq_revision_no") or 0)
    except (TypeError, ValueError):
        return 0


def bid_compliance(meta: dict | None, bids: list[Any]) -> dict[str, dict[str, Any]]:
    """Per bid: the revision priced, whether it is current, and addenda not acknowledged."""
    current = current_boq_revision(meta)
    addenda = published_addenda(meta)
    out: dict[str, dict[str, Any]] = {}
    for bid in bids:
        ids = bid_identities(bid)
        missing = [int(a.get("revision_no", 0)) for a in addenda if not (ack_ids(a) & ids)]
        rev = bid_revision(bid)
        out[str(bid.id)] = {
            "boq_revision_no": rev,
            "current_boq_revision": current,
            "revision_current": rev >= current,
            "missing_addenda": missing,
            "compliant": not missing and rev >= current,
        }
    return out


def next_boq_revision(meta: dict, entry: dict, now: str) -> dict:
    """Return ``meta`` with a new BOQ revision for ``entry``'s BOQ changes recorded."""
    rev = current_boq_revision(meta) + 1
    revisions = [r for r in (meta.get("boq_revisions") or []) if isinstance(r, dict)]
    revisions.append(
        {
            "revision_no": rev,
            "addendum_id": entry.get("id"),
            "addendum_revision_no": entry.get("revision_no"),
            "changes": entry.get("boq_changes") or [],
            "created_at": now,
        }
    )
    meta = dict(meta)
    meta["boq_revisions"] = revisions
    meta["boq_revision_no"] = rev
    entry["boq_revision_no"] = rev
    return meta


def apply_boq_changes_to_scope(meta: dict, changes: list[dict]) -> dict:
    """Keep the package scope in step: an added line joins it, a deleted line leaves it."""
    scope = meta.get("scope_position_ids")
    if not isinstance(scope, list):
        return meta
    ids = [str(x) for x in scope]
    for ch in changes:
        pid = str(ch.get("position_id") or "")
        if not pid:
            continue
        if ch.get("op") == "add" and pid not in ids:
            ids.append(pid)
        elif ch.get("op") == "delete" and pid in ids:
            ids.remove(pid)
    meta = dict(meta)
    meta["scope_position_ids"] = ids
    return meta


def timeline(meta: dict | None, deadline: str | None, rules: TenderRules, today: date) -> list[dict]:
    """Dated steps: issued, questions close, each published addendum, closing."""
    meta = meta or {}
    events: list[dict] = []
    issued = meta.get("issued_at")
    if issued:
        events.append({"kind": "issued", "at": str(issued), "label": ""})
    close = closing_date(deadline)
    if close:
        q_close = close - timedelta(days=rules.questions_close_days_before_closing)
        events.append({"kind": "questions_closed", "at": q_close.isoformat(), "label": ""})
    for a in published_addenda(meta):
        events.append(
            {
                "kind": "deadline_extended" if a.get("new_deadline") else "addendum",
                "at": str(a.get("published_at")),
                "label": f"{a.get('revision_no')}: {a.get('title', '')}",
                "ref_id": a.get("id"),
            }
        )
    if close:
        events.append({"kind": "closing", "at": str(deadline), "label": ""})
    for ev in events:
        day = closing_date(ev.get("at"))
        ev["past"] = bool(day and day <= today)
    events.sort(key=lambda e: str(e.get("at") or ""))
    return events


def validation_payload(
    meta: dict | None,
    deadline: str | None,
    bids: list[Any],
    clarifications: list[Any],
    bonds: list[dict],
    rules: TenderRules,
    today: date,
) -> dict[str, Any]:
    """The data the ``tendering_addenda`` rule set reads."""
    meta = meta or {}
    close = closing_date(deadline)
    invited = invited_recipient_ids(meta)
    addenda = []
    for a in published_addenda(meta):
        pub = closing_date(a.get("published_at"))
        acked = ack_ids(a)
        addenda.append(
            {
                "id": a.get("id"),
                "revision_no": a.get("revision_no"),
                "days_before_closing": (close - pub).days if close and pub else None,
                "pending_recipient_ids": [r for r in invited if r not in acked],
            }
        )
    compliance = bid_compliance(meta, bids)
    questions = []
    for c in clarifications:
        answered = c.answered_at.date() if c.answered_at else None
        questions.append(
            {
                "id": str(c.id),
                "number": c.number,
                "answered": bool(c.answer),
                "days_left": (close - (answered or today)).days if close else None,
            }
        )
    validity_until = close + timedelta(days=rules.bid_validity_days) if close else None
    return {
        "closing": close.isoformat() if close else None,
        "closed": bool(close and today >= close),
        "rules": rules.as_dict(),
        "addenda": addenda,
        "bids": [{"bid_id": bid_id, **row} for bid_id, row in compliance.items()],
        "questions": questions,
        "bid_validity_until": validity_until.isoformat() if validity_until else None,
        "bonds": bonds,
    }


def pending_recipients(meta: dict | None, entry: dict) -> list[str]:
    if not entry.get("published_at"):
        return []
    acked = ack_ids(entry)
    return [r for r in invited_recipient_ids(meta) if r not in acked]


# ── Service ─────────────────────────────────────────────────────────────────


class AddendaService:
    """Q&A, compliance, timeline and the side effects of publishing an addendum."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _project(self, package: TenderPackage) -> Any:
        from app.modules.projects.repository import ProjectRepository

        return await ProjectRepository(self.session).get_by_id(package.project_id)

    async def rules(self, package: TenderPackage) -> TenderRules:
        project = await self._project(package)
        overrides = (package.metadata_ or {}).get("tender_rules")
        return rules_for(getattr(project, "country_code", None), overrides if isinstance(overrides, dict) else None)

    # Publishing side effects -------------------------------------------------

    async def after_publish(self, package: TenderPackage, entry: dict, user_id: str | None) -> list[dict]:
        """Mail the addendum to invited firms, notify the project owner, write the audit row."""
        from app.modules.tendering.addendum_email import addendum_html, addendum_subject

        project = await self._project(package)
        locale = getattr(project, "locale", None)
        notified = await self._mail_recipients(
            package,
            lambda company: (
                addendum_subject(locale, package.name, int(entry.get("revision_no", 0))),
                addendum_html(locale=locale, company_name=company, package_name=package.name, entry=entry),
            ),
            tag="addendum",
        )
        await self._notify_owner(
            project,
            package,
            "notification.tender_addendum_title",
            {"package": package.name, "number": str(entry.get("revision_no"))},
        )
        await self.audit(
            user_id,
            package,
            "addendum_published",
            {
                "addendum_id": entry.get("id"),
                "revision_no": entry.get("revision_no"),
                "boq_revision_no": entry.get("boq_revision_no"),
                "new_deadline": entry.get("new_deadline"),
                "previous_deadline": entry.get("previous_deadline"),
            },
        )
        return notified

    async def _mail_recipients(self, package: TenderPackage, render: Any, *, tag: str) -> list[dict]:
        from app.core.email import EmailMessage, get_email_service

        service = get_email_service()
        out: list[dict] = []
        for r in (package.metadata_ or {}).get("recipients") or []:
            if not isinstance(r, dict) or r.get("status") != "sent" or not str(r.get("email", "")).strip():
                continue
            subject, html_body = render(str(r.get("company_name", "")))
            ok = False
            try:
                result = await service.send(
                    EmailMessage(
                        to=str(r["email"]).strip(),
                        subject=subject,
                        html_body=html_body,
                        tags=["tendering", tag, str(package.id)],
                    )
                )
                ok = bool(getattr(result, "ok", False))
            except Exception:  # noqa: BLE001 - one bad address never stops the batch
                logger.warning("tender %s mail failed for recipient %s", tag, r.get("id"), exc_info=True)
            out.append(
                {"recipient_id": str(r.get("id")), "status": "sent" if ok else "failed", "at": _now().isoformat()}
            )
        return out

    async def _notify_owner(self, project: Any, package: TenderPackage, title_key: str, ctx: dict) -> None:
        owner = getattr(project, "owner_id", None)
        if owner is None:
            return
        try:
            from app.modules.notifications.service import NotificationService

            await NotificationService(self.session).notify_users(
                [owner],
                "info",
                title_key,
                entity_type="tender_package",
                entity_id=str(package.id),
                body_key=title_key.replace("_title", "_body"),
                body_context=ctx,
                action_url=f"/tendering?package={package.id}",
            )
        except Exception:  # noqa: BLE001 - a notification never blocks the tender
            logger.debug("tender notification skipped", exc_info=True)

    async def audit(self, user_id: str | None, package: TenderPackage, action: str, meta: dict) -> None:
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=user_id,
                entity_type="tender_package",
                entity_id=package.id,
                action=action,
                metadata=meta,
                module="tendering",
            )
        except Exception:  # noqa: BLE001
            logger.debug("tender audit row skipped", exc_info=True)

    # Clarifications ----------------------------------------------------------

    async def list_clarifications(self, package_id: uuid.UUID) -> list[TenderClarification]:
        rows = await self.session.execute(
            select(TenderClarification)
            .where(TenderClarification.package_id == package_id)
            .order_by(TenderClarification.number)
        )
        return list(rows.scalars().all())

    async def page_clarifications(
        self, package_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[TenderClarification], int]:
        base = select(TenderClarification).where(TenderClarification.package_id == package_id)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        page = base.order_by(TenderClarification.number, TenderClarification.id).offset(offset).limit(limit)
        return list((await self.session.execute(page)).scalars().all()), total

    async def get_clarification(self, package_id: uuid.UUID, clarification_id: uuid.UUID) -> TenderClarification:
        row = await self.session.get(TenderClarification, clarification_id)
        if row is None or row.package_id != package_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clarification not found")
        return row

    async def ask(
        self, package: TenderPackage, question: str, recipient_id: str | None, email: str, user_id: str | None
    ) -> TenderClarification:
        if package.status in ("awarded", "closed"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tender is closed for questions")
        number = (
            await self.session.execute(
                select(func.coalesce(func.max(TenderClarification.number), 0)).where(
                    TenderClarification.package_id == package.id
                )
            )
        ).scalar_one()
        row = TenderClarification(
            package_id=package.id,
            number=int(number) + 1,
            recipient_id=recipient_id,
            asked_by_email=email or "",
            question=question,
            asked_at=_now(),
            status="open",
        )
        self.session.add(row)
        await self.session.flush()
        await self.audit(user_id, package, "clarification_asked", {"clarification_id": str(row.id)})
        await _publish(
            "tendering.clarification.asked", {"package_id": str(package.id), "clarification_id": str(row.id)}
        )
        return row

    async def answer(self, row: TenderClarification, answer: str, user_id: str | None) -> TenderClarification:
        if row.status == "published":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Answer already published")
        row.answer = answer
        row.answered_at = _now()
        row.answered_by = str(user_id) if user_id else None
        row.status = "answered"
        await self.session.flush()
        return row

    async def publish_answer(
        self, package: TenderPackage, row: TenderClarification, user_id: str | None
    ) -> TenderClarification:
        """Publish an answer to every invited firm, without who asked."""
        if not row.answer:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Answer the question before publishing")
        if row.status == "published":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Answer already published")
        row.status = "published"
        row.published_at = _now()
        await self.session.flush()
        from app.modules.tendering.addendum_email import answer_html, answer_subject

        project = await self._project(package)
        locale = getattr(project, "locale", None)
        await self._mail_recipients(
            package,
            lambda company: (
                answer_subject(locale, package.name, row.number),
                answer_html(
                    locale=locale,
                    company_name=company,
                    package_name=package.name,
                    question=row.question,
                    answer=row.answer,
                ),
            ),
            tag="clarification",
        )
        await self.audit(user_id, package, "clarification_published", {"clarification_id": str(row.id)})
        await _publish(
            "tendering.clarification.published", {"package_id": str(package.id), "clarification_id": str(row.id)}
        )
        return row

    async def public_clarifications(self, package_id: uuid.UUID) -> list[dict]:
        return [
            {"number": c.number, "question": c.question, "answer": c.answer, "published_at": c.published_at}
            for c in await self.list_clarifications(package_id)
            if c.status == "published"
        ]

    # Reads -------------------------------------------------------------------

    async def bid_bonds(self, package: TenderPackage, bids: list[TenderBid]) -> list[dict]:
        """Bid bonds held for this package, with expiry, for the validity check."""
        from app.modules.guarantees.models import Guarantee

        rows = await self.session.execute(
            select(Guarantee).where(Guarantee.tender_id == package.id, Guarantee.guarantee_type == "bid_bond")
        )
        names = {str(b.id): b.company_name for b in bids}
        return [
            {
                "guarantee_id": str(g.id),
                "reference": g.reference,
                "bid_id": str(g.bid_id) if g.bid_id else None,
                "company_name": names.get(str(g.bid_id), g.applicant),
                "expiry_date": g.expiry_date.isoformat() if g.expiry_date else None,
            }
            for g in rows.scalars().all()
            if g.status not in _SPENT_BOND_STATUSES
        ]

    async def validation_data(self, package: TenderPackage, bids: list[TenderBid]) -> dict[str, Any]:
        rules = await self.rules(package)
        return validation_payload(
            package.metadata_,
            package.deadline,
            bids,
            await self.list_clarifications(package.id),
            await self.bid_bonds(package, bids),
            rules,
            _now().date(),
        )


def _now() -> datetime:
    return datetime.now(UTC)


async def _publish(name: str, data: dict) -> None:
    from app.core.events import event_bus

    try:
        event_bus.publish_detached(name, data, source_module="oe_tendering")
    except Exception:  # noqa: BLE001
        logger.debug("Event publish skipped: %s", name)
