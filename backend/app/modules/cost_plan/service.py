# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Database layer of the NRM 1 cost plan: read the bill, hand it to the engine.

This writes nothing. It reads a bill exactly the way the bill editor reads it,
so the plan's direct cost and grand total are the editor's to the cent:

* every leaf is converted to the project's base currency by
  ``_leaf_total_base_with_resources``, the helper the structured view, the
  exports and the bill list all use;
* the markup lines come from ``markup_repo.list_for_boq``, the editor's own
  query and order (``sort_order``, then creation time), and their amounts from
  ``_calculate_markup_amounts_scoped``, the bill's one markup engine;
* an escalation line whose index cannot be resolved refuses the plan with the
  same 409 the editor gives (``strict=True``). A cost plan is a figure somebody
  signs, and a total that quietly left a line out is not one.

Those helpers are private to the BOQ module by name. They are called rather
than copied on purpose: a second copy of the markup cascade is the one thing
this module must never contain.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import Position
from app.modules.boq.service import (
    BOQService,
    _calculate_markup_amounts_scoped,
    _is_section,
    _leaf_total_base_with_resources,
    is_empty_position,
)
from app.modules.cost_plan.engine import LeafInput, MarkupInput, build_cost_plan
from app.modules.cost_plan.schemas import CostPlanResponse

logger = logging.getLogger(__name__)

__all__ = ["build_nrm1_cost_plan", "parse_gifa"]


def parse_gifa(raw: object) -> Decimal | None:
    """Read a floor area, or None when it is absent or not a positive number.

    Used for the project's stored ``gross_floor_area``, a free decimal string,
    where an unreadable value means "no area" rather than an error: the plan
    still renders, only without cost per m2.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    return value


def _nrm_code(position: Position) -> object:
    """The position's own NRM code as written, or None."""
    classification = position.classification if isinstance(position.classification, dict) else {}
    value = classification.get("nrm")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return value


def _inherited_codes(positions: list[Position]) -> dict[uuid.UUID, object]:
    """For each position, the nearest ancestor's NRM code, if any.

    Walks parent links with a seen-set, because a corrupt tree can point a
    position at its own descendant and the walk must end anyway.
    """
    by_id = {p.id: p for p in positions}
    result: dict[uuid.UUID, object] = {}
    for position in positions:
        seen: set[uuid.UUID] = {position.id}
        current = position.parent_id
        while current is not None and current not in seen:
            seen.add(current)
            parent = by_id.get(current)
            if parent is None:
                break
            code = _nrm_code(parent)
            if code is not None:
                result[position.id] = code
                break
            current = parent.parent_id
    return result


async def _project_gifa(session: AsyncSession, project_id: uuid.UUID) -> Decimal | None:
    """The project's stored gross floor area in m2, if it holds a usable one."""
    from app.modules.projects.models import Project  # noqa: PLC0415 - keep the import graph narrow

    row = (await session.execute(select(Project.gross_floor_area).where(Project.id == project_id))).first()
    return parse_gifa(row[0]) if row else None


async def build_nrm1_cost_plan(
    session: AsyncSession,
    boq_id: uuid.UUID,
    *,
    entered_gifa: Decimal | None = None,
) -> CostPlanResponse:
    """Roll one bill up into the NRM 1 elemental structure.

    Args:
        session: The request's database session.
        boq_id: The bill to read.
        entered_gifa: A floor area the reader typed. It wins over the project's
            stored area and is not saved. The caller validates it is positive.

    Returns:
        The cost plan.

    Raises:
        HTTPException: 404 when the bill does not exist, 409 when an escalation
            line names an index that cannot be resolved.
    """
    service = BOQService(session)
    boq = await service.get_boq(boq_id)
    positions = await service.position_repo.list_all_for_boq(boq_id)
    base_currency, fx_map = await service._resolve_project_fx(boq_id)  # noqa: SLF001 - the bill's own FX read

    def leaf_amount(position: Position) -> Decimal:
        return _leaf_total_base_with_resources(position, fx_map, base_currency or "")

    inherited = _inherited_codes(positions)
    leaves: list[LeafInput] = []
    direct_cost = Decimal("0")
    for position in positions:
        if _is_section(position):
            continue
        amount = leaf_amount(position)
        direct_cost += amount
        leaves.append(
            LeafInput(
                id=position.id,
                ordinal=position.ordinal or "",
                description=position.description or "",
                amount=amount,
                code=_nrm_code(position),
                inherited_code=inherited.get(position.id),
                listable=not (amount == 0 and is_empty_position(position)),
            )
        )

    markups = await service.markup_repo.list_for_boq(boq_id)
    escalation = await service._resolve_escalation_factors(markups)  # noqa: SLF001 - strict, as the editor
    calculated = _calculate_markup_amounts_scoped(direct_cost, markups, positions, leaf_amount, escalation.factors)
    markup_inputs = [
        MarkupInput(
            id=markup.id,
            name=markup.name,
            category=markup.category or "other",
            markup_type=markup.markup_type or "percentage",
            apply_to=markup.apply_to or "direct_cost",
            amount=amount,
            percentage=_decimal_or_none(markup.percentage)
            if (markup.markup_type or "percentage") == "percentage"
            else None,
            fixed_amount=_decimal_or_none(markup.fixed_amount) if markup.markup_type == "fixed" else None,
            scoped=markup.scope_position_id is not None,
        )
        for markup, amount in calculated
        # An inactive line contributes nothing to the cascade and is not
        # printed. A scoped line that is inactive is simply not there.
        if markup.is_active
    ]

    gifa: Decimal | None
    gifa_source: Literal["project", "entered", "none"]
    if entered_gifa is not None:
        gifa, gifa_source = entered_gifa, "entered"
    else:
        gifa = await _project_gifa(session, boq.project_id)
        gifa_source = "project" if gifa is not None else "none"

    return build_cost_plan(
        boq_id=boq.id,
        boq_name=boq.name,
        project_id=boq.project_id,
        currency=(base_currency or "").upper(),
        leaves=leaves,
        markups=markup_inputs,
        gifa=gifa,
        gifa_source=gifa_source,
    )


def _decimal_or_none(raw: Any) -> Decimal | None:
    """A stored decimal string as Decimal, or None when it is not a number."""
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return value if value.is_finite() else None
