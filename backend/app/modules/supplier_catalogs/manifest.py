# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Supplier Catalogs module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.supplier_catalogs.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_supplier_catalogs",
    version="1.0.0",
    display_name="Supplier Catalogs & Vendor Management",
    description=(
        "Extends Procurement: vendor master, item catalogs, price lists, "
        "purchase requisitions, extended POs, goods receipts with batch/serial "
        "tracking, vendor invoices with 3-way match, and warehouse stock control."
    ),
    author="OpenConstructionERP",
    category="extension",
    depends=["oe_projects", "oe_users", "oe_procurement"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
