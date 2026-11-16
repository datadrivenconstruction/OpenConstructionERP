# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Documents and templates: a firm's wording of every PDF and email it sends.

The neutral core lives in :mod:`app.core.doc_templates` (registry, merge
engine, rules, resolver, generic PDF, pack legal blocks). This module stores
drafts and immutable published versions per kind and language, and serves the
editor, preview and test send.
"""


async def on_startup() -> None:
    """Register permissions, validation rules and the built-in kinds."""
    from app.modules.doc_templates.kinds import register_builtin_kinds
    from app.modules.doc_templates.permissions import register_doc_templates_permissions
    from app.modules.doc_templates.validators import register_doc_template_rules

    register_doc_templates_permissions()
    register_doc_template_rules()
    register_builtin_kinds()
