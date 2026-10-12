# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost-match business logic.

This is where the pure matcher meets the database. The split is deliberate and
worth keeping: :mod:`app.modules.cost_match.matcher` knows nothing about
sessions, rows or users and is therefore trivially testable, while everything
that has to persist, page, authorise or be reviewed lives here.

The three tiers
---------------
Every submitted line is scored against a bounded pool of cost items and lands
in exactly one tier:

* ``exact``           - the normalised descriptions are word-for-word equal and
                        the units agree. Nothing to argue about.
* ``high_confidence`` - scored at or above :data:`~matcher.HIGH_CONFIDENCE`.
* ``needs_review``    - scored between :data:`~matcher.REVIEW_CONFIDENCE` and
                        that. Plausible, and a person decides.
* ``unmatched``       - below the review floor. The closest candidate is still
                        recorded for context, exactly as the matcher offers it,
                        together with the matcher's own hint about what to try
                        next - but the tier does not claim it is a match.

Nothing is applied automatically
--------------------------------
The tier is what the machine found, never what the project adopts. A result
becomes usable only when a person confirms, overrides or rejects it, and that
ruling is written as its own row carrying the reviewer, the moment, and the
confidence the machine was showing at the time. An ``exact`` match is presented
first and still waits for a human. That is platform rule 7, and
``cost_match.decision_has_reviewer`` is the rule that catches a violation.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cost_scope
from app.core.events import event_bus
from app.modules.cost_match import events
from app.modules.cost_match.matcher import (
    HIGH_CONFIDENCE,
    REVIEW_CONFIDENCE,
    Candidate,
    MatchScore,
    best_match,
    canonical_tokens,
    explain,
    no_match_hint,
    normalize_text,
    normalize_unit,
    suggestion_rate,
)
from app.modules.cost_match.models import (
    DECISION_CONFIRMED,
    DECISION_OVERRIDDEN,
    DECISION_PENDING,
    DECISION_REJECTED,
    RUN_STATUS_CLOSED,
    TIER_EXACT,
    TIER_HIGH_CONFIDENCE,
    TIER_NEEDS_REVIEW,
    TIER_UNMATCHED,
    MatchDecision,
    MatchResult,
    MatchRun,
)
from app.modules.cost_match.repository import (
    QUEUE_TIERS,
    CostBaseRepository,
    MatchDecisionRepository,
    MatchResultRepository,
    MatchRunRepository,
)
from app.modules.cost_match.schemas import (
    MatchDecisionCreate,
    MatchResultResponse,
    MatchRunCounts,
    MatchRunCreate,
    MatchRunResponse,
    MatchRunUpdate,
)
from app.modules.cost_match.validators import (
    CostMatchValidationReport,
    evaluate_result,
    evaluate_run,
    merge_reports,
)
from app.modules.costs.models import CostItem

logger = logging.getLogger(__name__)

# How many scored candidates are kept on each result so an override is a pick
# from a list rather than a fresh search. The winner is included, so the
# reviewer sees the runners-up next to what was chosen for them.
ALTERNATIVES_KEPT = 5

# Confidence is stored with the same four-decimal precision the matcher
# produces, so a value never changes shape between scoring and reading.
_CONFIDENCE_PLACES = Decimal("0.0001")


class CatalogueNotFoundError(LookupError):
    """The run names a catalogue that does not exist for this caller.

    A catalogue the caller may not read and one that was never created give
    the same answer.
    """

    def __init__(self, catalog_id: uuid.UUID) -> None:
        super().__init__("Cost catalog not found")
        self.catalog_id = catalog_id


class RunClosedError(RuntimeError):
    """Raised when a ruling is attempted on a run whose review is closed.

    Closing a run is how a surveyor says the pricing is settled. Letting a
    late ruling in silently would move a bill that has already been quoted
    from, so the run is re-opened deliberately or not at all.
    """

    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        super().__init__(f"match run {run_id} is closed and does not accept new decisions")


class NoSuggestionToConfirmError(ValueError):
    """Raised when confirming a result that never received a suggestion.

    There is nothing to confirm: the base returned no candidate for the line.
    The honest rulings here are an override onto an item the reviewer found
    themselves, or a rejection.
    """

    def __init__(self, result_id: uuid.UUID) -> None:
        self.result_id = result_id
        super().__init__(f"match result {result_id} has no suggestion to confirm")


