# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement book module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.measurement_book.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_measurement_book",
    version="0.1.0",
    display_name="Measurement Book",
    description=(
        "Dated site measurements per BOQ position with dimensions, measured by and check-measured by, "
        "cumulative measured and checked quantities, and a running bill that feeds progress claims"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_projects", "oe_boq", "oe_progress"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
