# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""FastAPI dependencies for the survey register."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status

from app.dependencies import get_current_user_payload
from app.modules.survey_core.permissions import CONFIRM, can_confirm


async def require_survey_confirm(payload: Annotated[dict[str, Any], Depends(get_current_user_payload)]) -> None:
    """FastAPI dependency: 403 unless the caller may confirm survey results."""
    if not can_confirm(payload):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {CONFIRM}")
