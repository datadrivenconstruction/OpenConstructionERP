"""‌⁠‍QMS module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_qms",
    version="1.0.0",
    display_name="Quality Management System (QMS)",
    description=("Unified ITP + Inspections + NCR + Punch List + Audits with COPQ analytics"),
    author="OpenConstructionERP",
    category="extension",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
)
