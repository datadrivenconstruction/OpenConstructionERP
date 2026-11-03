# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project document assistant: grounded, cited answers over the project record."""


async def on_startup() -> None:
    """Register permissions and the ``doc_assistant_answer`` validation rule set."""
    from app.modules.doc_assistant.permissions import register_doc_assistant_permissions
    from app.modules.doc_assistant.validators import register_doc_assistant_rules

    register_doc_assistant_permissions()
    register_doc_assistant_rules()
