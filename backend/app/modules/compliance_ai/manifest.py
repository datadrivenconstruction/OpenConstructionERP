"""Compliance-AI module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_compliance_ai",
    version="0.1.0",
    display_name="Compliance AI",
    description=(
        "DSL-based compliance rule engine plus a natural-language rule "
        "builder powered by Claude. Rules compile into core ValidationRule "
        "subclasses so evaluation uses the single validation pipeline."
    ),
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_dashboards"],
    optional_depends=["oe_ai"],
    auto_install=True,
    enabled=True,
)
