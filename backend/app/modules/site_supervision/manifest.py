# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Design-side site-supervision module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.site_supervision.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_site_supervision",
    version="0.1.0",
    display_name="Site Supervision",
    description=(
        "Design-side site supervision: plan and record the design team's "
        "supervision visits to a project, raise observations (conformance, "
        "deviation, hidden-works acceptance, instruction, motivated refusal), "
        "track plan-versus-fact and overdue visits, keep a hidden-works "
        "acceptance register, feed instructions and deviations into the change "
        "route, and export a visit as a structured supervision log. "
        "Jurisdiction-neutral: it records what was inspected and observed, "
        "never a country's rule; regional packs supply the local vocabularies "
        "(author supervision / contract administration / construction "
        "administration / Objektüberwachung)."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
