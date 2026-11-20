"""Design module manifest: model revisions from the design editor, brief, estimate binding."""

from app.core.module_loader import ModuleManifest
from app.modules.design.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_design",
    version="0.1.0",
    display_name="Design",
    description=(
        "Links the design editor to projects: brief, model revisions, acceptance, "
        "estimate recomputation from the model."
    ),
    author="DataDrivenConstruction",
    category="integration",
    depends=["oe_projects", "oe_bim_hub", "oe_boq", "oe_collaboration_locks"],
    # MCP entry point and proposals (R15) are offered only when these are loaded.
    optional_depends=["oe_mcp", "oe_erp_chat"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
