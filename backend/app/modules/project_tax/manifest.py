# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_project_tax."""

from app.core.module_loader import ModuleManifest
from app.modules.project_tax.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_project_tax",
    version="1.0.0",
    display_name="Project Tax Profile",
    display_name_i18n={
        "de": "Steuerprofil des Projekts",
        "ru": "Налоговый профиль проекта",
        "zh": "项目税务设置",
    },
    description=(
        "How one project accounts for output tax: the method (general, simplified or exempt) "
        "with its election date and lock period, whether it is grandfathered, the edition of the "
        "bill standard it is priced to, and where the site is for tax prepaid at the place of supply."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
