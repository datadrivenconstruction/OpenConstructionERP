# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cost-match ORM models.

Tables:
    oe_cost_match_run       - one batch of pasted descriptions matched at once
    oe_cost_match_result    - one source line and the suggestion it received
    oe_cost_match_decision  - one human ruling on one result (append-only)

Why a run is persisted at all
-----------------------------
A quantity surveyor pastes a few hundred free-text lines from a foreign
subcontractor's bill and needs the answer to survive the browser tab: which
lines were matched, how confidently, on what evidence, and who accepted each
one. The three tables above are that record.

The suggestion is a snapshot, not a pointer
-------------------------------------------
``suggested_cost_item_id`` (and ``decided_cost_item_id`` on the decision) are
bare indexed UUID columns with **no** foreign key to ``oe_costs_item``, and the
code, description, unit, rate and currency of the matched item are copied onto
the row. Two reasons, both load-bearing:

* Cost bases are reloaded. A regional base is re-imported and rows are
  re-keyed; a FK would either block the import or cascade the review history
  away with it. The same reasoning is on ``FormworkAssignment.boq_position_id``.
* A confirmed match has to stay auditable against the rate that was **shown**
  at confirm time, not against today's rate. Reconstructing it by following a
  pointer would silently re-price history.

Money
-----
``suggested_rate`` / ``decided_rate`` are ``Numeric(18, 4)`` and nullable.
``CostItem.rate`` is a Decimal-as-string column, so an unparseable or absent
value lands here as ``NULL``, which is precisely the signal the
``cost_match.rate_present`` validation rule reads. They serialise as strings
through :mod:`app.modules.cost_match.schemas`.

Relationship loading is declared explicitly on every ``relationship()`` per
``.claude/rules/backend-modules.md``. ``MatchRun.results`` is the case that
rules file names by hand: a run holds hundreds of results and every screen
pages through them, so it is ``raise_on_sql`` and the repository does the
paging. A result's decision history is small, always read with the result and
is the point of the review UI, so it is ``selectin``. Every back-reference is
``raise_on_sql``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

# ── Vocabulary shared with the service, schemas and validators ──────────────

TIER_EXACT = "exact"
"""The normalised description of the source line equals the cost item's."""

TIER_HIGH_CONFIDENCE = "high_confidence"
"""Scored at or above the matcher's confident band, but not word-for-word."""

TIER_NEEDS_REVIEW = "needs_review"
"""Scored in the middle band: plausible, but a person decides."""

TIER_UNMATCHED = "unmatched"
"""Nothing in the base scored high enough to be worth offering."""

TIERS: tuple[str, ...] = (
    TIER_EXACT,
    TIER_HIGH_CONFIDENCE,
    TIER_NEEDS_REVIEW,
    TIER_UNMATCHED,
)

DECISION_PENDING = "pending"
"""No person has ruled on this result yet. Nothing is applied."""

DECISION_CONFIRMED = "confirmed"
"""A person accepted the suggestion the matcher offered."""

DECISION_OVERRIDDEN = "overridden"
"""A person replaced the suggestion with a different cost item."""

DECISION_REJECTED = "rejected"
"""A person ruled that no cost item in this base fits the line."""

DECISION_STATES: tuple[str, ...] = (
    DECISION_PENDING,
    DECISION_CONFIRMED,
    DECISION_OVERRIDDEN,
    DECISION_REJECTED,
)

DECISION_KINDS: tuple[str, ...] = (
    DECISION_CONFIRMED,
    DECISION_OVERRIDDEN,
    DECISION_REJECTED,
)

RUN_STATUS_MATCHED = "matched"
"""The batch has been scored; results are open for review."""

RUN_STATUS_CLOSED = "closed"
"""The surveyor declared the review finished."""

RUN_STATUSES: tuple[str, ...] = (RUN_STATUS_MATCHED, RUN_STATUS_CLOSED)


