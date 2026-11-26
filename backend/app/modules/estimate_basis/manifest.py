# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Basis-of-estimate module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.estimate_basis.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_estimate_basis",
    version="1.0.0",
    display_name="Basis of Estimate",
    description=(
        "Auto-drafts the qualifications that accompany an estimate - what it "
        "includes, what it excludes and the assumptions behind it - from the "
        "finished estimate contents. Reads which trades are present, absent or "
        "flagged by the coverage check, drafts editable inclusions, exclusions "
        "and assumptions, and exports them with the proposal."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # Reads BOQ positions and verifies project access; also reads the sibling
    # estimating modules (allowances / contingency, preliminaries and the cost
    # database price dates) to enrich the drafted assumptions.
    depends=["oe_boq", "oe_projects", "oe_allowances", "oe_preliminaries", "oe_costs"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
