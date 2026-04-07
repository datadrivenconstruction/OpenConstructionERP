"""RFI module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_rfi",
    version="0.1.0",
    display_name="Requests for Information",
    description="RFI management — questions, responses, cost/schedule impact tracking, and drawing cross-references",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
