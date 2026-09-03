# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Comms Intelligence business logic.

The pipeline per message: heuristics always (pure stdlib, free), then an
optional LLM pass that merges OVER the heuristic floor - the model can
sharpen a verdict but a parse failure can never lose the cheap facts.
Suggestions only touch the correspondence row through
:func:`confirm_analysis`, after a person chose what to apply.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.pricing import estimate_cost_usd
from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model
from app.modules.ai.repository import AISettingsRepository
from app.modules.comms_intelligence import heuristics
from app.modules.comms_intelligence.models import CommsAnalysis, CommsDraft
from app.modules.comms_intelligence.prompts import (
    ANALYSIS_RETRY_PROMPT,
    ANALYSIS_SYSTEM_PROMPT,
    CHASER_TEMPLATE_BODY,
    PROMPT_VERSION,
    REPLY_SYSTEM_PROMPT,
    REPLY_TEMPLATE_BODY,
    build_analysis_prompt,
    build_reply_prompt,
)
from app.modules.comms_intelligence.repository import (
    CommsAnalysisRepository,
)
from app.modules.comms_intelligence.schemas import AnalysisVerdict
from app.modules.correspondence.models import Correspondence

logger = logging.getLogger(__name__)

#: Wall-clock bound for the analysis LLM pair (initial + retry) - same
#: rationale and figure as clash_ai_triage: a bad-day provider must not
#: pin a worker for minutes.
_LLM_CALL_TIMEOUT_S: float = 180.0

#: "Due soon" horizon for the dashboard, in days.
_DUE_SOON_DAYS = 3


class CommsIntelligenceError(Exception):
    """Base class - the router translates subclasses to HTTP statuses."""


class CorrespondenceNotFound(CommsIntelligenceError):
    """The correspondence id does not exist."""


class AnalysisNotFound(CommsIntelligenceError):
    """The analysis id does not exist."""


class AnalysisAlreadyReviewed(CommsIntelligenceError):
    """Confirm/dismiss called on a row that is no longer ``suggested``."""


class AIUnavailable(CommsIntelligenceError):
    """No AI provider configured for the current user."""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def _load_correspondence(session: AsyncSession, correspondence_id: str) -> Correspondence:
    try:
        cid = uuid.UUID(str(correspondence_id))
    except (ValueError, AttributeError) as exc:
        raise CorrespondenceNotFound(str(correspondence_id)) from exc
    row = (await session.execute(select(Correspondence).where(Correspondence.id == cid))).scalar_one_or_none()
    if row is None:
        raise CorrespondenceNotFound(str(correspondence_id))
    return row


async def _rfi_candidates(session: AsyncSession, project_id: uuid.UUID) -> list[dict[str, str]]:
    """Open RFIs the model may link to. Empty when oe_rfi is absent.

    oe_rfi is an optional dependency - import inside the function so the
    module keeps loading on installs without it (the loader only
    guarantees hard ``depends``).
    """
    try:
        from app.modules.rfi.models import RFI
    except ImportError:  # pragma: no cover - optional module absent
        return []
    try:
        stmt = (
            select(RFI)
            .where(RFI.project_id == project_id)
            .where(RFI.status.notin_(("closed", "responded")))
            .order_by(RFI.rfi_number)
            .limit(30)
        )
        rows = (await session.execute(stmt)).scalars().all()
    except Exception:  # noqa: BLE001 - table may pre-date the module's migration
        logger.debug("RFI candidate lookup failed", exc_info=True)
        return []
    return [{"id": str(r.id), "rfi_number": r.rfi_number or "", "subject": (r.subject or "")[:120]} for r in rows]


def _correspondence_body(row: Correspondence) -> str:
    """The best body text we hold for a register entry.

    Hand-entered records carry their text in ``notes``; captured inbound
    messages additionally store the normalised envelope under metadata -
    prefer the notes (the full body) and fall back to the envelope.
    """
    if row.notes:
        return row.notes
    meta = row.metadata_ or {}
    envelope = meta.get("inbound_capture") or {}
    if isinstance(envelope, dict):
        body = envelope.get("body")
        if isinstance(body, str) and body:
            return body
    return ""


async def project_id_of_correspondence(session: AsyncSession, correspondence_id: str) -> uuid.UUID:
    """The owning project of a correspondence record, for access checks
    BEFORE any pipeline work runs."""
    row = await _load_correspondence(session, correspondence_id)
    return row.project_id


# ── Analysis ─────────────────────────────────────────────────────────────


