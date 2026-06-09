# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Point Cloud module permission definitions.

Four families, mirroring ``geo_hub``:

* ``pointcloud.read``     - list / get scans and registrations.
* ``pointcloud.write``    - register an upload, create / update scans.
* ``pointcloud.delete``   - destructive removal of a scan and its artifacts.
                            Gated to MANAGER+ because a large scan is expensive
                            to re-capture and re-convert.
* ``pointcloud.job_run``  - enqueue the out-of-core ingest / cut-fill /
                            deviation jobs. Separated from ``write`` so the CPU
                            budget on the VPS can be limited without blocking
                            basic registration.

The router IDOR helper collapses cross-tenant accesses to 404, so this
permission set never leaks scan existence to unauthorised callers.
"""

from app.core.permissions import Role, permission_registry

POINTCLOUD_PERMISSIONS: dict[str, Role] = {
    "pointcloud.read": Role.VIEWER,
    "pointcloud.write": Role.EDITOR,
    "pointcloud.delete": Role.MANAGER,
    "pointcloud.job_run": Role.EDITOR,
}


def register_pointcloud_permissions() -> None:
    """Register permissions for the pointcloud module."""
    permission_registry.register_module_permissions(
        "pointcloud",
        POINTCLOUD_PERMISSIONS,
    )
