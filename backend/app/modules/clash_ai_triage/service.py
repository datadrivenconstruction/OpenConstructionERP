# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍LLM-assisted clash triage service.

Public surface
--------------
:class:`ClashTriageService` exposes three methods:

* :meth:`triage_clash` - produce a verdict for a single clash. Cached on
  ``(subject_id, prompt_version, model_name)`` so a repeat call returns
  the persisted row without paying for another LLM call.
* :meth:`triage_batch` - fan out :meth:`triage_clash` across many clash
  ids with bounded concurrency.
* :meth:`replay_with_new_prompt` - re-triage an existing result against a
  newer prompt version, always producing a NEW row (the original audit
  trail is preserved).

Honesty about cost
------------------
``cost_usd_estimate`` is computed from the token counts the LLM reports
multiplied by a hard-coded per-1k-token rate table (see ``MODEL_COSTS``).
The rates are deliberately documented next to the constants so a future
operator can refresh them without hunting through prompt logic.

Graceful degradation
--------------------
* No LLM key configured → :class:`ClashTriageUnavailable`. The router
  translates this to ``503``.
* LLM returns invalid JSON → retry once with a "respond with valid JSON
  only" follow-up.
* Two invalid JSON attempts in a row → persist with
  ``category="unclear"``, the raw response intact for the operator to
  inspect.
* ``ClashIssue`` table missing on the DB → fall back to ``subject_type=
  "clash"`` (the upstream sibling agent's table may not exist yet).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.pricing import (
    DEFAULT_COST_PER_1K,
    MODEL_COSTS,
)
from app.core.ai.pricing import (
    estimate_cost_usd as _shared_estimate_cost_usd,
)
from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model
from app.modules.ai.models import AISettings
from app.modules.clash.models import ClashResult, ClashRun
from app.modules.clash_ai_triage.models import ClashTriageResult
from app.modules.clash_ai_triage.prompts import (
    PROMPT_VERSION,
    RETRY_PROMPT_V1,
    SYSTEM_PROMPT_V1,
    build_user_prompt,
)
from app.modules.clash_ai_triage.schemas import (
    TRIAGE_CATEGORIES,
    TRIAGE_SEVERITIES,
    TRIAGE_SUGGESTED_ACTIONS,
    TriageVerdict,
)

logger = logging.getLogger(__name__)


# ── Per-model cost table - now sourced from app.core.ai.pricing ─────────────
# Kept as local re-exports for backward compatibility with any caller that
# imported MODEL_COSTS / DEFAULT_COST_PER_1K from this module. Both modules
# (clash_ai_triage and ai) now share the same rate table so per-tenant
# cost rollups stay comparable.
# (MODEL_COSTS and DEFAULT_COST_PER_1K are imported above.)

#: Hard wall-clock cap for an end-to-end triage LLM call (initial + JSON
#: retry). The provider HTTP client already enforces ``AI_TIMEOUT`` (120 s
#: per request) but a stuck retry could still tie a request thread up for
#: ~4 minutes. We bound the whole pair at 180 s so the calling worker
#: recycles in a predictable time even on a bad-day provider. Exceeds it
#: → :class:`asyncio.TimeoutError` bubbles up as a 503 via the router's
#: existing ``ClashTriageUnavailable`` translation.
_LLM_CALL_TIMEOUT_S: float = 180.0


# ── Public exceptions ───────────────────────────────────────────────────────


class ClashTriageError(Exception):
    """Base class for triage-service errors that the router translates."""


class ClashTriageUnavailable(ClashTriageError):
    """No LLM provider is configured (no API key set in AI settings)."""


class ClashSubjectNotFound(ClashTriageError):
    """The clash id passed to ``triage_clash`` does not exist."""


# ── Per-subject lock registry (dedup concurrent calls on same clash) ────────
# In-process only - concurrent calls on the *same* subject within one
# process wait for the first to finish so they hit the cache instead of
# both paying for the LLM. Cross-process dedup would need Redis and is
# not in scope for v1.
_subject_locks: dict[uuid.UUID, asyncio.Lock] = {}
_subject_locks_master = asyncio.Lock()


async def _get_subject_lock(subject_id: uuid.UUID) -> asyncio.Lock:
    async with _subject_locks_master:
        lock = _subject_locks.get(subject_id)
        if lock is None:
            lock = asyncio.Lock()
            _subject_locks[subject_id] = lock
        return lock


