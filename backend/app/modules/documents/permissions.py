"""Document Management module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_document_permissions() -> None:
    """Register permissions for the document management module."""
    permission_registry.register_module_permissions(
        "documents",
        {
            "documents.create": Role.EDITOR,
            "documents.read": Role.VIEWER,
            "documents.update": Role.EDITOR,
            "documents.delete": Role.MANAGER,
        },
    )
