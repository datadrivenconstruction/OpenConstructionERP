"""ACAP module API routes."""

from fastapi import APIRouter

router = APIRouter(tags=["acap"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for the ACAP module. Unauthenticated."""
    return {"status": "ok", "module": "acap"}
