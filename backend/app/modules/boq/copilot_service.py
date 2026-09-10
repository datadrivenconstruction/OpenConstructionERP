# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Per-position AI copilot service (stateless).

Business logic for the BOQ position copilot: a position-scoped chat where the
estimator asks the assistant to refine a single BOQ position and the assistant
replies with prose plus zero or more structured action proposals. The four
supported actions map onto the existing ``BOQService.update_position`` write
path:

* ``update_description`` -> rewrite ``Position.description``
* ``set_quantity``       -> set ``quantity`` (optionally ``unit``)
* ``set_unit_rate``      -> set ``unit_rate`` (optionally ``currency`` metadata)
* ``add_resources``      -> append to ``metadata.resources`` (``unit_rate`` then
                            re-derives from the resource breakdown)

Grounding. Every price/resource the model proposes must reference a catalogue
``code`` we supplied (CWICR matches via ``match_cwicr_items`` + the top
candidate's resource ``components``). The prompt forbids invented prices; an
action that cites no provided code is still surfaced, but priced actions carry
the catalogue row in ``source`` so the user can verify provenance.

Confidence gates (per the platform contract):

* ``>= 0.85`` -> auto-apply during chat (status ``auto_applied``)
* ``0.65 - 0.85`` -> ``needs_review`` (proposed, not applied)
* ``< 0.65``  -> ``needs_review`` as well (kept, never silently dropped); the
  frontend may grey out / hide sub-0.65 proposals.

Tenant safety. Reads and applies go through ``_load_position_scoped``, which
reuses the exact BOQ -> project ownership check the position routes use
(``_verify_boq_owner``), so a cross-tenant ``position_id`` yields 404/403 before
any data is read or mutated.

No tool-calling: the model returns strict JSON in its reply and we parse it with
``extract_json`` (the same convention as ``ai/service.py``).
"""

from __future__ import annotations

import logging
import math
import uuid
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.copilot_models import PositionCopilotMessage
from app.modules.boq.copilot_schemas import (
    CopilotActionProposal,
    CopilotChatResponse,
    CopilotMessageOut,
)
from app.modules.boq.schemas import PositionUpdate

if TYPE_CHECKING:
    from app.modules.boq.models import Position
    from app.modules.projects.models import Project

logger = logging.getLogger(__name__)

# Confidence thresholds (platform contract).
AUTO_APPLY_THRESHOLD = 0.85
REVIEW_THRESHOLD = 0.65

# ``Position.source`` values written by the two copilot write paths. The caller
# is the only thing that tells them apart, so the value has to be passed down
# rather than derived from the action: the same proposal, on the same field,
# reaches the same builder whether the copilot applied it unattended or an
# estimator read it and pressed apply.
#: Applied by the copilot alone, on the model's self-reported confidence.
SOURCE_AUTO_APPLIED = "ai_copilot_auto"
#: Proposed by the copilot, read and accepted by a person.
SOURCE_HUMAN_ACCEPTED = "ai_copilot_accepted"

# How many sibling positions to feed the model for context.
_MAX_SIBLINGS = 6
# How many catalogue candidates to ground against.
_MATCH_TOP_K = 5
# Cap on resources a single add_resources action may append (defensive).
_MAX_RESOURCES = 40

_ALLOWED_ACTION_TYPES = {
    "update_description",
    "set_quantity",
    "set_unit_rate",
    "add_resources",
}

_ALLOWED_RESOURCE_TYPES = {"material", "labor", "equipment", "operator", "subcontractor", "other"}


# ── System / user prompt ────────────────────────────────────────────────────

COPILOT_SYSTEM_PROMPT = (
    "You are a construction cost-estimating copilot embedded in the "
    "OpenConstructionERP BOQ editor. You help refine ONE Bill-of-Quantities "
    "position at a time. You propose concrete, conservative edits and explain "
    "them briefly. You NEVER invent prices or resource rates: every price, unit "
    "rate, or resource you propose MUST come from a catalogue item provided to "
    "you (reference it by its 'code'). If no catalogue item supports a price, "
    "do not propose a priced action - describe what you would need instead. "
    "You return STRICT JSON only, no prose outside the JSON object."
)


def _build_user_prompt(
    *,
    message: str,
    position: Position,
    project: Project | None,
    siblings: list[Position],
    candidates: list[dict[str, Any]],
) -> str:
    """Render the copilot user prompt.

    All free-text that originates from the user / stored data is sanitized by
    the caller before it reaches here; this function only lays out the prompt
    skeleton and the JSON contract the model must follow.
    """
    import json

    region = (getattr(project, "region", "") or "") if project else ""
    currency = (getattr(project, "currency", "") or "") if project else ""

    pos_block = {
        "ordinal": position.ordinal,
        "description": position.description,
        "unit": position.unit,
        "quantity": str(position.quantity),
        "unit_rate": str(position.unit_rate),
        "currency": currency,
        "has_resources": bool(isinstance(position.metadata_, dict) and position.metadata_.get("resources")),
    }
    sibling_block = [{"ordinal": s.ordinal, "description": s.description, "unit": s.unit} for s in siblings]

    return (
        f"Project region: {region or '(unspecified)'}; currency: {currency or '(unspecified)'}.\n\n"
        f"The position being edited:\n{json.dumps(pos_block, ensure_ascii=False)}\n\n"
        f"Nearby positions (for context only, do not edit them):\n"
        f"{json.dumps(sibling_block, ensure_ascii=False)}\n\n"
        f"Catalogue candidates you MAY cite for any price/resource (use the 'code'; "
        f"each may carry a 'components' resource breakdown):\n"
        f"{json.dumps(candidates, ensure_ascii=False)}\n\n"
        f"User request:\n{message}\n\n"
        "Decide which edits to the position best satisfy the request. Reply with a "
        "STRICT JSON object of exactly this shape:\n"
        "{\n"
        '  "reply": "<one or two sentences explaining what you propose>",\n'
        '  "actions": [\n'
        "    {\n"
        '      "action_type": "update_description | set_quantity | set_unit_rate | add_resources",\n'
        '      "payload": { ... },\n'
        '      "confidence": 0.0,\n'
        '      "rationale": "<short why>",\n'
        '      "source_code": "<catalogue code you cited, or null>"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "payload shapes by action_type:\n"
        '  update_description -> {"description": "<new text>"}\n'
        '  set_quantity       -> {"quantity": <number>, "unit": "<optional unit>"}\n'
        '  set_unit_rate      -> {"unit_rate": <number>, "currency": "<optional ISO code>"}\n'
        '  add_resources      -> {"resources": [{"name": "...", "type": "material|labor|equipment|other",'
        ' "unit": "...", "quantity": <per-unit number>, "unit_rate": <number>, "code": "<catalogue code>",'
        ' "currency": "<optional>"}]}\n\n'
        "Rules: propose only actions the request asks for; set 'confidence' honestly in [0,1] "
        "(>=0.85 means you are very sure); any unit_rate / resource unit_rate MUST come from a "
        "catalogue candidate above and you MUST put that catalogue code in 'source_code'; if you "
        "cannot ground a price, omit that action. Return ONLY the JSON object."
    )


# ── Coercion helpers ────────────────────────────────────────────────────────


def _coerce_confidence(value: Any) -> float:
    """Coerce a model-supplied confidence to a float in [0, 1] (default 0.0).

    Accepts a 0..1 probability or a 0..100 percentage (values >2 and <=100 are
    divided by 100). Non-finite / out-of-range -> 0.0 (treated as low / review).
    """
    if value is None:
        return 0.0
    try:
        conf = float(value)
    except (ValueError, TypeError):
        return 0.0
    if not math.isfinite(conf):
        return 0.0
    if 2.0 < conf <= 100.0:
        conf = conf / 100.0
    if conf < 0.0 or conf > 1.0:
        return 0.0
    return round(conf, 4)


def _coerce_number(value: Any) -> float | None:
    """Coerce a model-supplied numeric to a finite float, else None."""
    try:
        num = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(num):
        return None
    return num


def _to_decimal(value: Any) -> Decimal:
    """Best-effort Decimal coercion (0 on failure). Mirrors the service layer."""
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    return dec if dec.is_finite() else Decimal("0")


def _resources_unit_rate(resources: list[dict[str, Any]]) -> Decimal:
    """Sum of per-unit resource subtotals (qty * rate), no FX, for `before`.

    The authoritative re-derivation (with project FX) runs inside
    ``update_position``; this is only used to show the user the expected new
    unit_rate in the ``before`` snapshot, so a plain same-currency sum is fine.
    """
    total = Decimal("0")
    for r in resources:
        if isinstance(r, dict):
            total += _to_decimal(r.get("quantity")) * _to_decimal(r.get("unit_rate"))
    return total


# ── Catalogue grounding ─────────────────────────────────────────────────────


def _looks_like_search(message: str) -> bool:
    """Heuristic: does the message read like a catalogue search vs an edit?

    Short, noun-phrase-ish messages ("c30/37 wall", "M25 concrete rate") are
    treated as a search query; longer imperative sentences fall back to the
    position description for grounding.
    """
    msg = message.strip()
    if not msg:
        return False
    words = msg.split()
    if len(words) <= 6:
        return True
    lowered = msg.lower()
    return any(kw in lowered for kw in ("rate for", "price for", "cost of", "find ", "search "))


async def _ground_candidates(
    session: AsyncSession,
    *,
    message: str,
    position: Position,
    region: str,
) -> list[dict[str, Any]]:
    """Return up to ``_MATCH_TOP_K`` catalogue candidates with resource breakdowns.

    Query selection: if the message reads like a search, ground on the message;
    otherwise ground on the position description. The top candidate's CostItem is
    loaded so its ``components`` (resource breakdown) can seed an
    ``add_resources`` action. Degrades to an empty list on any failure - the
    chat must still return.
    """
    from app.modules.costs.matcher import match_cwicr_items
    from app.modules.costs.repository import CostItemRepository

    query = message if _looks_like_search(message) else (position.description or "")
    query = (query or "").strip()
    if not query:
        return []

    try:
        matches = await match_cwicr_items(
            session,
            query,
            unit=position.unit or None,
            region=region or None,
            mode="hybrid",
            top_k=_MATCH_TOP_K,
        )
    except Exception:
        logger.debug("copilot grounding match failed for position %s", position.id, exc_info=True)
        return []

    candidates: list[dict[str, Any]] = []
    for idx, m in enumerate(matches):
        cand: dict[str, Any] = {
            "code": m.code,
            "description": m.description,
            "unit": m.unit,
            "unit_rate": m.unit_rate,
            "currency": m.currency,
            "score": m.score,
        }
        # Load the resource breakdown for the best candidate only (keeps the
        # prompt small and the DB work bounded).
        if idx == 0 and m.cost_item_id:
            try:
                repo = CostItemRepository(session)
                cost_item = await repo.get_by_id(uuid.UUID(str(m.cost_item_id)))
                comps = getattr(cost_item, "components", None) if cost_item else None
                if isinstance(comps, list) and comps:
                    cand["components"] = [c for c in comps if isinstance(c, dict)][:_MAX_RESOURCES]
            except Exception:
                logger.debug("copilot component load failed for %s", m.cost_item_id, exc_info=True)
        candidates.append(cand)
    return candidates


def _source_for(code: str | None, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Resolve a cited catalogue code to its candidate dict (the action source)."""
    if not code:
        return None
    code_norm = str(code).strip()
    if not code_norm:
        return None
    for c in candidates:
        if str(c.get("code", "")).strip() == code_norm:
            return c
    return None


# ── Action parsing / normalisation ──────────────────────────────────────────


def _normalise_resources(raw: Any, *, default_currency: str) -> list[dict[str, Any]]:
    """Validate and clean an ``add_resources`` payload into resource dicts.

    Each resource is a per-unit norm: ``{name, type, unit, quantity, unit_rate,
    code?, currency?}``. Invalid entries are dropped. Returns ``[]`` when nothing
    usable remains so the caller can skip the action.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[:_MAX_RESOURCES]:
        if not isinstance(item, dict):
            continue
        qty = _coerce_number(item.get("quantity"))
        rate = _coerce_number(item.get("unit_rate"))
        if qty is None or rate is None or qty < 0 or rate < 0:
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        rtype = str(item.get("type", "material")).strip().lower()
        if rtype not in _ALLOWED_RESOURCE_TYPES:
            rtype = "material"
        resource: dict[str, Any] = {
            "name": name[:200],
            "type": rtype,
            "unit": str(item.get("unit", "")).strip()[:30] or "pcs",
            "quantity": round(qty, 6),
            "unit_rate": round(rate, 4),
        }
        code = str(item.get("code", "")).strip()
        if code:
            resource["code"] = code[:64]
        currency = str(item.get("currency", "")).strip() or default_currency
        if currency:
            resource["currency"] = currency[:10]
        out.append(resource)
    return out


def _build_proposal(
    raw_action: dict[str, Any],
    *,
    position: Position,
    candidates: list[dict[str, Any]],
    default_currency: str,
) -> CopilotActionProposal | None:
    """Turn one raw model action into a validated proposal with a ``before`` snapshot.

    Returns ``None`` when the action is malformed, unsupported, or (for priced
    actions) cites no provided catalogue code - the prompt forbids invented
    prices, and we enforce it server-side too.
    """
    action_type = str(raw_action.get("action_type", "")).strip()
    if action_type not in _ALLOWED_ACTION_TYPES:
        return None

    payload_raw = raw_action.get("payload")
    payload: dict[str, Any] = payload_raw if isinstance(payload_raw, dict) else {}
    confidence = _coerce_confidence(raw_action.get("confidence"))
    source_code = raw_action.get("source_code")
    source = _source_for(source_code if isinstance(source_code, str) else None, candidates)

    before: dict[str, Any] = {}
    clean_payload: dict[str, Any] = {}

    if action_type == "update_description":
        new_desc = str(payload.get("description", "")).strip()
        if len(new_desc) < 3:
            return None
        before = {"description": position.description}
        clean_payload = {"description": new_desc[:5000]}

    elif action_type == "set_quantity":
        qty = _coerce_number(payload.get("quantity"))
        if qty is None or qty < 0:
            return None
        before = {"quantity": str(position.quantity)}
        clean_payload = {"quantity": round(qty, 6)}
        new_unit = str(payload.get("unit", "")).strip()
        if new_unit and new_unit != position.unit:
            before["unit"] = position.unit
            clean_payload["unit"] = new_unit[:30]

    elif action_type == "set_unit_rate":
        # A bare unit-rate change is a price: it MUST be grounded in a catalogue
        # code, otherwise the model is inventing a price (forbidden).
        if source is None:
            return None
        rate = _coerce_number(payload.get("unit_rate"))
        if rate is None or rate < 0:
            return None
        before = {"unit_rate": str(position.unit_rate)}
        clean_payload = {"unit_rate": round(rate, 4)}
        currency = str(payload.get("currency", "")).strip() or default_currency
        if currency:
            clean_payload["currency"] = currency[:10]

    elif action_type == "add_resources":
        resources = _normalise_resources(payload.get("resources"), default_currency=default_currency)
        if not resources:
            return None
        # Resources carry prices -> require at least one cited catalogue code
        # (either at the action level or on an individual resource row).
        has_grounding = source is not None or any(r.get("code") for r in resources)
        if not has_grounding:
            return None
        existing = []
        if isinstance(position.metadata_, dict) and isinstance(position.metadata_.get("resources"), list):
            existing = position.metadata_["resources"]
        projected = list(existing) + resources
        before = {
            "unit_rate": str(position.unit_rate),
            "resource_count": len(existing),
        }
        clean_payload = {
            "resources": resources,
            # Informational: the unit_rate the user can expect after apply
            # (update_position re-derives it authoritatively, with FX).
            "expected_unit_rate": str(_resources_unit_rate(projected)),
        }
    else:  # pragma: no cover - guarded by the allow-set above
        return None

    return CopilotActionProposal(
        action_type=action_type,  # type: ignore[arg-type]
        payload=clean_payload,
        before=before,
        confidence=confidence,
        source=source,
        status="needs_review",
    )


def _position_update_for(
    action: CopilotActionProposal,
    position: Position,
    source: str,
) -> PositionUpdate:
    """Map a proposal to the ``PositionUpdate`` the service write path expects.

    For ``add_resources`` we append to the EXISTING ``metadata.resources`` and
    pass the full ``metadata`` so ``update_position`` re-derives ``unit_rate``
    from the resource breakdown (its trigger is "resources list changed").

    Every update carries ``source`` and ``confidence`` so the row records that
    the copilot wrote it. ``source`` comes from the caller because that is the
    only thing distinguishing the two write paths; ``confidence`` is the model's
    own figure for this proposal, the same number the auto-apply gate compared
    against.
    """
    at = action.action_type
    payload = action.payload
    provenance: dict[str, Any] = {"source": source, "confidence": action.confidence}

    if at == "update_description":
        return PositionUpdate(description=str(payload["description"]), **provenance)

    if at == "set_quantity":
        kwargs: dict[str, Any] = {"quantity": float(payload["quantity"]), **provenance}
        if "unit" in payload:
            kwargs["unit"] = str(payload["unit"])
        return PositionUpdate(**kwargs)

    if at == "set_unit_rate":
        return PositionUpdate(unit_rate=Decimal(str(payload["unit_rate"])), **provenance)

    if at == "add_resources":
        existing_meta = dict(position.metadata_) if isinstance(position.metadata_, dict) else {}
        existing_resources = existing_meta.get("resources")
        existing_list = list(existing_resources) if isinstance(existing_resources, list) else []
        new_resources = payload.get("resources") or []
        existing_meta["resources"] = existing_list + list(new_resources)
        return PositionUpdate(metadata=existing_meta, **provenance)

    # Unreachable: action_type is constrained by the schema Literal.
    msg = f"unsupported copilot action_type: {at}"
    raise ValueError(msg)


# ── Service ─────────────────────────────────────────────────────────────────


class BOQCopilotService:
    """Stateless business logic for the per-position AI copilot."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- ownership / loading --------------------------------------------------

    async def _load_position_scoped(
        self,
        position_id: uuid.UUID,
        user: dict[str, Any],
    ) -> Position:
        """Load a position after verifying the caller owns its BOQ's project.

        Reuses ``_verify_boq_owner`` (the exact check the position routes use),
        so a missing position is 404 and a cross-tenant one is also 404 - before any
        data is returned or mutated. ``user`` is the JWT payload (carries
        ``sub``/``role``); admins bypass via the same path the routes use.
        """
        from app.modules.boq.models import Position
        from app.modules.boq.router import _verify_boq_owner

        position = await self.session.get(Position, position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Position not found",
            )
        user_id = str(user.get("sub") or user.get("user_id") or "")
        await _verify_boq_owner(self.session, position.boq_id, user_id, user)
        return position

    async def _load_project(self, boq_id: uuid.UUID) -> Project | None:
        """Load the project that owns a BOQ (for region / currency / grounding)."""
        from app.modules.boq.repository import BOQRepository
        from app.modules.projects.repository import ProjectRepository

        boq = await BOQRepository(self.session).get_by_id(boq_id)
        if boq is None:
            return None
        return await ProjectRepository(self.session).get_by_id(boq.project_id)

    # -- messages -------------------------------------------------------------

    async def list_messages(
        self,
        session: AsyncSession,
        position_id: uuid.UUID,
        user: dict[str, Any],
    ) -> list[CopilotMessageOut]:
        """Return the tenant-scoped copilot thread for a position (oldest first)."""
        await self._load_position_scoped(position_id, user)
        rows = (
            (
                await session.execute(
                    select(PositionCopilotMessage)
                    .where(PositionCopilotMessage.position_id == position_id)
                    .order_by(PositionCopilotMessage.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return [self._to_message_out(r) for r in rows]

    def _to_message_out(self, row: PositionCopilotMessage) -> CopilotMessageOut:
        """Coerce a stored row into the API shape (actions JSON -> proposals)."""
        actions: list[CopilotActionProposal] = []
        if isinstance(row.actions, list):
            for a in row.actions:
                if not isinstance(a, dict):
                    continue
                try:
                    actions.append(CopilotActionProposal.model_validate(a))
                except Exception:
                    logger.debug("dropping unparseable stored copilot action", exc_info=True)
        return CopilotMessageOut(
            id=row.id,
            position_id=row.position_id,
            boq_id=row.boq_id,
            project_id=row.project_id,
            role=row.role,
            content=row.content,
            actions=actions,
            created_at=row.created_at,
            created_by=row.created_by,
        )

    async def _persist(
        self,
        *,
        position: Position,
        project_id: uuid.UUID,
        role: str,
        content: str,
        actions: list[CopilotActionProposal] | None,
        user_id: uuid.UUID | None,
    ) -> PositionCopilotMessage:
        """Insert one copilot message row and return the flushed instance."""
        row = PositionCopilotMessage(
            position_id=position.id,
            boq_id=position.boq_id,
            project_id=project_id,
            role=role,
            content=content,
            actions=[a.model_dump(mode="json") for a in actions] if actions else None,
            created_by=user_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    # -- chat -----------------------------------------------------------------

    async def chat(
        self,
        session: AsyncSession,
        position_id: uuid.UUID,
        message: str,
        user: dict[str, Any],
        settings: Any,
    ) -> CopilotChatResponse:
        """Run one copilot turn for a position.

        Verifies ownership, grounds against the cost catalogue, asks the model
        for STRICT JSON proposals, auto-applies high-confidence actions through
        ``update_position``, persists the user + assistant turns, and returns the
        assistant turn plus the proposal list.

        When no AI provider is configured the user turn is still persisted and a
        friendly assistant message is returned with no actions (HTTP 200) - the
        copilot degrades gracefully rather than erroring.
        """
        from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model
        from app.modules.ai.prompts import sanitize_user_text

        position = await self._load_position_scoped(position_id, user)
        project = await self._load_project(position.boq_id)
        project_id = project.id if project is not None else (await self._project_id_fallback(position))
        region = (getattr(project, "region", "") or "") if project else ""
        currency = (getattr(project, "currency", "") or "") if project else ""

        user_id = self._user_uuid(user)
        clean_message = sanitize_user_text(message, max_len=2000)

        # Persist the user's turn up front so it survives the no-key / error paths.
        await self._persist(
            position=position,
            project_id=project_id,
            role="user",
            content=clean_message,
            actions=None,
            user_id=user_id,
        )

        # No provider configured -> friendly assistant message, empty actions, 200.
        try:
            provider, api_key, model_override = resolve_provider_key_model(settings)
        except ValueError:
            assistant_row = await self._persist(
                position=position,
                project_id=project_id,
                role="assistant",
                content=(
                    "AI is not configured. Add an API key in Settings > AI (or set an "
                    "environment variable such as ANTHROPIC_API_KEY) to use the position copilot."
                ),
                actions=[],
                user_id=None,
            )
            await self.session.commit()
            return CopilotChatResponse(
                assistant_message=self._to_message_out(assistant_row),
                actions=[],
            )

        # Grounding + sibling context.
        siblings = await self._load_siblings(position)
        candidates = await _ground_candidates(self.session, message=clean_message, position=position, region=region)
        prompt = _build_user_prompt(
            message=clean_message,
            position=position,
            project=project,
            siblings=siblings,
            candidates=candidates,
        )

        # Call the model. A provider failure becomes a friendly assistant turn
        # (200) rather than a 5xx - the chat thread is the product surface.
        reply_text = ""
        raw_actions: list[Any] = []
        try:
            raw_response, _tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=COPILOT_SYSTEM_PROMPT,
                prompt=prompt,
                max_tokens=2048,
                model=model_override,
            )
            parsed = extract_json(raw_response)
            if isinstance(parsed, dict):
                reply_text = str(parsed.get("reply") or "").strip()
                maybe = parsed.get("actions")
                if isinstance(maybe, list):
                    raw_actions = maybe
            elif isinstance(parsed, list):
                raw_actions = parsed
            if not reply_text:
                reply_text = (raw_response or "").strip() or "I could not produce a suggestion for that."
        except Exception as exc:  # noqa: BLE001 - surface as a friendly chat turn
            logger.warning("copilot AI call failed for position %s: %s", position_id, exc)
            assistant_row = await self._persist(
                position=position,
                project_id=project_id,
                role="assistant",
                content=f"The AI request did not complete: {exc}",
                actions=[],
                user_id=None,
            )
            await self.session.commit()
            return CopilotChatResponse(
                assistant_message=self._to_message_out(assistant_row),
                actions=[],
            )

        # Build validated proposals, then apply the high-confidence ones.
        proposals: list[CopilotActionProposal] = []
        for raw_action in raw_actions:
            if not isinstance(raw_action, dict):
                continue
            proposal = _build_proposal(
                raw_action,
                position=position,
                candidates=candidates,
                default_currency=currency,
            )
            if proposal is None:
                continue
            if proposal.confidence >= AUTO_APPLY_THRESHOLD:
                # Auto-apply, wrapped so one failure never fails the whole chat.
                try:
                    await self._apply_via_service(position_id, proposal, user_id, source=SOURCE_AUTO_APPLIED)
                    proposal.status = "auto_applied"
                    # Refresh the in-memory position so a second action in the
                    # same turn sees the latest resources/quantity.
                    refreshed = await self.session.get(type(position), position_id)
                    if refreshed is not None:
                        position = refreshed
                except Exception as exc:  # noqa: BLE001 - per-action isolation
                    logger.warning("copilot auto-apply failed for position %s: %s", position_id, exc)
                    proposal.status = "failed"
                    proposal.error = str(exc)[:300]
            else:
                proposal.status = "needs_review"
            proposals.append(proposal)

        assistant_row = await self._persist(
            position=position,
            project_id=project_id,
            role="assistant",
            content=reply_text,
            actions=proposals,
            user_id=None,
        )
        await self.session.commit()
        return CopilotChatResponse(
            assistant_message=self._to_message_out(assistant_row),
            actions=proposals,
        )

    # -- apply ----------------------------------------------------------------

    async def apply_action(
        self,
        session: AsyncSession,
        position_id: uuid.UUID,
        action: CopilotActionProposal,
        user: dict[str, Any],
    ) -> tuple[Position, CopilotActionProposal]:
        """Apply a single previously-proposed action via ``update_position``.

        Verifies ownership, applies the change, persists a short audit turn, and
        returns the updated position plus the action stamped ``applied`` (or
        ``failed`` with an ``error`` note). Raises 422 only when the action is
        structurally un-appliable; an apply-time error is captured on the action
        and returned with status ``failed`` so the caller still gets the (un
        changed) position back.
        """
        position = await self._load_position_scoped(position_id, user)
        project_id = await self._project_id_fallback(position)
        user_id = self._user_uuid(user)

        try:
            updated = await self._apply_via_service(position_id, action, user_id, source=SOURCE_HUMAN_ACCEPTED)
            action.status = "applied"
            action.error = ""
            await self._persist(
                position=updated,
                project_id=project_id,
                role="assistant",
                content=f"Applied: {action.action_type}.",
                actions=[action],
                user_id=user_id,
            )
            await self.session.commit()
            return updated, action
        except HTTPException:
            raise
        except ValueError as exc:
            # Structurally bad action (e.g. unknown type / missing payload key).
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Cannot apply action: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - capture apply failure on the action
            logger.warning("copilot apply_action failed for position %s: %s", position_id, exc)
            action.status = "failed"
            action.error = str(exc)[:300]
            await self.session.rollback()
            # Return the un-mutated current position with the failed action.
            current = await self._load_position_scoped(position_id, user)
            return current, action

    async def _apply_via_service(
        self,
        position_id: uuid.UUID,
        action: CopilotActionProposal,
        user_id: uuid.UUID | None,
        source: str,
    ) -> Position:
        """Translate a proposal to a ``PositionUpdate`` and run the write path.

        ``source`` says which path is writing: both the unattended auto-apply and
        the human accept land here, and the row cannot tell them apart otherwise.
        """
        from app.modules.boq.models import Position
        from app.modules.boq.service import BOQService

        position = await self.session.get(Position, position_id)
        if position is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
        update = _position_update_for(action, position, source)
        service = BOQService(self.session)
        return await service.update_position(position_id, update, actor_id=user_id)

    # -- small helpers --------------------------------------------------------

    async def _load_siblings(self, position: Position) -> list[Position]:
        """Up to ``_MAX_SIBLINGS`` other positions in the same BOQ (for context)."""
        from app.modules.boq.repository import PositionRepository

        all_positions = await PositionRepository(self.session).list_all_for_boq(position.boq_id)
        siblings = [p for p in all_positions if p.id != position.id and (p.unit or "") != "section"]
        return siblings[:_MAX_SIBLINGS]

    async def _project_id_fallback(self, position: Position) -> uuid.UUID:
        """Resolve the owning project id for a position (via its BOQ)."""
        from app.modules.boq.repository import PositionRepository

        pid = await PositionRepository(self.session).project_id_for_boq(position.boq_id)
        if pid is None:
            # Should never happen (the BOQ FK guarantees a project), but keep the
            # column non-null with a deterministic zero rather than raising.
            return uuid.UUID(int=0)
        return pid

    @staticmethod
    def _user_uuid(user: dict[str, Any]) -> uuid.UUID | None:
        """Extract the acting user's UUID from the JWT payload, if parseable."""
        raw = str(user.get("sub") or user.get("user_id") or "")
        try:
            return uuid.UUID(raw)
        except (ValueError, TypeError):
            return None
