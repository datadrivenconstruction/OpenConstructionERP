# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Assemblies & Calculations module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.assemblies.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_assemblies",
    version="0.1.0",
    display_name="Assemblies & Calculations",
    description=(
        "Composite cost items built from cost database entries with factors. "
        "Supports templates, regional factors, and BOQ integration."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # ``oe_fx`` prices an assembly whose currency differs from the target
    # project's; without it the only rate source is the project's hand-typed
    # ``fx_rates``, which is empty on a default project.
    depends=["oe_costs", "oe_fx"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