# ── Helpers ─────────────────────────────────────────────────────────────────


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _estimate_cost_usd(model_name: str, tokens: int) -> Decimal:
    """Estimate USD cost for ``tokens`` against the per-1k rate table.

    Thin compatibility wrapper around
    :func:`app.core.ai.pricing.estimate_cost_usd` - kept so existing
    callers (and the public ``__all__`` re-export) keep working without
    a churn-y rename. New code should import from ``app.core.ai`` direct.
    """
    return _shared_estimate_cost_usd(model_name, tokens)


def _coerce_verdict(parsed: Any) -> TriageVerdict | None:
    """Turn an extracted JSON payload into a validated :class:`TriageVerdict`.

    Returns ``None`` if the payload cannot be coerced. Defensive against
    unknown enum values (the model occasionally hallucinates
    ``"high_priority"`` instead of ``"high"``) by snapping them to the
    nearest legal value when possible.
    """
    if not isinstance(parsed, dict):
        return None
    data = dict(parsed)
    cat = str(data.get("category", "")).strip().lower()
    if cat not in TRIAGE_CATEGORIES:
        return None
    data["category"] = cat

    sev = str(data.get("severity_suggested", "medium")).strip().lower()
    if sev not in TRIAGE_SEVERITIES:
        sev = "medium"
    data["severity_suggested"] = sev

    action = data.get("suggested_action")
    if action is not None:
        action = str(action).strip().lower()
        if action in TRIAGE_SUGGESTED_ACTIONS:
            data["suggested_action"] = action
        else:
            data["suggested_action"] = None

    evidence_raw = data.get("model_evidence_used", []) or []
    if isinstance(evidence_raw, list):
        data["model_evidence_used"] = [str(x) for x in evidence_raw if x is not None]
    else:
        data["model_evidence_used"] = []

    try:
        # Pydantic will coerce confidence + run range validation.
        return TriageVerdict.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - Pydantic ValidationError
        logger.debug("Verdict coercion failed: %s", exc)
        return None


def _build_evidence_from_clash(clash: ClashResult) -> dict[str, Any]:
    """Project a ``ClashResult`` row into the evidence mapping the prompt expects."""
    return {
        "element_a_id": str(clash.a_stable_id or clash.a_element_id),
        "element_b_id": str(clash.b_stable_id or clash.b_element_id),
        "ifc_class_a": clash.a_element_type or clash.a_discipline or "Element",
        "ifc_class_b": clash.b_element_type or clash.b_discipline or "Element",
        "material_a": "",  # Not snapshotted on ClashResult - left blank.
        "material_b": "",
        "properties_a": clash.a_name or "",
        "properties_b": clash.b_name or "",
        "trade_pair": f"{clash.a_discipline}/{clash.b_discipline}",
        "clash_type": clash.clash_type or "hard",
        "clearance_mm": (clash.distance_m or 0.0) * 1000.0,
        "tolerance_mm": getattr(clash, "tolerance_at_signature_time_mm", 10.0) or 10.0,
        "x": clash.cx or 0.0,
        "y": clash.cy or 0.0,
        "z": clash.cz or 0.0,
        "grid_label": "",
        "storey_label": str(clash.a_storey) if clash.a_storey is not None else "",
    }


