// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * API helpers for the Geo Hub module.
 *
 * Backed by /api/v1/geo-hub/ — see backend/app/modules/geo_hub/router.py
 */

import { apiDelete, apiGet, apiPatch, apiPost, apiPut, ApiError } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

import type {
  AnchoredProject,
  DiaryPhotoPin,
  GeoAnchor,
  GeoOverlay,
  GeoRasterOverlay,
  GeoRasterOverlayPatch,
  GeocodeCachePurgeResult,
  GeocodeCacheStats,
  GeocodeSuggestResponse,
  HSEPin,
  ImageryLayer,
  MapConfig,
  MapSummary,
  PdfOverlayUploadResponse,
  PunchlistPin,
  TerrainSource,
  TileJob,
  Tileset,
  Viewpoint,
} from './types';

const BASE = '/v1/geo-hub';

/* ── Map config one-shot bundle ──────────────────────────────────────── */

export function getMapConfig(
  projectId: string,
  options?: { developmentId?: string | null },
): Promise<MapConfig> {
  const params = new URLSearchParams();
  if (options?.developmentId) {
    params.set('development_id', options.developmentId);
  }
  const qs = params.toString();
  return apiGet<MapConfig>(
    `${BASE}/map-config/${projectId}${qs ? `?${qs}` : ''}`,
  );
}

/* ── Map summary (project-scoped layer legend) ───────────────────────── */

/**
 * Aggregate counts + breakdowns for every layer on a project's map.
 * One round-trip backing the layer legend - per-layer feature counts
 * plus small domain breakdowns (HSE severity, punch priority, tileset
 * status). See backend ``GET /map-summary/{project_id}``.
 */
export function getMapSummary(projectId: string): Promise<MapSummary> {
  return apiGet<MapSummary>(`${BASE}/map-summary/${projectId}`);
}

/* ── Anchors ─────────────────────────────────────────────────────────── */

export function listAnchors(projectId: string): Promise<GeoAnchor[]> {
  return apiGet<GeoAnchor[]>(`${BASE}/anchors/?project_id=${projectId}`);
}

export function createAnchor(body: {
  project_id: string;
  lat: string;
  lon: string;
  alt?: string;
  epsg_code?: number;
  region_code?: string | null;
  address?: string | null;
  accuracy_m?: string | null;
  metadata?: Record<string, unknown>;
}): Promise<GeoAnchor> {
  return apiPost<GeoAnchor>(`${BASE}/anchors/`, body);
}

export function updateAnchor(
  id: string,
  body: Partial<GeoAnchor>,
): Promise<GeoAnchor> {
  return apiPatch<GeoAnchor>(`${BASE}/anchors/${id}`, body);
}

export function deleteAnchor(id: string): Promise<void> {
  return apiDelete(`${BASE}/anchors/${id}`);
}

/* ── Tilesets ────────────────────────────────────────────────────────── */

export function listTilesets(projectId: string): Promise<Tileset[]> {
  return apiGet<Tileset[]>(`${BASE}/tilesets/?project_id=${projectId}`);
}

export function getTileset(id: string): Promise<Tileset> {
  return apiGet<Tileset>(`${BASE}/tilesets/${id}`);
}

export function generateTileset(body: {
  project_id: string;
  source_kind: Tileset['source_kind'];
  source_id: string;
  force?: boolean;
}): Promise<TileJob> {
  return apiPost<TileJob>(`${BASE}/tilesets/generate/`, body);
}

export function deleteTileset(id: string): Promise<void> {
  return apiDelete(`${BASE}/tilesets/${id}`);
}

/**
 * Place an already-converted BIM/CAD model on the project map as a
 * georeferenced 3D Tileset, anchored to the project location.
 *
 * ``cadImportId`` is the bim_hub model id - the backend resolves it
 * through ``BIMModelRepository`` in ``POST /from-canonical/{id}``, then
 * builds the tileset against the project's geo anchor. The body is left
 * empty so the tileset name falls back to the model's own name.
 *
 * Surfaced errors (the picker maps these to friendly toasts):
 *   - 404 ``cad_import_not_found`` - bad id or project mismatch;
 *   - 422 ``no_anchor_for_project`` - project has no map location yet;
 *   - 422 ``canonical_elements_empty`` / ``canonical_elements_have_no_geometry``
 *     - the model carries no usable 3D geometry to place.
 */
