"""Russia & CIS regional pack API routes.

Endpoints:
    GET /config  — Return the full Russia & CIS regional configuration
"""

import logging

from fastapi import APIRouter

from app.modules.russia_pack.config import PACK_CONFIG

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/config")
async def get_config() -> dict:
    """Return the Russia & CIS regional pack configuration."""
    return PACK_CONFIG
