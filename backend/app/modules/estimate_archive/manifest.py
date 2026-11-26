# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sealed estimate module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.estimate_archive.data_paths import DATA_PATHS
from app.modules.estimate_archive.policy import markets

manifest = ModuleManifest(
    name="oe_estimate_archive",
    version="0.1.0",
    display_name="Sealed Estimates",
    description=(
        "Seal the estimate behind the contract rates with a SHA-256 fingerprint, open it only in a "
        "recorded session with witnesses, and price changes from the sealed basis side by side with cost plus"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects", "oe_boq", "oe_contracts", "oe_documents", "oe_signing", "oe_variations"],
    # Markets come from the profile data; elsewhere the Modules toggle still turns it on.
    markets=markets(),
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