class DecisionPayloadError(ValueError):
    """Raised when a ruling's payload contradicts the ruling itself.

    An override with no target is not an override, and a rejection that names
    a cost item is two different answers at once.
    """


# ── small helpers ───────────────────────────────────────────────────────────


def _quantise_confidence(value: float | Decimal) -> Decimal:
    """Bring a confidence onto the stored four-decimal Decimal scale.

    Goes through ``str`` rather than ``Decimal(float)`` so 0.75 stays 0.75
    instead of becoming 0.750000000000000055511151231257827.
    """
    try:
        return Decimal(str(value)).quantize(_CONFIDENCE_PLACES)
    except (InvalidOperation, ValueError, ArithmeticError):
        return Decimal("0").quantize(_CONFIDENCE_PLACES)


def _band(confidence: Decimal) -> str:
    """Traffic-light band for a stored confidence.

    Mirrors the matcher's own banding, read off the same two constants, so a
    stored result cannot be shown in a different colour from the one the
    scorer meant.
    """
    if confidence >= Decimal(str(HIGH_CONFIDENCE)):
        return "high"
    if confidence >= Decimal(str(REVIEW_CONFIDENCE)):
        return "medium"
    return "low"


def _localized_description(item: CostItem, locale: str) -> str:
    """The cost item's description in ``locale``, falling back sensibly.

    Cost bases carry per-locale descriptions in ``CostItem.descriptions``.
    Scoring against the reader's own language is not cosmetic: it puts the
    query and the candidate in the same vocabulary before the matcher folds
    them onto shared concepts, which is where a foreign bill gets its recall.
    Falls back to the base language of a regional tag (``de-AT`` to ``de``)
    and finally to the item's primary description.
    """
    descriptions = item.descriptions if isinstance(item.descriptions, dict) else {}
    for key in (locale, (locale or "").split("-")[0].split("_")[0]):
        if not key:
            continue
        value = descriptions.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return item.description or ""


def _to_candidate(item: CostItem, locale: str) -> Candidate:
    """Wrap a cost item as a matcher candidate, money untouched.

    The rate travels in ``payload`` as the Decimal-string the base stores, so
    it reaches :func:`~matcher.suggestion_rate` without ever passing through a
    float.
    """
    return Candidate(
        ref=str(item.id),
        text=_localized_description(item, locale),
        unit=item.unit,
        payload={
            "unit_rate": item.rate,
            "currency": item.currency,
            "code": item.code,
        },
    )


def _tier_for(confidence: Decimal, factors: dict[str, Any], has_candidate: bool) -> str:
    """Place a scored line in one of the three tiers, or leave it unmatched.

    ``exact`` requires both the word-for-word equality the matcher reports in
    ``factors["exact"]`` **and** a confidence that survived the unit check:
    an exact text match priced per cubic metre against a line measured in
    square metres is not an exact match, it is a trap, and the matcher's unit
    penalty is what pushes it back down into review.
    """
    if not has_candidate:
        return TIER_UNMATCHED
    if confidence < Decimal(str(REVIEW_CONFIDENCE)):
        return TIER_UNMATCHED
    if confidence >= Decimal(str(HIGH_CONFIDENCE)):
        exact = factors.get("exact")
        if exact is not None and float(exact) >= 1.0:
            return TIER_EXACT
        return TIER_HIGH_CONFIDENCE
    return TIER_NEEDS_REVIEW


def _candidate_snapshot(candidate: Candidate, score: MatchScore) -> dict[str, Any]:
    """One scored candidate as the JSON snapshot kept on the result.

    Money and confidence are stored as strings: a JSON column cannot hold a
    Decimal, and storing a float here would undo the precision the rest of the
    path is careful about.
    """
    payload = candidate.payload or {}
    rate = suggestion_rate(candidate)
    return {
        "cost_item_id": candidate.ref,
        "code": str(payload.get("code") or ""),
        "description": candidate.text,
        "unit": candidate.unit or "",
        "rate": None if rate is None else format(rate, "f"),
        "currency": str(payload.get("currency") or ""),
        "confidence": format(_quantise_confidence(score.confidence), "f"),
        "band": score.band,
        "reason_codes": list(score.reasons),
    }


