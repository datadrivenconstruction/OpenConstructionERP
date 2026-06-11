"""‌⁠‍AI Estimation service - business logic for AI-powered BOQ generation.

Stateless service layer. Handles:
- Per-user AI settings (get, create, update)
- Quick text-based estimation (description -> AI -> BOQ items)
- Photo-based estimation (image -> AI Vision -> BOQ items)
- Creating real BOQ from AI estimate results
- Job tracking with status, timing, and token usage
"""

import base64
import logging
import math
import time
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.pricing import estimate_cost_usd
from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate

_logger_ev = __import__("logging").getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model
from app.modules.ai.models import AIEstimateJob, AISettings
from app.modules.ai.prompts import (
    CAD_IMPORT_PROMPT,
    PHOTO_ESTIMATE_PROMPT,
    SMART_IMPORT_PROMPT,
    SMART_IMPORT_VISION_PROMPT,
    SYSTEM_PROMPT,
    TEXT_ESTIMATE_PROMPT,
    fence_user_content,
    sanitize_user_text,
)
from app.modules.ai.repository import AIEstimateJobRepository, AISettingsRepository
from app.modules.ai.schemas import (
    AISettingsResponse,
    AISettingsUpdate,
    CreateBOQFromEstimateRequest,
    EstimateItem,
    EstimateJobListResponse,
    EstimateJobResponse,
    EstimateJobSummary,
    QuickEstimateRequest,
)

logger = logging.getLogger(__name__)


async def _resolve_project_currency(
    session: AsyncSession,
    project_id: uuid.UUID | None,
) -> str:
    """Look up the project's default currency.

    Returns empty string when no project_id is supplied or the project is
    missing - callers fall back to a literal default for prompt rendering.
    Inline import keeps the AI module decoupled from projects at module level.
    """
    if project_id is None:
        return ""
    from sqlalchemy import select

    from app.modules.projects.models import Project

    project = (await session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        return ""
    return project.currency or ""


def _coerce_confidence(value: Any) -> float | None:
    """Coerce a model-supplied confidence to a float in [0, 1], else None.

    The AI may emit a per-item ``confidence`` (0..1, or 0..100 percent). We
    only keep a value we can trust as a real score; anything missing or
    out-of-range returns None so the position stores no fake confidence.
    """
    if value is None:
        return None
    try:
        conf = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(conf):
        return None
    # Only treat a value clearly in the percentage band (>2, up to 100) as a
    # percentage. A value like 1.5 is neither a valid probability nor a
    # plausible percentage confidence, so it must fall through to the
    # out-of-range guard and return None rather than be mangled into a fake
    # 0.015 by an unconditional ``/100``.
    if 2.0 < conf <= 100.0:
        conf = conf / 100.0
    if conf < 0.0 or conf > 1.0:
        return None
    return round(conf, 2)


# ── Photo defect-category suggestion (Lane 7) ────────────────────────────
#
# The set of categories the photo gallery understands. Kept in sync with
# ``VALID_PHOTO_CATEGORIES`` in documents/service.py - duplicated here on
# purpose so the AI module stays import-decoupled from documents.
PHOTO_CATEGORIES: tuple[str, ...] = ("site", "progress", "defect", "delivery", "safety", "other")

# Deterministic keyword → category map used when no AI provider is
# configured. Ordered most-specific first; the first category whose keyword
# matches the combined text (filename + caption + tags) wins. This is a
# transparent, explainable heuristic - never a fabricated AI score.
_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "defect",
        (
            "defect",
            "crack",
            "damage",
            "damaged",
            "leak",
            "leakage",
            "rust",
            "corrosion",
            "snag",
            "snagging",
            "fault",
            "broken",
            "spall",
            "mould",
            "mold",
            "stain",
            "deficien",
            "punch",
            "rework",
            "mangel",
            "riss",
            "schaden",
            "defaut",
            "fissure",
            "defecto",
        ),
    ),
    (
        "safety",
        (
            "safety",
            "hazard",
            "ppe",
            "helmet",
            "harness",
            "guardrail",
            "scaffold",
            "fall",
            "fire",
            "extinguisher",
            "first aid",
            "danger",
            "warning",
            "barrier",
            "sicherheit",
            "gefahr",
            "securite",
        ),
    ),
    (
        "delivery",
        (
            "delivery",
            "delivered",
            "shipment",
            "pallet",
            "truck",
            "unload",
            "material",
            "rebar bundle",
            "lieferung",
            "livraison",
            "entrega",
        ),
    ),
    (
        "progress",
        (
            "progress",
            "pour",
            "poured",
            "concrete",
            "formwork",
            "rebar",
            "installed",
            "erection",
            "framing",
            "milestone",
            "wip",
            "fortschritt",
            "avancement",
            "progreso",
        ),
    ),
    (
        "site",
        ("site", "overview", "aerial", "general", "panorama", "baustelle", "chantier"),
    ),
)


# Defect keywords ranked by how serious the visible problem usually is, so a
# text-only heuristic can still offer an ADVISORY severity (low/medium/high)
# when no vision model is configured. This is intentionally conservative - it
# is a hint the user confirms, never an auto-applied rating.
_DEFECT_SEVERITY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "high",
        (
            "structural",
            "collapse",
            "spall",
            "corrosion",
            "rust",
            "leak",
            "leakage",
            "broken",
            "schaden",
            "fissure",
        ),
    ),
    (
        "medium",
        ("crack", "damage", "damaged", "fault", "riss", "defaut", "defecto", "deficien"),
    ),
    (
        "low",
        ("snag", "snagging", "stain", "mould", "mold", "punch", "rework", "mangel"),
    ),
)


def heuristic_photo_category(
    *,
    filename: str = "",
    caption: str = "",
    tags: list[str] | None = None,
) -> tuple[str, float] | None:
    """Deterministically guess a photo category from textual signals.

    Returns ``(category, confidence)`` or ``None`` when nothing matches.
    The confidence is a fixed, honest "this is a keyword match" score -
    NOT an AI probability - so the UI can clearly label it as a heuristic.
    """
    parts = [filename or "", caption or ""]
    parts.extend(tags or [])
    text = " ".join(parts).lower()
    if not text.strip():
        return None
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in text for kw in keywords):
            return category, 0.55
    return None


def heuristic_photo_suggestion(
    *,
    filename: str = "",
    caption: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any] | None:
    """Richer heuristic suggestion dict, mirroring the AI path's shape.

    Builds on :func:`heuristic_photo_category` and, for a ``defect`` match,
    additionally derives an advisory ``defect_severity`` and the matched
    keywords as ``suggested_tags`` from the same textual signal - so the
    severity and auto-tag chips work even with no vision model configured.
    Everything here is a hint the user confirms; nothing is auto-applied.

    Returns ``{suggested_category, confidence, source="heuristic", ...}`` or
    ``None`` when nothing matches.
    """
    base = heuristic_photo_category(filename=filename, caption=caption, tags=tags)
    if base is None:
        return None
    category, confidence = base
    result: dict[str, Any] = {
        "suggested_category": category,
        "confidence": confidence,
        "source": "heuristic",
    }
    if category != "defect":
        return result

    text = " ".join([filename or "", caption or "", *(tags or [])]).lower()
    # Auto-tags: the defect keywords actually present, normalised + de-duped.
    defect_keywords = next((kw for cat, kw in _CATEGORY_KEYWORDS if cat == "defect"), ())
    matched: list[str] = []
    for kw in defect_keywords:
        if kw in text and kw not in matched:
            matched.append(kw)
    if matched:
        result["suggested_tags"] = matched[:6]
    # Advisory severity from the highest-tier severity keyword present.
    for severity, sev_keywords in _DEFECT_SEVERITY_KEYWORDS:
        if any(kw in text for kw in sev_keywords):
            result["defect_severity"] = severity
            break
    return result


