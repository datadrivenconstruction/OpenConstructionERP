# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Business logic for the external-review-authority (expertise cycle) module.

The module-level functions here are pure - no session, no clock unless one is
passed in - so the whole decision core is unit-tested without a database:

* :func:`classify_remark` - contestability classifier. A remark with a norm
  reference is grounded; one without is flagged ``no_norm_ref_contestable`` so a
  human confirms contestability. It never silently *decides* a remark is
  contestable; it surfaces the missing reference.
* :func:`is_remark_stale` - a remark is stale when its cycle's pinned document
  version differs from the live version, i.e. the authority reviewed a drawing
  set the project has since moved past.
* :func:`find_repeats` - repeat-remark radar. Flags a new remark whose
  normalised token set closely matches a prior *accepted* remark, so a reviewer
  sees the authority re-raising a settled point.
* :func:`cycle_timeline` - SLA clock: days remaining against ``due_at`` (or
  ``opened_at + sla_days``) and an overdue flag.

The FSM transition tables are the single source of truth for both the cycle and
the remark; the service and the API both consult them, so an illegal move is a
400 in one place.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status

from app.modules.review_authority.models import Remark, ReviewCycle
from app.modules.review_authority.repository import ReviewAuthorityRepository
from app.modules.review_authority.schemas import (
    RemarkCreate,
    ReviewCycleCreate,
    ReviewCycleSubmit,
    ReviewCycleUpdate,
)

logger = logging.getLogger(__name__)

# ── FSM transition tables ──────────────────────────────────────────────

# A cycle walks: draft -> submitted -> under_review -> remarks_issued ->
# responding -> resubmitted -> approved | rejected. It can be withdrawn from any
# non-terminal state. approved / rejected / withdrawn are terminal.
CYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"submitted", "withdrawn"}),
    "submitted": frozenset({"under_review", "withdrawn"}),
    "under_review": frozenset({"remarks_issued", "approved", "rejected", "withdrawn"}),
    "remarks_issued": frozenset({"responding", "withdrawn"}),
    "responding": frozenset({"resubmitted", "withdrawn"}),
    "resubmitted": frozenset({"under_review", "approved", "rejected", "withdrawn"}),
    "approved": frozenset(),
    "rejected": frozenset(),
    "withdrawn": frozenset(),
}
CYCLE_TERMINAL: frozenset[str] = frozenset({"approved", "rejected", "withdrawn"})

# A remark walks: open -> responded -> accepted | contested | withdrawn. It can
# also be withdrawn directly from open (raised then dropped by the authority).
REMARK_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"responded", "withdrawn"}),
    "responded": frozenset({"accepted", "contested", "withdrawn"}),
    "accepted": frozenset(),
    "contested": frozenset(),
    "withdrawn": frozenset(),
}
REMARK_TERMINAL: frozenset[str] = frozenset({"accepted", "contested", "withdrawn"})

# Default repeat-radar similarity threshold (Jaccard on normalised token sets).
DEFAULT_REPEAT_THRESHOLD = 0.6

# Tiny stop-word set so boilerplate ("the", "of", "shall") does not inflate the
# overlap between otherwise-unrelated remarks. Kept deliberately small and
# language-neutral-ish; the radar is a human-confirmed hint, not an oracle.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "on",
        "and",
        "or",
        "is",
        "are",
        "be",
        "for",
        "with",
        "as",
        "at",
        "by",
        "shall",
        "must",
        "should",
        "this",
        "that",
        "it",
        "not",
        "no",
        "per",
        "from",
    }
)

_TOKEN_RE = re.compile(r"[0-9a-zA-Zа-яёА-ЯЁ]+")


# ── Pure decision core ─────────────────────────────────────────────────


