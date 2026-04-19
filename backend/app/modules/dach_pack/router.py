"""DACH regional pack API routes.

Endpoints:
    GET /config  — Return the full DACH regional configuration
"""

import logging

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user_id
from app.modules.dach_pack.config import PACK_CONFIG

router = APIRouter(dependencies=[Depends(get_current_user_id)])
logger = logging.getLogger(__name__)


@router.get("/config/")
async def get_config() -> dict:
    """Return the DACH regional pack configuration."""
    return PACK_CONFIG