export function placeBimModelOnMap(
  cadImportId: string,
  options: { projectId: string; developmentId?: string | null },
): Promise<Tileset> {
  const qs = new URLSearchParams({ project_id: options.projectId });
  if (options.developmentId) qs.set('development_id', options.developmentId);
  // Packaging a model into a 3D Tileset is heavy CAD work: the backend
  // loads every canonical element, builds a glTF + b3dm, and uploads the
  // artifacts synchronously. On a large model this comfortably exceeds the
  // default 30 s mutation budget, and when the client-side abort fired the
  // user got a spurious "Request timed out" toast (plus a generic
  // "placement failed") even though the server kept working and the tileset
  // landed a moment later. Opt into the long-running budget so the success
  // path actually waits for the real response.
  return apiPost<Tileset>(
    `${BASE}/from-canonical/${cadImportId}?${qs.toString()}`,
    {},
    { longRunning: true },
  );
}

/* ── Jobs ────────────────────────────────────────────────────────────── */

export function listJobs(projectId: string, state?: string): Promise<TileJob[]> {
  const qs = new URLSearchParams({ project_id: projectId });
  if (state) qs.set('state', state);
  return apiGet<TileJob[]>(`${BASE}/jobs/?${qs.toString()}`);
}

export function getJob(id: string): Promise<TileJob> {
  return apiGet<TileJob>(`${BASE}/jobs/${id}`);
}

export function cancelJob(id: string): Promise<TileJob> {
  return apiPost<TileJob>(`${BASE}/jobs/${id}/cancel`, {});
}

/* ── Imagery ─────────────────────────────────────────────────────────── */

export function listImageryLayers(
  projectId: string,
): Promise<ImageryLayer[]> {
  return apiGet<ImageryLayer[]>(
    `${BASE}/imagery-layers/?project_id=${projectId}`,
  );
}

export function createImageryLayer(body: {
  project_id: string;
  name: string;
  provider: ImageryLayer['provider'];
  url_template: string;
  attribution?: string;
  requires_api_key?: boolean;
  default_for_project?: boolean;
  is_visible?: boolean;
}): Promise<ImageryLayer> {
  return apiPost<ImageryLayer>(`${BASE}/imagery-layers/`, body);
}

export function updateImageryLayer(
  id: string,
  body: Partial<ImageryLayer>,
): Promise<ImageryLayer> {
  return apiPatch<ImageryLayer>(`${BASE}/imagery-layers/${id}`, body);
}

export function deleteImageryLayer(id: string): Promise<void> {
  return apiDelete(`${BASE}/imagery-layers/${id}`);
}

/* ── Terrain ─────────────────────────────────────────────────────────── */

export function listTerrainSources(): Promise<TerrainSource[]> {
  return apiGet<TerrainSource[]>(`${BASE}/terrain-sources/`);
}

/* ── Viewpoints ──────────────────────────────────────────────────────── */

export function listViewpoints(projectId: string): Promise<Viewpoint[]> {
  return apiGet<Viewpoint[]>(`${BASE}/viewpoints/?project_id=${projectId}`);
}

export function createViewpoint(body: {
  project_id: string;
  name: string;
  camera_lat: string;
  camera_lon: string;
  camera_alt?: string;
  heading?: string;
  pitch?: string;
  roll?: string;
  description?: string;
}): Promise<Viewpoint> {
  return apiPost<Viewpoint>(`${BASE}/viewpoints/`, body);
}

export function deleteViewpoint(id: string): Promise<void> {
  return apiDelete(`${BASE}/viewpoints/${id}`);
}

/* ── Overlays + GeoJSON / KML I/O ────────────────────────────────────── */

export function listOverlays(
  projectId: string,
  kind?: string,
): Promise<GeoOverlay[]> {
  const qs = new URLSearchParams({ project_id: projectId });
  if (kind) qs.set('kind', kind);
  return apiGet<GeoOverlay[]>(`${BASE}/overlays/?${qs.toString()}`);
}

export function importGeoJSON(body: {
  project_id: string;
  name?: string;
  kind?: string;
  geojson: Record<string, unknown>;
}): Promise<GeoOverlay> {
  return apiPost<GeoOverlay>(`${BASE}/overlays/import-geojson/`, body);
}

