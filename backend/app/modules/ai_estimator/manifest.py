# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""AI Estimate Builder module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_ai_estimator",
    version="0.1.0",
    display_name="AI Estimate Builder",
    description=(
        "Full AI-driven precise estimate from any source. The agent understands "
        "your data, groups quantities, finds exact logical rates with resource "
        "breakdowns, and assembles a validated estimate you confirm. Rates come "
        "only from the cost database, never invented by the LLM."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[
        "oe_users",
        "oe_projects",
        "oe_costs",
        "oe_boq",
        "oe_match_elements",
        "oe_ai",
        "oe_ai_agents",
    ],
    auto_install=True,
    enabled=True,
)
