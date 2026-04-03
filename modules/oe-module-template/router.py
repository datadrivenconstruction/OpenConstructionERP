"""Module API routes.

Routes are auto-mounted at /api/v1/{module_name}/.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def module_info():
    """Return module status."""
    return {"module": "oe_template", "status": "active"}
