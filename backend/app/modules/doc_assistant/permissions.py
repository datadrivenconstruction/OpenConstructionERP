# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document assistant permissions."""

from app.core.permissions import Role, permission_registry


def register_doc_assistant_permissions() -> None:
    """Asking is a read; keeping an answer writes a note or an RFI draft."""
    permission_registry.register_module_permissions(
        "doc_assistant",
        {
            "doc_assistant.ask": Role.VIEWER,
            "doc_assistant.save": Role.EDITOR,
        },
    )