class CostMatchService:
    """Persisting, scoring and reviewing cost-match runs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.run_repo = MatchRunRepository(session)
        self.result_repo = MatchResultRepository(session)
        self.decision_repo = MatchDecisionRepository(session)
        self.base_repo = CostBaseRepository(session)

    # ── creating and scoring a run ──────────────────────────────────────

    async def create_run(
        self,
        data: MatchRunCreate,
        *,
        created_by: uuid.UUID | None = None,
    ) -> MatchRun:
        """Score a submitted batch and persist the run with all its results.

        Identical lines are retrieved and scored once and the outcome is
        copied onto each of them. A pasted bill repeats itself constantly
        (the same "reinforced concrete C30/37" on eight floors), and scoring
        it eight times would multiply the database work for an answer that is
        deterministic anyway.

        Args:
            data: The batch, plus the cost base it is being priced against.
            created_by: The user submitting it, recorded on the run.

        Returns:
            The persisted run. Its results are queried through the repository,
            never through ``run.results`` - that relationship refuses lazy SQL
            by design.
        """
        if data.catalog_id is not None and not await cost_scope.may_read_catalogue(self.session, data.catalog_id):
            raise CatalogueNotFoundError(data.catalog_id)
        run = MatchRun(
            project_id=data.project_id,
            name=data.name,
            source_label=data.source_label,
            source_locale=data.source_locale or "en",
            cost_source=data.cost_source,
            region=data.region,
            catalog_id=data.catalog_id,
            item_count=len(data.lines),
            candidate_limit=data.candidate_limit,
            created_by=created_by,
            tenant_id=data.tenant_id,
            notes=data.notes,
        )
        await self.run_repo.create(run)

        scored_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        rows: list[MatchResult] = []
        for index, line in enumerate(data.lines, start=1):
            key = (
                normalize_text(line.description),
                normalize_unit(line.unit) or normalize_text(line.unit),
                (line.source_ref or "").strip().lower(),
            )
            if key not in scored_cache:
                scored_cache[key] = await self._score_line(
                    description=line.description,
                    unit=line.unit,
                    source_ref=line.source_ref,
                    run=run,
                )
            rows.append(
                MatchResult(
                    run_id=run.id,
                    project_id=run.project_id,
                    line_no=index,
                    source_ref=line.source_ref,
                    source_description=line.description,
                    source_unit=line.unit,
                    source_quantity=line.quantity,
                    **scored_cache[key],
                )
            )
        await self.result_repo.bulk_create(rows)

        counts = _counts_from_rows(rows)
        event_bus.publish_detached(
            events.MATCH_COMPLETED,
            {
                "run_id": str(run.id),
                "project_id": str(run.project_id),
                "item_count": run.item_count,
                "exact": counts.exact,
                "high_confidence": counts.high_confidence,
                "needs_review": counts.needs_review,
                "unmatched": counts.unmatched,
                "tenant_id": str(run.tenant_id) if run.tenant_id else None,
            },
            source_module=events.SOURCE_MODULE,
        )
        return run

    async def _score_line(
        self,
        *,
        description: str,
        unit: str,
        source_ref: str,
        run: MatchRun,
    ) -> dict[str, Any]:
        """Retrieve, score and shape one distinct line into result columns.

        Retrieval is bounded by the run's ``candidate_limit``; the code
        lookup, when the foreign bill carried one, adds at most one more row
        and is placed first so a tie with a code hit resolves toward it. The
        code never decides the tier on its own - it only widens what the
        matcher gets to look at.
        """
        items = await self.base_repo.find_candidates(
            description,
            cost_source=run.cost_source,
            region=run.region,
            catalog_id=run.catalog_id,
            limit=run.candidate_limit,
        )
        if source_ref:
            coded = await self.base_repo.find_by_code(
                source_ref,
                cost_source=run.cost_source,
                region=run.region,
                catalog_id=run.catalog_id,
            )
            if coded is not None and all(existing.id != coded.id for existing in items):
                items = [coded, *items]

        candidates = [_to_candidate(item, run.source_locale) for item in items]
        outcome = best_match(
            description,
            candidates,
            query_unit=unit,
            locale=run.source_locale,
            top_n=ALTERNATIVES_KEPT,
        )

        alternatives = [_candidate_snapshot(cand, score) for cand, score in outcome.alternatives]
        if outcome.candidate is None or outcome.score is None:
            return {
                "tier": TIER_UNMATCHED,
                "confidence": Decimal("0").quantize(_CONFIDENCE_PLACES),
                "tie": outcome.tie,
                "hint_code": _hint_code(outcome.hint, description, candidates),
                "reason_codes": [],
                "factors": {},
                "alternatives": alternatives,
                "suggested_cost_item_id": None,
                "suggested_code": "",
                "suggested_description": "",
                "suggested_unit": "",
                "suggested_rate": None,
                "suggested_currency": "",
            }

        confidence = _quantise_confidence(outcome.score.confidence)
        payload = outcome.candidate.payload or {}
        return {
            "tier": _tier_for(confidence, outcome.score.factors, has_candidate=True),
            "confidence": confidence,
            "tie": outcome.tie,
            "hint_code": _hint_code(outcome.hint, description, candidates),
            "reason_codes": list(outcome.score.reasons),
            "factors": {name: float(value) for name, value in outcome.score.factors.items()},
            "alternatives": alternatives,
            "suggested_cost_item_id": uuid.UUID(outcome.candidate.ref),
            "suggested_code": str(payload.get("code") or ""),
            "suggested_description": outcome.candidate.text,
            "suggested_unit": outcome.candidate.unit or "",
            "suggested_rate": suggestion_rate(outcome.candidate),
            "suggested_currency": str(payload.get("currency") or ""),
        }

    # ── reading ─────────────────────────────────────────────────────────

    async def counts_for_runs(self, run_ids: list[uuid.UUID]) -> dict[uuid.UUID, MatchRunCounts]:
        """Aggregated tier and decision counts for several runs at once."""
        grouped = await self.result_repo.tier_decision_counts(run_ids)
        return {run_id: _counts_from_groups(buckets) for run_id, buckets in grouped.items()}

    async def run_response(self, run: MatchRun) -> MatchRunResponse:
        """One run header with its counts filled in."""
        counts = await self.counts_for_runs([run.id])
        response = MatchRunResponse.model_validate(run)
        response.counts = counts.get(run.id, MatchRunCounts())
        return response

    def result_response(self, result: MatchResult, *, locale: str) -> MatchResultResponse:
        """Shape one result for the API, rendered in ``locale``.

        The explanation is rendered here rather than stored: the reason codes
        are the durable record and the sentence is a view of them, so the same
        row reads in German for one reviewer and in Russian for the next.
        """
        response = MatchResultResponse.model_validate(result)
        codes = list(result.reason_codes or [])
        if codes:
            score = MatchScore(
                confidence=float(result.confidence),
                band=_band(result.confidence),
                factors={name: float(value) for name, value in (result.factors or {}).items()},
                reasons=codes,
            )
            response.explanation = explain(score, locale=locale)
        if result.hint_code:
            response.hint = no_match_hint(result.hint_code, locale=locale)
        return response

    # ── deciding ────────────────────────────────────────────────────────

    async def record_decision(
        self,
        run: MatchRun,
        result: MatchResult,
        data: MatchDecisionCreate,
        *,
        decided_by: uuid.UUID | None,
    ) -> MatchDecision:
        """Record one person's ruling on one result.

        Appends to the ruling history rather than overwriting it, so changing
        your mind is visible instead of invisible, and moves the result's
        ``decision_state`` to match. The confidence and tier the machine was
        showing at that moment are frozen onto the ruling, because the point
        of the record is what the reviewer was looking at, not what the row
        says today.

        Args:
            run: The run the result belongs to, used to scope an override
                target to the same cost base and to refuse rulings on a
                closed run.
            result: The line being ruled on.
            data: The ruling.
            decided_by: The reviewer. Recorded on the row; a ruling without
                one is an ERROR from ``cost_match.decision_has_reviewer``.

        Returns:
            The persisted ruling.

        Raises:
            RunClosedError: The run's review has been closed.
            NoSuggestionToConfirmError: Confirming a line that got no
                suggestion.
            DecisionPayloadError: The payload contradicts the ruling.
            LookupError: The override target is not an active item of this
                run's cost base.
        """
        if run.status == RUN_STATUS_CLOSED:
            raise RunClosedError(run.id)

        snapshot: dict[str, Any] = {
            "decided_cost_item_id": None,
            "decided_code": "",
            "decided_description": "",
            "decided_unit": "",
            "decided_rate": None,
            "decided_currency": "",
        }

        if data.decision == DECISION_CONFIRMED:
            if data.cost_item_id is not None and data.cost_item_id != result.suggested_cost_item_id:
                raise DecisionPayloadError(
                    "a confirmation adopts the suggestion as it stands; use 'overridden' to choose another item"
                )
            if result.suggested_cost_item_id is None:
                raise NoSuggestionToConfirmError(result.id)
            snapshot.update(
                decided_cost_item_id=result.suggested_cost_item_id,
                decided_code=result.suggested_code,
                decided_description=result.suggested_description,
                decided_unit=result.suggested_unit,
                decided_rate=result.suggested_rate,
                decided_currency=result.suggested_currency,
            )
        elif data.decision == DECISION_OVERRIDDEN:
            if data.cost_item_id is None:
                raise DecisionPayloadError("an override must name the cost item to adopt")
            item = await self.base_repo.get_active(
                data.cost_item_id,
                cost_source=run.cost_source,
                region=run.region,
                catalog_id=run.catalog_id,
            )
            if item is None:
                raise LookupError("cost item is not an active entry of this run's cost base")
            snapshot.update(
                decided_cost_item_id=item.id,
                decided_code=item.code,
                decided_description=_localized_description(item, run.source_locale),
                decided_unit=item.unit,
                decided_rate=_parse_rate(item.rate),
                decided_currency=item.currency,
            )
        elif data.cost_item_id is not None:
            raise DecisionPayloadError("a rejection adopts no cost item, so it must not name one")

        decision = MatchDecision(
            result_id=result.id,
            run_id=result.run_id,
            seq=await self.decision_repo.next_seq(result.id),
            decision=data.decision,
            tier_at_decision=result.tier,
            confidence_at_decision=result.confidence,
            decided_by=decided_by,
            note=data.note,
            **snapshot,
        )
        await self.decision_repo.create(decision)
        result.decision_state = data.decision
        await self.session.flush()

        event_bus.publish_detached(
            events.MATCH_REVIEWED,
            {
                "result_id": str(result.id),
                "run_id": str(result.run_id),
                "project_id": str(result.project_id),
                "decision": data.decision,
                "decided_by": str(decided_by) if decided_by else None,
                "tenant_id": str(run.tenant_id) if run.tenant_id else None,
            },
            source_module=events.SOURCE_MODULE,
        )
        return decision

    async def update_run(self, run: MatchRun, data: MatchRunUpdate) -> MatchRun:
        """Patch a run's reviewer-editable metadata.

        Only the fields the caller actually sent are touched, so an omitted
        field is left alone. ``notes`` is nullable and can be cleared with an
        explicit null; the rest are NOT NULL and an explicit null is simply
        not applied rather than written and failing at flush.
        """
        fields = data.model_dump(exclude_unset=True)
        for name, value in fields.items():
            if value is None and name != "notes":
                continue
            setattr(run, name, value)
        await self.session.flush()
        return run

    # ── validation ──────────────────────────────────────────────────────

    def result_payload(self, result: MatchResult) -> dict[str, Any]:
        """Plain-dict view of one result for the rule engine.

        Money, quantities and confidence go across as decimal strings so no
        rule ever sees a float, and the ruling in force is flattened onto the
        payload because that is what every result-scope rule is actually
        about.
        """
        payload: dict[str, Any] = {
            "id": str(result.id),
            "run_id": str(result.run_id),
            "line_no": result.line_no,
            "source_ref": result.source_ref,
            "source_description": result.source_description,
            "source_unit": result.source_unit,
            "source_quantity": None if result.source_quantity is None else format(result.source_quantity, "f"),
            "tier": result.tier,
            "confidence": format(result.confidence, "f"),
            "tie": result.tie,
            "hint_code": result.hint_code,
            "suggested_cost_item_id": (str(result.suggested_cost_item_id) if result.suggested_cost_item_id else None),
            "suggested_code": result.suggested_code,
            "suggested_unit": result.suggested_unit,
            "suggested_rate": None if result.suggested_rate is None else format(result.suggested_rate, "f"),
            "suggested_currency": result.suggested_currency,
            "decision_state": result.decision_state,
            "alternative_count": len(result.alternatives or []),
        }
        decision = result.current_decision
        if decision is not None:
            payload.update(
                {
                    "decision_seq": decision.seq,
                    "decided_by": str(decision.decided_by) if decision.decided_by else None,
                    "decided_cost_item_id": (
                        str(decision.decided_cost_item_id) if decision.decided_cost_item_id else None
                    ),
                    "decided_code": decision.decided_code,
                    "decided_description": decision.decided_description,
                    "decided_unit": decision.decided_unit,
                    "decided_rate": None if decision.decided_rate is None else format(decision.decided_rate, "f"),
                    "decided_currency": decision.decided_currency,
                    "confidence_at_decision": format(decision.confidence_at_decision, "f"),
                    "note": decision.note,
                }
            )
        return payload

    async def validate_result(
        self,
        result: MatchResult,
        *,
        locale: str = "",
    ) -> CostMatchValidationReport:
        """Run the result-scope ``cost_match`` rules over one line."""
        return await evaluate_result(
            {"result": self.result_payload(result)},
            project_id=str(result.project_id),
            locale=locale,
        )

    async def validate_run(
        self,
        run: MatchRun,
        *,
        locale: str = "",
    ) -> CostMatchValidationReport:
        """Run both scopes over a whole run and merge the reports.

        The run-scope rules see what no single line can (currency spread,
        the same scope priced two ways, how much queue is left); the
        result-scope rules are applied to every line and folded in, because a
        bill is only as sound as its worst line.
        """
        results = await self.result_repo.list_all_for_run(run.id)
        payloads = [self.result_payload(r) for r in results]
        reports = [
            await evaluate_run(
                {
                    "run": {
                        "id": str(run.id),
                        "name": run.name,
                        "status": run.status,
                        "item_count": run.item_count,
                        "cost_source": run.cost_source,
                        "region": run.region,
                    },
                    "results": payloads,
                },
                project_id=str(run.project_id),
                locale=locale,
            )
        ]
        for payload in payloads:
            reports.append(
                await evaluate_result(
                    {"result": payload},
                    project_id=str(run.project_id),
                    locale=locale,
                )
            )
        return merge_reports(reports, target_type="cost_match_run", target_id=str(run.id))


# ── module-level count helpers ──────────────────────────────────────────────


def _parse_rate(raw: str | None) -> Decimal | None:
    """Parse a cost base's Decimal-as-string rate, or ``None`` if unusable.

    ``None`` rather than zero on failure: a missing rate and a rate of zero
    are different findings and the ``cost_match.rate_present`` rule reports
    them differently.
    """
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def _hint_code(hint: str | None, description: str, candidates: list[Candidate]) -> str:
    """Recover the matcher's hint code from the fact that it produced a hint.

    The matcher renders hints into the reader's language, and a rendered
    sentence is the one thing that must not be persisted. The three cases it
    hints about are distinguishable from the inputs, so the code is derived
    from those and the sentence is re-rendered per reader on the way out.

    The empty-query test asks the matcher's own question, not whether the text
    looks blank. A line of nothing but stop words is not blank and does still
    retrieve rows, but it carries no term to score on, so the matcher treats it
    as empty. Testing ``strip()`` here would label it a poor match and send the
    reviewer looking for a better candidate that cannot exist.
    """
    if not hint:
        return ""
    if not canonical_tokens(description or ""):
        return "empty_query"
    if not candidates:
        return "no_candidates"
    return "no_good_match"


def _counts_from_rows(rows: list[MatchResult]) -> MatchRunCounts:
    """Aggregate freshly scored rows without a round trip to the database."""
    buckets: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row.tier, row.decision_state)
        buckets[key] = buckets.get(key, 0) + 1
    return _counts_from_groups(buckets)


def _counts_from_groups(buckets: dict[tuple[str, str], int]) -> MatchRunCounts:
    """Fold a ``(tier, decision_state) -> count`` grouping into the response.

    Every figure the UI shows is derived here from the rows themselves, which
    is why no count is stored on the run: a counter and its rows drift, and a
    queue badge that disagrees with the queue destroys trust in the feature.
    """
    counts = MatchRunCounts()
    tier_field = {
        TIER_EXACT: "exact",
        TIER_HIGH_CONFIDENCE: "high_confidence",
        TIER_NEEDS_REVIEW: "needs_review",
        TIER_UNMATCHED: "unmatched",
    }
    state_field = {
        DECISION_PENDING: "pending",
        DECISION_CONFIRMED: "confirmed",
        DECISION_OVERRIDDEN: "overridden",
        DECISION_REJECTED: "rejected",
    }
    for (tier, state), count in buckets.items():
        counts.total += count
        if tier in tier_field:
            setattr(counts, tier_field[tier], getattr(counts, tier_field[tier]) + count)
        if state in state_field:
            setattr(counts, state_field[state], getattr(counts, state_field[state]) + count)
        if tier in QUEUE_TIERS and state == DECISION_PENDING:
            counts.queue_length += count
    return counts
