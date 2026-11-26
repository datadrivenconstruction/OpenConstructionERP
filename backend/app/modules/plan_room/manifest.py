# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan Room module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.plan_room.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_plan_room",
    version="1.0.0",
    display_name="Plan Room",
    description=(
        "Read-only overlay compositor for a document page - defect pins, "
        "markups, measurements and photos - plus positioned photo / note pins"
    ),
    author="OpenConstructionERP",
    category="business",
    # Hard needs: project access + document resolution.
    depends=["oe_projects", "oe_users", "oe_documents"],
    # Overlay sources read fail-soft, so they are optional at load time.
    optional_depends=["oe_punchlist", "oe_markups", "oe_takeoff"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
