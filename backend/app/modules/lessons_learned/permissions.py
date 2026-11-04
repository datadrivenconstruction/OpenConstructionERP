# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lessons learned permission definitions."""

from app.core.permissions import Role, permission_registry

# Editors write drafts; a manager confirms, because a confirmed lesson is shown on other projects.
LESSONS_LEARNED_PERMISSIONS: dict[str, Role] = {
    "lessons_learned.read": Role.VIEWER,
    "lessons_learned.create": Role.EDITOR,
    "lessons_learned.update": Role.EDITOR,
    "lessons_learned.confirm": Role.MANAGER,
    "lessons_learned.delete": Role.MANAGER,
}


def register_lessons_learned_permissions() -> None:
    """Register permissions for the lessons learned module."""
    permission_registry.register_module_permissions("lessons_learned", LESSONS_LEARNED_PERMISSIONS)
