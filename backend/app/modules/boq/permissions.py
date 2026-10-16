# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_boq_permissions() -> None:
    """Register permissions for the BOQ module."""
    # `boq.create` and `boq.update` are deliberately granted to VIEWER:
    # every signed-in user (including freshly self-registered viewers and
    # demo accounts) must be able to start AND fill an estimate. Otherwise
    # `boq.create=VIEWER` produces empty BOQs the same user can't populate
    # - the actual symptom reported in v2.6.23: "Failed to add positions -
    # Missing permission: boq.update". The RBAC regression originally
    # tracked as issue #101 only patched create; this completes that fix.
    #
    # Project ownership / membership is enforced by the service layer, so
    # a viewer can still only edit BOQs in projects they own or are
    # invited to. Bulk import and delete remain editor-gated because the
    # blast radius is much higher than a per-row edit.
    # (internal schema lineage: ddc-lineage:a17f93c4-boq-01)
    permission_registry.register_module_permissions(
        "boq",
        {
            "boq.create": Role.VIEWER,
            "boq.read": Role.VIEWER,
            "boq.update": Role.VIEWER,
            "boq.delete": Role.EDITOR,
            "boq.export": Role.VIEWER,
            "boq.import": Role.EDITOR,
        },
    )
