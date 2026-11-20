# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey register permissions.

Anyone with project read can view, an editor can import, and confirming
(a detected CRS, a CRS change once points exist, later volumes and parcels)
needs ``survey.confirm``: managers and admins by default, plus the surveyor
role, which otherwise works as an editor. Kept free of web-framework imports so
scripts can read the registry; the FastAPI dependency lives in ``dependencies.py``.
"""

from __future__ import annotations

from typing import Any

from app.core.permissions import Role, permission_registry

SURVEYOR_ROLE = "surveyor"
CONFIRM = "survey.confirm"


def register_survey_permissions() -> None:
    """Register permissions for the survey register."""
    permission_registry.register_module_permissions(
        "survey_core",
        {
            "survey.read": Role.VIEWER,
            "survey.write": Role.EDITOR,
            CONFIRM: Role.MANAGER,
        },
    )


def can_confirm(payload: dict[str, Any]) -> bool:
    """Whether the token's holder may confirm survey results."""
    role = str(payload.get("role") or "").strip().lower()
    if role in (Role.ADMIN.value, SURVEYOR_ROLE):
        return True
    if CONFIRM in (payload.get("permissions") or []):
        return True
    return permission_registry.role_has_permission(role, CONFIRM)
