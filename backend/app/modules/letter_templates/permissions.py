# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Letter templates permission definitions."""

from app.core.permissions import Role, permission_registry


def register_letter_templates_permissions() -> None:
    """Reading a template is open to editors (they issue letters); changing one is for managers.

    A one-off edit of a single letter is not a template change: it is gated by
    the permission that issues the letter (``tendering.distribute``).
    """
    permission_registry.register_module_permissions(
        "letter_templates",
        {
            "letter_templates.read": Role.EDITOR,
            "letter_templates.edit": Role.MANAGER,
        },
    )
