# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Economics module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.economics.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_economics",
    version="0.1.0",
    display_name="Economics",
    display_name_i18n={"de": "Wirtschaftlichkeit"},
    description=(
        "Business case with investment, benefits and key figures, a cost frame by classification code of the "
        "project's own standard compared with the estimate and the commitments, and a financing plan with "
        "sources, tranches and a coverage check, approved together at the governance gate"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # oe_project_governance owns the gate that approves the plan and the frame document that carries it;
    # oe_boq and oe_costmodel are where the estimate and the commitments are read from; oe_funding holds the
    # applications a grant or subsidy source can point at.
    depends=["oe_users", "oe_projects", "oe_project_governance", "oe_boq", "oe_costmodel"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
