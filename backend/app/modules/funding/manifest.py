# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Public funding module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.funding.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_funding",
    version="0.1.0",
    display_name="Public Funding & Grants",
    description=(
        "Public funding lifecycle: programme -> application and award -> "
        "disbursement -> proof of use, with the deadlines and eligible-cost "
        "rules each programme imposes"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # oe_projects: an application is always for one project, and the award
    # period is checked against the project's own dates.
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
