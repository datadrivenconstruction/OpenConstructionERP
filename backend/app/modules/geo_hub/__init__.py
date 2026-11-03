# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Geo Hub - Cesium 3D Tiles + cross-module geospatial integration.

Adds geospatial capabilities to OpenConstructionERP:

* WGS84 anchors for projects + developments + BIM federations
* Pure-Python canonical-JSON -> glTF (``EXT_structural_metadata``) ->
  3D Tiles 1.1 pipeline (OGC Community Standard, Jan 2025) served from
  the existing MinIO / nginx stack
* Imagery + terrain provider catalogue (OSM, Bing, WMS, Cesium World
  Terrain bring-your-own-ion-key, ellipsoid free fallback)
* GeoJSON / KML import + export for boundaries, easements, drone scans,
  flood / risk overlays
* Saved camera viewpoints per project + 4D-aware metadata so the
  schedule module can animate timeline playback
* An OGC API - Features service at ``/api/v1/geo-hub/ogc`` so QGIS and
  every other GIS client can read project anchors, vector overlays and
  viewpoints through the same permission gate as the rest of the module
  (see ``ogc_features.py``) - no PostGIS, no new dependency
* Twelve cross-module event subscribers (projects / bim_hub /
  property_dev / carbon / schedule / clash / field_reports / safety /
  ncr / risk) so the geo dashboard is populated automatically when other
  modules emit domain events

Design notes (Cesium / 3D Tiles research):

* CesiumJS, ``cesium-native``, ``3d-tiles-tools`` and ``gltf-pipeline``
  are all Apache-2.0 - one-way compatible with our AGPL-3.0 community
  ship and our commercial enterprise license.
* Tile generation runs as a job (``TileGenerationJob`` FSM) and writes
  output under ``tilesets/{tileset_id}/`` in the existing storage
  backend.
* No Cesium ion key is required - terrain defaults to the WGS84
  ellipsoid. Cesium World Terrain is offered as a bring-your-own-key
  ``TerrainSource`` so the community ship has no third-party hard
  dependency.
* CesiumJS itself is ~3 MB and lives in a dedicated lazy frontend
  chunk; the main bundle is untouched.
"""

from __future__ import annotations


async def on_startup() -> None:
    """Module startup hook - register permissions + event subscribers.

    The module loader calls ``on_startup`` exactly once at application
    boot. The work is delegated to local imports to keep import-time
    side-effects minimal (the loader scans manifests before any module
    code runs, and circular imports between ``permissions`` and
    ``events`` are easy to introduce otherwise).
    """
    from app.modules.geo_hub.events import register_subscribers
    from app.modules.geo_hub.permissions import register_geo_hub_permissions
    from app.modules.geo_hub.validators import register_geo_hub_survey_rules

    register_geo_hub_permissions()
    register_subscribers()
    register_geo_hub_survey_rules()