async def _resolve_provider_settings(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> tuple[str, str, str | None]:
    """Resolve the AI provider/key/model override for ``user_id``.

    Raises :class:`ClashTriageUnavailable` (not ValueError) so the caller
    can map cleanly to a 503.
    """
    result = await session.execute(select(AISettings).where(AISettings.user_id == user_id))
    settings = result.scalar_one_or_none()
    try:
        return resolve_provider_key_model(settings)
    except ValueError as exc:
        msg = (
            "No AI provider configured for the current user - add an API "
            "key in Settings > AI to enable LLM-assisted clash triage."
        )
        raise ClashTriageUnavailable(msg) from exc


# ── Main service ────────────────────────────────────────────────────────────


class ClashTriageService:
    """‌⁠‍Business logic for LLM-assisted clash triage."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Cache lookup ────────────────────────────────────────────────────

    async def _get_cached(
        self,
        subject_id: uuid.UUID,
        prompt_version: str,
        model_name: str,
    ) -> ClashTriageResult | None:
        """Return the most-recent triage row matching the cache key."""
        stmt = (
            select(ClashTriageResult)
            .where(
                ClashTriageResult.subject_id == subject_id,
                ClashTriageResult.prompt_version == prompt_version,
                ClashTriageResult.model_name == model_name,
            )
            .order_by(ClashTriageResult.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ── Load clash with optional issue promotion ────────────────────────

    async def _load_clash(self, clash_id: uuid.UUID) -> ClashResult:
        """Fetch a ClashResult by id or raise :class:`ClashSubjectNotFound`."""
        result = await self.session.execute(select(ClashResult).where(ClashResult.id == clash_id))
        clash = result.scalar_one_or_none()
        if clash is None:
            raise ClashSubjectNotFound(f"Clash {clash_id} not found")
        return clash

    async def _project_id_for_clash(self, clash_id: uuid.UUID) -> uuid.UUID | None:
        """Resolve ``ClashResult → ClashRun → project_id`` (``None`` if orphaned)."""
        stmt = (
            select(ClashRun.project_id)
            .join(ClashResult, ClashResult.run_id == ClashRun.id)
            .where(ClashResult.id == clash_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _resolve_subject(self, clash: ClashResult) -> tuple[str, uuid.UUID]:
        """Decide whether the triage targets a clash or a clash_issue.

        Polymorphism rule: if the clash row carries an ``issue_id`` AND
        the ``oe_clash_issue`` table is reachable, prefer the issue
        (cross-run identity stays meaningful). Otherwise fall back to
        the per-run row so the feature still works on dev DBs that
        pre-date the smart-issue migration.
        """
        issue_id = getattr(clash, "issue_id", None)
        if issue_id is None:
            return "clash", clash.id
        # Probe the issue table - if the migration is missing we degrade
        # silently rather than 500.
        try:
            from app.modules.clash.models import ClashIssue  # local import

            stmt = select(ClashIssue.id).where(ClashIssue.id == issue_id)
            issue_pk = (await self.session.execute(stmt)).scalar_one_or_none()
            if issue_pk is None:
                return "clash", clash.id
            return "clash_issue", issue_pk
        except (OperationalError, ProgrammingError, ImportError):
            logger.debug("ClashIssue table unreachable - degrading to subject_type=clash")
            return "clash", clash.id

    # ── Prior triage lookup (for re-run context) ────────────────────────

    async def _latest_prior(self, subject_id: uuid.UUID) -> Mapping[str, Any] | None:
        stmt = (
            select(ClashTriageResult)
            .where(ClashTriageResult.subject_id == subject_id)
            .order_by(ClashTriageResult.created_at.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return {
            "date": row.created_at.date().isoformat() if row.created_at else "",
            "category": row.category,
            "confidence": row.confidence,
        }

    # ── Single triage (the core workflow) ──────────────────────────────

    async def triage_clash(
        self,
        clash_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        force_refresh: bool = False,
        allowed_project_ids: set[uuid.UUID] | None = None,
    ) -> ClashTriageResult:
        """‌⁠‍Triage one clash. Cached unless ``force_refresh=True``.

        Args:
            clash_id: The ``ClashResult.id`` to triage.
            user_id: The authenticated user - needed to resolve their AI
                provider settings and stamped on the persisted row.
            force_refresh: When True, bypass the cache and force a fresh
                LLM call.
            allowed_project_ids: Optional defense-in-depth scope. When given,
                the clash's owning project MUST be in this set or the call
                raises :class:`ClashSubjectNotFound` (which the router maps to
                404). ``None`` skips the check - the router authorizes the
                single-clash path before calling, so this re-check only guards
                the fan-out/replay paths where a foreign id could slip in.

        Raises:
            ClashSubjectNotFound: ``clash_id`` does not match any row, or the
                clash is outside ``allowed_project_ids``.
            ClashTriageUnavailable: No AI provider key configured.
        """
        clash = await self._load_clash(clash_id)
        if allowed_project_ids is not None:
            project_id = await self._project_id_for_clash(clash_id)
            if project_id is None or project_id not in allowed_project_ids:
                # Collapse "foreign" and "orphaned" to the same 404-shaped
                # error so the caller cannot use it as an existence oracle.
                raise ClashSubjectNotFound(f"Clash {clash_id} not found")
        subject_type, subject_id = await self._resolve_subject(clash)

        # Lock the subject so concurrent callers in the same process
        # deduplicate (the second call hits the cache).
        lock = await _get_subject_lock(subject_id)
        async with lock:
            # Resolve LLM provider FIRST so an unconfigured user gets a
            # 503 before we pay for a cache lookup.
            provider, api_key, model_override = await _resolve_provider_settings(self.session, user_id)
            model_name = model_override or _default_model_name_for(provider)

            if not force_refresh:
                cached = await self._get_cached(subject_id, PROMPT_VERSION, model_name)
                if cached is not None:
                    return cached

            evidence = _build_evidence_from_clash(clash)
            prior = await self._latest_prior(subject_id)
            user_prompt = build_user_prompt(evidence, prior=prior)

            try:
                async with asyncio.timeout(_LLM_CALL_TIMEOUT_S):
                    text, tokens = await _call_llm_with_retry(
                        provider=provider,
                        api_key=api_key,
                        model=model_override,
                        user_prompt=user_prompt,
                    )
            except TimeoutError as exc:
                msg = (
                    f"LLM call exceeded {_LLM_CALL_TIMEOUT_S:.0f}s on provider "
                    f"{provider} model={model_name}; aborted to free the worker."
                )
                raise ClashTriageUnavailable(msg) from exc

            verdict = _coerce_verdict(extract_json(text) or _try_fence_extract(text))

            if verdict is None:
                # Twice-failed JSON parse - persist with ``unclear`` so
                # the audit trail still captures the raw response.
                verdict = TriageVerdict(
                    category="unclear",
                    confidence=0.0,
                    severity_suggested="medium",
                    explanation=(
                        "LLM returned non-JSON response after retry. See raw_response for the original output."
                    ),
                    suggested_action=None,
                    model_evidence_used=[],
                )

            cost_estimate = _estimate_cost_usd(model_name, int(tokens or 0))
            # Structured cost log - one line per real LLM call so ops can
            # aggregate spend by user / project / model without instrumenting
            # the provider client. Uses ``extra=`` so log aggregators (Loki,
            # Datadog, etc.) ingest the fields as structured columns rather
            # than parsing the message string.
            logger.info(
                "clash_triage.llm_call",
                extra={
                    "event": "clash_triage.llm_call",
                    "provider": provider,
                    "model": model_name,
                    "prompt_version": PROMPT_VERSION,
                    "tokens_used": int(tokens or 0),
                    "cost_usd_estimate": float(cost_estimate),
                    "user_id": str(user_id),
                    "clash_id": str(clash.id),
                    "subject_type": subject_type,
                    "subject_id": str(subject_id),
                    "verdict_category": verdict.category,
                },
            )

            row = ClashTriageResult(
                subject_type=subject_type,
                subject_id=subject_id,
                clash_id=clash.id,
                model_name=model_name,
                prompt_version=PROMPT_VERSION,
                category=verdict.category,
                confidence=float(verdict.confidence),
                severity_suggested=verdict.severity_suggested,
                explanation=verdict.explanation,
                suggested_action=verdict.suggested_action,
                model_evidence_used=list(verdict.model_evidence_used or []),
                raw_prompt=user_prompt,
                raw_response=text,
                tokens_used=int(tokens or 0),
                cost_usd_estimate=float(cost_estimate),
                created_by_user_id=user_id,
            )
            self.session.add(row)
            await self.session.flush()
            await self.session.refresh(row)
            return row

    # ── Batch ──────────────────────────────────────────────────────────

    async def triage_batch(
        self,
        clash_ids: list[uuid.UUID],
        *,
        user_id: uuid.UUID,
        max_concurrent: int = 4,
        force_refresh: bool = False,
        allowed_project_ids: set[uuid.UUID] | None = None,
    ) -> list[ClashTriageResult]:
        """‌⁠‍Triage ``clash_ids`` with bounded concurrency.

        The semaphore caps in-flight LLM calls at ``max_concurrent`` so a
        large batch cannot stampede the provider. Per-clash failures are
        logged and skipped - the method always returns whatever rows
        completed successfully.

        ``allowed_project_ids`` is forwarded to each per-clash worker as a
        defense-in-depth IDOR guard: a clash whose project is outside the set
        is skipped (treated as a per-clash failure) so a foreign id can never
        be triaged even if it reaches the service directly.

        Implementation note: SQLAlchemy ``AsyncSession`` instances are
        NOT concurrency-safe (only one flush at a time per session). So
        each batch worker is given its OWN short-lived session from
        ``async_session_factory`` - the LLM calls genuinely fan out in
        parallel and only the request-scoped ``self.session`` stays
        single-writer.
        """
        if not clash_ids:
            return []

        from app.database import async_session_factory

        semaphore = asyncio.Semaphore(max_concurrent)
        results_by_id: dict[uuid.UUID, ClashTriageResult] = {}

        async def _one(cid: uuid.UUID) -> None:
            async with semaphore:
                try:
                    async with async_session_factory() as worker_session:
                        worker_svc = ClashTriageService(worker_session)
                        row = await worker_svc.triage_clash(
                            cid,
                            user_id=user_id,
                            force_refresh=force_refresh,
                            allowed_project_ids=allowed_project_ids,
                        )
                        await worker_session.commit()
                        # Detach so the row stays usable outside the
                        # closed session.
                        worker_session.expunge(row)
                        results_by_id[cid] = row
                except ClashTriageUnavailable:
                    # Batch-wide configuration error (no AI provider key): no
                    # clash in the batch can succeed, so surface it. The router
                    # translates this to 503.
                    raise
                except Exception as exc:  # noqa: BLE001 - per-clash failure
                    # Per-clash failures (including a missing/not-found clash)
                    # are logged and skipped, per the method contract.
                    logger.warning("Batch triage skipped clash %s: %s", cid, exc)

        # ``return_exceptions=True`` so a single worker raising
        # ``ClashTriageUnavailable`` does not cancel the other in-flight
        # workers and discard rows that already completed. We surface the
        # config error afterwards (preserving the router's 503 path).
        gathered = await asyncio.gather(*[_one(cid) for cid in clash_ids], return_exceptions=True)
        for outcome in gathered:
            if isinstance(outcome, ClashTriageUnavailable):
                raise outcome
        # Preserve input order in the result list.
        return [results_by_id[cid] for cid in clash_ids if cid in results_by_id]

    # ── Replay (re-run with a different prompt version) ────────────────

    async def replay_with_new_prompt(
        self,
        triage_result_id: uuid.UUID,
        new_prompt_version: str | None = None,
        *,
        user_id: uuid.UUID,
    ) -> ClashTriageResult:
        """‌⁠‍Re-triage the clash behind an existing result row.

        Always writes a NEW row - the original audit trail is preserved.
        ``new_prompt_version`` defaults to the current ``PROMPT_VERSION``
        in the repo.
        """
        stmt = select(ClashTriageResult).where(ClashTriageResult.id == triage_result_id)
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            msg = f"Triage result {triage_result_id} not found"
            raise ClashSubjectNotFound(msg)
        # We always force a fresh call on replay - the WHOLE POINT is to
        # bypass the cache.
        target_version = (new_prompt_version or PROMPT_VERSION).strip() or PROMPT_VERSION
        # The replay records the new prompt_version it was run under, even
        # if the underlying templates string in this Python file isn't the
        # version the caller asked for - coordinators tune the file then
        # bump the version, so this column tracks intent, not git SHA.
        clash_id = existing.clash_id or existing.subject_id
        # Force the prompt_version stamp on the new row to ``target_version``
        # via a thin wrapper that temporarily overrides the constant.
        return await self._triage_with_explicit_prompt_version(clash_id, target_version, user_id=user_id)

    async def _triage_with_explicit_prompt_version(
        self,
        clash_id: uuid.UUID,
        prompt_version: str,
        *,
        user_id: uuid.UUID,
    ) -> ClashTriageResult:
        """Same as triage_clash but stamps a caller-supplied prompt_version.

        Used by ``replay_with_new_prompt`` so a replay against a tuned
        prompt is faithfully recorded even when the in-repo template
        string has not been updated (e.g. the caller pre-bumped the
        version while staging the edit).
        """
        clash = await self._load_clash(clash_id)
        subject_type, subject_id = await self._resolve_subject(clash)
        provider, api_key, model_override = await _resolve_provider_settings(self.session, user_id)
        model_name = model_override or _default_model_name_for(provider)
        evidence = _build_evidence_from_clash(clash)
        prior = await self._latest_prior(subject_id)
        user_prompt = build_user_prompt(evidence, prior=prior)
        try:
            async with asyncio.timeout(_LLM_CALL_TIMEOUT_S):
                text, tokens = await _call_llm_with_retry(
                    provider=provider,
                    api_key=api_key,
                    model=model_override,
                    user_prompt=user_prompt,
                )
        except TimeoutError as exc:
            msg = (
                f"LLM call exceeded {_LLM_CALL_TIMEOUT_S:.0f}s on provider "
                f"{provider} model={model_name}; replay aborted."
            )
            raise ClashTriageUnavailable(msg) from exc
        verdict = _coerce_verdict(extract_json(text) or _try_fence_extract(text))
        if verdict is None:
            verdict = TriageVerdict(
                category="unclear",
                confidence=0.0,
                severity_suggested="medium",
                explanation=("LLM returned non-JSON response after retry. See raw_response for the original output."),
                suggested_action=None,
                model_evidence_used=[],
            )
        cost_estimate = _estimate_cost_usd(model_name, int(tokens or 0))
        logger.info(
            "clash_triage.llm_call",
            extra={
                "event": "clash_triage.llm_call",
                "provider": provider,
                "model": model_name,
                "prompt_version": prompt_version,
                "tokens_used": int(tokens or 0),
                "cost_usd_estimate": float(cost_estimate),
                "user_id": str(user_id),
                "clash_id": str(clash.id),
                "subject_type": subject_type,
                "subject_id": str(subject_id),
                "verdict_category": verdict.category,
                "replay": True,
            },
        )
        row = ClashTriageResult(
            subject_type=subject_type,
            subject_id=subject_id,
            clash_id=clash.id,
            model_name=model_name,
            prompt_version=prompt_version,
            category=verdict.category,
            confidence=float(verdict.confidence),
            severity_suggested=verdict.severity_suggested,
            explanation=verdict.explanation,
            suggested_action=verdict.suggested_action,
            model_evidence_used=list(verdict.model_evidence_used or []),
            raw_prompt=user_prompt,
            raw_response=text,
            tokens_used=int(tokens or 0),
            cost_usd_estimate=float(cost_estimate),
            created_by_user_id=user_id,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    # ── History ────────────────────────────────────────────────────────

    async def list_history(
        self,
        clash_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ClashTriageResult], int]:
        """Return (rows, total) for the clash's triage history, newest first."""
        page = max(page, 1)
        page_size = max(min(page_size, 200), 1)
        # Match by clash_id OR subject_id so issue-promoted triages still
        # appear when the caller asks for "history for clash X".
        from sqlalchemy import func, or_

        filter_clause = or_(
            ClashTriageResult.clash_id == clash_id,
            ClashTriageResult.subject_id == clash_id,
        )
        total_q = select(func.count(ClashTriageResult.id)).where(filter_clause)
        total = int((await self.session.execute(total_q)).scalar_one() or 0)

        rows_q = (
            select(ClashTriageResult)
            .where(filter_clause)
            .order_by(ClashTriageResult.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list((await self.session.execute(rows_q)).scalars().all())
        return rows, total


# ── LLM call wrapper (retry + JSON-only follow-up) ──────────────────────────


def _default_model_name_for(provider: str) -> str:
    """Return the model name we'd LIKE to record when the user did not override."""
    # Lazy import to avoid a circular at module-load time.
    from app.modules.ai.ai_client import DEFAULT_MODELS

    return DEFAULT_MODELS.get(provider, provider)


def _try_fence_extract(text: str) -> Any:
    """Last-ditch JSON extraction from markdown code fences.

    ``extract_json`` already handles markdown fences but only succeeds
    when the fenced content is valid top-level JSON. This helper handles
    the slightly-broken case where the LLM wrapped JSON in a fence AND
    added trailing commentary - common with some models on the first
    call.
    """
    if not text:
        return None
    match = _JSON_FENCE_RE.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


async def _call_llm_with_retry(
    provider: str,
    api_key: str,
    model: str | None,
    user_prompt: str,
) -> tuple[str, int]:
    """Call the LLM, retrying once with a JSON-only follow-up on parse failure.

    Returns the LATEST attempt's text + total tokens (sum across attempts).
    """
    text, tokens = await call_ai(
        provider=provider,
        api_key=api_key,
        system=SYSTEM_PROMPT_V1,
        prompt=user_prompt,
        model=model,
        max_tokens=1024,
    )
    parsed = extract_json(text) or _try_fence_extract(text)
    if isinstance(parsed, dict):
        return text, int(tokens or 0)
    # Retry - combine the original prompt + the retry directive so the
    # model has the clash context AND the new constraint in the same call.
    retry_prompt = f"{user_prompt}\n\n---\n{RETRY_PROMPT_V1}\n\nYour previous answer was:\n{text[:1000]}"
    text2, tokens2 = await call_ai(
        provider=provider,
        api_key=api_key,
        system=SYSTEM_PROMPT_V1,
        prompt=retry_prompt,
        model=model,
        max_tokens=1024,
    )
    return text2, int((tokens or 0) + (tokens2 or 0))


__all__ = [
    "ClashSubjectNotFound",
    "ClashTriageError",
    "ClashTriageService",
    "ClashTriageUnavailable",
    "DEFAULT_COST_PER_1K",
    "MODEL_COSTS",
    "_LLM_CALL_TIMEOUT_S",
    "_coerce_verdict",
    "_estimate_cost_usd",
]
