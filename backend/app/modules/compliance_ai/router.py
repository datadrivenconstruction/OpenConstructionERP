"""Compliance-AI router — populated incrementally by T08 and T13."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.compliance_ai.manifest import manifest

router = APIRouter(prefix="/compliance-ai", tags=["Compliance AI"])


@router.get("/_health", include_in_schema=False)
async def module_health() -> dict[str, str]:
    return {
        "module": manifest.name,
        "version": manifest.version,
        "status": "healthy",
    }
