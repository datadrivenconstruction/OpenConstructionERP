# Point Cloud / Reality Capture + Spatial Section - Build Plan

> STATUS: PLANNING (design locked, not yet implemented)
> LAST UPDATED: 2026-06-08
> OWNER: DataDrivenConstruction
> SCOPE: add point-cloud (laser scan / photogrammetry / LiDAR) capability and regroup the
> 3D/spatial surfaces into a dedicated sidebar section.

## How to resume (read this first)

This file is the single source of truth for the point-cloud initiative. It survives reboots
and is meant to be picked up by any agent that enters the repo. To continue the work:

1. Read this whole file. The design decisions in section "Locked decisions" are FINAL
   (chosen by the founder); do not re-open them without explicit instruction.
2. Find the first unchecked `[ ]` item in the "Roadmap & progress" section and continue there.
   Phases are ordered; do not start a later phase until the foundation gates of the earlier
   one are checked.
3. After each meaningful step, tick the checkbox and append a dated line to the "Progress log".
4. Respect every hard constraint (lightweight 2GB core, no IfcOpenShell, PostgreSQL-only,
   AGPL-only, modules=plugins, i18n in 27 locales, AI proposes/human confirms).
5. The companion design memory is `v7_2_0_release.md` and the founder's verbal decisions are
   captured below verbatim in intent.
6. CLARITY IS A FEATURE (founder directive): every screen ships with in-product guidance - module
   intro / empty state, field-level "what's this?" help (plain language; explain scan/accuracy terms
   like LOA tier, registration RMS, coverage, cut/fill so a non-surveyor understands), guided first
   run, explanatory errors, and AI suggestions that state their reason + confidence. A feature is not
   done if a brand-new user cannot understand and use it from on-screen guidance alone. See the same
   "In-product guidance & UX" standard in `ERP_PLATFORM_BUILD_PLAN.md`. All copy i18n'd in 26 locales.

Nothing here is committed/shipped yet. No code has been written for `oe_pointcloud`.

---

## 1. Strategy (one line)

We do NOT compete with capture/registration vendors (Leica Cyclone, Faro SCENE, Trimble
RealWorks, NavVis, Pix4D, ReCap). We INGEST their exports (E57/LAS/LAZ/COPC/PLY/PCD) and own
the "last mile" neither they nor cost vendors (Procore, iTWO) close: a registered cloud becomes
human-confirmed, validation-gated, priced BOQ quantities and EVM progress on a self-hostable
AGPL stack.

## 2. Locked decisions (founder-approved 2026-06-08)

| # | Question | Decision |
|---|----------|----------|
| 1 | Worker on weak hardware | Adaptive, never crash. (a) pre-tiled vendor COPC/pnts always render even on 2GB/no-worker; (b) small clouds (< threshold, default **1.5 GB**) convert via a detached, memory-capped OS subprocess (NOT `asyncio.to_thread` in the API process); (c) large clouds need the external worker, and if absent show a friendly "uploaded, conversion pending - enable the service or upload a pre-tiled COPC", never an error. |
| 2 | Accuracy-tier thresholds | Use the industry standard **USIBD Level of Accuracy (LOA)**. survey = LOA30-40 (±3-6 mm, TLS); standard = LOA20 (±15 mm, MLS/SLAM/drone); coarse = LOA10 (±50 mm, iPhone/iPad LiDAR). Registration RMS must be below the tier tolerance or validation blocks. coarse tier is forbidden from dimensional QA and from cut/fill feeding BOQ price (without explicit override). Show a friendly accuracy badge. |
| 3 | COPC vs pnts | **COPC always** on ingest (archive + Three.js local view source); **pnts generated on demand** when a Cesium geo-view is first opened, then cached in MinIO. Not both eagerly. |
| 4 | v1 geometry scope | **point-set + DTM only** in v1. Volumes from DTM-diff (cut/fill) + prism; areas from DTM or convex-hull/plane-fit; distances 3D. Mesh reconstruction (Poisson/ball-pivot) deferred to a later phase as an opt-in heavy job. |
| 5 | Per-point classification | Store class **inside COPC/pnts** + aggregates in `classification_stats` JSONB. Filtering/colouring by class happens **client-side from the COPC** (covers ~95% of needs). `pgPointCloud` (SQL per-point queries) is an opt-in enterprise add-on on **external PG only**, feature-flagged off on the embedded default. |
| 6 | Retention & egress | Keep raw by default (data safety). Optional per-project/tenant policy "delete raw after COPC verified" with a grace window (default **30 days**); never auto-delete the COPC/tiles. Egress: COPC range-reads only fetch visible LODs; recommend (not require) a CDN/cache in front of object storage for multi-user deployments; client caches LOD tiles in IndexedDB; document egress. |
| 7 | Module placement | `oe_pointcloud` is a standalone top-level module AND it lives inside a NEW dedicated sidebar section "Reality Capture & 3D" together with Geo Hub, BIM Viewer and CAD-BIM Data Explorer (see section 4). |