async def analyze_correspondence(
    session: AsyncSession,
    correspondence_id: str,
    *,
    use_ai: bool = True,
    user_id: uuid.UUID | None = None,
) -> CommsAnalysis:
    """Run (or re-run) the enrichment pipeline for one register entry.

    Heuristics always run. The AI pass runs only when ``use_ai`` is true
    AND the calling user has a provider key in Settings > AI; with no key
    the verdict is stored as heuristic-only rather than failing - the
    module degrades gracefully (platform precedent, e.g. inbound_email).

    Never called automatically with ``use_ai=True``: auto-analysis from
    the event bus is heuristic-only, so a busy inbox can not silently
    spend the user's AI budget (tokens are spent on explicit request).
    """
    row = await _load_correspondence(session, correspondence_id)
    subject = row.subject or ""
    body = _correspondence_body(row)

    heuristic_raw = heuristics.analyze_text(subject, body)
    verdict = AnalysisVerdict.model_validate(heuristic_raw)
    source = "heuristic"
    model_name = ""
    raw_response = ""
    tokens_used = 0

    if use_ai and user_id is not None:
        ai_settings = await AISettingsRepository(session).get_by_user_id(user_id)
        try:
            provider, api_key, model_override = resolve_provider_key_model(ai_settings)
        except ValueError as exc:
            raise AIUnavailable(
                "No AI provider configured - add an API key in Settings > AI, "
                "or re-run with use_ai=false for the keyword-only analysis."
            ) from exc

        candidates = await _rfi_candidates(session, row.project_id)
        prompt = build_analysis_prompt(
            reference_number=row.reference_number or "",
            direction=row.direction or "",
            correspondence_type=row.correspondence_type or "",
            subject=subject,
            body=body,
            heuristic_verdict=heuristic_raw,
            rfi_candidates=candidates,
        )
        ai_verdict, raw_response, tokens_used, model_name = await _call_analysis_llm(
            provider=provider, api_key=api_key, model=model_override, prompt=prompt
        )
        if ai_verdict is not None:
            verdict = _merge_verdicts(heuristic=verdict, ai=ai_verdict, candidates=candidates)
            source = "ai"
        # else: keep the heuristic verdict; raw_response is the receipt of
        # the failed parse so the reviewer can see what the model said.

    repo = CommsAnalysisRepository(session)
    analysis = await repo.get_for_correspondence(str(row.id))
    if analysis is None:
        analysis = CommsAnalysis(project_id=row.project_id, correspondence_id=str(row.id))
        session.add(analysis)

    analysis.reference_number = row.reference_number or ""
    analysis.category = verdict.category
    analysis.confidence = float(verdict.confidence)
    analysis.summary = verdict.summary
    analysis.extracted = verdict.extracted.model_dump()
    analysis.suggestions = verdict.suggestions.model_dump()
    analysis.reply_needed = bool(verdict.reply_needed)
    # Re-analysis reopens review: the person is judging the NEW verdict.
    analysis.status = "suggested"
    analysis.reviewed_by = None
    analysis.reviewed_at = None
    analysis.applied = {}
    analysis.source = source
    analysis.model_name = model_name
    analysis.prompt_version = PROMPT_VERSION
    analysis.raw_response = raw_response
    analysis.tokens_used = tokens_used
    analysis.cost_usd_estimate = float(estimate_cost_usd(model_name, tokens_used)) if model_name else 0.0
    analysis.created_by = str(user_id) if user_id else None
    await session.flush()

    await _safe_publish(
        "comms_intelligence.analysis.suggested",
        {
            "project_id": str(row.project_id),
            "correspondence_id": str(row.id),
            "analysis_id": str(analysis.id),
            "category": analysis.category,
            "confidence": analysis.confidence,
        },
    )
    return analysis


async def _call_analysis_llm(
    *, provider: str, api_key: str, model: str | None, prompt: str
) -> tuple[AnalysisVerdict | None, str, int, str]:
    """One analysis call with one format-reminder retry.

    Returns ``(verdict_or_None, raw_response, tokens_used, model_name)``.
    Provider errors are caught and reported as a parse failure - the
    caller stores the heuristic verdict either way.
    """
    model_name = model or ""
    total_tokens = 0
    text = ""
    try:
        async with asyncio.timeout(_LLM_CALL_TIMEOUT_S):
            text, tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=ANALYSIS_SYSTEM_PROMPT,
                prompt=prompt,
                model=model,
                max_tokens=2048,
            )
            total_tokens += int(tokens or 0)
            parsed = extract_json(text)
            if not isinstance(parsed, dict):
                text, tokens = await call_ai(
                    provider=provider,
                    api_key=api_key,
                    system=ANALYSIS_SYSTEM_PROMPT,
                    prompt=f"{prompt}\n\n{ANALYSIS_RETRY_PROMPT}",
                    model=model,
                    max_tokens=2048,
                )
                total_tokens += int(tokens or 0)
                parsed = extract_json(text)
    except (TimeoutError, Exception) as exc:  # noqa: BLE001 - provider/network errors degrade, never raise
        logger.warning("Comms analysis LLM call failed: %s", exc)
        return None, f"[LLM call failed: {exc}]", total_tokens, model_name
    if not isinstance(parsed, dict):
        return None, text, total_tokens, model_name
    try:
        return AnalysisVerdict.model_validate(parsed), text, total_tokens, model_name
    except Exception:  # noqa: BLE001 - schema mismatch is a model failure, not ours
        logger.debug("Comms analysis verdict coercion failed", exc_info=True)
        return None, text, total_tokens, model_name


