# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Owner schedule module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_owner_schedule",
    version="1.0.0",
    display_name="Owner Bid Schedule",
    description=(
        "Imports an owner's bid schedule (pay items in the owner's spreadsheet or CSV) into an estimate in one "
        "step, keeps the owner's item number, text and unit on each position, shows addenda as a diff and writes "
        "the priced schedule back into the owner's own file with the owner's rounding. Format profiles come from "
        "the platform, from packs and from the mapping wizard."
    ),
    author="OpenConstructionERP Core Team",
    category="estimation",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
)
