# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Point Cloud / Reality Capture module manifest.

Standalone, opt-in module (``auto_install=False``). It ingests laser-scan,
photogrammetry and LiDAR exports (E57/LAS/LAZ/COPC/PLY/PCD/PTS/XYZ), turns a
registered cloud into human-confirmed, validation-gated quantities, and lives in
the dedicated "Reality Capture & 3D" sidebar group alongside Geo Hub and the BIM
viewer. The FastAPI core stays thin: it stores metadata only and dispatches all
heavy point-cloud work to ``services/cad-converter`` via the job runner. The core
imports zero point-cloud libraries.
"""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_pointcloud",
    version="1.0.0",
    display_name="Point Cloud / Reality Capture",
    description=(
        "Ingest laser-scan, photogrammetry and LiDAR exports and turn a registered "
        "cloud into human-confirmed, validation-gated quantities and progress. Thin "
        "core that stores metadata only and dispatches heavy conversion to the "
        "out-of-core converter service."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[
        "oe_projects",
        "oe_bim_hub",
        "oe_geo_hub",
        "oe_uploads",
        "oe_takeoff",
        "oe_costs",
    ],
    auto_install=False,
    enabled=True,
)
