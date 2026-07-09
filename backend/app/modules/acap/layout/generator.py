"""LLM-driven floor-plan generator with geometric validation + auto-retry.

Reuses the fork's existing ``call_ai`` / ``resolve_provider_key_model``
from :mod:`app.modules.ai.ai_client` and the key-resolution pattern from
:mod:`app.modules.ai_estimator.intake`.  NEVER returns an invalid plan.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model

logger = logging.getLogger(__name__)

# ── Domain prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert Indonesian residential architect. Generate a house floor plan as STRICT JSON matching this schema: a FloorPlan has `kavling` {width_m, length_m}, `levels` (one per floor), each Level has `level` (1-based int) and `rooms`. Each Room has `name`, `type` (one of: kamar_tidur_utama, kamar_tidur, kamar_mandi, dapur, ruang_tamu, ruang_keluarga, ruang_makan, carport, garasi, musholla, gudang, teras, taman, sirkulasi, other), `polygon` (EXACTLY 4 corners in CCW order as [{x,y},...] meters), and `area_m2`.
RULES:
- Coordinate origin (0,0) at kavling south-west corner; x→east (width_m), y→north (length_m); meters.
- Every room is an axis-aligned rectangle: polygon = [{x:X,y:Y},{x:X+W,y:Y},{x:X+W,y:Y+H},{x:X,y:Y+H}] and area_m2 = W*H exactly.
- Rooms MUST NOT overlap. All rooms fully inside the kavling [0,0]..[width_m,length_m].
- Ground-floor (level 1) built footprint must be <= 70% of kavling area (KDB). Leave setback/garden.
- Minimum room sizes (SNI): kamar_tidur_utama >=9, kamar_tidur >=6, kamar_mandi >=2.25 (min side 1.2 m), dapur >=4, ruang_tamu >=7.5, ruang_keluarga >=9, carport >=12.5 m². Every room side >= 1.2 m.
- Include circulation (type sirkulasi) linking rooms; for 2-story include a stair (type sirkulasi named 'Tangga') on each level and stack levels consistently.
- Sensible adjacency: kamar_mandi near bedrooms, dapur near ruang_makan, carport/ruang_tamu at the front.
- Output ONLY the JSON object. No prose, no markdown fences."""


# ── Error ────────────────────────────────────────────────────────────────────


class LayoutGenerationError(Exception):
    """Raised when the LLM cannot produce a valid floor-plan within retries."""

    def __init__(self, reasons: list[str], attempts: int = 0) -> None:
        self.reasons = reasons
        self.attempts = attempts
        msg = f"Layout generation failed after {attempts} attempt(s):\n" + "\n".join(
            f"  - {r}" for r in reasons
        )
        super().__init__(msg)


# ── Settings helper (small, monkeypatchable) ─────────────────────────────────


async def _load_ai_settings(session, user_id):
    """Load AI provider/key/model from DB settings for *user_id*."""
    from app.modules.ai.repository import AISettingsRepository

    settings = await AISettingsRepository(session).get_by_user_id(user_id)
    return resolve_provider_key_model(settings)


# ── Generator ────────────────────────────────────────────────────────────────


async def generate_layout(
    session,
    requirement_text: str,
    kavling_width_m: float,
    kavling_length_m: float,
    jumlah_lantai: int = 1,
    user_id=None,
    max_retries: int = 3,
):
    """Generate a validated :class:`~app.modules.acap.layout.schema.FloorPlan`.

    Resolves AI settings, then loops up to *max_retries* calling the LLM
    and running :func:`~app.modules.acap.layout.validator.validate_plan`.
    Only returns when a plan passes all checks — never returns invalid.
    """
    from app.modules.acap.layout.schema import FloorPlan
    from app.modules.acap.layout.validator import LayoutValidationError, validate_plan

    # ── Resolve AI settings ─────────────────────────────────────────
    try:
        provider, api_key, model = await _load_ai_settings(session, user_id)
    except ValueError as exc:
        raise LayoutGenerationError([str(exc)], attempts=0) from exc

    # ── Build base prompt ───────────────────────────────────────────
    base_prompt = (
        f"{requirement_text}\n"
        f"Kavling: {kavling_width_m}m x {kavling_length_m}m. "
        f"Jumlah lantai: {jumlah_lantai}. "
        f"Return ONE FloorPlan JSON with a Level for each floor."
    )

    last_reasons: list[str] = []
    prompt = base_prompt

    for attempt in range(1, max_retries + 1):
        # ── Call LLM ────────────────────────────────────────────────
        try:
            text, _tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=SYSTEM_PROMPT,
                prompt=prompt,
                max_tokens=8192,
                model=model,
            )
        except Exception as exc:
            last_reasons = [f"LLM call failed: {exc}"]
            continue

        # ── Extract JSON ────────────────────────────────────────────
        data = extract_json(text)
        if data is None:
            reason = "model did not return valid JSON"
            last_reasons = [reason]
            prompt = base_prompt + f"\n\nPREVIOUS ATTEMPT FAILED: {reason}\nReturn corrected JSON only."
            continue

        # ── Validate ────────────────────────────────────────────────
        try:
            plan = FloorPlan.model_validate(data)
            validate_plan(plan)
        except Exception as exc:
            if isinstance(exc, LayoutValidationError):
                reasons_list = exc.reasons
            else:
                reasons_list = [str(exc)]
            last_reasons = reasons_list
            feedback = "\n".join(f"  - {r}" for r in reasons_list)
            prompt = (
                base_prompt
                + f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION:\n{feedback}\nReturn corrected JSON only."
            )
            continue

        # ── Success ─────────────────────────────────────────────────
        plan.generated_by = model or provider
        plan.requirement_text = requirement_text
        plan.jumlah_lantai = jumlah_lantai
        return plan

    # ── Exhausted retries ───────────────────────────────────────────
    raise LayoutGenerationError(last_reasons, attempts=max_retries)