def classify_remark(text: str, norm_reference: str | None) -> str:
    """Classify a remark's contestability from its norm reference.

    A remark that cites a norm / code reference is grounded (``has_norm_ref``);
    one without is flagged ``no_norm_ref_contestable`` - meaning "no basis was
    cited, a human must confirm whether this is contestable". The function never
    returns a *decision* of contestability on its own; ``no_norm_ref_contestable``
    is the honest "missing reference" flag, not an auto-judgement.

    Args:
        text: The remark body (unused for the norm-ref decision but kept in the
            signature so callers pass the full remark and a future heuristic can
            use it).
        norm_reference: The cited norm / code, or ``None`` / blank if absent.

    Returns:
        ``"has_norm_ref"`` when a non-blank reference is present, otherwise
        ``"no_norm_ref_contestable"``.
    """
    _ = text  # reserved for a future text-based heuristic; see docstring
    if norm_reference is not None and norm_reference.strip():
        return "has_norm_ref"
    return "no_norm_ref_contestable"


def is_remark_stale(pinned_version: str | None, current_version: str | None) -> bool:
    """Return True when the live document has moved past the pinned version.

    A remark was raised against ``pinned_version`` (the version frozen at
    submission). Once the project's ``current_version`` differs, the remark
    refers to a drawing set that no longer matches the live document and must be
    reviewed rather than silently re-mapped.

    A cycle that has not been submitted yet has no pinned version; nothing is
    stale in that case.
    """
    if not pinned_version:
        return False
    return (pinned_version or "") != (current_version or "")


def normalise_tokens(text: str) -> set[str]:
    """Lowercase, tokenise and drop stop-words for the repeat radar."""
    tokens = _TOKEN_RE.findall((text or "").lower())
    return {t for t in tokens if t not in _STOPWORDS}


def token_overlap_ratio(a: str, b: str) -> float:
    """Jaccard overlap of the two texts' normalised token sets, in ``0.0-1.0``.

    Two empty (or all-stop-word) texts are treated as non-matching (``0.0``) so
    a pair of blank remarks never registers as a repeat.
    """
    ta, tb = normalise_tokens(a), normalise_tokens(b)
    if not ta or not tb:
        return 0.0
    intersection = len(ta & tb)
    union = len(ta | tb)
    if union == 0:
        return 0.0
    return intersection / union


def find_repeats(
    new_remark_text: str,
    prior_remarks: list[dict[str, Any]],
    *,
    threshold: float = DEFAULT_REPEAT_THRESHOLD,
) -> list[str]:
    """Flag prior accepted remarks a new remark closely repeats.

    Args:
        new_remark_text: The incoming remark body.
        prior_remarks: Prior *accepted* remarks to compare against, each a
            mapping with at least ``id`` and ``text`` keys.
        threshold: Minimum normalised-token overlap ratio to count as a repeat.

    Returns:
        The ids of matching prior remarks, most-similar first. Empty when
        nothing clears the threshold.
    """
    scored: list[tuple[float, str]] = []
    for prior in prior_remarks:
        prior_id = prior.get("id")
        if prior_id is None:
            continue
        ratio = token_overlap_ratio(new_remark_text, str(prior.get("text", "")))
        if ratio >= threshold:
            scored.append((ratio, str(prior_id)))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [rid for _, rid in scored]