Tunable defaults the founder may adjust later: in-process conversion threshold (1.5 GB);
raw-delete grace window (30 days).

## 3. Pipeline (ingest -> tile -> store -> render -> measure -> validate -> integrate)

```
1. INGEST   browser/CLI -> MinIO directly (presigned multipart). Backend only writes the key.
            Never proxy 5-200 GB through FastAPI. laspy header-sniff (~hundreds of bytes) for
            instant preview: point_count, bbox, CRS.
2. CONVERT  services/cad-converter (heavy, OUT-OF-CORE) via JobRun(kind=pointcloud_ingest):
            PDAL read any format -> reproject to project CRS -> ground-classify (smrf/pmf) ->
            writers.copc (COPC) + py3dtiles (pnts, on demand) + writers.gdal (DTM/DSM, terrain).
            Outputs -> MinIO.
3. STORE    FastAPI core (thin): ScanDataset row (metadata) + geo_hub Tileset(source_kind=
            point_cloud). bbox as JSON + Numeric min/max (NO PostGIS). CRS -> GeoAnchor.
4. RENDER   browser, bytes from MinIO. Path A geo-referenced: Cesium pnts + pointCloudShading/EDL.
            Path B local/indoor/scan-vs-design: Three.js + @loaders.gl/copc (range-reads COPC octree).
5. MEASURE  browser UI + off-core diff-jobs. 3D measurements -> TakeoffMeasurement(type=pointcloud_*).
            Cut/fill = DTM-diff. AI suggests primitive-fit/segmentation with confidence -> human confirm.
6. VALIDATE FastAPI core: pointcloud rule set (coverage %, accuracy-tier gate, density, CRS-present,
            classification-mapped, deviation-tolerance, registration-RMS). BLOCKS (not flags) cut/fill
            and deviation when coverage/RMS/tier are out of bounds.
7. INTEGRATE volume_m3 -> boq/costs/assemblies + match_elements. Deviation -> clash_cost_impact.
            Progress -> schedule/EVM. QA -> BCF (XML I/O). Archive -> COPC + E57.
```

Execution contract (mandatory): FastAPI core (2 GB) writes/reads thin metadata, serves range
URLs, header-sniffs (laspy only) and imports ZERO point-cloud libraries. The converter
(`services/cad-converter`) does all PDAL/Open3D/py3dtiles work. MinIO holds raw + COPC + pnts +
DTM blobs and serves range reads. The browser does LOD rendering and measurement.

## 4. New sidebar section "Reality Capture & 3D" (decision #7)

Today geo, BIM viewer and the CAD-BIM data explorer are mixed into the `takeoff` group
(`frontend/src/app/layout/Sidebar.tsx`, group `sidebar.group.takeoff`). Create a dedicated group
and move the 3D/spatial surfaces into it; leave 2D drawing takeoff (quantities, PDF, DWG) where
it is.

