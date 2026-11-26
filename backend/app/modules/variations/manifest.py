# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Variations module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.variations.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_variations",
    version="0.1.0",
    display_name="Variations & Site Measurements",
    description=(
        "Variations lifecycle: Notice -> VR -> VO -> site measurements -> "
        "daywork -> disruption/EOT claims -> Final Account"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # oe_boq: a variation request may own a dedicated bill of quantities
    # (Issue #435), created through BOQService and stamped with the
    # request it belongs to.
    depends=["oe_users", "oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
