# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document template permissions and the Document manager role.

Everyone signed in may read wording. Editing and publishing are admin by
default; an admin can grant the *Document manager* role to any user, which
allows both without making them an admin. The grant lives on the user's
metadata under :data:`DOC_MANAGER_KEY`.
"""

from __future__ import annotations

from typing import Any

from app.core.permissions import Role, permission_registry

DOC_MANAGER_KEY = "doc_templates_manager"


def register_doc_templates_permissions() -> None:
    """Read for viewers; edit and publish for admins and granted Document managers."""
    permission_registry.register_module_permissions(
        "doc_templates",
        {
            "doc_templates.read": Role.VIEWER,
            "doc_templates.edit": Role.ADMIN,
            "doc_templates.publish": Role.ADMIN,
        },
    )


def is_doc_manager(role: str | None, metadata: dict[str, Any] | None) -> bool:
    """Whether a user may edit and publish document templates."""
    if (role or "").strip().lower() in {"admin", "superuser", "owner"}:
        return True
    return bool((metadata or {}).get(DOC_MANAGER_KEY) is True)
