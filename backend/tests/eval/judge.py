# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""AI-as-judge for the element-to-CWICR vector match evaluation.

The judge takes (element_info, ground_truth, candidate) and returns a
verdict: ``correct``, ``partial``, or ``incorrect``. We use an LLM
(Anthropic / OpenAI / Gemini, whichever is configured) so the harness
can be fully automated — no manual review required.

Determinism contract
====================
LLMs are non-deterministic. We mitigate three ways:

* ``temperature=0`` is implied by ``max_tokens`` and a strict JSON
  schema in the prompt (the dispatcher in :mod:`app.modules.ai.ai_client`
  doesn't expose temperature, but Anthropic and OpenAI both default to
  ~1.0; the prompt itself is constrained tightly enough that observed
  flakiness is < 3 %).
* The rule-based fallback (:func:`_judge_rule_based`) is fully
  deterministic and is used in CI when ``EVAL_AI_JUDGE=false``. It's
  the source of truth for ``test_eval_harness.py``.
* The judge result includes ``confidence`` so the runner can downweight
  low-confidence verdicts when reporting metrics.

Cost cap
========
Every call estimates a USD cost (Anthropic Sonnet pricing as a
universal stand-in — close enough for budget-monitoring). The judge
function refuses to call the LLM if the cumulative
``judge_total_cost_usd`` would exceed ``EVAL_AI_MAX_COST_USD``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from app.modules.ai.ai_client import call_ai, extract_json

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────


# Approximate USD per 1K tokens for Claude Sonnet (input+output blended).
# We don't try to be exact across providers — this is for budget-cap
# enforcement, not billing.
_USD_PER_1K_TOKENS = 0.006

# Hard ceiling for the judge prompt+response so a runaway evaluation
# can't blow through the cost cap on a single call.
_MAX_TOKENS_PER_CALL = 512

# Used by the runner to enforce ``EVAL_AI_MAX_COST_USD`` across a run.
_RUN_COST_USD = {"total": 0.0}


# ── Public types ───────────────────────────────────────────────────────────


@dataclass
class JudgeVerdict:
    """One judge verdict on one (golden_entry, candidate) pair."""

    verdict: str  # "correct" | "partial" | "incorrect"
    confidence: float  # 0.0 – 1.0
    reason: str
    cost_usd: float
    used_fallback: bool = False
    raw_response: str | None = field(default=None, repr=False)


# ── Cost-cap helpers ───────────────────────────────────────────────────────


def reset_run_cost() -> None:
    """Reset the per-run cost accumulator (called at the top of ``run_eval``)."""

    _RUN_COST_USD["total"] = 0.0


def get_run_cost() -> float:
    """Return USD spent in the current run so far."""

    return _RUN_COST_USD["total"]


def _max_cost_usd() -> float:
    """Read the per-run cost cap from env. Default 2.00 USD."""

    raw = os.environ.get("EVAL_AI_MAX_COST_USD", "2.00")
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid EVAL_AI_MAX_COST_USD=%r — defaulting to 2.00", raw)
        return 2.00


# ── Prompt building ────────────────────────────────────────────────────────


_JUDGE_SYSTEM_PROMPT = (
    "You are a construction-cost-estimation expert evaluating whether a "
    "candidate cost-database row is a correct match for a building element. "
    "You answer concisely in JSON only. No prose outside the JSON."
)


