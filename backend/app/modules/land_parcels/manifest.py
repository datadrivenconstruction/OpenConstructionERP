# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Land and parcels module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_land_parcels",
    version="0.1.0",
    display_name="Land & Parcels",
    description=(
        "The parcels a project needs: boundaries in the project coordinate system, area from the boundary "
        "points next to the registered area, owners, leases and easements as recorded data, and the "
        "acquisition status and cost of each parcel. Flags open rings, overlaps, gaps and works on land "
        "not yet acquired; imports and exports GeoJSON and Shapefile, exports DXF, prints the schedule."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_survey_core"],
    optional_depends=["oe_boq"],
    auto_install=True,
    enabled=True,
)