def _merge_verdicts(
    *, heuristic: AnalysisVerdict, ai: AnalysisVerdict, candidates: list[dict[str, str]]
) -> AnalysisVerdict:
    """AI verdict wins, but heuristic facts it dropped are folded back in.

    The model saw the heuristic findings in its prompt; when it omits a
    price or reference the regex found VERBATIM in the text, that is a
    miss, not a correction - regexes do not hallucinate.
    """
    merged = ai.model_copy(deep=True)

    have_amounts = {p.amount for p in merged.extracted.prices}
    merged.extracted.prices.extend(p for p in heuristic.extracted.prices if p.amount not in have_amounts)
    # The package price and reply-kind feed the QUOTE GATE counting, so the
    # deterministic scanner's verdicts are never displaced by a model guess:
    # the price only upgrades (model silent → keep ours), the kind is ALWAYS
    # the scanner's - one definition on every surface.
    if merged.extracted.package_price is None:
        merged.extracted.package_price = heuristic.extracted.package_price
    if not merged.extracted.lead_time:
        merged.extracted.lead_time = heuristic.extracted.lead_time
    merged.extracted.reply_kind = heuristic.extracted.reply_kind
    have_refs = set(merged.extracted.reference_numbers)
    merged.extracted.reference_numbers.extend(r for r in heuristic.extracted.reference_numbers if r not in have_refs)
    if merged.extracted.quote_number is None:
        merged.extracted.quote_number = heuristic.extracted.quote_number
    if merged.extracted.dates.response_requested_by is None:
        merged.extracted.dates.response_requested_by = heuristic.extracted.dates.response_requested_by
    merged.reply_needed = merged.reply_needed or heuristic.reply_needed

    # Fence: only accept a link id that was actually offered as a candidate.
    valid_ids = {c["id"] for c in candidates}
    if merged.suggestions.link_rfi_id and merged.suggestions.link_rfi_id not in valid_ids:
        merged.suggestions.link_rfi_id = None
    return merged


# ── Review (confirm / dismiss) ───────────────────────────────────────────


async def confirm_analysis(
    session: AsyncSession,
    analysis_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    apply_status: bool = True,
    apply_response_required_by: bool = True,
    apply_link_rfi: bool = True,
    apply_type: bool = False,
) -> CommsAnalysis:
    """Apply the reviewer-selected suggestions to the correspondence row.

    THE one place this module mutates another module's data, and it only
    runs on an explicit authenticated request - the AI-augmented,
    human-confirmed rule is enforced here, not merely documented.
    """
    analysis = await CommsAnalysisRepository(session).get_by_id(analysis_id)
    if analysis is None:
        raise AnalysisNotFound(str(analysis_id))
    if analysis.status != "suggested":
        raise AnalysisAlreadyReviewed(analysis.status)

    row = await _load_correspondence(session, analysis.correspondence_id)
    suggestions = analysis.suggestions or {}
    applied: dict[str, Any] = {}

    if apply_status and suggestions.get("set_status"):
        row.status = suggestions["set_status"]
        applied["set_status"] = suggestions["set_status"]
    if apply_response_required_by and suggestions.get("response_required_by"):
        row.response_required_by = suggestions["response_required_by"]
        applied["response_required_by"] = suggestions["response_required_by"]
    if apply_link_rfi and suggestions.get("link_rfi_id"):
        row.linked_rfi_id = suggestions["link_rfi_id"]
        applied["link_rfi_id"] = suggestions["link_rfi_id"]
    if apply_type and suggestions.get("correspondence_type"):
        row.correspondence_type = suggestions["correspondence_type"]
        applied["correspondence_type"] = suggestions["correspondence_type"]

    # File the extracted facts on the record itself so every consumer of
    # correspondence metadata (search, exports) sees them - namespaced
    # under this module's key, never clobbering foreign keys in the blob.
    meta = dict(row.metadata_ or {})
    meta["comms_intelligence"] = {
        "category": analysis.category,
        "confidence": analysis.confidence,
        "extracted": analysis.extracted,
        "confirmed_by": str(user_id),
        "confirmed_at": _utc_now_iso(),
    }
    row.metadata_ = meta

    analysis.status = "confirmed"
    analysis.reviewed_by = str(user_id)
    analysis.reviewed_at = _utc_now_iso()
    analysis.applied = applied
    await session.flush()

    # Publish the same lifecycle event the correspondence service emits on
    # its own updates so the vector indexer re-embeds the enriched row.
    await _safe_publish(
        "correspondence.updated",
        {
            "project_id": str(row.project_id),
            "correspondence_id": str(row.id),
            "reference_number": row.reference_number,
        },
    )
    await _safe_publish(
        "comms_intelligence.analysis.confirmed",
        {
            "project_id": str(row.project_id),
            "correspondence_id": str(row.id),
            "analysis_id": str(analysis.id),
            "applied": applied,
        },
    )
    return analysis