class MatchRun(Base):
    """One batch of free-text lines matched against one cost base.

    The base is pinned on the run (``cost_source`` / ``region`` /
    ``catalog_id``) rather than resolved per request, because a review that
    started against one regional base must keep scoring and overriding against
    that same base however the caller's filters change afterwards.

    ``item_count`` is the only count kept on the row, and it is immutable: it
    is how many lines were submitted. Every other figure a screen wants (tier
    counts, how many are still pending) is aggregated from the results in SQL,
    so no counter can drift out of step with the rows it claims to describe.
    """

    __tablename__ = "oe_cost_match_run"
    __table_args__ = (Index("ix_cost_match_run_project_created", "project_id", "created_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Who the bill came from. Free text on purpose: the counterparty may not
    # exist as a record yet when the surveyor is still pricing the enquiry.
    source_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Locale used to pick the cost item's description for scoring and to
    # render the matcher's reason codes back to the reviewer.
    source_locale: Mapped[str] = mapped_column(String(12), nullable=False, default="en")
    # ── the cost base this run is pinned to ──────────────────────────────
    cost_source: Mapped[str] = mapped_column(String(50), nullable=False, default="cwicr", index=True)
    region: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    catalog_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RUN_STATUS_MATCHED, index=True)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # How many cost items each line was allowed to be scored against. Kept on
    # the run so a thin result set can be explained later ("the pool was 10").
    candidate_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Hundreds of rows per run and every screen pages through them, so this is
    # the ``raise_on_sql`` case from the loading policy: a caller either pages
    # via the repository or orders the eager load explicitly. Deleting a run
    # still cascades - the ORM's delete path is not intercepted by the
    # strategy, which is why ``delete-orphan`` is safe here.
    results: Mapped[list[MatchResult]] = relationship(
        back_populates="run",
        lazy="raise_on_sql",
        cascade="all, delete-orphan",
        order_by="MatchResult.line_no",
    )

    def __repr__(self) -> str:
        return f"<MatchRun {self.name or self.id} items={self.item_count} status={self.status}>"


class MatchResult(Base):
    """One submitted line, the suggestion it drew, and how it was ruled on.

    ``tier`` is the automatic pass and never changes after the run: it says
    what the matcher found. ``decision_state`` is the human pass and is the
    only field a review moves. Keeping them apart is what makes "the machine
    proposed, a person disposed" reconstructable months later.

    ``reason_codes`` holds the matcher's codes (``exact_match``,
    ``unit_mismatch``, ...), not a rendered sentence. Storing the sentence
    would freeze one locale into the database; the codes render through the
    module's message bundle in whatever language the reader wants.
    """

    __tablename__ = "oe_cost_match_result"
    __table_args__ = (
        # The review queue is exactly this predicate, so it gets its own index.
        Index("ix_cost_match_result_queue", "run_id", "tier", "decision_state"),
        Index("ix_cost_match_result_run_line", "run_id", "line_no"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_cost_match_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised from the run so a project-wide read (and the access check
    # on a single result) never has to join back up to the run.
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # ── the submitted line, exactly as pasted ────────────────────────────
    source_ref: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    source_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_unit: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    source_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    # ── what the matcher found ───────────────────────────────────────────
    tier: Mapped[str] = mapped_column(String(20), nullable=False, default=TIER_UNMATCHED, index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("0"))
    # True when a second candidate scored identically to the winner. The
    # winner was then picked by input order, which is not a judgement, so the
    # review UI has to say so.
    tie: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # ``empty_query`` / ``no_candidates`` / ``no_good_match`` - the matcher's
    # own vocabulary for why there is nothing to offer. Empty when there is.
    hint_code: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    reason_codes: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    factors: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # Runner-up candidates with their own scores, so an override is a pick
    # from a list rather than a fresh search. Same snapshot shape as the
    # suggestion columns below.
    alternatives: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # ── snapshot of the suggested cost item (see the module docstring) ───
    suggested_cost_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    suggested_code: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    suggested_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    suggested_unit: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    suggested_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    suggested_currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    # ── the human pass ───────────────────────────────────────────────────
    decision_state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DECISION_PENDING,
        index=True,
    )

    # The ruling history is small, always read with the result and is the
    # whole point of the review screen, so it loads eagerly in one extra
    # SELECT. Ordered by an explicit persisted sequence, never by timestamp:
    # two rulings written in the same microsecond would otherwise come back
    # in an order the database was free to choose.
    decisions: Mapped[list[MatchDecision]] = relationship(
        back_populates="result",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="MatchDecision.seq",
    )
    # Back-reference up to the run. The FK is already in ``run_id``, so an
    # implicit walk up here is exactly the lazy SELECT the loading policy
    # exists to refuse. Callers that need the run order it eagerly.
    run: Mapped[MatchRun] = relationship(back_populates="results", lazy="raise_on_sql")

    @property
    def current_decision(self) -> MatchDecision | None:
        """The ruling in force, or ``None`` while the result is pending.

        Reads the eagerly loaded, sequence-ordered history, so it costs no
        query and cannot disagree with :attr:`decision_state`.
        """
        if not self.decisions:
            return None
        return self.decisions[-1]

    def __repr__(self) -> str:
        return f"<MatchResult #{self.line_no} {self.tier}/{self.decision_state} conf={self.confidence}>"


class MatchDecision(Base):
    """One human ruling on one result. Append-only.

    A review decision is a record, not a flag. It carries who ruled, when,
    what the machine was offering at that moment (``tier_at_decision``,
    ``confidence_at_decision``) and what was actually chosen. Changing your
    mind appends a second row rather than overwriting the first, so the
    sequence of judgements survives - which is the difference between an
    audit trail and a checkbox.

    ``seq`` is a per-result counter assigned by the service. Ordering on it
    rather than on ``created_at`` keeps the history stable even when two
    rulings land inside the same clock tick.

    The counter is derived with ``max(seq) + 1``, which two concurrent
    reviewers can compute identically. The unique constraint below is what
    makes that safe: the second writer fails loudly on the collision instead
    of quietly producing two rulings at the same position and destroying the
    ordering the whole append-only design rests on.
    """

    __tablename__ = "oe_cost_match_decision"
    __table_args__ = (UniqueConstraint("result_id", "seq", name="uq_oe_cost_match_decision_result_id_seq"),)

    result_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_cost_match_result.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised so run-wide reporting (currency spread, duplicate lines
    # decided differently) is one query against this table.
    run_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    decision: Mapped[str] = mapped_column(String(20), nullable=False, default=DECISION_CONFIRMED, index=True)
    # What the machine was saying when the person ruled. Frozen here because
    # the result row keeps only the current automatic pass.
    tier_at_decision: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    confidence_at_decision: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("0"))
    # ── snapshot of the cost item actually chosen ────────────────────────
    decided_cost_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    decided_code: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    decided_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_unit: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    decided_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    decided_currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    # Nullable in the column so a restore or a direct SQL write cannot fail,
    # but a row without it is an ERROR from the
    # ``cost_match.decision_has_reviewer`` rule: an unattributed ruling is an
    # auto-applied suggestion wearing a person's hat.
    decided_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Child back-reference: FK already in ``result_id``. ``raise_on_sql``
    # still allows the free read when the parent came in through
    # ``MatchResult.decisions``.
    result: Mapped[MatchResult] = relationship(back_populates="decisions", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<MatchDecision #{self.seq} {self.decision} item={self.decided_code or '-'}>"
