# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid / no-bid business logic.

The score and the recommendation are computed from the stored ratings and are never stored, so they cannot drift.
Every change writes one audit line. A decision is a person's; validation errors block it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bid_no_bid import logic
from app.modules.bid_no_bid.logic import CRITERIA
from app.modules.bid_no_bid.models import BidNoBidEvent, BidNoBidScorecard
from app.modules.bid_no_bid.repository import BidNoBidRepository
from app.modules.bid_no_bid.schemas import DecideRequest, OutcomeRequest, ScorecardUpdate
from app.modules.bid_no_bid.validators import evaluate
from app.modules.win_loss.models import BidOutcome


def _conflict(code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": code, "message": message, **extra})


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def _finding(f: Any) -> dict[str, Any]:
    return {
        "rule_id": f.rule_id,
        "severity": getattr(f.severity, "value", str(f.severity)),
        "message": f.message,
        "element_ref": f.element_ref,
        "details": f.details or {},
    }


def _is_error(f: Any) -> bool:
    return getattr(f.severity, "value", str(f.severity)).lower().endswith("error")


def _outcome_of(entry: BidOutcome | None) -> str:
    """The scorecard's view of the ledger outcome: open states read as no outcome yet."""
    return entry.outcome if entry is not None and entry.outcome in ("won", "lost", "withdrawn") else ""


class BidNoBidService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = BidNoBidRepository(session)

    async def tender(self, tender_id: uuid.UUID) -> Any:
        from app.modules.tendering.models import TenderPackage

        tender = await self.session.get(TenderPackage, tender_id)
        if tender is None:
            raise _not_found("Tender")
        return tender

    async def card(self, card_id: uuid.UUID) -> BidNoBidScorecard:
        card = await self.repo.card(card_id)
        if card is None:
            raise _not_found("Scorecard")
        return card

    async def open_card(self, tender_id: uuid.UUID, user_id: str | None) -> BidNoBidScorecard:
        """The tender's scorecard, created with default weights on first open."""
        card = await self.repo.card_for_tender(tender_id)
        if card is not None:
            return card
        tender = await self.tender(tender_id)
        card = BidNoBidScorecard(
            project_id=tender.project_id,
            tender_id=tender_id,
            weights=dict(logic.DEFAULT_WEIGHTS),
            scores={},
            notes={},
            threshold=logic.DEFAULT_THRESHOLD,
            created_by=user_id,
        )
        try:
            async with self.session.begin_nested():
                await self.repo.add(card)
        except IntegrityError:
            # A concurrent open won the unique tender_id race: return its card.
            existing = await self.repo.card_for_tender(tender_id)
            if existing is None:
                raise
            return existing
        await self._log(card, user_id, "created", "Scorecard opened")
        return card

    # ── outcome: the single record lives in the win-loss ledger ───────────

    async def _entry(self, tender_id: uuid.UUID) -> BidOutcome | None:
        stmt = select(BidOutcome).where(BidOutcome.tender_id == tender_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ── computation ──────────────────────────────────────────────────────

    def compute(self, card: BidNoBidScorecard) -> dict[str, Any]:
        weights = logic.clean_weights(card.weights)
        scores = logic.clean_scores(card.scores)
        score = logic.weighted_score(weights, scores)
        return {
            "weights": weights,
            "scores": scores,
            "score": str(score) if score is not None else None,
            "recommendation": logic.recommendation(score, card.threshold),
        }

    def validation_input(self, card: BidNoBidScorecard, decision: str = "", reason: str = "") -> dict[str, Any]:
        c = self.compute(card)
        return {
            "weights": c["weights"],
            "scores": c["scores"],
            "notes": dict(card.notes or {}),
            "threshold": card.threshold,
            "score": c["score"],
            "recommendation": c["recommendation"],
            "decision": decision or card.decision,
            "decision_reason": reason if decision else card.decision_reason,
        }

    async def view(self, card: BidNoBidScorecard) -> dict[str, Any]:
        c = self.compute(card)
        tender = await self.tender(card.tender_id)
        findings = await evaluate(self.validation_input(card), target_id=str(card.id))
        events = await self.repo.events(card.id)
        entry = await self._entry(card.tender_id)
        return {
            "id": card.id,
            "project_id": card.project_id,
            "tender_id": card.tender_id,
            "tender_name": tender.name,
            "opportunity_id": card.opportunity_id,
            "weights": c["weights"],
            "scores": c["scores"],
            "notes": {k: str(v) for k, v in (card.notes or {}).items()},
            "threshold": card.threshold,
            "score": c["score"],
            "recommendation": c["recommendation"],
            "decision": card.decision,
            "decision_reason": card.decision_reason,
            "decided_by_name": await self._user_name(card.decided_by),
            "decided_at": card.decided_at,
            "outcome": _outcome_of(entry),
            "outcome_note": entry.notes if entry else "",
            "version": card.version,
            "findings": [_finding(f) for f in findings],
            "events": events,
        }

    # ── edits ────────────────────────────────────────────────────────────

    def _check_version(self, card: BidNoBidScorecard, version: int | None) -> None:
        if version is not None and version != card.version:
            raise _conflict("stale_revision", "The scorecard was changed by someone else since you loaded it.")

    async def update(self, card: BidNoBidScorecard, body: ScorecardUpdate, user_id: str | None) -> None:
        self._check_version(card, body.version)
        changes: list[str] = []
        if body.weights is not None:
            card.weights = {**logic.clean_weights(card.weights), **body.weights}
            changes.append("weights")
        if body.scores is not None:
            card.scores = {**logic.clean_scores(card.scores), **body.scores}
            changes.append("ratings")
        if body.notes is not None:
            card.notes = {**(card.notes or {}), **{k: v.strip() for k, v in body.notes.items()}}
            changes.append("notes")
        if body.threshold is not None and body.threshold != card.threshold:
            card.threshold = body.threshold
            changes.append("threshold")
        if body.clear_opportunity and card.opportunity_id is not None:
            card.opportunity_id = None
            changes.append("CRM link")
        elif body.opportunity_id is not None and body.opportunity_id != card.opportunity_id:
            await self._check_opportunity(card, body.opportunity_id)
            card.opportunity_id = body.opportunity_id
            changes.append("CRM link")
        if not changes:
            return
        # A changed score no longer backs a recorded decision: keep the decision, show the audit line.
        card.version += 1
        await self.repo.save(card, "weights", "scores", "notes")
        c = self.compute(card)
        await self._log(
            card, user_id, "updated", f"Changed {', '.join(changes)}; score {c['score'] or 'incomplete'}",
            score=c["score"], threshold=card.threshold,
        )  # fmt: skip

    async def decide(self, card: BidNoBidScorecard, body: DecideRequest, user_id: str | None) -> None:
        self._check_version(card, body.version)
        findings = await evaluate(
            self.validation_input(card, body.decision, body.reason.strip()), target_id=str(card.id)
        )
        errors = [f for f in findings if _is_error(f)]
        if errors:
            raise _conflict(
                "validation_errors",
                "Resolve the errors before recording the decision.",
                findings=[{"rule_id": f.rule_id, "message": f.message, "element_ref": f.element_ref} for f in errors],
            )
        c = self.compute(card)
        previous = card.decision
        card.decision = body.decision
        card.decision_reason = body.reason.strip()
        card.decided_by = user_id
        card.decided_at = datetime.now(UTC)
        if body.decision != "bid":
            entry = await self._entry(card.tender_id)
            if entry is not None and entry.outcome != "pending":
                entry.outcome = "pending"
                entry.version += 1
        card.version += 1
        await self.repo.save(card)
        verb = "Changed decision" if previous and previous != body.decision else "Decided"
        await self._log(
            card, user_id, "decided", f"{verb}: {body.decision.replace('_', '-')} at score {c['score']}",
            decision=body.decision, previous=previous, score=c["score"], recommendation=c["recommendation"],
            threshold=card.threshold, reason=card.decision_reason,
        )  # fmt: skip

    async def set_outcome(self, card: BidNoBidScorecard, body: OutcomeRequest, user_id: str | None) -> None:
        self._check_version(card, body.version)
        if card.decision != "bid":
            raise _conflict("not_bid", "An outcome can be recorded only for a tender that was bid.")
        outcome, note = body.outcome or "pending", body.note.strip()
        entry = await self._entry(card.tender_id)
        if entry is None:
            tender = await self.tender(card.tender_id)
            entry = BidOutcome(
                title=tender.name,
                project_id=card.project_id,
                tender_id=card.tender_id,
                outcome=outcome,
                notes=note,
                created_by=uuid.UUID(user_id) if user_id else None,
            )
            try:
                async with self.session.begin_nested():
                    await self.repo.add(entry)
            except IntegrityError:
                entry = await self._entry(card.tender_id)
                if entry is None:
                    raise
                self._apply_outcome(entry, outcome, note)
        else:
            self._apply_outcome(entry, outcome, note)
        card.version += 1
        await self.repo.save(card)
        await self._log(
            card, user_id, "outcome", f"Outcome: {body.outcome or 'cleared'}", outcome=body.outcome, note=note
        )

    @staticmethod
    def _apply_outcome(entry: BidOutcome, outcome: str, note: str) -> None:
        # The ledger note is shared with the ledger page: an empty scorecard note must not erase it.
        entry.outcome = outcome
        if note:
            entry.notes = note
        entry.version += 1

    # ── win-loss ledger ──────────────────────────────────────────────────

    async def ledger(self, project_id: uuid.UUID) -> dict[str, Any]:
        cards = await self.repo.cards(project_id)
        crm = await self._crm_status({c.opportunity_id for c in cards if c.opportunity_id}, project_id)
        tenders = await self._tender_names({c.tender_id for c in cards})
        entries = await self._entries({c.tender_id for c in cards})
        rows: list[dict[str, Any]] = []
        for card in cards:
            c = self.compute(card)
            outcome = _outcome_of(entries.get(card.tender_id))
            source = "ledger" if outcome else ""
            if not outcome and card.decision == "bid" and crm.get(card.opportunity_id) in ("won", "lost"):
                outcome, source = crm[card.opportunity_id], "crm"
            rows.append(
                {
                    "id": card.id,
                    "project_id": card.project_id,
                    "tender_id": card.tender_id,
                    "tender_name": tenders[card.tender_id],
                    "score": c["score"],
                    "threshold": card.threshold,
                    "recommendation": c["recommendation"],
                    "decision": card.decision,
                    "decision_reason": card.decision_reason,
                    "decided_at": card.decided_at,
                    "outcome": outcome,
                    "outcome_source": source,
                }
            )
        return {"summary": logic.win_loss_summary(rows), "rows": rows}

    async def _tender_names(self, tender_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not tender_ids:
            return {}
        from app.modules.tendering.models import TenderPackage

        stmt = select(TenderPackage.id, TenderPackage.name).where(TenderPackage.id.in_(tender_ids))
        names = {tid: name for tid, name in (await self.session.execute(stmt)).all()}
        if tender_ids - names.keys():
            # Same contract as tender(): a card whose tender is gone is a 404.
            raise _not_found("Tender")
        return names

    async def _entries(self, tender_ids: set[uuid.UUID]) -> dict[uuid.UUID, BidOutcome]:
        if not tender_ids:
            return {}
        stmt = select(BidOutcome).where(BidOutcome.tender_id.in_(tender_ids))
        return {e.tender_id: e for e in (await self.session.execute(stmt)).scalars().all()}

    async def _crm_status(self, ids: set[uuid.UUID | None], project_id: uuid.UUID) -> dict[uuid.UUID | None, str]:
        wanted = {i for i in ids if i}
        if not wanted:
            return {}
        try:
            from sqlalchemy import or_, select

            from app.modules.crm.models import Opportunity
        except ImportError:
            return {}
        stmt = select(Opportunity.id, Opportunity.status).where(
            Opportunity.id.in_(wanted), or_(Opportunity.project_id.is_(None), Opportunity.project_id == project_id)
        )
        return {oid: str(st) for oid, st in (await self.session.execute(stmt)).all()}

    async def _check_opportunity(self, card: BidNoBidScorecard, opportunity_id: uuid.UUID) -> None:
        try:
            from app.modules.crm.models import Opportunity
        except ImportError as exc:
            raise _conflict("crm_missing", "The CRM module is not installed.") from exc
        opp = await self.session.get(Opportunity, opportunity_id)
        # An opportunity tied to another project is invisible here, same as a missing one.
        if opp is None or (opp.project_id is not None and opp.project_id != card.project_id):
            raise _not_found("Opportunity")

    # ── audit ────────────────────────────────────────────────────────────

    async def _user_name(self, user_id: str | None) -> str:
        if not user_id:
            return ""
        from app.modules.users.models import User

        try:
            user = await self.session.get(User, uuid.UUID(str(user_id)))
        except ValueError:
            return ""
        return (user.full_name or user.email) if user else ""

    async def _log(self, card: BidNoBidScorecard, user_id: str | None, kind: str, message: str, **params: Any) -> None:
        await self.repo.add(
            BidNoBidEvent(
                scorecard_id=card.id,
                user_id=user_id,
                user_name=await self._user_name(user_id),
                kind=kind,
                message=message,
                params={k: v for k, v in params.items() if v is not None},
            )
        )


__all__ = ["CRITERIA", "BidNoBidService"]
