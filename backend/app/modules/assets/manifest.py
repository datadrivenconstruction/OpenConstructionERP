"""Asset Operations module manifest.

Operational-phase intelligence on top of the BIM-sourced asset register.
This module never owns its own tables. It reads tracked assets straight
from the shared ``oe_bim_element`` / ``oe_bim_model`` tables (populated by
the BIM Hub) and computes lifecycle / warranty / maintenance state from
the ``asset_info`` JSON blob already persisted there. Writes (promoting a
candidate, logging a service event) ride the existing BIM Hub PATCH
endpoint, so no schema migration is required.
"""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_assets",
    version="1.0.0",
    display_name="Asset Operations",
    description=(
        "Operational-phase asset intelligence: discover asset candidates "
        "from BIM models, compute warranty / maintenance / lifecycle "
        "health, roll up a portfolio summary, and dispatch warranty-expiry "
        "alerts. Reads the BIM-sourced asset register; persists nothing of "
        "its own (state rides the existing asset_info JSON)."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_bim_hub"],
    optional_depends=["oe_notifications"],
    auto_install=True,
    enabled=True,
)
