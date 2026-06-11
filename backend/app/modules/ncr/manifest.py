"""‌⁠‍NCR module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_ncr",
    version="0.1.0",
    display_name="Non-Conformance Reports",
    description="NCR management - material, workmanship, design non-conformances with root cause analysis and corrective actions",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
