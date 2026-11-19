# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Construction-control module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.construction_control.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_construction_control",
    version="0.1.0",
    display_name="Construction Control",
    description=(
        "Universal QA/QC engine: acceptance criteria, inspections (MIR/WIR/IR/"
        "hidden-works/acceptance), material records (digital passport: EN 10204, "
        "CE/UKCA, batch/heat/lot traceability), lab test results, as-built records "
        "(verified survey/scan records with metrology and a signed legal-record "
        "attestation), hold/witness/surveillance/review gating, and handover / "
        "acceptance packages (regime-aware taking-over / substantial / practical "
        "completion: auto-assembled acceptance evidence, a completion gate over open "
        "NCRs and unreleased hold points, and an e-signed acceptance certificate), with "
        "format-agnostic model linking and a failed check automatically raising "
        "a non-conformance report."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_bim_hub", "oe_ncr"],
    optional_depends=["oe_pointcloud", "oe_approval_routes", "oe_closeout"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
