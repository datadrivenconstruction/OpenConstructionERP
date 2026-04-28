"""BOQ module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_boq_permissions() -> None:
    """Register permissions for the BOQ module."""
    # `boq.create` deliberately granted to VIEWER: every signed-in user
    # (including freshly self-registered viewers caught by the RBAC
    # regression in issue #101) must be able to start an estimate.
    # Project ownership / membership is enforced by the service layer,
    # so a viewer can still only create BOQs in projects they own or are
    # invited to. Update / delete remain editor-gated.
    permission_registry.register_module_permissions(
        "boq",
        {
            "boq.create": Role.VIEWER,
            "boq.read": Role.VIEWER,
            "boq.update": Role.EDITOR,
            "boq.delete": Role.EDITOR,
            "boq.export": Role.VIEWER,
            "boq.import": Role.EDITOR,
        },
    )
