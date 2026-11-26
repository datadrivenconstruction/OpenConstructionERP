# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Delivery model module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.delivery_model.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_delivery_model",
    version="0.1.0",
    display_name="Delivery model",
    description=(
        "Project delivery form decision: compare forms against weighted criteria, allocate every risk "
        "category to a party, record the decision for the governance gate, and plan the contract packages "
        "and owner-furnished items that procurement and contracts apply"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # oe_project_governance owns the catalogue store, the gate that approves the
    # decision and the frame document that carries it; risk holds the register
    # the allocations seed; contracts holds the vocabulary of contract types.
    depends=["oe_users", "oe_projects", "oe_project_governance", "oe_risk", "oe_contracts"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
