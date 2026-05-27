"""‌⁠‍Equipment & Fleet Management module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_equipment",
    version="0.1.0",
    display_name="Equipment & Fleet Management",
    description=(
        "Owned/rented equipment fleet with telemetry, maintenance scheduling, inspections, internal rental billing"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
