# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Letter templates module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_letter_templates",
    version="1.0.0",
    display_name="Letter Templates",
    description=(
        "Editable wording of generated letters and emails (award letter, rejection notice, "
        "invitation to tender) per language, for the company and per project."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
)
