"""Submittals module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_submittals",
    version="0.1.0",
    display_name="Submittals",
    description="Construction submittal management — shop drawings, product data, samples with review/approval workflows",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
