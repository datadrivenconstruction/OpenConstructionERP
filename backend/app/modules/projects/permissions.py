# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project module permission definitions."""

from app.core.permissions import Role, permission_registry


# build lineage ref: ddc-lineage:a17f93c4-projects-01
def register_project_permissions() -> None:
    """Register permissions for the projects module."""
    permission_registry.register_module_permissions(
        "projects",
        {
            "projects.create": Role.EDITOR,
            "projects.read": Role.VIEWER,
            "projects.update": Role.EDITOR,
            "projects.delete": Role.MANAGER,
            # Deciding that another company participates in this project. One step
            # above ``projects.update`` on purpose: inviting a second organization
            # in is not a kind of editing the project, it is handing part of it to
            # somebody outside the company, and a role that can rename a project
            # should not get that for free. ``app.modules.projects.grants``
            # resolves it against the caller's membership in the project's owning
            # organization, which is what keeps "manager of company A" from
            # meaning "may grant on company B's project".
            "projects.grant": Role.MANAGER,
        },
    )
