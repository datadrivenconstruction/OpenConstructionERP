# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Drawing revision compare permission definitions."""

from app.core.permissions import Role, permission_registry


def register_drawing_compare_permissions() -> None:
    """Register the module's permissions.

    Reading compares and exporting the change report is open to viewers.
    Saving a compare, triaging changes and flagging quantities for re-measure
    is editor work; deleting a stored compare is a manager's call because it
    removes the record of what changed between two issued revisions.
    """
    permission_registry.register_module_permissions(
        "drawing_compare",
        {
            "drawing_compare.read": Role.VIEWER,
            "drawing_compare.create": Role.EDITOR,
            "drawing_compare.update": Role.EDITOR,
            "drawing_compare.delete": Role.MANAGER,
        },
    )
