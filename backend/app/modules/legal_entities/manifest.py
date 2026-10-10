# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Legal Entities module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_legal_entities",
    version="0.1.0",
    display_name="Legal Entities",
    description="Companies of the group and their branches, each with its country and functional currency",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],
    auto_install=True,
    enabled=True,
)
