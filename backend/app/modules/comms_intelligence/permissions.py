# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Comms Intelligence permission declarations.

Reading the smarts is viewer-level (same as reading correspondence);
anything that spends AI tokens or mutates a register row on confirm is
editor-level, matching correspondence.create/update.
"""

from app.core.permissions import Role, permission_registry


def register_comms_intelligence_permissions() -> None:
    permission_registry.register_module_permissions(
        "comms_intelligence",
        {
            "comms_intelligence.read": Role.VIEWER,
            "comms_intelligence.analyze": Role.EDITOR,
            "comms_intelligence.review": Role.EDITOR,
            "comms_intelligence.draft": Role.EDITOR,
        },
    )


register_comms_intelligence_permissions()
