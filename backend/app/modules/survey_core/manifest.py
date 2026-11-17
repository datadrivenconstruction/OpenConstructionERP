# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey register module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_survey_core",
    version="0.1.0",
    display_name="Survey Register",
    description=(
        "The project's coordinate system and its survey points in one register: control points, "
        "benchmarks and topo points imported from instrument CSV/TXT files or GeoJSON, with the file, "
        "instrument and date each set came from. Coordinates are transformed only when the person sees "
        "both systems and imports; duplicate point ids and missing systems are flagged."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects"],
    optional_depends=["oe_geo_hub", "oe_cad"],
    auto_install=True,
    enabled=True,
)
