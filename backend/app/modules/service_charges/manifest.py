# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service charges module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_service_charges",
    version="0.1.0",
    display_name="Service Charges",
    description=(
        "Owners associations and service charge budgets in any country: apportionment keys by area, "
        "permille, equal or custom shares, approved yearly budgets, demands raised as finance receivables, "
        "year-end reconciliation against actual costs from finance payables and service work orders"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_projects", "oe_finance"],
    optional_depends=["oe_legal_entities", "oe_service", "oe_contacts"],
    auto_install=True,
    enabled=True,
)
