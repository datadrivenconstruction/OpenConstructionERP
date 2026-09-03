# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Work Requests module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_work_requests",
    version="0.1.0",
    display_name="Work Requests",
    description=(
        "Cross-department work requests: a PM raises work for engineering, "
        "drafting, the workshop, automation or hazardous-area review; each "
        "department runs it through its own stages, logs hours against the "
        "quote, hands off to the next department, and the planner shows the "
        "five-week headcount per board."
    ),
    author="Projects Team",
    category="community",
    depends=["oe_users", "oe_projects"],
    optional_depends=["oe_notifications", "oe_contacts"],
    auto_install=False,
    enabled=True,
)