New `NavGroup` in `Sidebar.tsx`:
```
{
  id: 'grp_reality',
  labelKey: 'sidebar.group.reality',   // defaultLabel: 'Reality Capture & 3D'
  items: [
    { labelKey: 'sidebar.geo_hub',        to: '/geo',           icon: Globe },
    { labelKey: 'nav.point_cloud',        to: '/pointcloud',    icon: <scan icon>, badge: 'BETA' },  // NEW
    { labelKey: 'nav.bim_viewer',         to: '/bim',           icon: Box },
    { labelKey: 'nav.cad_bim_explorer',   to: '/data-explorer', icon: TableProperties, advancedOnly: true },
  ],
}
```
- Remove `bim_viewer`, `cad_bim_explorer`, `geo_hub` items from the `takeoff` group.
- Add i18n keys `sidebar.group.reality` and `nav.point_cloud` and run the full 26-locale sweep.
- Module nav items injected via `getModuleNavItems('reality')` so `oe_pointcloud`'s manifest can
  add its own entry into this group.
- Keep "Model Coordination" (clash/federations/coordination) as a sibling group; do not merge.

NOTE: prior feedback once said "no separate sidebar section" for a different (project-split)
context; this section is an explicit founder request and supersedes that for the spatial cluster.

## 5. Module `oe_pointcloud` + integration map

Standalone module, sibling to `bim_hub`. Convention layout: `manifest.py / models.py / schemas.py /
repository.py / service.py / router.py / validators.py / migrations/ / tests/`. Thin core: dispatches
heavy work to the converter via `job_runner`, stores metadata only.

```python
# backend/app/modules/pointcloud/manifest.py
manifest = ModuleManifest(
    name="oe_pointcloud", version="1.0.0",
    display_name="Point Cloud / Reality Capture",
    depends=["oe_projects", "oe_bim_hub", "oe_geo_hub", "oe_uploads", "oe_takeoff", "oe_costs"],
    auto_install=False,   # opt-in; sidebar entry in grp_reality
)
```

Key `service.py` functions: `register_upload`, `submit_ingest_job` (register_handler kind=
pointcloud_ingest, idempotency_key=scan_id, proportional_timeout by size), `on_ingest_complete`
(write copc_uri/tileset_uri/point_count/bbox/classification_stats; create geo_hub Tileset; publish
`pointcloud.tileset.ready`), `compute_cutfill` (DTM-diff -> volume_m3 + coverage% + hole-area +
accuracy_tier), `create_measurement` (stamps scan_id + accuracy_tier + CRS into geometry JSON),
`propose_elements` (AI primitive-fit/segmentation suggestions, confidence, human-confirm queue),
`confirm_elements` (publishes `pointcloud.elements.confirmed`; bim_hub owns canonical-element
writes), `detect_deviation` (point-to-mesh, only after a human-confirmed datum/alignment step).

Integration map:
| Module | Addition | New or extend |
|--------|----------|---------------|
| `geo_hub` | pnts-branch in `tile_pipeline.py` bypassing the glTF/b3dm box path; add `copc` to `_TILE_FORMAT_PATTERN`; `source_kind=point_cloud`; Cesium `pointCloudShading`+EDL, classification legend, intensity ramp, clip-box | **NET-NEW render work** |
| `cad/crs_detector.py` | `detect_from_las(header)` (EPSG GeoKeys/WKT VLR), `detect_from_e57(xml)`; bbox-heuristic fallback for PLY/PCD; returns the same `CRSGuess` | Extend |
| `takeoff` | types `pointcloud_distance/area/volume/footprint/count`; 3D anchors + scan_id/accuracy_tier/CRS in `geometry` JSON; reuse `Numeric(18,6)` + BOQ rollup | Extend |
| `bim_hub` | API/event to promote confirmed fits to canonical elements (write-ownership stays in bim_hub); render cloud beside federated IFC in Three.js | Extend |
| `clash`/`clash_cost_impact` | accept scan-vs-design deviation as a clash source ("clash with reality"); dollar via existing cost-impact loop | Extend |
| `match_elements` | subscribe to `pointcloud.*.confirmed`; vector-match volume_m3 -> earth-removal/haul cost items | Extend |
| `boq`/`costs`/`assemblies` | confirmed volume_m3/area_m2/count -> BOQ positions; cut/fill -> earth removal/haul/disposal | Extend (no model change) |
| `validation` | colocated pointcloud rules in `core/validation/rules/__init__.py` + i18n | Extend |
| `core/jobs` + `services/cad-converter` | job-kinds `pointcloud_ingest/cutfill/segment/deviation`; **build the converter service from scratch** | **NET-NEW service** |
| `schedule`/EVM, `bcf`, `closeout/assets` | progress -> percent-complete -> EVM; QA viewpoints -> BCF (XML I/O); classified as-built -> O&M handover | Extend |

