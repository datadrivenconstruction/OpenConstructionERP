# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data feeds module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_bi_feed",
    version="1.0.0",
    display_name="Data feeds",
    description=(
        "Read-only flat tables (CSV, Parquet, JSON) over projects, BOQ positions, invoices, purchase orders "
        "and schedule activities, for Excel, Power Query and any BI tool; optional PostgreSQL views for SQL access"
    ),
    author="OpenConstructionERP Core Team",
    category="integration",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
