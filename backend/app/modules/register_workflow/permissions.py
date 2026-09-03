# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Register Workflow permissions."""

from app.core.permissions import Role, permission_registry


def register_register_workflow_permissions() -> None:
    permission_registry.register_module_permissions(
        "register_workflow",
        {
            "register_workflow.read": Role.VIEWER,
            "register_workflow.create": Role.EDITOR,
            "register_workflow.update": Role.EDITOR,
            "register_workflow.delete": Role.MANAGER,
        },
    )


register_register_workflow_permissions()