## 6. Data model

Thin row in PG, points in MinIO, zero PostGIS.
- `ScanDataset` (new, PG): id, project_id, tenant_id, source_type, original_format (e57|las|laz|
  copc|ply|pcd|pts|xyz, NO rcp/rcs), accuracy_tier (survey|standard|coarse), registration_status,
  crs_epsg, crs_confidence, point_count, bbox_json, bbox_min/max_lat/lon Numeric(10,7),
  upload_key, copc_uri, tileset_uri, dtm_uri, classification_stats JSONB, status, generation_job_id,
  retention_policy (keep_raw|delete_raw_after_copc), created_by, timestamps.
- `geo_hub Tileset` (reuse): source_kind=point_cloud, tile_format=pnts|copc, tileset_json_uri,
  bounding_volume JSON, tile_count, total_bytes, status, metadata_.
- `TakeoffMeasurement` (reuse): type=pointcloud_*, Numeric(18,6) values, geometry JSON (3D anchors
  + scan_id + accuracy_tier + CRS).
- `ScanRegistration`/deviation (new, PG): scan_id, target_ref, transform_matrix, rms_error,
  deviation_map_uri, out_of_tolerance_count, coverage_pct, hole_area, confidence.
- Blobs in MinIO (tenant-namespaced keys): raw, COPC `.copc.laz`, 3D Tiles pnts, DTM/DSM GeoTIFF.

CRITICAL: no PostGIS geometry/geography columns or indexes (embedded pixeltable-pgserver is vanilla
PG; geometry columns break create_all/alembic). Follow `geo_hub/models.py`: JSON bbox + plain
`Numeric` min/max lat/lon for cheap B-tree range filters.

## 7. Rendering (in the existing stack, but it is NEW work)

- Path A geo-referenced (drone/aerial/survey/exterior): Cesium consumes py3dtiles `pnts`. Build:
  pnts-branch in `geo_hub.tile_pipeline`, `pointCloudShading`+EDL in `CesiumViewer.tsx`, add `copc`
  to the frontend `TileFormat` union (`frontend/src/features/geo-hub/types.ts`).
- Path B local/indoor/scan-vs-design: Three.js `FederatedViewer` renders the cloud beside IFC. Add
  `@loaders.gl/copc` (MIT) or `@pnext/three-loader` (BSD-2). Stream = HTTP range reads from MinIO;
  core never re-tiles on demand.
- Licence hygiene: loaders.gl MIT, @pnext/three-loader BSD-2 OK. AVOID PotreeConverter 2.x
  (non-free); use py3dtiles/PDAL as the tiler.

## 8. AI features (confidence + human confirm; never auto-apply)

- Ground/class segmentation: PDAL smrf/pmf (deterministic) in the converter; optional PointNet++/
  KPConv/RandLA-Net suggestion-jobs. User edits class assignment before it drives DTM/quantity.
- Primitive fit (scan-to-BIM lite): Open3D plane/cylinder/cluster -> walls/floors/pipes/columns;
  residual-based confidence; only human-accepted fits promoted via bim_hub.
- Earthwork cut/fill: DTM diff vs design/prior-scan; volume shown with an uncertainty band (not a
  single number) + coverage % + tier; estimator confirms surface pair and tolerance.
- Scan-vs-design deviation (QA): point-to-mesh distance map; requires explicit human-confirmed
  datum/alignment before trust; deviations into clash_cost_impact queue.
