# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Estimate-rollup module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.estimate_rollup.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_estimate_rollup",
    version="1.0.0",
    display_name="Estimate Rollup",
    description=(
        "Composes a project's full estimate headline number from the estimating "
        "modules that are tracked separately today: the BOQ base (measured works "
        "plus markups), the preliminaries register and the allowances / "
        "contingency register. Read-only - it reuses each module's own rollup and "
        "adds preliminaries and remaining allowances on top of the BOQ base "
        "without double-counting, with a line-item breakdown a UI can render as "
        "'BOQ base + Preliminaries + Contingency = Estimate total'."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # Read-only composition over the BOQ totals, the preliminaries register and
    # the allowances register; verifies project access. No models of its own, so
    # no migration is authored here.
    depends=["oe_boq", "oe_projects", "oe_preliminaries", "oe_allowances"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
