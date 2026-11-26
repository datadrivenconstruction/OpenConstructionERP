# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Portfolio module manifest.

Without this file ``ModuleLoader.discover()`` skips the package entirely
(``module_loader.py:87`` requires a ``manifest.py`` to exist), so the router
never mounts and every ``/v1/portfolio/`` endpoint answers 404 while the
frontend page keeps calling them. The tables themselves are created regardless,
because schema provisioning walks ``app.modules`` by directory scan rather than
by the manifest list, which is why the breakage looked like an empty page
instead of a startup error.
"""

from app.core.module_loader import ModuleManifest
from app.modules.portfolio.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_portfolio",
    version="0.1.0",
    display_name="Portfolio",
    description=(
        "Programme and portfolio tree: hierarchical nodes, project membership, "
        "cross-schedule links and portfolio-level CPM over a subtree"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects", "oe_schedule_advanced"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