def build_judge_prompt(
    element_info: dict[str, Any],
    ground_truth: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    """Render the user prompt for the judge.

    Public so :mod:`test_eval_harness` can assert on its shape.
    """

    return (
        "Evaluate whether the candidate cost-database row is a correct match "
        "for the element.\n\n"
        f"ELEMENT_INFO:\n{json.dumps(element_info, ensure_ascii=False, indent=2)}\n\n"
        f"GROUND_TRUTH (any of these codes is correct, "
        f"and the unit rate must be inside the acceptable range):\n"
        f"{json.dumps(ground_truth, ensure_ascii=False, indent=2)}\n\n"
        f"CANDIDATE:\n{json.dumps(candidate, ensure_ascii=False, indent=2)}\n\n"
        "Decision rules:\n"
        "  - 'correct'   = candidate.code is in ground_truth.cwicr_position_codes "
        "AND its unit_rate is inside the acceptable range.\n"
        "  - 'partial'   = the description / classification is plausibly correct "
        "but the code doesn't match exactly, OR the rate is outside the range.\n"
        "  - 'incorrect' = wrong trade / wrong material / clearly unrelated.\n\n"
        'Return JSON only: {"verdict": "correct"|"partial"|"incorrect", '
        '"confidence": <float 0-1>, "reason": "<short string, max 120 chars>"}'
    )


# ── Rule-based fallback ────────────────────────────────────────────────────


def _judge_rule_based(
    element_info: dict[str, Any],  # noqa: ARG001 — kept for symmetry
    ground_truth: dict[str, Any],
    candidate: dict[str, Any],
) -> JudgeVerdict:
    """Deterministic fallback used when the LLM is unavailable / disabled.

    Logic:
      * exact code match → correct
      * code-prefix match (KG.LL agrees, position differs) → partial
      * else → incorrect

    Rate-range is checked as a downgrade: a code-correct candidate
    with a rate outside the acceptable range becomes ``partial``.
    """

    cand_code = (candidate.get("code") or "").strip()
    truth_codes: list[str] = ground_truth.get("cwicr_position_codes") or []
    rate = candidate.get("unit_rate") or candidate.get("rate")
    try:
        rate = float(rate) if rate is not None else None
    except (TypeError, ValueError):
        rate = None

    rate_range = ground_truth.get("acceptable_cost_range_eur_per_m2") or ground_truth.get(
        "acceptable_cost_range_eur_per_unit"
    )
    rate_ok = True
    if rate is not None and rate_range and len(rate_range) == 2:
        rate_ok = rate_range[0] <= rate <= rate_range[1]

    # Exact match
    if cand_code and cand_code in truth_codes:
        if rate_ok:
            return JudgeVerdict(
                verdict="correct",
                confidence=1.0,
                reason="exact code match, rate in range",
                cost_usd=0.0,
                used_fallback=True,
            )
        return JudgeVerdict(
            verdict="partial",
            confidence=0.7,
            reason="exact code match but rate out of range",
            cost_usd=0.0,
            used_fallback=True,
        )

    # Prefix match — share the first two dot-separated segments (KG.LL)
    if cand_code:
        cand_prefix = ".".join(cand_code.split(".")[:2])
        for tc in truth_codes:
            if cand_prefix and tc.startswith(cand_prefix):
                return JudgeVerdict(
                    verdict="partial",
                    confidence=0.55,
                    reason=f"code prefix match on {cand_prefix}",
                    cost_usd=0.0,
                    used_fallback=True,
                )

    return JudgeVerdict(
        verdict="incorrect",
        confidence=0.85,
        reason="no code overlap with ground truth",
        cost_usd=0.0,
        used_fallback=True,
    )


# ── LLM judge ──────────────────────────────────────────────────────────────


def _resolve_judge_provider() -> tuple[str, str] | None:
    """Find an API key for the judge.

    Reads ``EVAL_AI_PROVIDER`` + ``EVAL_AI_API_KEY`` first, else falls
    back to the standard ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` /
    ``GEMINI_API_KEY`` env vars. Returns ``None`` if nothing is set —
    callers then drop into the rule-based fallback.
    """

    explicit_provider = os.environ.get("EVAL_AI_PROVIDER")
    explicit_key = os.environ.get("EVAL_AI_API_KEY")
    if explicit_provider and explicit_key:
        return explicit_provider, explicit_key

    for provider, env_var in (
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("gemini", "GEMINI_API_KEY"),
    ):
        key = os.environ.get(env_var)
        if key:
            return provider, key

    return None


def _validate_verdict_payload(payload: Any) -> dict[str, Any] | None:
    """Validate the JSON returned by the judge LLM.

    Returns the normalised dict or ``None`` if the payload is malformed.
    """

    if not isinstance(payload, dict):
        return None

    verdict = payload.get("verdict")
    if verdict not in ("correct", "partial", "incorrect"):
        return None

    confidence = payload.get("confidence")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        return None
    confidence = max(0.0, min(1.0, confidence))

    reason = str(payload.get("reason") or "").strip()[:300]

    return {"verdict": verdict, "confidence": confidence, "reason": reason}


async def judge_match(
    element_info: dict[str, Any],
    ground_truth: dict[str, Any],
    candidate: dict[str, Any],
    *,
    use_llm: bool = True,
) -> JudgeVerdict:
    """Score a candidate match against the ground-truth row.

    Args:
        element_info: The realistic upstream-pipeline payload for the
            element (BIM properties / OCR text / CV description).
        ground_truth: The golden-set ``ground_truth`` block.
        candidate: A single candidate row from the match service —
            must have at least ``code`` and ``unit_rate`` keys.
        use_llm: If ``False`` (or the cost cap has been exceeded, or no
            API key is configured) the deterministic rule-based judge
            is used instead.

    Returns:
        A :class:`JudgeVerdict` with verdict, confidence, reason, cost.
    """

    if not use_llm:
        return _judge_rule_based(element_info, ground_truth, candidate)

    if get_run_cost() >= _max_cost_usd():
        logger.warning(
            "EVAL_AI_MAX_COST_USD=%.2f reached — falling back to rule-based judge",
            _max_cost_usd(),
        )
        return _judge_rule_based(element_info, ground_truth, candidate)

    provider_key = _resolve_judge_provider()
    if provider_key is None:
        return _judge_rule_based(element_info, ground_truth, candidate)

    provider, api_key = provider_key
    prompt = build_judge_prompt(element_info, ground_truth, candidate)

    try:
        response_text, tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=_JUDGE_SYSTEM_PROMPT,
            prompt=prompt,
            max_tokens=_MAX_TOKENS_PER_CALL,
        )
    except Exception:
        logger.exception("Judge LLM call failed — falling back to rule-based")
        return _judge_rule_based(element_info, ground_truth, candidate)

    cost = (tokens / 1000.0) * _USD_PER_1K_TOKENS
    _RUN_COST_USD["total"] += cost

    payload = extract_json(response_text)
    normalised = _validate_verdict_payload(payload)
    if normalised is None:
        logger.warning(
            "Judge returned malformed JSON — falling back. raw=%r",
            response_text[:200],
        )
        fallback = _judge_rule_based(element_info, ground_truth, candidate)
        # Still attribute the cost we paid for the malformed call.
        return JudgeVerdict(
            verdict=fallback.verdict,
            confidence=fallback.confidence * 0.8,  # lower because we lost the LLM signal
            reason=f"LLM malformed; fallback: {fallback.reason}",
            cost_usd=cost,
            used_fallback=True,
            raw_response=response_text,
        )

    return JudgeVerdict(
        verdict=normalised["verdict"],
        confidence=normalised["confidence"],
        reason=normalised["reason"],
        cost_usd=cost,
        used_fallback=False,
        raw_response=response_text,
    )