export function importKML(body: {
  project_id: string;
  name?: string;
  kind?: string;
  kml: string;
}): Promise<GeoOverlay> {
  return apiPost<GeoOverlay>(`${BASE}/overlays/import-kml/`, body);
}

/**
 * Export a project's whole map as one GeoJSON FeatureCollection. By
 * default this folds in the anchor point + the HSE / punchlist / diary
 * pin layers alongside the vector overlays (each feature tagged with an
 * ``oe:layer`` property). Pass ``include`` to export only a subset of
 * layers, or ``kind`` to narrow the vector-overlay slice.
 */
export function exportGeoJSON(
  projectId: string,
  options?: { kind?: string; include?: string[] },
): Promise<Record<string, unknown>> {
  const qs = new URLSearchParams({ project_id: projectId });
  if (options?.kind) qs.set('kind', options.kind);
  if (options?.include && options.include.length > 0) {
    qs.set('include', options.include.join(','));
  }
  return apiGet<Record<string, unknown>>(
    `${BASE}/overlays/export-geojson/?${qs.toString()}`,
  );
}

export function deleteOverlay(id: string): Promise<void> {
  return apiDelete(`${BASE}/overlays/${id}`);
}

/* ── Auto-anchor (from project address) ──────────────────────────────── */

export interface AnchorFromAddressResult {
  anchor: GeoAnchor;
  precision: 'address' | 'street' | 'city' | 'region' | 'country';
  source: 'nominatim' | 'cache' | 'manual';
  display_name: string | null;
}

export interface BulkAnchorResultRow {
  project_id: string;
  project_name: string | null;
  status: 'ok' | 'skipped' | 'failed';
  reason: string | null;
  anchor_id: string | null;
  precision: string | null;
}

export interface BulkAnchorSummary {
  succeeded: number;
  skipped: number;
  failed: number;
  results: BulkAnchorResultRow[];
}

/** Auto-anchor a project from its stored address.
 *
 * 422 → address missing (UI should prompt for project address).
 * 409 → anchor already exists (UI offers "Re-geocode" toggling `force`).
 * 502 → geocoder unavailable.
 */
export function autoAnchorFromAddress(
  projectId: string,
  options?: { force?: boolean },
): Promise<AnchorFromAddressResult> {
  const qs = options?.force ? '?force=true' : '';
  return apiPost<AnchorFromAddressResult>(
    `${BASE}/anchors/from-address/${qs}`,
    { project_id: projectId },
  );
}

/** Bulk auto-anchor every caller-accessible un-anchored project. */
export function bulkAutoAnchorFromAddress(): Promise<BulkAnchorSummary> {
  // The backend serialises every project through the geocoder at >=1 req/sec
  // (a process-global rate limit) over up to 200 rows, so a workspace with
  // many un-cached projects comfortably exceeds the default 45s mutation
  // budget. Opt into the long-running budget so the primary empty-state CTA
  // waits for the real per-project summary instead of aborting at 45s and
  // showing a spurious "Bulk auto-anchor failed" toast while pins keep landing.
  return apiPost<BulkAnchorSummary>(`${BASE}/anchors/from-address/bulk/`, {}, { longRunning: true });
}

/* ── Anchored projects (Global Geo Hub pin layer) ───────────────────── */

export function fetchAnchoredProjects(
  limit = 500,
): Promise<AnchoredProject[]> {
  return apiGet<AnchoredProject[]>(`${BASE}/projects?limit=${limit}`);
}

/* ── Cross-module geo pin layers ─────────────────────────────────────── */

export function fetchHsePins(
  projectId: string,
  limit = 500,
): Promise<HSEPin[]> {
  return apiGet<HSEPin[]>(
    `${BASE}/projects/${projectId}/hse-pins?limit=${limit}`,
  );
}

export function fetchPunchlistPins(
  projectId: string,
  limit = 500,
): Promise<PunchlistPin[]> {
  return apiGet<PunchlistPin[]>(
    `${BASE}/projects/${projectId}/punchlist-pins?limit=${limit}`,
  );
}

export function fetchDiaryPhotoPins(
  projectId: string,
  limit = 500,
): Promise<DiaryPhotoPin[]> {
  return apiGet<DiaryPhotoPin[]>(
    `${BASE}/projects/${projectId}/diary-photo-pins?limit=${limit}`,
  );
}

/* ── Raster overlays (PDF / DWG / image pinned on the globe) ─────────── */

