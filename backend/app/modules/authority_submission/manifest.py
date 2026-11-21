# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Authority-submission factory module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.authority_submission.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_authority_submission",
    version="0.1.0",
    display_name="Authority Submission Factory",
    description=(
        "Generic engine for the structured XML documents a delivery must hand "
        "to an authority - tender exchange, expertise packages, asset handover "
        "registers. Driven by profiles carried as data (root element, expected "
        "field set, schema version) so a new format is a new profile, not new "
        "code. Ships jurisdiction-neutral built-in profiles (generic XML, a "
        "GAEB-X83-shaped tender example, a COBie-shaped handover example); "
        "regional packs plug in national dialects such as RU Minstroy. The same "
        "payload is the single source for both the machine XML and the human "
        "review, and a submission must validate cleanly before it can be sent."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
