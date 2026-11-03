# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Geo Hub module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_geo_hub",
    version="0.2.0",
    display_name="Geo Hub",
    description=(
        "Geospatial + 3D Tiles platform module: WGS84 anchors, canonical -> "
        "glTF -> 3D Tiles 1.1 pipeline on MinIO, imagery / terrain providers, "
        "GeoJSON & KML I/O, saved viewpoints, an OGC API - Features service "
        "for QGIS and other GIS clients, twelve cross-module subscribers "
        "(projects / bim_hub / property_dev / carbon / schedule / clash / "
        "field_reports / safety / ncr / risk), dated site survey captures "
        "(drone orthophotos and scans) compared with the schedule, and a "
        "Cesium-based frontend."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_bim_hub", "oe_property_dev", "oe_uploads"],
    optional_depends=["oe_schedule", "oe_pointcloud"],
    auto_install=True,
    enabled=True,
)