async def dismiss_analysis(session: AsyncSession, analysis_id: uuid.UUID, *, user_id: uuid.UUID) -> CommsAnalysis:
    analysis = await CommsAnalysisRepository(session).get_by_id(analysis_id)
    if analysis is None:
        raise AnalysisNotFound(str(analysis_id))
    if analysis.status != "suggested":
        raise AnalysisAlreadyReviewed(analysis.status)
    analysis.status = "dismissed"
    analysis.reviewed_by = str(user_id)
    analysis.reviewed_at = _utc_now_iso()
    await session.flush()
    await _safe_publish(
        "comms_intelligence.analysis.dismissed",
        {
            "project_id": str(analysis.project_id),
            "correspondence_id": analysis.correspondence_id,
            "analysis_id": str(analysis.id),
        },
    )
    return analysis


# ── Drafts (replies and chase-ups) ───────────────────────────────────────


async def create_draft(
    session: AsyncSession,
    correspondence_id: str,
    *,
    kind: str,
    instructions: str = "",
    use_ai: bool = True,
    user_id: uuid.UUID | None = None,
) -> CommsDraft:
    """Draft a reply or chase-up for a register entry.

    AI path needs a provider key; the template path always works and is
    visibly skeletal so nobody sends it unread. The module never sends
    mail - a draft is text for a person to take to their mail client.
    """
    row = await _load_correspondence(session, correspondence_id)
    subject = row.subject or ""
    ref = row.reference_number or ""

    body_text = ""
    draft_subject = f"RE: {subject}" if subject else f"RE: {ref}"
    confidence = 0.0
    source = "template"
    model_name = ""
    tokens_used = 0

    if use_ai and user_id is not None:
        ai_settings = await AISettingsRepository(session).get_by_user_id(user_id)
        try:
            provider, api_key, model_override = resolve_provider_key_model(ai_settings)
        except ValueError as exc:
            raise AIUnavailable(
                "No AI provider configured - add an API key in Settings > AI, "
                "or re-run with use_ai=false for a fill-in template."
            ) from exc

        analysis = await CommsAnalysisRepository(session).get_for_correspondence(str(row.id))
        steer = instructions
        if kind == "chaser":
            due = row.response_required_by or "the requested date"
            steer = (
                f"This is a CHASE-UP: our {ref} requested a response by {due} and none was "
                f"received. Firm but courteous; reserve our position on delay. {instructions}"
            ).strip()
        prompt = build_reply_prompt(
            reference_number=ref,
            subject=subject,
            body=_correspondence_body(row),
            analysis_summary=(analysis.summary if analysis else ""),
            instructions=steer,
        )
        try:
            async with asyncio.timeout(_LLM_CALL_TIMEOUT_S):
                text, tokens = await call_ai(
                    provider=provider,
                    api_key=api_key,
                    system=REPLY_SYSTEM_PROMPT,
                    prompt=prompt,
                    model=model_override,
                    max_tokens=1500,
                )
            tokens_used = int(tokens or 0)
            parsed = extract_json(text)
            if isinstance(parsed, dict) and isinstance(parsed.get("body"), str) and parsed["body"].strip():
                body_text = parsed["body"].strip()
                if isinstance(parsed.get("subject"), str) and parsed["subject"].strip():
                    draft_subject = parsed["subject"].strip()[:500]
                try:
                    confidence = min(1.0, max(0.0, float(parsed.get("confidence", 0.5))))
                except (TypeError, ValueError):
                    confidence = 0.5
                source = "ai"
                model_name = model_override or ""
        except Exception as exc:  # noqa: BLE001 - degrade to template on any provider failure
            logger.warning("Comms draft LLM call failed, using template: %s", exc)

    if not body_text:
        template = CHASER_TEMPLATE_BODY if kind == "chaser" else REPLY_TEMPLATE_BODY
        body_text = template.format(
            recipient="[RECIPIENT]",
            reference_number=ref or "[REF]",
            subject=subject or "[SUBJECT]",
            due_date=row.response_required_by or "[DUE DATE]",
        )

    draft = CommsDraft(
        project_id=row.project_id,
        correspondence_id=str(row.id),
        kind=kind,
        subject=draft_subject,
        body=body_text,
        confidence=confidence,
        source=source,
        model_name=model_name,
        tokens_used=tokens_used,
        created_by=str(user_id) if user_id else None,
    )
    session.add(draft)
    await session.flush()
    await _safe_publish(
        "comms_intelligence.draft.created",
        {
            "project_id": str(row.project_id),
            "correspondence_id": str(row.id),
            "draft_id": str(draft.id),
            "kind": kind,
            "source": source,
        },
    )
    return draft


