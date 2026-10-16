# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_boq_permissions() -> None:
    """Register permissions for the BOQ module."""
    # `boq.update` is deliberately granted to VIEWER: a viewer invited to a
    # project must be able to fill an estimate there (v2.6.23: "Failed to
    # add positions - Missing permission: boq.update"). Project ownership /
    # membership is enforced by the service layer, so a viewer can still
    # only edit BOQs in projects they own or are invited to.
    #
    # `boq.create` is EDITOR, the same rank as `boq.delete`. When create was
    # VIEWER, a viewer could start estimates (new, from template, duplicate,
    # revision) that the same viewer could never remove again, and the
    # leftovers piled up for an admin to clean. Creating a BOQ is the same
    # tier as creating the project it lives in (`projects.create=EDITOR`).
    # Bulk import and delete stay editor-gated as well.
    # (internal schema lineage: ddc-lineage:a17f93c4-boq-01)
    permission_registry.register_module_permissions(
        "boq",
        {
            "boq.create": Role.EDITOR,
            "boq.read": Role.VIEWER,
            "boq.update": Role.VIEWER,
            "boq.delete": Role.EDITOR,
            "boq.export": Role.VIEWER,
            "boq.import": Role.EDITOR,
        },
    )