- Cost matching: match_elements vector similarity volume_m3/area_m2/count -> cost items.

Accuracy traps the AI layer must close: registration/georeferencing error (a 25 mm vertical bias
over a hectare invents big phantom volume = real money), occlusion holes silently filled by DTM
interpolation, point-to-mesh deviation mixing real deviation with scan noise. So coverage %,
hole/occlusion area, registration RMS and accuracy_tier are MANDATORY companions to every cut/fill
and deviation figure, and validation BLOCKS when out of tier.

## 9. Keeping the 2 GB core thin

1. Backend imports zero point-cloud libraries (exception: `laspy` for header-sniff). PDAL,
   py3dtiles, Open3D, pye57 live only in `services/cad-converter`.
2. Off-core execution via JobRun, never `asyncio.to_thread` in core (bim_hub's current
   BackgroundTasks+to_thread+trimesh pattern is banned for clouds). Real worker, else detached
   subprocess. `register_handler`/`proportional_timeout` already exist in `core/job_runner.py`.
3. Presigned-direct-to-MinIO multipart is the REQUIRED ingest path. `uploads/router.py:90` does
   `b"".join(chunks)` (buffers the whole body) - never use it for clouds; if a proxied path is
   needed use `core/upload_streaming.stream_upload_to_temp` (chunk->disk, no accumulation) + a hard
   max-proxied-bytes cap.
4. COPC keystone: one range-readable `.copc.laz`; server serves range URLs, never re-tiles.
5. Points never in Postgres on the default path.
6. Graceful degradation on bare 2 GB w/o worker = "render pre-tiled vendor COPC/pnts, conversion
   disabled", not an in-core fallback.
7. Back-pressure: max-concurrent-ingest gate + size threshold for subprocess-vs-worker split.

AGPL hygiene: PDAL/laspy BSD, Open3D MIT, py3dtiles Apache-2.0, loaders.gl MIT, @pnext/three-loader
BSD-2 - all clean. AVOID CloudCompare (GPLv2), Untwine (GPLv3), Entwine (LGPL, separate-process
only), PotreeConverter 2.x (non-free). No IfcOpenShell, no native IFC. Reject RCP/RCS (proprietary).

## 10. Risks (and how we close them)

- RAM blowout in core -> presigned ingest mandatory; reuse upload_streaming; never the buffering path.
- Off-core converter is greenfield (`services/cad-converter` is empty) -> build it first; ban
  in-core threading; no-worker default = render-only.
- PostGIS on embedded PG -> JSON+Numeric bbox like geo_hub; pgPointCloud only on external PG behind a flag.
- Silent accuracy fraud -> coverage/RMS/tier are BLOCKING; uncertainty band; human-confirmed datum.
- RCP/RCS licensing trap -> dropped from accepted inputs.
- Storage egress -> retention/tiering policy; CDN/cache recommendation; client tile cache.
- i18n at scale -> all new strings via the full 26-locale sweep, not EN/DE/RU only.
- Multi-tenant -> tenant_id on ScanDataset + tenant-namespaced MinIO keys.

## 11. Roadmap & progress

Tick `[x]` as each item lands; append a dated note to the Progress log.

### Phase 0 - Foundation gates (preconditions)
- [ ] Presigned-direct-to-MinIO multipart ingest path + max-proxied-bytes cap + max-concurrent-ingest gate
- [ ] `ScanDataset` + `ScanRegistration` models (JSON+Numeric bbox, NO PostGIS, tenant_id, retention_policy) + migration (single alembic head)
- [ ] Add `copc` to frontend `TileFormat` union; pnts-branch in `geo_hub.tile_pipeline`; Cesium pointCloudShading+EDL; add `@loaders.gl/copc` to package.json
- [ ] New sidebar section `grp_reality` "Reality Capture & 3D" (move geo/bim/data-explorer; add point cloud) + i18n keys (`sidebar.group.reality`, `nav.point_cloud`) + 26-locale sweep

