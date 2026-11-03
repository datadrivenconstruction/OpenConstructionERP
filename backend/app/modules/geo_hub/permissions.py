# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Geo Hub permission definitions.

Five families:

* ``geo_hub.read``      - list / get any geo entity.
* ``geo_hub.write``     - create / update anchors, imagery, terrain,
                          viewpoints, overlays.
* ``geo_hub.create`` / ``geo_hub.update`` - site survey captures and the
                          observations recorded against them.
* ``geo_hub.delete``    - destructive removal of any project-scoped geo
                          entity (anchor, tileset, imagery layer,
                          viewpoint, vector overlay). Gated to MANAGER+
                          because losing a hand-drawn boundary overlay
                          or a manually-anchored project is harder to
                          recover from than re-uploading a raster.
                          (Raster-overlay deletes intentionally stay on
                          ``geo_hub.write`` - they are soft-deletes and
                          R6-audited.)
* ``geo_hub.admin``     - reserved for irreversible operations
                          (delete-all, cross-project cleanup) - gated
                          to MANAGER+.
* ``geo_hub.job_run``   - enqueue + cancel TileGenerationJob (read of
                          jobs is via ``geo_hub.read``).

Tile generation is a write-shaped action - it produces persistent
artefacts in MinIO and consumes CPU - but separating it from
``geo_hub.write`` lets us limit who can hot-spin the CPU budget on the
VPS without forcing them out of basic CRUD.

The router IDOR helper (see ``service._verify_project_owner``) collapses
cross-tenant accesses to 404 so this permission set never leaks
existence to unauthorised callers.
"""

from app.core.permissions import Role, permission_registry

GEO_HUB_PERMISSIONS: dict[str, Role] = {
    "geo_hub.read": Role.VIEWER,
    "geo_hub.write": Role.EDITOR,
    "geo_hub.create": Role.EDITOR,
    "geo_hub.update": Role.EDITOR,
    "geo_hub.delete": Role.MANAGER,
    "geo_hub.admin": Role.MANAGER,
    "geo_hub.job_run": Role.EDITOR,
}


def register_geo_hub_permissions() -> None:
    """Register permissions for the geo_hub module."""
    permission_registry.register_module_permissions(
        "geo_hub",
        GEO_HUB_PERMISSIONS,
    )