def _coerce_suggested_category(value: Any) -> str | None:
    """Normalise an AI-returned category to the allowed set, else None."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned if cleaned in PHOTO_CATEGORIES else None


# Defect-severity levels surfaced for ``category == "defect"`` suggestions.
DEFECT_SEVERITIES: tuple[str, ...] = ("low", "medium", "high")


def _coerce_defect_severity(value: Any) -> str | None:
    """Normalise an AI-returned defect severity to the allowed set, else None."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned if cleaned in DEFECT_SEVERITIES else None


def _coerce_suggested_tags(value: Any, *, limit: int = 6) -> list[str]:
    """Normalise AI-returned auto-tags into a short, de-duplicated list.

    Tags are lower-cased, stripped, capped at ``limit`` items and 40 chars
    each. Non-list / empty input yields ``[]`` so the caller can store it
    unconditionally. The tags are advisory only - never auto-applied.
    """
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        tag = item.strip().lower()[:40]
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= limit:
            break
    return out


def _validate_items(raw_items: Any, currency: str = "") -> list[dict[str, Any]]:
    """‌⁠‍Validate and clean AI-generated work items.

    Filters out invalid entries, normalises fields, and computes totals.

    Args:
        raw_items: Parsed JSON (expected to be a list of dicts).
        currency: Resolved currency code the items are priced in. Stamped on
            every item so totals/rates are never displayed without an ISO
            currency (and never blended across currencies downstream).

    Returns:
        List of validated item dicts.
    """
    if not isinstance(raw_items, list):
        return []
    currency = (currency or "").strip()

    valid: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue

        description = str(item.get("description", "")).strip()
        if len(description) < 3:
            continue

        try:
            quantity = float(item.get("quantity", 0))
        except (ValueError, TypeError):
            quantity = 0.0

        try:
            unit_rate = float(item.get("unit_rate", 0))
        except (ValueError, TypeError):
            unit_rate = 0.0

        # Reject non-finite values up front. ``float("nan")``/``float("inf")``
        # parse cleanly and slip past the range checks below (every NaN
        # comparison is False), then poison BOQ quantity/total and break the
        # JSON serializers that reject non-finite floats.
        if not math.isfinite(quantity) or not math.isfinite(unit_rate):
            continue

        if quantity <= 0 or quantity > 10_000_000:
            continue
        if unit_rate < 0 or unit_rate > 100_000_000:
            continue

        unit = str(item.get("unit", "m2")).strip()
        if not unit:
            unit = "m2"

        category = str(item.get("category", "General")).strip()
        if not category:
            category = "General"

        ordinal = str(item.get("ordinal", "")).strip()
        if not ordinal:
            # Auto-generate ordinal
            section = (idx // 10) + 1
            position = (idx % 10) + 1
            ordinal = f"{section:02d}.01.{position:04d}"

        classification = item.get("classification", {})
        if not isinstance(classification, dict):
            classification = {}

        total = round(quantity * unit_rate, 2)

        item_out: dict[str, Any] = {
            "ordinal": ordinal,
            "description": description,
            "unit": unit,
            "quantity": round(quantity, 2),
            "unit_rate": round(unit_rate, 2),
            "total": total,
            "classification": classification,
            "category": category,
            "currency": currency,
        }
        # Carry a real per-item confidence only when the model supplied a
        # usable one - never fabricate a placeholder score.
        confidence = _coerce_confidence(item.get("confidence"))
        if confidence is not None:
            item_out["confidence"] = confidence
        valid.append(item_out)

    return valid


def _build_settings_response(settings: AISettings) -> AISettingsResponse:
    """‌⁠‍Build an AISettingsResponse from an AISettings ORM instance.

    A key is only reported as "set" when it is both present *and* decryptable
    with the current backend encryption key. If the ciphertext was written
    under a rotated JWT_SECRET the key is functionally useless - surfacing it
    as "configured" would make the Settings UI show "Key configured" while
    every chat/estimate call fails with a decrypt error.
    """
    from app.core.crypto import decrypt_secret
    from app.modules.ai.ai_client import DEFAULT_MODELS

    def _usable(value: Any) -> bool:
        return bool(decrypt_secret(value)) if value else False

    meta = settings.metadata_ or {}
    raw_overrides = meta.get("model_overrides") if isinstance(meta, dict) else None
    model_overrides: dict[str, str] = {}
    if isinstance(raw_overrides, dict):
        # Only surface non-empty string overrides.
        model_overrides = {str(k): str(v).strip() for k, v in raw_overrides.items() if isinstance(v, str) and v.strip()}

    # Pull the saved self-hosted endpoints (Ollama / vLLM) straight off metadata_.
    _meta_is_dict = isinstance(meta, dict)
    raw_ollama_base_url = meta.get("ollama_base_url") if _meta_is_dict else None
    raw_vllm_base_url = meta.get("vllm_base_url") if _meta_is_dict else None
    ollama_url = (
        str(raw_ollama_base_url).strip()
        if isinstance(raw_ollama_base_url, str) and raw_ollama_base_url.strip()
        else None
    )
    vllm_url = (
        str(raw_vllm_base_url).strip() if isinstance(raw_vllm_base_url, str) and raw_vllm_base_url.strip() else None
    )

    return AISettingsResponse(
        id=settings.id,
        user_id=settings.user_id,
        anthropic_api_key_set=_usable(settings.anthropic_api_key),
        openai_api_key_set=_usable(settings.openai_api_key),
        gemini_api_key_set=_usable(settings.gemini_api_key),
        kimi_api_key_set=_usable(getattr(settings, "kimi_api_key", None)),
        openrouter_api_key_set=_usable(settings.openrouter_api_key),
        mistral_api_key_set=_usable(settings.mistral_api_key),
        groq_api_key_set=_usable(settings.groq_api_key),
        deepseek_api_key_set=_usable(settings.deepseek_api_key),
        together_api_key_set=_usable(getattr(settings, "together_api_key", None)),
        fireworks_api_key_set=_usable(getattr(settings, "fireworks_api_key", None)),
        perplexity_api_key_set=_usable(getattr(settings, "perplexity_api_key", None)),
        cohere_api_key_set=_usable(getattr(settings, "cohere_api_key", None)),
        ai21_api_key_set=_usable(getattr(settings, "ai21_api_key", None)),
        xai_api_key_set=_usable(getattr(settings, "xai_api_key", None)),
        zhipu_api_key_set=_usable(getattr(settings, "zhipu_api_key", None)),
        baidu_api_key_set=_usable(getattr(settings, "baidu_api_key", None)),
        yandex_api_key_set=_usable(getattr(settings, "yandex_api_key", None)),
        gigachat_api_key_set=_usable(getattr(settings, "gigachat_api_key", None)),
        ollama_base_url=ollama_url,
        vllm_base_url=vllm_url,
        preferred_model=settings.preferred_model,
        model_overrides=model_overrides,
        default_models=dict(DEFAULT_MODELS),
        metadata_=settings.metadata_ or {},
        created_at=settings.created_at,
        updated_at=settings.updated_at,
    )


def _build_job_response(job: AIEstimateJob) -> EstimateJobResponse:
    """Build an EstimateJobResponse from an AIEstimateJob ORM instance."""
    from decimal import Decimal

    items: list[EstimateItem] = []
    grand_total: Decimal = Decimal("0")
    currency = ""

    if job.result and isinstance(job.result, list):
        for item_data in job.result:
            if not isinstance(item_data, dict):
                continue
            raw_conf = item_data.get("confidence")
            ei = EstimateItem(
                ordinal=str(item_data.get("ordinal", "")),
                description=str(item_data.get("description", "")),
                unit=str(item_data.get("unit", "m2")),
                quantity=float(item_data.get("quantity", 0)),
                unit_rate=Decimal(str(item_data.get("unit_rate", 0) or 0)),
                total=float(item_data.get("total", 0)),
                classification=item_data.get("classification", {}),
                category=str(item_data.get("category", "General")),
                confidence=float(raw_conf) if isinstance(raw_conf, (int, float)) else None,
            )
            items.append(ei)
            grand_total += Decimal(str(ei.total))
            # All items in a job share one resolved currency; take the first
            # non-empty one we see.
            if not currency:
                cur = item_data.get("currency")
                if isinstance(cur, str) and cur.strip():
                    currency = cur.strip()

    return EstimateJobResponse(
        id=job.id,
        user_id=job.user_id,
        project_id=job.project_id,
        input_type=job.input_type,
        input_text=job.input_text,
        input_filename=job.input_filename,
        status=job.status,
        items=items,
        currency=currency,
        error_message=job.error_message,
        model_used=job.model_used,
        tokens_used=job.tokens_used,
        duration_ms=job.duration_ms,
        cost_usd_estimate=Decimal(str(getattr(job, "cost_usd_estimate", 0.0) or 0.0)),
        grand_total=grand_total.quantize(Decimal("0.01")),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _build_job_summary(job: AIEstimateJob) -> EstimateJobSummary:
    """Build a lightweight history summary (no full items payload).

    Recomputes ``grand_total`` from the stored line totals and reads the
    resolved currency from the first priced line - the same contract as
    :func:`_build_job_response` but without echoing the per-item rows.
    """
    from decimal import Decimal

    grand_total: Decimal = Decimal("0")
    currency = ""
    items_count = 0
    if job.result and isinstance(job.result, list):
        for item_data in job.result:
            if not isinstance(item_data, dict):
                continue
            items_count += 1
            try:
                grand_total += Decimal(str(item_data.get("total", 0) or 0))
            except (ValueError, ArithmeticError):
                pass
            if not currency:
                cur = item_data.get("currency")
                if isinstance(cur, str) and cur.strip():
                    currency = cur.strip()

    return EstimateJobSummary(
        id=job.id,
        project_id=job.project_id,
        input_type=job.input_type,
        input_text=job.input_text,
        input_filename=job.input_filename,
        status=job.status,
        items_count=items_count,
        currency=currency,
        grand_total=grand_total.quantize(Decimal("0.01")),
        model_used=job.model_used,
        tokens_used=job.tokens_used,
        cost_usd_estimate=Decimal(str(getattr(job, "cost_usd_estimate", 0.0) or 0.0)),
        duration_ms=job.duration_ms,
        error_message=job.error_message,
        created_at=job.created_at,
    )


async def _match_cost_items(
    session: AsyncSession,
    *,
    description: str,
    item_unit: str,
    region: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Find cost-DB matches for one estimate line (vector first, text fallback).

    Returns a ranked list of ``{code, description, unit, rate, currency,
    region, score}`` dicts (best first). This is the single source of truth
    for both the ``/enrich`` endpoint preview and the persisted
    ``apply_enriched`` BOQ-creation path, so what the user sees matched in the
    table is exactly what gets saved. Degrades gracefully: a missing
    embedder / vector DB silently falls back to SQL keyword search, and any
    error yields an empty match list rather than raising.
    """
    from sqlalchemy import or_, select

    from app.modules.costs.models import CostItem

    matches: list[dict[str, Any]] = []

    # 1. Vector similarity search (best signal when the embedder is present).
    try:
        from app.core.vector import encode_texts, vector_search

        query_vec = encode_texts([description])[0]
        for m in vector_search(query_vec, region=region or None, limit=limit):
            matches.append(
                {
                    "code": m.get("code", ""),
                    "description": m.get("description", ""),
                    "unit": m.get("unit", ""),
                    "rate": float(m.get("rate", 0) or 0),
                    "currency": m.get("currency", ""),
                    "region": m.get("region", ""),
                    "score": float(m.get("score", 0) or 0),
                }
            )
    except Exception:
        logger.debug("Vector search unavailable for enrich; falling back to text", exc_info=True)

    # 2. Text keyword fallback (one OR query, optional region retry).
    if not matches:
        stop = {"the", "and", "for", "with", "from", "into", "per", "all"}
        keywords = [w for w in description.lower().split() if len(w) > 2 and w not in stop][:5]
        if keywords:
            try:
                conditions = [CostItem.description.ilike(f"%{kw}%") for kw in keywords]

                async def _kw_search(use_region: bool) -> list[CostItem]:
                    stmt = select(CostItem).where(CostItem.is_active.is_(True), or_(*conditions))
                    if use_region and region:
                        stmt = stmt.where(CostItem.region == region)
                    stmt = stmt.limit(15)
                    res = await session.execute(stmt)
                    return list(res.scalars().all())

                kw_results = await _kw_search(use_region=True)
                if not kw_results and region:
                    kw_results = await _kw_search(use_region=False)

                for ci in kw_results:
                    if any(m["code"] == ci.code for m in matches):
                        continue
                    desc_lower = (ci.description or "").lower()
                    kw_hits = sum(1 for k in keywords if k in desc_lower)
                    score = min(0.9, 0.3 + kw_hits * 0.15)
                    matches.append(
                        {
                            "code": ci.code,
                            "description": (ci.description or "")[:200],
                            "unit": ci.unit or "",
                            "rate": float(ci.rate) if ci.rate else 0.0,
                            "currency": ci.currency or "",
                            "region": ci.region or "",
                            "score": score,
                        }
                    )
            except Exception:
                logger.warning("Text search failed during enrich for %r", description[:40], exc_info=True)

    # 3. Prefer same-unit matches, then sort best-first and cap.
    if item_unit:
        for m in matches:
            if m["unit"].lower() == item_unit.lower():
                m["score"] = min(1.0, m["score"] + 0.05)
    matches.sort(key=lambda m: m["score"], reverse=True)
    return matches[:limit]


class AIService:
    """Business logic for AI estimation operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings_repo = AISettingsRepository(session)
        self.job_repo = AIEstimateJobRepository(session)

    # ── Settings operations ──────────────────────────────────────────────

    async def get_ai_settings(self, user_id: str) -> AISettingsResponse:
        """Get or create default AI settings for a user.

        Args:
            user_id: Current user's ID (string from JWT).

        Returns:
            AISettingsResponse with masked API keys.
        """
        uid = uuid.UUID(user_id)
        settings = await self.settings_repo.get_by_user_id(uid)

        if settings is None:
            # Create default settings for the user
            settings = AISettings(
                user_id=uid,
                preferred_model="claude-sonnet",
            )
            settings = await self.settings_repo.create(settings)
            logger.info("Created default AI settings for user %s", user_id)

        return _build_settings_response(settings)

    async def update_ai_settings(self, user_id: str, data: AISettingsUpdate) -> AISettingsResponse:
        """Update per-user AI settings (API keys, preferred model).

        Only updates fields that are explicitly provided (not None).

        Args:
            user_id: Current user's ID.
            data: Update payload.

        Returns:
            Updated AISettingsResponse.
        """
        uid = uuid.UUID(user_id)
        settings = await self.settings_repo.get_by_user_id(uid)

        # All API key field names that can be saved
        _API_KEY_FIELDS = [
            "anthropic_api_key",
            "openai_api_key",
            "gemini_api_key",
            "kimi_api_key",
            "openrouter_api_key",
            "mistral_api_key",
            "groq_api_key",
            "deepseek_api_key",
            "together_api_key",
            "fireworks_api_key",
            "perplexity_api_key",
            "cohere_api_key",
            "ai21_api_key",
            "xai_api_key",
            "zhipu_api_key",
            "baidu_api_key",
            "yandex_api_key",
            "gigachat_api_key",
        ]

        from app.core.crypto import encrypt_secret

        def _merge_overrides(
            existing_meta: Any,
            incoming: dict[str, str] | None,
        ) -> dict[str, Any]:
            """Merge model-id overrides into the metadata JSON blob.

            A blank/whitespace value for a provider clears that override
            (falls back to the built-in default). Returns the full new
            metadata dict (other metadata keys are preserved).
            """
            meta: dict[str, Any] = dict(existing_meta) if isinstance(existing_meta, dict) else {}
            current = meta.get("model_overrides")
            overrides: dict[str, str] = dict(current) if isinstance(current, dict) else {}
            for provider, model_id in (incoming or {}).items():
                key = str(provider).strip()
                if not key:
                    continue
                cleaned = str(model_id).strip() if isinstance(model_id, str) else ""
                if cleaned:
                    overrides[key] = cleaned
                else:
                    overrides.pop(key, None)  # blank clears the override
            meta["model_overrides"] = overrides
            return meta

        def _merge_base_urls(current: Any, ollama: str | None, vllm: str | None) -> dict[str, Any]:
            """Fold the self-hosted endpoint URLs (Ollama / vLLM) into metadata."""
            merged: dict[str, Any] = dict(current) if isinstance(current, dict) else {}
            for meta_key, supplied in (
                ("ollama_base_url", ollama),
                ("vllm_base_url", vllm),
            ):
                if supplied is None:
                    continue
                trimmed = supplied.strip()
                merged[meta_key] = trimmed or None
            return merged

        if settings is None:
            # Create with provided values (encrypt API keys at rest)
            create_kwargs: dict[str, Any] = {"user_id": uid}
            for key_field in _API_KEY_FIELDS:
                val = getattr(data, key_field, None)
                if val is not None:
                    create_kwargs[key_field] = encrypt_secret(val)
            create_kwargs["preferred_model"] = data.preferred_model or "claude-sonnet"
            if data.model_overrides is not None:
                create_kwargs["metadata_"] = _merge_overrides({}, data.model_overrides)
            current_meta = create_kwargs.get("metadata_", {})
            if isinstance(current_meta, dict):
                create_kwargs["metadata_"] = _merge_base_urls(current_meta, data.ollama_base_url, data.vllm_base_url)
            settings = AISettings(**create_kwargs)
            settings = await self.settings_repo.create(settings)
        else:
            fields: dict[str, Any] = {}
            for key_field in _API_KEY_FIELDS:
                val = getattr(data, key_field, None)
                if val is not None:
                    fields[key_field] = encrypt_secret(val)
            if data.preferred_model is not None:
                fields["preferred_model"] = data.preferred_model
            if data.model_overrides is not None:
                fields["metadata_"] = _merge_overrides(settings.metadata_, data.model_overrides)
            has_base_url_update = data.ollama_base_url is not None or data.vllm_base_url is not None
            if has_base_url_update:
                base_meta = fields.get("metadata_", settings.metadata_)
                fields["metadata_"] = _merge_base_urls(base_meta, data.ollama_base_url, data.vllm_base_url)

            if fields:
                await self.settings_repo.update_fields(settings.id, **fields)

        # Re-fetch to return fresh data
        settings = await self.settings_repo.get_by_user_id(uid)
        if settings is None:
            msg = "Settings not found after update"
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)

        await _safe_publish(
            "ai.settings.updated",
            {"user_id": user_id},
            source_module="oe_ai",
        )

        # Propagate the saved self-hosted endpoints into the process-wide
        # provider config. That way every later call_ai() invocation, no
        # matter which module fires it (boq, takeoff, erp_chat and so on),
        # picks up the user's custom URL without passing it around.
        from app.modules.ai import ai_client

        ai_client.update_provider_config(settings.metadata_)
        return _build_settings_response(settings)

    # ── Quick estimate (text -> AI -> BOQ items) ─────────────────────────

    async def quick_estimate(self, user_id: str, request: QuickEstimateRequest) -> EstimateJobResponse:
        """Generate a BOQ estimate from a text description using AI.

        Args:
            user_id: Current user's ID.
            request: Estimation request with description and optional context.

        Returns:
            EstimateJobResponse with generated items.
        """
        uid = uuid.UUID(user_id)
        settings = await self.settings_repo.get_by_user_id(uid)

        # Resolve which AI provider / model to use
        try:
            provider, api_key, model_override = resolve_provider_key_model(settings)
        except ValueError as exc:
            logger.warning("AI provider config error for user %s: %s", user_id, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No AI provider configured. Please add an API key in Settings.",
            ) from exc

        # Create the job record
        job = AIEstimateJob(
            user_id=uid,
            project_id=request.project_id,
            input_type="text",
            input_text=request.description,
            status="processing",
        )
        job = await self.job_repo.create(job)
        job_id = job.id  # Save before expire_all() in update_fields

        # Build prompt with context
        extra_parts: list[str] = []
        if request.project_type:
            extra_parts.append(f"Building type: {request.project_type}")
        if request.area_m2:
            extra_parts.append(f"Total area: {request.area_m2} m2")
        if request.location:
            extra_parts.append(f"Location: {request.location}")
        extra_context = "\n".join(extra_parts)

        # Currency precedence: explicit request → project default →
        # empty string (LLM prompts tolerate a blank currency token).
        currency = request.currency or await _resolve_project_currency(self.session, request.project_id) or ""
        # No standard fallback - empty token signals "no preferred classification"
        # so the LLM is steered by the project's explicit setting (or absence).
        standard_val = request.standard or ""

        # Audit AI1: hard-strip control chars + truncate any free-form
        # user text before it reaches the LLM, so attackers can't smuggle
        # role-switch escapes (\x1b, raw bidi marks, etc.) through the
        # description / extra-context fields.
        prompt = TEXT_ESTIMATE_PROMPT.format(
            description=sanitize_user_text(request.description, max_len=5000),
            extra_context=sanitize_user_text(extra_context, max_len=2000),
            currency=sanitize_user_text(currency, max_len=20),
            standard=sanitize_user_text(standard_val, max_len=64),
        )

        # Call AI
        start_time = time.monotonic()
        try:
            raw_response, tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=SYSTEM_PROMPT,
                prompt=prompt,
                model=model_override,
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)

            # Parse response
            parsed = extract_json(raw_response)
            items = _validate_items(parsed, currency=currency)

            if not items:
                await self.job_repo.update_fields(
                    job_id,
                    status="failed",
                    error_message="AI returned no valid work items. Please try a more detailed description.",
                    model_used=provider,
                    tokens_used=tokens,
                    cost_usd_estimate=float(estimate_cost_usd(provider, int(tokens or 0))),
                    duration_ms=duration_ms,
                )
                self.session.expunge(job)
                job = await self.job_repo.get_by_id(job_id)
                if job is None:
                    msg = "Job not found after update"
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=msg,
                    )
                return _build_job_response(job)

            # Update job with results
            await self.job_repo.update_fields(
                job_id,
                status="completed",
                result=items,
                model_used=provider,
                tokens_used=tokens,
                cost_usd_estimate=float(estimate_cost_usd(provider, int(tokens or 0))),
                duration_ms=duration_ms,
            )

        except HTTPException:
            raise
        except ValueError as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = str(exc)
            logger.warning("Quick estimate user error for %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            # Forward the precise, already-sanitized message from call_ai (e.g.
            # "invalid key", "model rejected", "rate limit") instead of masking
            # it - call_ai never echoes secrets, so this is safe to show and
            # tells the user exactly what to fix.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"AI estimation failed: {exc}"
            logger.exception("Quick estimate failed for user %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI service temporarily unavailable. Please try again.",
            ) from exc

        # Re-fetch the completed job
        self.session.expunge(job)
        job = await self.job_repo.get_by_id(job_id)
        if job is None:
            msg = "Job not found after completion"
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)

        await _safe_publish(
            "ai.estimate.completed",
            {
                "job_id": str(job.id),
                "user_id": user_id,
                "input_type": "text",
                "items_count": len(items),
            },
            source_module="oe_ai",
        )

        logger.info(
            "Quick estimate completed: job=%s, items=%d, tokens=%d, duration=%dms",
            job.id,
            len(items),
            tokens,
            duration_ms,
        )

        return _build_job_response(job)

    # ── Photo estimate (image -> AI Vision -> BOQ items) ─────────────────

    async def photo_estimate(
        self,
        user_id: str,
        image_bytes: bytes,
        filename: str,
        media_type: str = "image/jpeg",
        location: str | None = None,
        currency: str | None = None,
        standard: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> EstimateJobResponse:
        """Generate a BOQ estimate from a building photo using AI Vision.

        Args:
            user_id: Current user's ID.
            image_bytes: Raw image file content.
            filename: Original filename.
            media_type: Image MIME type.
            location: Optional location for pricing context.
            currency: Optional currency code.
            standard: Optional classification standard.
            project_id: Optional project to link to.

        Returns:
            EstimateJobResponse with generated items.
        """
        uid = uuid.UUID(user_id)
        settings = await self.settings_repo.get_by_user_id(uid)

        try:
            provider, api_key, model_override = resolve_provider_key_model(settings)
        except ValueError as exc:
            logger.warning("AI provider config error for user %s: %s", user_id, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No AI provider configured. Please add an API key in Settings.",
            ) from exc

        # Create job record
        job = AIEstimateJob(
            user_id=uid,
            project_id=project_id,
            input_type="photo",
            input_filename=filename,
            status="processing",
        )
        job = await self.job_repo.create(job)
        job_id = job.id  # Save before expire_all() in update_fields

        # Build prompt - currency: explicit arg → project default → blank.
        currency_val = currency or await _resolve_project_currency(self.session, project_id) or ""
        # No standard / location fallback - explicit-only avoids steering
        # the LLM toward DIN 276 / Europe on non-DACH projects.
        standard_val = standard or ""
        location_val = location or ""

        # Audit AI1: sanitize any free-form user strings reaching the LLM.
        prompt = PHOTO_ESTIMATE_PROMPT.format(
            location=sanitize_user_text(location_val, max_len=200),
            currency=sanitize_user_text(currency_val, max_len=20),
            standard=sanitize_user_text(standard_val, max_len=64),
        )

        # Encode image
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Call AI with vision
        start_time = time.monotonic()
        try:
            raw_response, tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=SYSTEM_PROMPT,
                prompt=prompt,
                image_base64=image_b64,
                image_media_type=media_type,
                model=model_override,
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)

            parsed = extract_json(raw_response)
            items = _validate_items(parsed, currency=currency_val)

            if not items:
                await self.job_repo.update_fields(
                    job_id,
                    status="failed",
                    error_message="AI could not extract work items from this photo. Please try a clearer image.",
                    model_used=provider,
                    tokens_used=tokens,
                    cost_usd_estimate=float(estimate_cost_usd(provider, int(tokens or 0))),
                    duration_ms=duration_ms,
                )
                self.session.expunge(job)
                job = await self.job_repo.get_by_id(job_id)
                if job is None:
                    msg = "Job not found after update"
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=msg,
                    )
                return _build_job_response(job)

            await self.job_repo.update_fields(
                job_id,
                status="completed",
                result=items,
                model_used=provider,
                tokens_used=tokens,
                cost_usd_estimate=float(estimate_cost_usd(provider, int(tokens or 0))),
                duration_ms=duration_ms,
            )

        except HTTPException:
            raise
        except ValueError as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = str(exc)
            logger.warning("Photo estimate user error for %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            # Forward the precise, already-sanitized message from call_ai
            # instead of masking it (call_ai never echoes secrets).
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"AI photo analysis failed: {exc}"
            logger.exception("Photo estimate failed for user %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI service temporarily unavailable. Please try again.",
            ) from exc

        self.session.expunge(job)
        job = await self.job_repo.get_by_id(job_id)
        if job is None:
            msg = "Job not found after completion"
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)

        await _safe_publish(
            "ai.estimate.completed",
            {
                "job_id": str(job.id),
                "user_id": user_id,
                "input_type": "photo",
                "items_count": len(items),
            },
            source_module="oe_ai",
        )

        logger.info(
            "Photo estimate completed: job=%s, items=%d, tokens=%d, duration=%dms",
            job.id,
            len(items),
            tokens,
            duration_ms,
        )

        return _build_job_response(job)

    # ── Photo defect-category suggestion (Lane 7) ────────────────────────

    async def suggest_photo_category(
        self,
        user_id: str,
        *,
        image_bytes: bytes | None = None,
        media_type: str = "image/jpeg",
        filename: str = "",
        caption: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Suggest a photo category (e.g. ``defect``) without ever applying it.

        Resolution order:

        1. If the user has a usable AI provider key AND ``image_bytes`` is
           supplied, ask the vision model to classify the photo into one of
           ``PHOTO_CATEGORIES`` and report a confidence. The model output is
           strictly validated against the allowed set; anything off-list is
           discarded (no fabricated category).
        2. Otherwise fall back to the deterministic keyword heuristic over
           filename / caption / tags.
        3. If neither yields a result, return ``None`` ("no suggestion").

        Returns a dict ``{suggested_category, confidence, source}`` where
        ``source`` is ``"ai"`` or ``"heuristic"`` so the UI can label it
        honestly. NEVER raises - a classification failure degrades to the
        heuristic (and then to ``None``); it must not block the upload.
        """
        uid = uuid.UUID(user_id)
        settings = await self.settings_repo.get_by_user_id(uid)

        # 1. Try the configured AI provider (vision) when we have both a key
        #    and image bytes to look at.
        if image_bytes:
            try:
                provider, api_key, model_override = resolve_provider_key_model(settings)
            except ValueError:
                provider = ""
                api_key = ""
                model_override = None
            if provider:
                ai_result = await self._ai_suggest_category(
                    provider=provider,
                    api_key=api_key,
                    model_override=model_override,
                    image_bytes=image_bytes,
                    media_type=media_type,
                )
                if ai_result is not None:
                    return ai_result

        # 2. Deterministic fallback - clearly labelled as a heuristic. For a
        #    defect match this also carries an advisory severity + matched
        #    keyword tags so those chips work without a vision model.
        heuristic = heuristic_photo_suggestion(filename=filename, caption=caption, tags=tags)
        if heuristic is not None:
            return heuristic

        # 3. No signal at all.
        return None

    async def _ai_suggest_category(
        self,
        *,
        provider: str,
        api_key: str,
        model_override: str | None,
        image_bytes: bytes,
        media_type: str,
    ) -> dict[str, Any] | None:
        """Ask the vision model to classify the photo. Best-effort, never raises."""
        prompt = (
            "You are tagging a construction-site photo. Classify it into EXACTLY one "
            "of these categories: site, progress, defect, delivery, safety, other.\n"
            "- defect: visible damage, cracks, leaks, snags, deficiencies\n"
            "- safety: PPE, hazards, scaffolding, fire/first-aid equipment, warnings\n"
            "- delivery: materials/goods being delivered or stored on site\n"
            "- progress: construction work in progress (pours, formwork, framing, installs)\n"
            "- site: general site overview / context shots\n"
            "- other: anything that fits none of the above\n\n"
            'Also return up to 4 short lower-case tags for what is visible (e.g. "crack", '
            '"rebar", "scaffold", "water-damage").\n'
            'If and ONLY IF the category is "defect", also rate the defect severity as '
            "one of: low, medium, high (low = cosmetic, medium = needs repair, high = "
            "structural / safety risk). Omit severity for any non-defect photo.\n\n"
            "Reply with ONLY a JSON object: "
            '{"category": "<one>", "confidence": <0..1>, "tags": ["..."], '
            '"severity": "<low|medium|high>"}'
        )
        try:
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            raw_response, _tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system="You are a precise image classifier. Output JSON only.",
                prompt=prompt,
                image_base64=image_b64,
                image_media_type=media_type,
                model=model_override,
                max_tokens=120,
            )
        except Exception:
            logger.debug("AI photo-category suggestion failed; will fall back", exc_info=True)
            return None

        parsed = extract_json(raw_response)
        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]
        if not isinstance(parsed, dict):
            return None
        category = _coerce_suggested_category(parsed.get("category"))
        if category is None:
            return None
        confidence = _coerce_confidence(parsed.get("confidence"))
        result: dict[str, Any] = {
            "suggested_category": category,
            "confidence": confidence,
            "source": "ai",
        }
        tags = _coerce_suggested_tags(parsed.get("tags"))
        if tags:
            result["suggested_tags"] = tags
        # Severity is only meaningful for defect photos - discard it otherwise
        # so a stray model value can't mislabel a non-defect photo.
        if category == "defect":
            severity = _coerce_defect_severity(parsed.get("severity"))
            if severity is not None:
                result["defect_severity"] = severity
        return result

    # ── Universal file estimate ──────────────────────────────────────────

    async def file_estimate(
        self,
        user_id: str,
        content: bytes,
        filename: str,
        ext: str,
        category: str,
        location: str | None = None,
        currency: str | None = None,
        standard: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> EstimateJobResponse:
        """Generate a BOQ estimate from any file type using AI.

        Routes to the appropriate extraction method based on file category,
        then sends extracted data to the AI for BOQ generation.

        Args:
            user_id: Current user's ID.
            content: Raw file bytes.
            filename: Original filename.
            ext: Lowercase extension (e.g. "pdf", "rvt").
            category: File category ("pdf", "excel", "csv", "cad", "image").
            location: Optional location for pricing context.
            currency: Optional currency code.
            standard: Optional classification standard.
            project_id: Optional project to link to.

        Returns:
            EstimateJobResponse with generated items.
        """
        uid = uuid.UUID(user_id)
        settings = await self.settings_repo.get_by_user_id(uid)

        try:
            provider, api_key, model_override = resolve_provider_key_model(settings)
        except ValueError as exc:
            logger.warning("AI provider config error for user %s: %s", user_id, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No AI provider configured. Please add an API key in Settings.",
            ) from exc

        # Create job record
        job = AIEstimateJob(
            user_id=uid,
            project_id=project_id,
            input_type=category,
            input_filename=filename,
            status="processing",
        )
        job = await self.job_repo.create(job)
        job_id = job.id  # Save before expire_all() in update_fields

        # Currency: explicit arg → project default → blank token.
        currency_val = currency or await _resolve_project_currency(self.session, project_id) or ""
        # No region/standard steering - empty tokens let the LLM rely on
        # the file's content rather than defaulting to DACH / DIN 276.
        standard_val = standard or ""
        location_val = location or ""

        # ── Extract content based on file category ──
        extracted_text = ""
        image_b64: str | None = None
        image_mime: str | None = None
        cad_elements: int | None = None
        cad_format: str | None = None

        try:
            if category == "pdf":
                from app.modules.boq.router import _extract_from_pdf

                result = _extract_from_pdf(content)
                extracted_text = result.get("text", "")

            elif category == "excel":
                from app.modules.boq.router import _extract_from_excel_for_smart

                result = _extract_from_excel_for_smart(content)
                if result.get("structured") and result.get("rows"):
                    # Format structured rows as text for AI
                    rows = result["rows"]
                    lines = []
                    for r in rows:
                        parts = [
                            r.get("ordinal", ""),
                            r.get("description", ""),
                            r.get("unit", ""),
                            str(r.get("quantity", "")),
                            str(r.get("unit_rate", "")),
                        ]
                        lines.append("\t".join(parts))
                    extracted_text = "Pos\tDescription\tUnit\tQty\tRate\n" + "\n".join(lines)
                else:
                    extracted_text = result.get("text", "")

            elif category == "csv":
                from app.modules.boq.router import _extract_from_csv_for_smart

                result = _extract_from_csv_for_smart(content)
                if result.get("structured") and result.get("rows"):
                    rows = result["rows"]
                    lines = []
                    for r in rows:
                        parts = [
                            r.get("ordinal", ""),
                            r.get("description", ""),
                            r.get("unit", ""),
                            str(r.get("quantity", "")),
                            str(r.get("unit_rate", "")),
                        ]
                        lines.append("\t".join(parts))
                    extracted_text = "Pos\tDescription\tUnit\tQty\tRate\n" + "\n".join(lines)
                else:
                    extracted_text = result.get("text", "")

            elif category == "cad":
                from app.modules.boq.router import _extract_from_cad

                result = await _extract_from_cad(content, ext, filename)
                extracted_text = result.get("text", "")
                cad_elements = result.get("cad_elements")
                cad_format = result.get("cad_format", ext)

                if result.get("cad_no_converter"):
                    # No converter installed - return helpful error
                    await self.job_repo.update_fields(
                        job_id,
                        status="failed",
                        error_message=(
                            f"DDC converter for .{ext} files is not installed. "
                            f"Go to Quantities page to install the converter module."
                        ),
                        model_used=provider,
                        duration_ms=0,
                    )
                    self.session.expunge(job)
                    job = await self.job_repo.get_by_id(job_id)
                    if job is None:
                        raise HTTPException(
                            status_code=404, detail=translate("errors.estimate_job_not_found", locale=get_locale())
                        )
                    return _build_job_response(job)

            elif category == "image":
                from app.modules.boq.router import _extract_from_image

                result = _extract_from_image(content, ext)
                image_b64 = result.get("image_base64")
                image_mime = result.get("mime", "image/jpeg")

        except Exception as exc:
            logger.warning("File extraction failed for %s: %s", filename, exc)
            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=f"Failed to extract content from file: {exc}",
                model_used=provider,
                duration_ms=0,
            )
            self.session.expunge(job)
            job = await self.job_repo.get_by_id(job_id)
            if job is None:
                raise HTTPException(
                    status_code=404, detail=translate("errors.estimate_job_not_found", locale=get_locale())
                )
            return _build_job_response(job)

        # ── Choose prompt and call AI ──
        start_time = time.monotonic()
        try:
            if category == "cad":
                # Audit AI1: wrap extracted CAD/element data in the
                # "treat as data not instructions" fence so a malicious
                # element description in the model can't issue commands.
                prompt = CAD_IMPORT_PROMPT.format(
                    text=fence_user_content(extracted_text),
                    currency=sanitize_user_text(currency_val, max_len=20),
                )
                raw_response, tokens = await call_ai(
                    provider=provider,
                    api_key=api_key,
                    system=SYSTEM_PROMPT,
                    prompt=prompt,
                    model=model_override,
                )
            elif image_b64:
                # Audit AI1: filename is user-controlled - sanitize before
                # interpolation.
                prompt = SMART_IMPORT_VISION_PROMPT.format(
                    filename=sanitize_user_text(filename, max_len=255),
                )
                raw_response, tokens = await call_ai(
                    provider=provider,
                    api_key=api_key,
                    system=SYSTEM_PROMPT,
                    prompt=prompt,
                    image_base64=image_b64,
                    image_media_type=image_mime or "image/jpeg",
                    model=model_override,
                )
            else:
                # Audit AI1: filename + extracted text are user-controlled.
                # Fence the text (which carries the heaviest injection risk)
                # and sanitize the filename so neither can break out of the
                # prompt template.
                prompt = SMART_IMPORT_PROMPT.format(
                    filename=sanitize_user_text(filename, max_len=255),
                    text=fence_user_content(extracted_text),
                )
                raw_response, tokens = await call_ai(
                    provider=provider,
                    api_key=api_key,
                    system=SYSTEM_PROMPT,
                    prompt=prompt,
                    model=model_override,
                )

            duration_ms = int((time.monotonic() - start_time) * 1000)

            parsed = extract_json(raw_response)
            items = _validate_items(parsed, currency=currency_val)

            if not items:
                await self.job_repo.update_fields(
                    job_id,
                    status="failed",
                    error_message="AI returned no valid work items from this file. Try a different file or add more detail.",
                    model_used=provider,
                    tokens_used=tokens,
                    cost_usd_estimate=float(estimate_cost_usd(provider, int(tokens or 0))),
                    duration_ms=duration_ms,
                )
                self.session.expunge(job)
                job = await self.job_repo.get_by_id(job_id)
                if job is None:
                    raise HTTPException(
                        status_code=404, detail=translate("errors.estimate_job_not_found", locale=get_locale())
                    )
                return _build_job_response(job)

            # Store metadata about the file
            meta: dict[str, Any] = {}
            if cad_elements is not None:
                meta["cad_elements"] = cad_elements
            if cad_format:
                meta["cad_format"] = cad_format

            await self.job_repo.update_fields(
                job_id,
                status="completed",
                result=items,
                model_used=provider,
                tokens_used=tokens,
                cost_usd_estimate=float(estimate_cost_usd(provider, int(tokens or 0))),
                duration_ms=duration_ms,
            )

        except HTTPException:
            raise
        except ValueError as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = str(exc)
            logger.warning("File estimate user error for %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            # Forward the precise, already-sanitized message from call_ai
            # instead of masking it (call_ai never echoes secrets).
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"AI file analysis failed: {exc}"
            logger.exception("File estimate failed for user %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI service temporarily unavailable. Please try again.",
            ) from exc

        self.session.expunge(job)
        job = await self.job_repo.get_by_id(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=translate("errors.estimate_job_not_found", locale=get_locale()))

        await _safe_publish(
            "ai.estimate.completed",
            {
                "job_id": str(job.id),
                "user_id": user_id,
                "input_type": category,
                "items_count": len(items),
            },
            source_module="oe_ai",
        )

        logger.info(
            "File estimate completed: job=%s, category=%s, items=%d, tokens=%d, duration=%dms",
            job.id,
            category,
            len(items),
            tokens,
            duration_ms,
        )

        return _build_job_response(job)

    # ── Estimate history (server-side job list) ──────────────────────────

    async def list_estimates(
        self,
        user_id: str,
        *,
        project_id: uuid.UUID | None = None,
        status_filter: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> EstimateJobListResponse:
        """Return the current user's estimate jobs, newest first, paginated.

        Backs the "Recent estimates" panel so a user's runs survive a reload
        / device switch instead of living only in browser localStorage. The
        repository always scopes by ``user_id`` so this is tenant-safe.
        """
        uid = uuid.UUID(user_id)
        rows, total = await self.job_repo.list_for_user(
            uid,
            project_id=project_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
        return EstimateJobListResponse(
            items=[_build_job_summary(j) for j in rows],
            total=total,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
        )

    # ── Create BOQ from estimate ─────────────────────────────────────────

    async def create_boq_from_estimate(
        self,
        user_id: str,
        job_id: uuid.UUID,
        request: CreateBOQFromEstimateRequest,
    ) -> dict[str, Any]:
        """Save AI estimation results as a real BOQ with positions.

        Takes a completed AI estimate job and creates a BOQ in the specified
        project, with each estimated item becoming a BOQ position.

        Args:
            user_id: Current user's ID.
            job_id: ID of the completed estimate job.
            request: BOQ creation parameters (project_id, name).

        Returns:
            Dict with boq_id, positions_created count, and grand_total.

        Raises:
            HTTPException 404: If job not found.
            HTTPException 400: If job is not completed or has no results.
        """
        uid = uuid.UUID(user_id)
        job = await self.job_repo.get_by_id(job_id)

        # R7 audit: collapse "job missing" + "different owner" into the
        # same 404 surface so the response cannot be used as a job-id
        # oracle by another tenant.
        if job is None or str(job.user_id) != str(uid):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.estimate_job_not_found", locale=get_locale()),
            )

        # R7 audit: the caller can supply ANY ``request.project_id``;
        # without this guard a non-owner could land an AI-generated BOQ
        # inside a project they don't own (silent BOQ injection that
        # bypasses the projects-module RBAC). The shared helper returns
        # 404 on "missing" OR "no access" - identical surface.
        from app.dependencies import verify_project_access

        await verify_project_access(request.project_id, user_id, self.session)

        if job.status != "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Estimate job is not completed (status: {job.status})",
            )

        if not job.result or not isinstance(job.result, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Estimate job has no results",
            )

        # Import BOQ service to create the BOQ and positions
        from app.modules.boq.models import BOQ, Position
        from app.modules.boq.repository import BOQRepository, PositionRepository

        boq_repo = BOQRepository(self.session)
        position_repo = PositionRepository(self.session)

        # Resolved estimate currency (first priced line). When applying
        # enriched rates we only fold in a CWICR match that shares this
        # currency - never blend currencies into one persisted total (v3 §10).
        estimate_currency = ""
        for item_data in job.result:
            if isinstance(item_data, dict):
                cur = item_data.get("currency")
                if isinstance(cur, str) and cur.strip():
                    estimate_currency = cur.strip()
                    break

        # Create the BOQ
        boq = BOQ(
            project_id=request.project_id,
            name=request.boq_name,
            description=f"Generated by AI from {job.input_type} input",
            status="draft",
            metadata_={
                "ai_job_id": str(job_id),
                "ai_model": job.model_used or "",
                "ai_rates_enriched": bool(request.apply_enriched),
                "ai_enrich_region": request.region or "",
            },
        )
        boq = await boq_repo.create(boq)

        # Create positions from estimated items
        grand_total = 0.0
        positions_created = 0
        enriched_count = 0

        for sort_idx, item_data in enumerate(job.result):
            if not isinstance(item_data, dict):
                continue

            description = str(item_data.get("description", "")).strip()
            if not description:
                continue

            try:
                quantity = float(item_data.get("quantity", 0))
                unit_rate = float(item_data.get("unit_rate", 0))
            except (ValueError, TypeError):
                continue
            # Never persist a non-finite quantity/rate into BOQ money.
            if not math.isfinite(quantity) or not math.isfinite(unit_rate):
                continue
            unit = str(item_data.get("unit", "m2"))
            classification = dict(item_data.get("classification", {}) or {})
            position_metadata: dict[str, Any] = {
                "ai_job_id": str(job_id),
                "category": str(item_data.get("category", "")),
            }
            position_source = "ai_estimate"

            # ── Optional cost-DB enrichment: replace the AI rate with the best
            #    same-currency CWICR match the user reviewed in the table. The
            #    match code is recorded on the position so the persisted rate
            #    is traceable to the catalogue, not an opaque AI guess.
            if request.apply_enriched:
                cost_matches = await _match_cost_items(
                    self.session,
                    description=description,
                    item_unit=unit,
                    region=request.region or "",
                    limit=1,
                )
                best = cost_matches[0] if cost_matches else None
                if best:
                    from app.core.match_service.config import (
                        CONFIDENCE_MEDIUM_THRESHOLD,
                    )

                    match_currency = (best.get("currency") or "").strip()
                    same_currency = match_currency == "" or match_currency == estimate_currency
                    match_score = float(best.get("score", 0) or 0)
                    # Only let a catalogue rate override the AI rate when the
                    # match clears the medium-confidence band. A weak keyword
                    # fallback (score floor ~0.3) must NOT silently replace the
                    # rate that drives the persisted total - it stays a
                    # non-applied suggestion the user can review.
                    applied = bool(same_currency and best.get("rate") and match_score >= CONFIDENCE_MEDIUM_THRESHOLD)
                    position_metadata["cwicr_match"] = {
                        "code": best.get("code", ""),
                        "rate": best.get("rate", 0.0),
                        "currency": match_currency,
                        "region": best.get("region", ""),
                        "score": round(match_score, 4),
                        "applied": applied,
                    }
                    if applied:
                        unit_rate = float(best["rate"])
                        position_source = "ai_estimate_cwicr"
                        enriched_count += 1
                        code = best.get("code", "")
                        if code:
                            classification = {**classification, "cwicr": code}

            total = round(quantity * unit_rate, 2)
            grand_total += total

            # Use the model's real per-item confidence when it supplied one;
            # otherwise leave it unset rather than fabricating a placeholder.
            item_conf = _coerce_confidence(item_data.get("confidence"))
            confidence_str = str(item_conf) if item_conf is not None else None

            position = Position(
                boq_id=boq.id,
                parent_id=None,
                ordinal=str(item_data.get("ordinal", str(sort_idx + 1))),
                description=description,
                unit=unit,
                quantity=str(quantity),
                unit_rate=str(unit_rate),
                total=str(total),
                classification=classification,
                source=position_source,
                confidence=confidence_str,
                cad_element_ids=[],
                validation_status="pending",
                metadata_=position_metadata,
                sort_order=sort_idx,
            )
            await position_repo.create(position)
            positions_created += 1

        await _safe_publish(
            "ai.boq.created",
            {
                "boq_id": str(boq.id),
                "job_id": str(job_id),
                "user_id": user_id,
                "project_id": str(request.project_id),
                "positions_count": positions_created,
            },
            source_module="oe_ai",
        )

        logger.info(
            "BOQ created from AI estimate: boq=%s, job=%s, positions=%d, enriched=%d, total=%.2f",
            boq.id,
            job_id,
            positions_created,
            enriched_count,
            grand_total,
        )

        return {
            "boq_id": str(boq.id),
            "positions_created": positions_created,
            "positions_enriched": enriched_count,
            "grand_total": round(grand_total, 2),
        }
