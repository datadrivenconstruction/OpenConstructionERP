# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compliance-AI module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.compliance_ai.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_compliance_ai",
    version="0.1.0",
    display_name="Compliance AI",
    description=(
        "DSL-based compliance rule engine plus a natural-language rule "
        "builder powered by Claude. Rules compile into core ValidationRule "
        "subclasses so evaluation uses the single validation pipeline."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_dashboards"],
    optional_depends=["oe_ai"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
