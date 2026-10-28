# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠China regional pack API routes.

Endpoints:
    GET /config  - Return the full China regional configuration
"""

import logging

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user_id
from app.modules.china_pack.config import PACK_CONFIG

router = APIRouter(dependencies=[Depends(get_current_user_id)], tags=["china_pack"])
logger = logging.getLogger(__name__)


@router.get("/config/")
async def get_config() -> dict:
    """Return the China regional pack configuration."""
    return PACK_CONFIG
