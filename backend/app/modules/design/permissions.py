"""Design module permission definitions.

Project-level rights (who edits the design of a project, who accepts a revision) stay per project
(``design-rights``); these are the ERP role floors the routes check on top.
"""

from app.core.permissions import Role, permission_registry


def register_design_permissions() -> None:
    """Register permissions for the Design module."""
    permission_registry.register_module_permissions(
        "design",
        {
            "design.read": Role.VIEWER,
            # brief, drafts, server build, desktop upload (narrowed per project by design-rights)
            "design.edit": Role.EDITOR,
            # accept or reject a revision; change who may edit
            "design.accept": Role.MANAGER,
            # fetch the full browser editor from the release feed onto this server
            "design.web_editor.install": Role.EDITOR,
            "design.web_editor.remove": Role.ADMIN,
        },
    )
