# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Point Cloud / Reality Capture module.

Ingest laser-scan, photogrammetry and LiDAR exports (E57/LAS/LAZ/COPC/PLY/PCD/
PTS/XYZ) and turn a registered cloud into human-confirmed, validation-gated
quantities and progress. The FastAPI core stays thin: it stores metadata only,
serves range URLs, and dispatches all heavy point-cloud work to
``services/cad-converter`` via the job runner. The core imports zero
point-cloud libraries.
"""

from __future__ import annotations


async def on_startup() -> None:
    """Module startup hook - register permissions.

    Delegated to a local import so the loader can scan manifests before any
    module code runs without import-time side effects.
    """
    from app.modules.pointcloud.permissions import register_pointcloud_permissions

    register_pointcloud_permissions()
