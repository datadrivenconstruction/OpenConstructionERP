"""Inspections module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_inspections",
    version="0.1.0",
    display_name="Quality Inspections",
    description="Quality inspection management — concrete pours, waterproofing, MEP, fire stopping, handover with checklists and pass/fail workflows",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
