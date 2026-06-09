// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * TS types mirroring backend/app/modules/geo_hub/schemas.py.
 */

export type GeoSourceKind =
  | 'bim_model'
  | 'federation'
  | 'development'
  | 'upload'
  | 'point_cloud'
  | 'photogrammetry';

export type TilesetStatus =
  | 'draft'
  | 'generating'
  | 'ready'
  | 'failed'
  | 'obsolete';

export type TileFormat = 'b3dm' | 'i3dm' | 'pnts' | 'cmpt' | 'copc';

export type TileJobState =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type ImageryProvider = 'osm' | 'bing' | 'wms' | 'wmts' | 'custom';

export type TerrainProvider =
  | 'cesium_world'
  | 'quantized_mesh'
  | 'ellipsoid';

export type OverlayKind =
  | 'boundary'
  | 'survey'
  | 'contour'
  | 'drone_photo'
  | 'site_plan'
  | 'easement'
  | 'flood_zone'
  | 'clash_marker'
  | 'incident'
  | 'field_report'
  | 'risk_zone';

export interface GeoAnchor {
  id: string;
  project_id: string;
  lat: string;
  lon: string;
  alt: string;
  epsg_code: number;
  region_code: string | null;
  address: string | null;
  accuracy_m: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Tileset {
  id: string;
  project_id: string;
  source_kind: GeoSourceKind;
  source_id: string;
  name: string;
  bucket: string;
  prefix: string;
  tileset_json_uri: string | null;
  bounding_volume: Record<string, unknown> | null;
  geometric_error: string;
  tile_format: TileFormat;
  tile_count: number;
  total_bytes: number;
  status: TilesetStatus;
  generated_at: string | null;
  generation_job_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ImageryLayer {
  id: string;
  project_id: string;
  name: string;
  provider: ImageryProvider;
  url_template: string;
  attribution: string;
  requires_api_key: boolean;
  default_for_project: boolean;
  is_visible: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TerrainSource {
  id: string;
  name: string;
  provider: TerrainProvider;
  endpoint: string | null;
  is_default: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Viewpoint {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  camera_lat: string;
  camera_lon: string;
  camera_alt: string;
  heading: string;
  pitch: string;
  roll: string;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface GeoOverlay {
  id: string;
  project_id: string;
  name: string;
  kind: OverlayKind;
  geojson: Record<string, unknown>;
  source_file: string | null;
  style: Record<string, unknown>;
  is_visible: boolean;
  source_event_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TileJob {
  id: string;
  project_id: string;
  tileset_id: string | null;
  source_kind: GeoSourceKind;
  source_id: string;
  requested_by: string | null;
  state: TileJobState;
  progress_pct: number;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  output_uri: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MapConfig {
  project_id: string;
  anchor: GeoAnchor | null;
  imagery_layers: ImageryLayer[];
  terrain_source: TerrainSource | null;
  tilesets: Tileset[];
  overlays: GeoOverlay[];
  viewpoints: Viewpoint[];
  active_jobs: TileJob[];
}

/* ── Cross-module geo pin layers (HSE / Punchlist / Daily Diary) ─────── */

/**
 * Mirrors backend ``HSEPinResponse`` in
 * ``backend/app/modules/geo_hub/schemas.py``.
 */
export interface HSEPin {
  incident_id: string;
  incident_number: string;
  title: string | null;
  incident_type: string;
  severity: string;
  status: string;
  lat: number;
  lon: number;
}

/**
 * Mirrors backend ``PunchlistPinResponse`` in
 * ``backend/app/modules/geo_hub/schemas.py``.
 */
export interface PunchlistPin {
  item_id: string;
  title: string;
  priority: string;
  status: string;
  category: string | null;
  lat: number;
  lon: number;
}

/**
 * Mirrors backend ``DiaryPhotoPinResponse`` in
 * ``backend/app/modules/geo_hub/schemas.py``.
 */
export interface DiaryPhotoPin {
  photo_id: string;
  diary_id: string | null;
  taken_at: string;
  thumbnail_url: string | null;
  file_url: string;
  is_360: boolean;
  is_drone: boolean;
  lat: number;
  lon: number;
}

/**
 * Combined cross-module pin bundle handed to the Cesium viewer. Each
 * list is independently fetched so a backend hiccup on one module
 * doesn't black out the whole map.
 */
export interface GeoPinBundle {
  hse: HSEPin[];
  punchlist: PunchlistPin[];
  diary: DiaryPhotoPin[];
  /**
   * Optional project pin layer (Global Geo Hub only). Each pin is the
   * project's anchor — clicking jumps into the project-scoped map.
   * Empty in project / development modes.
   */
  projects?: AnchoredProject[];
}

/**
 * Mirrors backend ``AnchoredProjectResponse`` — one row per project
 * shown as a pin on the global Geo Hub map.
 *
 * ``project_type`` and ``status`` drive the pin icon family +
 * status tint. ``project_address_text`` is the source-of-truth address
 * text on the project — used by the drift indicator to flag pins whose
 * address was edited after the first geocode.
 */
export interface AnchoredProject {
  project_id: string;
  project_name: string;
  /**
   * ``null`` when the project is pinned purely from its address
   * coordinates (``address.lat``/``lng``) and has no ``GeoAnchor`` row
   * yet. Present projects keep their anchor id.
   */
  anchor_id: string | null;
  lat: string;
  lon: string;
  alt: string;
  region_code: string | null;
  address: string | null;
  project_type?: string | null;
  status?: string | null;
  project_address_text?: string | null;
}

/* ── Map layer summary (project-scoped legend) ───────────────────────── */

/** Mirrors backend ``MapLayerSummary``. */
export interface MapLayerSummary {
  total: number;
  /** Domain breakdown (e.g. ``{ high: 3, low: 1 }``); empty when N/A. */
  breakdown: Record<string, number>;
}

/** Mirrors backend ``MapSummaryResponse``. */
export interface MapSummary {
  project_id: string;
  has_anchor: boolean;
  /** ``true`` when the anchor was derived from address coords (not saved). */
  anchor_is_derived: boolean;
  tilesets: MapLayerSummary;
  overlays: MapLayerSummary;
  raster_overlays: MapLayerSummary;
  viewpoints: MapLayerSummary;
  hse_pins: MapLayerSummary;
  punchlist_pins: MapLayerSummary;
  diary_pins: MapLayerSummary;
  active_jobs: number;
  total_features: number;
}

/* ── Geocode suggest (autocomplete) ──────────────────────────────────── */

export interface GeocodeSuggestion {
  display_name: string;
  lat: string;
  lon: string;
  country_code: string | null;
  addresstype: string | null;
  osm_type: string | null;
  bbox: string[] | null;
  /** Structured address parts (road, city, country, postcode, ...) so
   *  consumers can autofill structured form inputs without parsing
   *  the free-text ``display_name``. */
  address_parts?: Record<string, string> | null;
}

export interface GeocodeSuggestResponse {
  query: string;
  suggestions: GeocodeSuggestion[];
  geocoder_disabled: boolean;
}

/* ── Geocode cache admin ────────────────────────────────────────────── */

export interface GeocodeCacheStats {
  total: number;
  fresh: number;
  stale: number;
  hit_sum: number;
  ttl_days: number;
  oldest_cached_at: string | null;
  newest_cached_at: string | null;
}

export interface GeocodeCachePurgeResult {
  deleted: number;
  older_than_days: number | null;
}

/* ── Raster overlays (PDF / DWG / image pinned on the globe) ─────────── */

export type RasterOverlayKind = 'pdf' | 'dwg' | 'image';

/**
 * GeoJSON-style polygon (Type + coordinates only — no Feature wrapper).
 * The outer ring of ``coordinates`` is the crop boundary on the imagery.
 */
export interface CropPolygon {
  type: 'Polygon';
  coordinates: [number, number][][];
}

/** Mirrors backend ``GeoRasterOverlayResponse``. */
export interface GeoRasterOverlay {
  id: string;
  project_id: string;
  name: string;
  source_kind: RasterOverlayKind;
  source_blob_url: string | null;
  source_page: number;
  raster_blob_url: string | null;
  raster_width_px: number;
  raster_height_px: number;
  /** ``[NW, NE, SE, SW]`` as ``[lon, lat]`` pairs. */
  corners_geojson: [number, number][];
  rotation_deg: string;
  opacity: string;
  crop_polygon_geojson: CropPolygon | null;
  z_order: number;
  visible: boolean;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface GeoRasterOverlayPatch {
  name?: string;
  corners_geojson?: [number, number][];
  rotation_deg?: string;
  opacity?: string;
  crop_polygon_geojson?: CropPolygon | null;
  z_order?: number;
  visible?: boolean;
}

export interface PdfOverlayUploadResponse {
  overlay: GeoRasterOverlay;
  page_count: number;
}
