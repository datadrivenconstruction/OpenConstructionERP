# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Letter templates: editable wording of the letters modules send out.

The registry of letters and their shipped defaults lives in
:mod:`app.core.letter_templates`. This module stores what a company changes:
one override per letter and language for the whole installation, and
optionally one per project. Resolution order is project, then company, then
the shipped default.
"""


async def on_startup() -> None:
    """Register permissions, validation rules and the known letters."""
    from app.modules.letter_templates.permissions import register_letter_templates_permissions
    from app.modules.letter_templates.validators import register_letter_template_rules
    from app.modules.tendering.letter_texts import register_tendering_letter_templates

    register_letter_templates_permissions()
    register_letter_template_rules()
    register_tendering_letter_templates()
