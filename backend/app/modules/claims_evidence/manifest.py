# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Claims evidence-pack module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.claims_evidence.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_claims_evidence",
    version="0.1.0",
    display_name="Claims Evidence",
    description=(
        "Assembles a deterministic, ordered evidence pack for a claim or "
        "dispute from a project's cross-module activity timeline and its "
        "change-family records. The pack is content-addressable, so two "
        "parties can independently reproduce and verify it. Assembled on "
        "demand with no tables of its own and no migration"
    ),
    author="OpenConstructionERP Core Team",
    category="controls",
    depends=[
        "oe_users",
        "oe_projects",
        "oe_timeline",
        "oe_changeorders",
        "oe_variations",
        "oe_moc",
    ],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
