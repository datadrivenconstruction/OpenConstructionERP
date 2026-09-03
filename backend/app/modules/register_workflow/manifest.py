# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Register Workflow module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_register_workflow",
    version="0.1.0",
    display_name="Register Workflow",
    description=(
        "Tier-one workflows for every register: ordered steps, ⛔ gates that "
        "somebody signs, 🔀 routes that append the path actually taken, and "
        "completed steps kept as immutable history."
    ),
    author="Projects Team",
    category="community",
    depends=["oe_users", "oe_projects"],
    optional_depends=["oe_rfq_bidding", "oe_correspondence", "oe_rfi"],
    auto_install=False,
    enabled=True,
)
