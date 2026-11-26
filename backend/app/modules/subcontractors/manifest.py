# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontractor Management module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.subcontractors.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_subcontractors",
    version="0.1.0",
    display_name="Subcontractor Management",
    description=(
        "Subcontractor lifecycle: prequalification, certificates, agreements, payment applications, retention, rating"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # oe_contracts: a subcontract agreement can sit under the GC's prime
    # contract, and its pay applications roll up into that contract's claims.
    depends=["oe_users", "oe_projects", "oe_contacts", "oe_contracts"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