const RASTER_BASE = `${BASE}/raster-overlays`;

export function listRasterOverlays(
  projectId: string,
  options?: { includeHidden?: boolean },
): Promise<GeoRasterOverlay[]> {
  const qs = new URLSearchParams({ project_id: projectId });
  if (options?.includeHidden !== undefined) {
    qs.set('include_hidden', String(options.includeHidden));
  }
  return apiGet<GeoRasterOverlay[]>(`${RASTER_BASE}/?${qs.toString()}`);
}

export function getRasterOverlay(id: string): Promise<GeoRasterOverlay> {
  return apiGet<GeoRasterOverlay>(`${RASTER_BASE}/${id}`);
}

export function updateRasterOverlay(
  id: string,
  body: GeoRasterOverlayPatch,
): Promise<GeoRasterOverlay> {
  return apiPatch<GeoRasterOverlay, GeoRasterOverlayPatch>(
    `${RASTER_BASE}/${id}`,
    body,
  );
}

export function deleteRasterOverlay(id: string): Promise<void> {
  return apiDelete(`${RASTER_BASE}/${id}`);
}

/**
 * Multipart uploads need their own fetch — the standard `apiPost` JSON
 * helper hard-codes `Content-Type: application/json` which would break
 * the multipart boundary. We rebuild the auth + accept headers locally
 * so the upload still flows through the same auth gate.
 */
async function multipartUpload<T>(
  path: string,
  formData: FormData,
): Promise<T> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'X-DDC-Client': 'OE/1.0',
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    headers,
    body: formData,
  });
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new ApiError(res.status, res.statusText, body);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function uploadPdfRasterOverlay(
  projectId: string,
  file: File,
  options?: { page?: number; name?: string | null },
): Promise<PdfOverlayUploadResponse> {
  const fd = new FormData();
  fd.append('project_id', projectId);
  fd.append('page', String(options?.page ?? 1));
  if (options?.name) fd.append('name', options.name);
  fd.append('file', file);
  return multipartUpload<PdfOverlayUploadResponse>(
    `${RASTER_BASE}/upload-pdf`,
    fd,
  );
}

export function uploadImageRasterOverlay(
  projectId: string,
  file: File,
  options?: { name?: string | null },
): Promise<GeoRasterOverlay> {
  const fd = new FormData();
  fd.append('project_id', projectId);
  if (options?.name) fd.append('name', options.name);
  fd.append('file', file);
  return multipartUpload<GeoRasterOverlay>(
    `${RASTER_BASE}/upload-image`,
    fd,
  );
}

export function rasterOverlayFromDwg(
  cadImportId: string,
  options?: { projectId?: string; name?: string | null },
): Promise<GeoRasterOverlay> {
  const qs = new URLSearchParams();
  if (options?.projectId) qs.set('project_id', options.projectId);
  if (options?.name) qs.set('name', options.name);
  const path = `${RASTER_BASE}/from-dwg/${cadImportId}${
    qs.toString() ? `?${qs.toString()}` : ''
  }`;
  return apiPost<GeoRasterOverlay>(path, {});
}

/** Resolve the public URL used by Cesium's SingleTileImageryProvider. */
export function rasterOverlayImageUrl(id: string): string {
  return `/api${RASTER_BASE}/${id}/raster.png`;
}

/**
 * URL Cesium uses to load a tileset artifact (``tileset.json`` or a child
 * tile such as ``tile_0.b3dm``). The DB stores only a storage key, so the
 * backend artifact route streams the bytes; Cesium resolves child tiles
 * relative to the ``tileset.json`` URL, so they hit this same route.
 */
export function tilesetArtifactUrl(tilesetId: string, filename = 'tileset.json'): string {
  return `/api${BASE}/tilesets/${tilesetId}/artifact/${filename}`;
}

/**
 * Authorization headers for the requests Cesium issues itself (imagery
 * overlays and 3D tilesets). Cesium cannot read the api-client interceptor,
 * so the bearer token is attached to the Cesium ``Resource`` instead. The
 * geo artifact endpoints are tenant-scoped and 401 without it.
 */