# ── Dashboard ────────────────────────────────────────────────────────────


def _days_until(iso_date: str | None, today: date) -> int | None:
    if not iso_date:
        return None
    try:
        due = date.fromisoformat(iso_date[:10])
    except ValueError:
        return None
    return (due - today).days


async def dashboard(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    """Aggregate the who-owes-whom picture for one project.

    Reads correspondence directly (read-only) plus this module's own
    analysis rows; nothing here mutates state.
    """
    today = date.today()

    corr_rows = (
        (
            await session.execute(
                select(Correspondence)
                .where(Correspondence.project_id == project_id)
                .where(Correspondence.status.in_(("open", "awaiting_response")))
                .order_by(Correspondence.response_required_by)
            )
        )
        .scalars()
        .all()
    )

    analyses = await CommsAnalysisRepository(session).list_for_project(project_id, limit=500)
    by_correspondence = {a.correspondence_id: a for a in analyses}

    def entry(row: Correspondence) -> dict[str, Any]:
        a = by_correspondence.get(str(row.id))
        return {
            "correspondence_id": str(row.id),
            "reference_number": row.reference_number or "",
            "subject": row.subject or "",
            "direction": row.direction or "",
            "status": row.status or "",
            "response_required_by": row.response_required_by,
            "days_until_due": _days_until(row.response_required_by, today),
            "from_contact_id": row.from_contact_id,
            "category": a.category if a else None,
            "confidence": a.confidence if a else None,
        }

    overdue: list[dict[str, Any]] = []
    due_soon: list[dict[str, Any]] = []
    awaiting: list[dict[str, Any]] = []
    for row in corr_rows:
        e = entry(row)
        days = e["days_until_due"]
        if days is not None and days < 0:
            overdue.append(e)
        elif days is not None and days <= _DUE_SOON_DAYS:
            due_soon.append(e)
        elif row.status == "awaiting_response":
            awaiting.append(e)

    pending_review = (
        await session.execute(
            select(func.count())
            .select_from(CommsAnalysis)
            .where(CommsAnalysis.project_id == project_id)
            .where(CommsAnalysis.status == "suggested")
        )
    ).scalar_one()

    reply_needed = (
        await session.execute(
            select(func.count())
            .select_from(CommsAnalysis)
            .where(CommsAnalysis.project_id == project_id)
            .where(CommsAnalysis.reply_needed.is_(True))
            .where(CommsAnalysis.status != "dismissed")
        )
    ).scalar_one()

    categories: dict[str, int] = {}
    for a in analyses:
        if a.status != "dismissed":
            categories[a.category] = categories.get(a.category, 0) + 1

    return {
        "project_id": project_id,
        "pending_review": int(pending_review or 0),
        "reply_needed": int(reply_needed or 0),
        "overdue": overdue,
        "due_soon": due_soon,
        "awaiting_response": awaiting,
        "categories": categories,
    }


# ── Event plumbing ───────────────────────────────────────────────────────


async def _safe_publish(name: str, data: dict, source_module: str = "oe_comms_intelligence") -> None:
    """Best-effort detached publish - an event-bus hiccup never breaks the
    business path (platform convention, see correspondence.service)."""
    try:
        from app.core.events import event_bus

        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:  # noqa: BLE001
        logger.debug("Event publish skipped: %s", name)
