"""Cost-match router — populated by T12."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.cost_match.manifest import manifest

router = APIRouter(prefix="/cost-match", tags=["Cost Match"])


@router.get("/_health", include_in_schema=False)
async def module_health() -> dict[str, str]:
    return {
        "module": manifest.name,
        "version": manifest.version,
        "status": "healthy",
    }
