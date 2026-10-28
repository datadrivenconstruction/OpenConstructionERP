# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠California regional pack API routes.

Endpoints:
    GET /config          - Return the full California regional configuration
    GET /rules           - Return the California state rules, grouped by topic
    GET /rules/{topic}   - Return one topic (sales_tax, prevailing_wage, ...)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user_id
from app.modules.us_ca_pack.config import PACK_CONFIG, STATE_RULES

router = APIRouter(dependencies=[Depends(get_current_user_id)])
logger = logging.getLogger(__name__)


@router.get("/config/")
async def get_config() -> dict:
    """Return the California regional pack configuration."""
    return PACK_CONFIG


@router.get("/rules/")
async def get_rules() -> dict:
    """Return every California state rule, grouped by topic."""
    return {"topics": sorted(STATE_RULES), "rules": STATE_RULES}


@router.get("/rules/{topic}/")
async def get_rules_for_topic(topic: str) -> dict:
    """Return the California rules for one topic.

    Args:
        topic: One of the keys of ``STATE_RULES``, for example ``sales_tax``.

    Raises:
        HTTPException: 404 when the topic is not one this pack carries. The
            message lists the topics that exist, because a caller that guessed
            the name needs to see the real ones rather than an empty list.
    """
    rules = STATE_RULES.get(topic)
    if rules is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown California rule topic {topic!r}. Known topics: {', '.join(sorted(STATE_RULES))}.",
        )
    return {"topic": topic, "rules": rules}
