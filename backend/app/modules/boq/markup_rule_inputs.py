# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The markup amounts a bill's validation reads, computed by the bill's own engine.

A rule that reports how much the markups add (the Italian general expenses and
profit check, for one) needs each line's amount. Working it out again inside
the rule would make a second markup engine, and the first one already knows
the escalation factors, the scoped overrides and the currency conversion a
rule cannot see. So the validate endpoint asks :meth:`BOQService.calculate_markups`
once and hands each line's amount to the rules beside the line itself.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

if TYPE_CHECKING:
    import uuid

    from app.modules.boq.service import BOQService

logger = logging.getLogger(__name__)


async def markup_amounts_for_rules(
    service: BOQService, boq_id: uuid.UUID, markups_data: list[dict[str, Any]]
) -> dict[str, Any]:
    """Stamp ``amount`` on each markup dict and return the direct cost they were computed on.

    Args:
        service: The BOQ service of the request.
        boq_id: The bill being validated.
        markups_data: The markup dicts handed to the rules, keyed by ``id``;
            each one that the engine priced gets ``amount`` as a string.

    Returns:
        ``{"markup_direct_cost": "<decimal>"}`` for the validation data, or an
        empty dict when the engine refused the stack. It refuses (409) when an
        escalation line names an index period that does not exist; the
        estimator fixes that in the markup editor, and validation must still
        run meanwhile, so the rules then compute from the lines alone.
    """
    try:
        direct_cost, calculated = await service.calculate_markups(boq_id)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        logger.info("Markup amounts left to the rules for BOQ %s: %s", boq_id, exc.detail)
        return {}
    amounts = {str(markup.id): amount for markup, amount in calculated}
    for markup in markups_data:
        amount = amounts.get(str(markup.get("id")))
        if amount is not None:
            markup["amount"] = format(amount, "f")
    return {"markup_direct_cost": format(direct_cost, "f")}


__all__ = ["markup_amounts_for_rules"]
