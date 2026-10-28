# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cost-match data access layer.

Two kinds of query live here:

* the module's own three tables, read the way the review screens read them
  (a page of a run's results, the needs-review queue, the aggregated counts);
* retrieval against the cost base, which is a **read-only** query over
  :class:`~app.modules.costs.models.CostItem`. Following the convention set by
  ``cost_explorer``, the cost item model is imported directly and this module
  builds its own ``select()`` rather than reaching through the costs service.

Retrieval matters more than it looks. The matcher is a pure in-memory scorer
with no notion of a database, so whatever this layer returns is the entire
universe the match is chosen from. Handing it the whole base would be both
slow and pointless; handing it a naive ``ILIKE`` on the pasted phrase would
lose every cross-language hit, which is the one thing the matcher exists to
get right.

So a description is broken into retrieval terms and each term goes through
``costs.repository.synonym_text_predicate``, the platform's shared
multilingual construction-vocabulary predicate, which expands one word into
its cross-language group at SQL level. That predicate takes a single term (it
folds and looks up the whole string it is given), so feeding it the phrase
would silently collapse to a substring match on the phrase - the exact failure
this module cannot afford.

The terms are the description's own words **and** the matcher's
:func:`~app.modules.cost_match.matcher.canonical_tokens` for it. The second
half is what carries a Russian or Spanish line onto an English base row: the
matcher maps every language's word for a concept onto one shared English
token, so retrieval ends up asking the database the same question the scorer
will ask in memory. Retrieval and scoring agreeing on the vocabulary is what
keeps a bounded pool from quietly dropping the right answer.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.cost_match.matcher import canonical_tokens
from app.modules.cost_match.models import (
    DECISION_PENDING,
    TIER_NEEDS_REVIEW,
    TIER_UNMATCHED,
    MatchDecision,
    MatchResult,
    MatchRun,
)
from app.modules.costs.models import CostItem
from app.modules.costs.repository import synonym_text_predicate

# Tiers that a person has to look at before anything can be priced. Confident
# and exact tiers still need confirming (nothing is auto-applied), but they are
# not what the queue is for.
QUEUE_TIERS: tuple[str, ...] = (TIER_NEEDS_REVIEW, TIER_UNMATCHED)

# Words shorter than this are dropped from retrieval. A one or two character
# token ("m", "de", "C") matches most of a catalogue as a substring and would
# turn the bounded pool into an arbitrary slice of the base.
_MIN_TERM_LENGTH = 3

# Upper bound on how many terms one description contributes. A long BOQ line
# would otherwise build an OR of a hundred predicates, and the terms past the
# first dozen are qualifiers ("including", "as detailed") that widen the pool
# without improving it.
_MAX_TERMS = 16

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def retrieval_terms(text: str) -> list[str]:
    """The terms one description contributes to the candidate query.

    The description's own words come first, spelling intact so an accented row
    is still reachable by an accented query, followed by the matcher's
    language-neutral concept tokens, which is what lets a foreign line reach a
    base written in another language. Order-preserving and deduplicated, so
    the generated SQL for a given description is stable.
    """
    terms: dict[str, None] = {}
    for word in _WORD_RE.findall(text or ""):
        if len(word) >= _MIN_TERM_LENGTH:
            terms.setdefault(word, None)
    for token in canonical_tokens(text):
        if len(token) >= _MIN_TERM_LENGTH:
            terms.setdefault(token, None)
    return list(terms)[:_MAX_TERMS]


class _CRUDBase:
    """Shared CRUD primitives for the cost-match repositories."""

    model: type
    session: AsyncSession

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, item_id: uuid.UUID) -> Any:
        return await self.session.get(self.model, item_id)

    async def create(self, item: Any) -> Any:
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, item_id: uuid.UUID, **fields: Any) -> None:
        """Write columns by id and keep any cached ORM instance in step.

        Mirrors the pattern used across the platform's repositories: the
        UPDATE goes out as SQL, then the identity-mapped instance (if any) is
        told the new values so the next read does not fire a refresh from an
        async context.
        """
        stmt = update(self.model).where(self.model.id == item_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(self.model, item_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, item_id: uuid.UUID) -> None:
        obj = await self.get_by_id(item_id)
        if obj is not None:
            await self.session.delete(obj)
            await self.session.flush()


class MatchRunRepository(_CRUDBase):
    """Runs, read the way the run list reads them."""

    model = MatchRun

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[MatchRun]:
        """Runs on one project, newest first."""
        stmt = select(MatchRun).where(MatchRun.project_id == project_id)
        if status:
            stmt = stmt.where(MatchRun.status == status)
        stmt = stmt.order_by(MatchRun.created_at.desc(), MatchRun.id).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_for_project(self, project_id: uuid.UUID, *, status: str | None = None) -> int:
        stmt = select(func.count(MatchRun.id)).where(MatchRun.project_id == project_id)
        if status:
            stmt = stmt.where(MatchRun.status == status)
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)