def cycle_timeline(
    *,
    opened_at: datetime | None,
    sla_days: int,
    due_at: datetime | None,
    status: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute the SLA clock for a cycle.

    The due date is ``due_at`` when set, otherwise ``opened_at + sla_days``. A
    cycle that has not opened (never submitted) has no clock. A cycle in a
    terminal state is never flagged overdue.

    Returns:
        ``{"due_on", "days_remaining", "overdue"}`` where ``due_on`` is an ISO
        string or ``None``, ``days_remaining`` is a signed int or ``None``, and
        ``overdue`` is a bool.
    """
    now = now or datetime.now(UTC)
    due_on: datetime | None = due_at
    if due_on is None and opened_at is not None:
        due_on = opened_at + timedelta(days=max(1, sla_days))

    if due_on is None:
        return {"due_on": None, "days_remaining": None, "overdue": False}

    days_remaining = (due_on.date() - now.date()).days
    overdue = days_remaining < 0 and status not in CYCLE_TERMINAL
    return {
        "due_on": due_on.isoformat(),
        "days_remaining": days_remaining,
        "overdue": overdue,
    }


# ── Service ────────────────────────────────────────────────────────────


class ReviewAuthorityService:
    """Orchestrates review cycles and remarks over the repository."""

    def __init__(self, session: object) -> None:
        self.session = session
        self.repo = ReviewAuthorityRepository(session)  # type: ignore[arg-type]

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    # ── Cycle CRUD ─────────────────────────────────────────────────────

    async def create_cycle(
        self,
        data: ReviewCycleCreate,
        *,
        user_id: str | None = None,
    ) -> ReviewCycle:
        cycle = ReviewCycle(
            project_id=data.project_id,
            authority_name=data.authority_name,
            authority_kind=data.authority_kind,
            submission_ref=data.submission_ref,
            current_document_version=data.current_document_version,
            status="draft",
            sla_days=data.sla_days,
            due_at=data.due_at,
            jurisdiction=data.jurisdiction,
            notes=data.notes,
            metadata_=data.metadata,
            created_by=user_id,
        )
        cycle = await self.repo.create_cycle(cycle)
        logger.info("Review cycle created: %s for project %s", cycle.id, cycle.project_id)
        return cycle

    async def get_cycle(self, cycle_id: uuid.UUID) -> ReviewCycle:
        row = await self.repo.get_cycle(cycle_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Review cycle not found.",
            )
        return row

    async def list_cycles(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        authority_kind: str | None = None,
    ) -> list[ReviewCycle]:
        return await self.repo.list_cycles(project_id, status=status, authority_kind=authority_kind)

    async def update_cycle(
        self,
        cycle_id: uuid.UUID,
        data: ReviewCycleUpdate,
        *,
        user_id: str | None = None,
    ) -> ReviewCycle:
        cycle = await self.get_cycle(cycle_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)

        if "metadata" in fields:
            incoming = fields.pop("metadata")
            merged = dict(cycle.metadata_ or {})
            if isinstance(incoming, dict):
                merged.update(incoming)
            fields["metadata_"] = merged

        if user_id is not None:
            merged_meta = dict(fields.get("metadata_") or cycle.metadata_ or {})
            merged_meta["updated_by"] = user_id
            merged_meta["updated_at"] = self._now().isoformat()
            fields["metadata_"] = merged_meta

        for key, value in fields.items():
            setattr(cycle, key, value)
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(cycle)  # type: ignore[attr-defined]
        return cycle

    async def delete_cycle(self, cycle_id: uuid.UUID) -> None:
        await self.get_cycle(cycle_id)
        await self.repo.delete_cycle(cycle_id)

    # ── Cycle FSM ──────────────────────────────────────────────────────

    async def submit_cycle(
        self,
        cycle_id: uuid.UUID,
        data: ReviewCycleSubmit,
        *,
        user_id: str | None = None,
    ) -> ReviewCycle:
        """Freeze the pinned document version and move the cycle to submitted.

        The pinned version is the document version the authority will review; it
        is frozen here and never moved by later edits, so remarks against it can
        be detected as stale once the live document advances.
        """
        cycle = await self.get_cycle(cycle_id)
        self._assert_cycle_transition(cycle.status, "submitted")

        pinned = data.document_version or cycle.current_document_version
        if not pinned:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="A document version must be set before submitting (nothing to pin).",
            )
        cycle.pinned_document_version = pinned
        cycle.current_document_version = pinned
        if data.submission_ref is not None:
            cycle.submission_ref = data.submission_ref
        cycle.status = "submitted"
        if cycle.opened_at is None:
            cycle.opened_at = self._now()
        if cycle.due_at is None:
            cycle.due_at = cycle.opened_at + timedelta(days=max(1, cycle.sla_days))
        if user_id is not None:
            meta = dict(cycle.metadata_ or {})
            meta["submitted_by"] = user_id
            meta["submitted_at"] = self._now().isoformat()
            cycle.metadata_ = meta
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(cycle)  # type: ignore[attr-defined]
        logger.info("Review cycle %s submitted, pinned version %s", cycle.id, pinned)
        return cycle

    async def transition_cycle(self, cycle_id: uuid.UUID, target_status: str) -> ReviewCycle:
        """Move a cycle along its FSM, rejecting illegal transitions with 400."""
        cycle = await self.get_cycle(cycle_id)
        self._assert_cycle_transition(cycle.status, target_status)
        cycle.status = target_status
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(cycle)  # type: ignore[attr-defined]
        return cycle

    @staticmethod
    def _assert_cycle_transition(current: str, target: str) -> None:
        allowed = CYCLE_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal cycle transition {current!r} -> {target!r}.",
            )

    # ── Remarks ────────────────────────────────────────────────────────

    async def add_remark(
        self,
        cycle_id: uuid.UUID,
        data: RemarkCreate,
        *,
        user_id: str | None = None,
    ) -> Remark:
        """Add a remark to a cycle, auto-classifying and running the repeat radar.

        Adding a remark also nudges the cycle from ``under_review`` (or
        ``submitted``) into ``remarks_issued`` so the FSM reflects that the
        authority has raised at least one point.
        """
        cycle = await self.get_cycle(cycle_id)

        classification = data.classification or classify_remark(data.text, data.norm_reference)
        ordinal = await self.repo.next_ordinal(cycle_id)

        remark = Remark(
            cycle_id=cycle_id,
            project_id=cycle.project_id,
            ordinal=ordinal,
            section=data.section,
            text=data.text,
            norm_reference=data.norm_reference,
            classification=classification,
            severity=data.severity,
            status="open",
            metadata_=data.metadata,
            created_by=user_id,
        )

        # Repeat radar: link to the closest prior accepted remark, if any.
        prior_accepted = await self.repo.list_remarks_by_status(cycle_id, "accepted")
        repeats = find_repeats(
            data.text,
            [{"id": str(r.id), "text": r.text} for r in prior_accepted],
        )
        if repeats:
            remark.repeat_of_id = uuid.UUID(repeats[0])

        remark = await self.repo.create_remark(remark)

        # Advance the cycle FSM if this is the first remark on a live review.
        if cycle.status in ("submitted", "under_review"):
            cycle.status = "remarks_issued"
            await self.session.flush()  # type: ignore[attr-defined]

        logger.info("Remark #%s added to cycle %s (class=%s)", ordinal, cycle_id, classification)
        return remark

    async def get_remark(self, remark_id: uuid.UUID) -> Remark:
        row = await self.repo.get_remark(remark_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Remark not found.",
            )
        return row

    async def respond_remark(
        self,
        remark_id: uuid.UUID,
        response_text: str,
        *,
        user_id: str | None = None,
    ) -> Remark:
        """Record a response to a remark, moving it open -> responded."""
        remark = await self.get_remark(remark_id)
        self._assert_remark_transition(remark.status, "responded")
        remark.response_text = response_text
        remark.responded_at = self._now()
        remark.status = "responded"
        if user_id is not None:
            meta = dict(remark.metadata_ or {})
            meta["responded_by"] = user_id
            remark.metadata_ = meta
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(remark)  # type: ignore[attr-defined]
        return remark

    async def decide_remark(
        self,
        remark_id: uuid.UUID,
        decision: str,
        *,
        note: str | None = None,
        user_id: str | None = None,
    ) -> Remark:
        """Apply a terminal decision (accepted|contested|withdrawn) to a remark."""
        remark = await self.get_remark(remark_id)
        self._assert_remark_transition(remark.status, decision)
        remark.status = decision
        if note is not None or user_id is not None:
            meta = dict(remark.metadata_ or {})
            if note is not None:
                meta["decision_note"] = note
            if user_id is not None:
                meta["decided_by"] = user_id
            meta["decided_at"] = self._now().isoformat()
            remark.metadata_ = meta
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(remark)  # type: ignore[attr-defined]
        return remark

    @staticmethod
    def _assert_remark_transition(current: str, target: str) -> None:
        allowed = REMARK_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal remark transition {current!r} -> {target!r}.",
            )

    # ── Derived views ──────────────────────────────────────────────────

    async def stale_remarks(self, cycle_id: uuid.UUID) -> list[Remark]:
        """Remarks whose cycle has advanced past the version they were raised on."""
        cycle = await self.get_cycle(cycle_id)
        if not is_remark_stale(cycle.pinned_document_version, cycle.current_document_version):
            return []
        return await self.repo.list_remarks(cycle_id)

    async def repeat_radar(self, cycle_id: uuid.UUID) -> list[dict[str, Any]]:
        """Rows for every remark the radar linked to a prior accepted remark."""
        remarks = await self.repo.list_remarks(cycle_id)
        by_id = {str(r.id): r for r in remarks}
        rows: list[dict[str, Any]] = []
        for r in remarks:
            if r.repeat_of_id is None:
                continue
            prior = by_id.get(str(r.repeat_of_id))
            rows.append(
                {
                    "remark_id": str(r.id),
                    "ordinal": r.ordinal,
                    "text": r.text,
                    "repeat_of_id": str(r.repeat_of_id),
                    "repeat_of_ordinal": prior.ordinal if prior else None,
                    "similarity": (token_overlap_ratio(r.text, prior.text) if prior else None),
                }
            )
        return rows

    async def build_dossier(self, cycle_id: uuid.UUID, *, locale: str = "en") -> dict[str, Any]:
        """Assemble the cycle, its remarks, responses and decisions for export.

        The dict carries a tamper-evident evidence header (generation time plus
        a content digest of the payload) so a downloaded dossier can be verified
        against the data it was produced from.
        """
        cycle = await self.get_cycle(cycle_id)
        remarks = await self.repo.list_remarks(cycle_id)
        now = self._now()

        timeline = cycle_timeline(
            opened_at=cycle.opened_at,
            sla_days=cycle.sla_days,
            due_at=cycle.due_at,
            status=cycle.status,
            now=now,
        )
        stale = is_remark_stale(cycle.pinned_document_version, cycle.current_document_version)

        remark_rows = [
            {
                "ordinal": r.ordinal,
                "section": r.section,
                "text": r.text,
                "norm_reference": r.norm_reference,
                "classification": r.classification,
                "severity": r.severity,
                "status": r.status,
                "response_text": r.response_text,
                "responded_at": r.responded_at.isoformat() if r.responded_at else None,
                "repeat_of_id": str(r.repeat_of_id) if r.repeat_of_id else None,
            }
            for r in remarks
        ]

        payload: dict[str, Any] = {
            "cycle": {
                "id": str(cycle.id),
                "project_id": str(cycle.project_id),
                "authority_name": cycle.authority_name,
                "authority_kind": cycle.authority_kind,
                "submission_ref": cycle.submission_ref,
                "pinned_document_version": cycle.pinned_document_version,
                "current_document_version": cycle.current_document_version,
                "status": cycle.status,
                "jurisdiction": cycle.jurisdiction,
                "opened_at": cycle.opened_at.isoformat() if cycle.opened_at else None,
                "due_at": cycle.due_at.isoformat() if cycle.due_at else None,
                "sla_days": cycle.sla_days,
            },
            "timeline": timeline,
            "document_version_stale": stale,
            "remarks": remark_rows,
            "summary": self._summarise(remark_rows),
        }

        header = self._evidence_header(generated_at=now.isoformat(), payload=payload, locale=locale)
        return {"evidence": header, **payload}

    @staticmethod
    def _summarise(remark_rows: list[dict[str, Any]]) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        by_classification: dict[str, int] = {}
        for r in remark_rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
            by_classification[r["classification"]] = by_classification.get(r["classification"], 0) + 1
        return {
            "total_remarks": len(remark_rows),
            "by_status": by_status,
            "by_classification": by_classification,
            "open_remarks": by_status.get("open", 0) + by_status.get("responded", 0),
        }

    @staticmethod
    def _evidence_header(*, generated_at: str, payload: Any, locale: str) -> list[dict[str, str]]:
        """Build the tamper-evident header rows, reusing the shared helper."""
        try:
            from app.core.evidence import evidence_header

            rows = evidence_header(generated_at=generated_at, payload=payload, locale=locale)
            return [{"label": label, "value": value} for label, value in rows]
        except Exception:  # pragma: no cover - evidence helper is best-effort
            return [{"label": "Generated", "value": generated_at}]


__all__ = [
    "CYCLE_TERMINAL",
    "CYCLE_TRANSITIONS",
    "DEFAULT_REPEAT_THRESHOLD",
    "REMARK_TERMINAL",
    "REMARK_TRANSITIONS",
    "ReviewAuthorityService",
    "classify_remark",
    "cycle_timeline",
    "find_repeats",
    "is_remark_stale",
    "normalise_tokens",
    "token_overlap_ratio",
]