export function geoAuthHeaders(): Record<string, string> {
  const token = useAuthStore.getState().accessToken;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/* ── Geocode autocomplete + cache admin (Wave 7 depth) ──────────────── */

/**
 * In-memory client cache for the autocomplete dropdown. Keyed by the
 * exact query string sent to the backend (already trimmed + lowercased
 * by the consumer). 5-minute TTL — short enough to avoid stale results
 * after the user fixes a typo, long enough to absorb the common
 * "back-up-and-retype" pattern without burning Nominatim budget.
 *
 * Map iteration order = insertion order, so a manual `keys().next()`
 * eviction acts as approximate LRU when the cache grows past ``CAP``.
 */
const SUGGEST_CACHE_TTL_MS = 5 * 60 * 1000;
const SUGGEST_CACHE_CAP = 100;
const _suggestCache = new Map<
  string,
  { at: number; data: GeocodeSuggestResponse }
>();

function _suggestCacheGet(key: string): GeocodeSuggestResponse | null {
  const hit = _suggestCache.get(key);
  if (!hit) return null;
  if (Date.now() - hit.at > SUGGEST_CACHE_TTL_MS) {
    _suggestCache.delete(key);
    return null;
  }
  return hit.data;
}

function _suggestCacheSet(key: string, data: GeocodeSuggestResponse): void {
  if (_suggestCache.size >= SUGGEST_CACHE_CAP) {
    const oldest = _suggestCache.keys().next().value;
    if (oldest !== undefined) _suggestCache.delete(oldest);
  }
  _suggestCache.set(key, { at: Date.now(), data });
}

/** Test-only — clear the client-side suggest cache. */
export function _clearSuggestCacheForTests(): void {
  _suggestCache.clear();
}

/**
 * Autocomplete address suggestions from Nominatim (via backend proxy).
 *
 * Performs no client-side debouncing — the caller is expected to debounce
 * keystrokes (300 ms is the recommended setting per Wave 7 plan). Uses
 * a 5-minute in-memory cache keyed on the exact query so back-and-forth
 * typing doesn't re-hit the backend.
 */
export async function geocodeSuggest(
  q: string,
  options?: { limit?: number; signal?: AbortSignal },
): Promise<GeocodeSuggestResponse> {
  const trimmed = q.trim();
  const limit = options?.limit ?? 5;
  const cacheKey = `${limit}:${trimmed.toLowerCase()}`;
  const cached = _suggestCacheGet(cacheKey);
  if (cached) return cached;
  const qs = new URLSearchParams({ q: trimmed, limit: String(limit) });
  const url = `${BASE}/geocode/suggest?${qs.toString()}`;
  // ``apiGet`` doesn't accept AbortSignal, so for cancellation support
  // we hand-roll the fetch with the shared headers. Imports the auth
  // store at call time to avoid a circular dependency at module load.
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'X-DDC-Client': 'OE/1.0',
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`/api${url}`, {
    method: 'GET',
    headers,
    signal: options?.signal,
  });
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new ApiError(res.status, res.statusText, body);
  }
  const data = (await res.json()) as GeocodeSuggestResponse;
  _suggestCacheSet(cacheKey, data);
  return data;
}

/** Admin — geocode cache statistics for the Geo Hub admin panel. */
/** Where project addresses may go for geocoding; asked once per installation. */
export type GeocodingConsentState =
  | 'unanswered'
  | 'allow'
  | 'deny'
  | 'mirror'
  | 'env_disabled'
  | 'env_mirror';

export interface GeocodingConsent {
  state: GeocodingConsentState;
  mirror_url: string | null;
  nominatim_url: string | null;
  photon_url: string | null;
  can_decide: boolean;
}

export function getGeocodingConsent(): Promise<GeocodingConsent> {
  return apiGet<GeocodingConsent>(`${BASE}/geocoding-consent`);
}

export function setGeocodingConsent(body: {
  choice: 'allow' | 'deny' | 'mirror';
  mirror_url?: string | null;
}): Promise<GeocodingConsent> {
  return apiPut<GeocodingConsent>(`${BASE}/geocoding-consent`, body);
}

export function getGeocodeCacheStats(): Promise<GeocodeCacheStats> {
  return apiGet<GeocodeCacheStats>(`${BASE}/geocode/cache/stats`);
}

/** Admin — purge cache rows older than ``olderThanDays`` (default 30). */
export function purgeGeocodeCache(
  olderThanDays = 30,
): Promise<GeocodeCachePurgeResult> {
  return apiDelete<GeocodeCachePurgeResult>(
    `${BASE}/geocode/cache?older_than_days=${olderThanDays}`,
  );
}
