# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Event reconciliation module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.reconciliation.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_reconciliation",
    version="0.1.0",
    display_name="Event Reconciliation",
    description=(
        "Stitches a project's record of an event back together across modules "
        "and channels. A single instruction may surface as correspondence, a "
        "change order, a variation and a management-of-change entry, each in its "
        "own table; the pure correlation engine scores which heterogeneous "
        "records describe the same underlying event and emits explainable links, "
        "and this module assembles the reconciled timeline for one event and "
        "persists a reviewer's confirm / reject decisions on each suggested link."
    ),
    author="OpenConstructionERP Core Team",
    category="controls",
    depends=["oe_users", "oe_projects"],
    optional_depends=[
        "oe_correspondence",
        "oe_changeorders",
        "oe_variations",
        "oe_moc",
    ],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