class MatchResultRepository(_CRUDBase):
    """Results, plus the aggregates that replace stored counters."""

    model = MatchResult

    def _filtered(
        self,
        run_id: uuid.UUID,
        *,
        tier: str | None,
        decision_state: str | None,
        queue_only: bool,
    ) -> Select[Any]:
        stmt = select(MatchResult).where(MatchResult.run_id == run_id)
        if tier:
            stmt = stmt.where(MatchResult.tier == tier)
        if decision_state:
            stmt = stmt.where(MatchResult.decision_state == decision_state)
        if queue_only:
            stmt = stmt.where(
                MatchResult.tier.in_(QUEUE_TIERS),
                MatchResult.decision_state == DECISION_PENDING,
            )
        return stmt

    async def list_for_run(
        self,
        run_id: uuid.UUID,
        *,
        tier: str | None = None,
        decision_state: str | None = None,
        queue_only: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[MatchResult]:
        """One page of a run's results in submission order.

        The rulings on each row come back with it: ``MatchResult.decisions``
        is ``selectin``, so a page of a hundred results costs two queries, not
        a hundred and one.
        """
        stmt = self._filtered(
            run_id,
            tier=tier,
            decision_state=decision_state,
            queue_only=queue_only,
        )
        stmt = stmt.order_by(MatchResult.line_no, MatchResult.id).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_for_run(
        self,
        run_id: uuid.UUID,
        *,
        tier: str | None = None,
        decision_state: str | None = None,
        queue_only: bool = False,
    ) -> int:
        stmt = self._filtered(
            run_id,
            tier=tier,
            decision_state=decision_state,
            queue_only=queue_only,
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        result = await self.session.execute(count_stmt)
        return int(result.scalar_one() or 0)

    async def list_all_for_run(self, run_id: uuid.UUID) -> list[MatchResult]:
        """Every result of one run, for validation and run-wide reporting.

        Unpaged on purpose: the run-scope rules (currency spread, duplicate
        lines decided differently) are defined over the whole set and a
        partial page would make them quietly wrong. A run is capped at
        ``MAX_BATCH_LINES`` rows, so this is bounded by construction.

        ``populate_existing`` for the same reason as
        :meth:`get_with_decisions`: this feeds the validation pass, and
        validating a run in the session that has just been ruling on it must
        see those rulings, not the identity map's memory of an empty history.
        """
        stmt = (
            select(MatchResult)
            .where(MatchResult.run_id == run_id)
            .order_by(MatchResult.line_no, MatchResult.id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def tier_decision_counts(
        self,
        run_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, dict[tuple[str, str], int]]:
        """``{run_id: {(tier, decision_state): count}}`` for many runs at once.

        One GROUP BY replaces every stored counter on the run row. The run
        list uses it for all its runs in a single query.
        """
        if not run_ids:
            return {}
        stmt = (
            select(
                MatchResult.run_id,
                MatchResult.tier,
                MatchResult.decision_state,
                func.count(MatchResult.id),
            )
            .where(MatchResult.run_id.in_(run_ids))
            .group_by(MatchResult.run_id, MatchResult.tier, MatchResult.decision_state)
        )
        result = await self.session.execute(stmt)
        grouped: dict[uuid.UUID, dict[tuple[str, str], int]] = {rid: {} for rid in run_ids}
        for run_id, tier, decision_state, count in result.all():
            grouped.setdefault(run_id, {})[(tier, decision_state)] = int(count or 0)
        return grouped

    async def get_with_decisions(self, result_id: uuid.UUID) -> MatchResult | None:
        """One result with its ruling history freshly loaded.

        ``populate_existing`` is not decoration here. A result this session
        created (or already read) sits in the identity map with a collection
        the ORM considers loaded, and a plain re-select hands that instance
        straight back - so a ruling written moments earlier in the same
        session would be invisible and the review screen would show an empty
        history right after somebody filled it. Forcing the refresh makes the
        method's name true whatever the session has seen before.
        """
        stmt = (
            select(MatchResult)
            .where(MatchResult.id == result_id)
            .options(selectinload(MatchResult.decisions))
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def bulk_create(self, items: list[MatchResult]) -> list[MatchResult]:
        """Insert a whole run's results in one flush."""
        if not items:
            return []
        self.session.add_all(items)
        await self.session.flush()
        return items


class MatchDecisionRepository(_CRUDBase):
    """The append-only ruling ledger."""

    model = MatchDecision

    async def next_seq(self, result_id: uuid.UUID) -> int:
        """The sequence number the next ruling on this result should carry.

        Derived in SQL from the rows that exist rather than from the length of
        an in-memory collection, so a stale or partially loaded history cannot
        hand back a number that is already taken.

        This read is not a lock. Two reviewers ruling on the same result at the
        same instant can both see the same maximum and both compute the same
        successor. What makes that safe is the unique constraint on
        ``(result_id, seq)``: the second writer fails, rather than quietly
        landing a second ruling at the same position and leaving the ordering
        of the ledger undefined. Nothing retries it - the loser's request
        errors and the reviewer rules again - which is the right trade while
        two people ruling on one line in the same instant stays rare.
        """
        stmt = select(func.max(MatchDecision.seq)).where(MatchDecision.result_id == result_id)
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0) + 1

    async def list_for_run(self, run_id: uuid.UUID) -> list[MatchDecision]:
        stmt = (
            select(MatchDecision)
            .where(MatchDecision.run_id == run_id)
            .order_by(MatchDecision.result_id, MatchDecision.seq)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class CostBaseRepository:
    """Read-only retrieval against the cost base a run is pinned to.

    Nothing here writes: the cost base belongs to ``oe_costs`` and this module
    only ever reads candidates out of it.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _scoped(
        self,
        *,
        cost_source: str | None,
        region: str | None,
        catalog_id: uuid.UUID | None,
    ) -> Select[Any]:
        """Base query narrowed to one cost base.

        ``is_active`` is not optional: an item withdrawn from the base must
        never come back as a suggestion, and every read path in ``oe_costs``
        applies the same filter.
        """
        stmt = select(CostItem).where(CostItem.is_active.is_(True))
        if cost_source:
            stmt = stmt.where(CostItem.source == cost_source)
        if region:
            stmt = stmt.where(CostItem.region == region)
        if catalog_id is not None:
            stmt = stmt.where(CostItem.catalog_id == catalog_id)
        return stmt

    async def find_candidates(
        self,
        text: str,
        *,
        cost_source: str | None = None,
        region: str | None = None,
        catalog_id: uuid.UUID | None = None,
        limit: int = 40,
    ) -> list[CostItem]:
        """Cost items worth scoring against ``text``, bounded by ``limit``.

        Recall comes from the shared multilingual predicate, so a Russian or
        Spanish line still reaches a German or English base row. Ordering is
        by ``code`` so the pool is deterministic: the same submission scored
        twice must produce the same result, and an arbitrary database order
        under a LIMIT would break that.

        Returns an empty list for a blank query rather than the first
        ``limit`` rows of the catalogue, which would be a suggestion with no
        evidence behind it.
        """
        clauses = [
            predicate
            for predicate in (synonym_text_predicate(term) for term in retrieval_terms(text))
            if predicate is not None
        ]
        if not clauses:
            return []
        stmt = self._scoped(cost_source=cost_source, region=region, catalog_id=catalog_id)
        stmt = stmt.where(or_(*clauses)).order_by(CostItem.code, CostItem.id).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_code(
        self,
        code: str,
        *,
        cost_source: str | None = None,
        region: str | None = None,
        catalog_id: uuid.UUID | None = None,
    ) -> CostItem | None:
        """The item whose ``code`` equals ``code`` inside this base, if any.

        A foreign bill often carries the subcontractor's own item code. When
        it happens to be a code in our base, that row is pulled into the
        candidate pool so the matcher can score it - but it is never promoted
        to a match on the strength of the code alone. A code that matches
        while the description does not is exactly the case a reviewer needs to
        see rather than have decided for them.
        """
        cleaned = (code or "").strip()
        if not cleaned:
            return None
        stmt = self._scoped(cost_source=cost_source, region=region, catalog_id=catalog_id)
        stmt = stmt.where(func.lower(CostItem.code) == cleaned.lower()).order_by(CostItem.code, CostItem.id).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_active(
        self,
        cost_item_id: uuid.UUID,
        *,
        cost_source: str | None = None,
        region: str | None = None,
        catalog_id: uuid.UUID | None = None,
    ) -> CostItem | None:
        """One active item from this base, used to resolve an override target.

        Scoped to the run's own base on purpose: overriding onto an item from
        a different regional base would put two price levels in one bill
        without anything on the row to say so.
        """
        stmt = self._scoped(cost_source=cost_source, region=region, catalog_id=catalog_id)
        stmt = stmt.where(CostItem.id == cost_item_id).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()
