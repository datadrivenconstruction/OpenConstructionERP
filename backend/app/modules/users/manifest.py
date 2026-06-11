"""‌⁠‍Users & authentication module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_users",
    version="0.1.0",
    display_name="Users & Authentication",
    description="User management, JWT authentication, API keys, and RBAC",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],
    auto_install=True,
    enabled=True,
)
