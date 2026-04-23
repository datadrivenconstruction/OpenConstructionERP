"""Dashboards module API router.

Endpoints are mounted incrementally as each task in CLAUDE-DASHBOARDS.md
lands. Today the router carries only the module-health ping so the
module loader can confirm the mount and so the smoke test in
``tests/unit/test_dashboards_scaffolding.py`` has something to hit.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.dashboards.manifest import manifest

router = APIRouter(prefix="/dashboards", tags=["Dashboards"])


@router.get("/_health", include_in_schema=False)
async def module_health() -> dict[str, str]:
    """Module-scoped health probe — mirrors the `/api/health` shape."""
    return {
        "module": manifest.name,
        "version": manifest.version,
        "status": "healthy",
    }