### Phase 1 - MVP: upload, stream, view (safe wedge)
- [ ] `oe_pointcloud` module scaffold (manifest + full file set; depends projects/bim_hub/geo_hub/uploads/takeoff/costs)
- [ ] Accept pre-tiled vendor COPC/pnts with ZERO server tiling (works without a worker)
- [ ] Header-sniff preview (laspy: count/bbox/CRS); `detect_from_las/e57` in `crs_detector`
- [ ] ScanDataset row + geo_hub Tileset registration; Cesium renders pnts on the globe; `source_kind=point_cloud` filter
- [ ] iPhone/iPad LiDAR (PLY/E57) upload as the low-barrier wedge
- [ ] Accuracy badge UI (USIBD LOA tier) on every scan

### Phase 2 - converter + measure + earthwork (the dollar value)
- [ ] Build `services/cad-converter` from scratch: `pdal_bridge.py` (read/reproject/ground-classify/COPC/DTM), `py3dtiles_bridge.py` (LAS/LAZ->pnts), `open3d_bridge.py` (ICP/segmentation/surface-diff)
- [ ] Job-kinds `pointcloud_ingest/cutfill/segment` via `register_handler`; worker or detached subprocess; in-process subprocess path for clouds < 1.5 GB (memory-capped); ban asyncio.to_thread
- [ ] 3D measurement (`TakeoffMeasurement pointcloud_*` with scan_id/tier/CRS in geometry) + BOQ rollup
- [ ] PDAL ground classification + DTM; surface-to-surface/plane cut/fill -> volume_m3 -> boq/costs
- [ ] `match_elements` wiring for earthwork cost
- [ ] pointcloud validation rule set with BLOCKING coverage/RMS/tier + occlusion-check + registration-RMS rule; 26-locale sweep
- [ ] Three.js path for local/indoor scans (`@loaders.gl/copc`) beside IFC

### Phase 3 - scan-vs-design + AI segmentation
- [ ] Registration/ICP (Open3D) + human-confirmed datum/alignment step + point-to-mesh deviation map -> clash/clash_cost_impact
- [ ] AI segmentation (smrf, optional PointNet++/KPConv) + primitive fit as human-confirm suggestion queues; promote via bim_hub
- [ ] Viewer enhancements: classification legend + intensity heatmap

### Phase 4 - progress, handover, enterprise
- [ ] 4D/EVM progress from captured geometry -> schedule/full_evm/eac
- [ ] BCF viewpoint export for QA (XML I/O); closeout/assets handover classified as-built
- [ ] Clip-box slicer + density contour
- [ ] Optional pgPointCloud enterprise add-on (external PG only, flagged off on embedded)
- [ ] E57+COPC archive export; OpenDroneMap (AGPL) drone-photogrammetry bridge

## 12. Key file references (verified at planning time)

- `services/cad-converter/` - EMPTY (greenfield; build here)
- `backend/app/modules/uploads/router.py:90` - `b"".join(chunks)` (RAM buffer; do not reuse for clouds)
- `backend/app/core/upload_streaming.py` - `stream_upload_to_temp` (safe chunk->disk; reuse)
- `backend/app/core/job_runner.py` - `register_handler` / `proportional_timeout` exist
- `backend/app/modules/geo_hub/tile_pipeline.py` - writes only b3dm/glTF today (pnts is new)
- `backend/app/modules/geo_hub/models.py` - Numeric lat/lon + JSON bounding_volume (no PostGIS) - the pattern to copy
- `backend/pyproject.toml` - `celery[redis]` is in the `server` extra, NOT base (no default worker)
- `frontend/src/features/geo-hub/types.ts` - `TileFormat` union (needs `copc`)
- `frontend/src/app/layout/Sidebar.tsx` - nav groups; `takeoff` group currently holds geo/bim/data-explorer

## 13. Progress log (append-only)

- 2026-06-08: Plan created. Design researched via multi-agent workflow (7 agents) and adversarially
  reviewed; founder locked decisions 1-7. No code written yet. Next: Phase 0 foundation gates.
