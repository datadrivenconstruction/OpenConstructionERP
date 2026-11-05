# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document Management module.

Manages project documents (drawings, contracts, specifications, photos)
with file upload/download, categorization, and tagging.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.documents.permissions import register_document_permissions

    register_document_permissions()

    from app.modules.documents.validators import register_documents_validation_rules

    register_documents_validation_rules()
