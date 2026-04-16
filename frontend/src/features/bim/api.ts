/**
 * API helpers for BIM Hub.
 *
 * Endpoints:
 *   GET  /v1/bim_hub?project_id=X          — list models for a project
 *   POST /v1/bim_hub/upload                 — upload BIM data (DataFrame + optional DAE)
 *   GET  /v1/bim_hub/models/{id}/elements   — list elements for a model
 *   GET  /v1/bim_hub/models/{id}/geometry   — serve DAE geometry file
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import type { BIMElementData, BIMModelData } from '@/shared/ui/BIMViewer';

/* ── Response Types ────────────────────────────────────────────────────── */

export interface BIMModelsResponse {
  items: BIMModelData[];
  total: number;
}

export interface BIMElementsResponse {
  items: BIMElementData[];
  total: number;
}

export interface BIMUploadResponse {
  model_id: string;
  element_count: number;
  storeys: string[];
  disciplines: string[];
  has_geometry: boolean;
}

export interface BIMCadUploadResponse {
  /** Nullable — preflight `converter_required` rejects return `null`
   *  because no BIMModel row is created in that path. */
  model_id: string | null;
  /** Nullable for the same reason as `model_id`. */
  name: string | null;
  format: string;
  file_size: number;
  /** Final status after processing. `'converter_required'` is a
   *  preflight reject (no file saved); `'needs_converter'` is the
   *  post-upload case where the file was accepted but could not
   *  be processed. */
  status:
    | 'processing'
    | 'ready'
    | 'needs_converter'
    | 'error'
    | 'converter_required'
    | string;
  /** Number of BIM elements extracted by the processor.  Always
   *  present in the backend response (defaults to 0 when no
   *  elements were extracted, e.g. unprocessable formats). */
  element_count: number;
  // ── Added in v1.4.7 (converter preflight + auto-install) ──────────
  /** Real backend error message from ``BIMModel.error_message`` —
   *  surfaced so the frontend can show the actual reason instead
   *  of a hardcoded generic string. */
  error_message?: string | null;
  /** Converter id (e.g. `"rvt"`) — present on `converter_required`
   *  and `needs_converter` so the UI can offer a one-click install. */
  converter_id?: string | null;
  /** Absolute API path that triggers the install — present alongside
   *  `converter_id` in the same statuses. */
  install_endpoint?: string | null;
  /** Human-readable message — present on `converter_required`
   *  preflight rejects. */
  message?: string | null;
}

/* ── Converter Management (BIM preflight + auto-install) ─────────────── */

/** Single DDC converter entry as returned by the backend
 *  `/v1/takeoff/converters/` endpoint. */
export interface BIMConverterInfo {
  /** Stable converter id — one of `'rvt'`, `'dwg'`, `'ifc'`, `'dgn'`. */
  id: string;
  name: string;
  description: string;
  engine: string;
  extensions: string[];
  exe: string;
  version: string;
  size_mb: number;
  installed: boolean;
  path: string | null;
}

/** Response payload of `GET /v1/takeoff/converters/`. */
export interface BIMConvertersResponse {
  converters: BIMConverterInfo[];
  installed_count: number;
  total_count: number;
}

/** Result of `POST /v1/takeoff/converters/{id}/install/`. */
export interface BIMConverterInstallResult {
  converter_id: string;
  installed: boolean;
  path: string;
  already_installed?: boolean;
  size_bytes?: number;
  message: string;
}

/** List every DDC converter and its install status.  Shared with the
 *  Quantities page — use the same `['bim-converters']` query key in
 *  any component that renders converter state so cache invalidations
 *  stay in sync. */
export async function fetchBIMConverters(): Promise<BIMConvertersResponse> {
  return apiGet<BIMConvertersResponse>('/v1/takeoff/converters/');
}

/** Trigger an auto-install of a DDC converter from GitHub releases.
 *  The request is blocking on the backend (downloads + extracts +
 *  verifies) and typically takes 60–120 s for the RVT converter. */
export async function installBIMConverter(
  converterId: string,
): Promise<BIMConverterInstallResult> {
  return apiPost<BIMConverterInstallResult>(
    `/v1/takeoff/converters/${encodeURIComponent(converterId)}/install/`,
    {},
  );
}

/* ── API Functions ─────────────────────────────────────────────────────── */

/** Fetch all BIM models for a project. */
export async function fetchBIMModels(projectId: string): Promise<BIMModelsResponse> {
  return apiGet<BIMModelsResponse>(`/v1/bim_hub/?project_id=${encodeURIComponent(projectId)}`);
}

/** Fetch a single BIM model by ID (used for status polling). */
export async function fetchBIMModel(modelId: string): Promise<BIMModelData> {
  return apiGet<BIMModelData>(`/v1/bim_hub/${encodeURIComponent(modelId)}`);
}

/** Fetch elements for a specific BIM model.
 *
 * Two modes:
 *   * `skeleton: true` — plain BIMElement rows, no enrichment joins. ~10×
 *     faster; used by the 3D viewer (it only needs id / mesh_ref / name /
 *     element_type / bbox for mesh matching). Server cap 50 000.
 *   * `skeleton: false` (default) — enriched with boq_links, linked
 *     documents / tasks / activities / requirements and validation
 *     results. Paginated (server cap 2000). Used by BOQ linking and the
 *     element list.
 *
 * A click in the viewer still resolves full Revit properties via
 * /dataframe/query/ against the Parquet, so selection cost is O(1) in
 * element count regardless of which mode fetched the list.
 */
export async function fetchBIMElements(
  modelId: string,
  opts?: {
    limit?: number;
    offset?: number;
    groupId?: string | null;
    skeleton?: boolean;
  },
): Promise<BIMElementsResponse> {
  const skeleton = opts?.skeleton ?? false;
  const limit = opts?.limit ?? (skeleton ? 50000 : 500);
  const offset = opts?.offset ?? 0;
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (opts?.groupId) params.set('group_id', opts.groupId);
  if (skeleton) params.set('skeleton', 'true');
  return apiGet<BIMElementsResponse>(
    `/v1/bim_hub/models/${encodeURIComponent(modelId)}/elements/?${params.toString()}`,
  );
}

/** Fetch specific elements by their IDs (DB UUID or stable_id).
 *  Used by the BIM Quantity Picker to load only linked elements. */
export async function fetchBIMElementsByIds(
  modelId: string,
  elementIds: string[],
): Promise<BIMElementsResponse> {
  return apiPost<BIMElementsResponse, { element_ids: string[] }>(
    `/v1/bim_hub/models/${encodeURIComponent(modelId)}/elements/by-ids/`,
    { element_ids: elementIds },
  );
}

/** Fetch the geometry file as a blob and return an object URL.
 *
 * Uses the Authorization header instead of a query-param token to avoid
 * leaking the JWT in logs, CDN caches, or error messages.  The caller
 * MUST call `URL.revokeObjectURL()` on the returned URL when done.
 */
export async function fetchGeometryBlobUrl(modelId: string): Promise<string> {
  const token = useAuthStore.getState().accessToken;
  // Cache-bust: geometry may have been re-generated with patched node names
  const url = `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/geometry/?_t=${Date.now()}`;
  const headers: HeadersInit = { Accept: '*/*', 'Cache-Control': 'no-cache' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const resp = await fetch(url, { headers });
  if (!resp.ok) {
    throw new Error(`Geometry fetch failed (HTTP ${resp.status})`);
  }
  const blob = await resp.blob();
  return URL.createObjectURL(blob);
}

/** Fetch the full Parquet row for a single element, keyed by its Revit
 *  ElementId (the Parquet `id` column).
 *
 *  The 3D viewer uses the lightweight "skeleton" element list
 *  (`fetchBIMElements(..., { skeleton: true })`) — five fields per row, no
 *  properties. When the user clicks a mesh the viewer calls this to pull
 *  the full ~45-1000 column row (all DDC-extracted Revit parameters) on
 *  demand. That keeps the initial load fast and lazy-loads detail only
 *  when needed.
 *
 *  `revitId` is typically `BIMElementData.mesh_ref`. For DDC-exported
 *  RVT / IFC this equals the DAE `<node id="...">` attribute and the
 *  Parquet row's `id`. Returns `null` when the Parquet has no row with
 *  that id (the element was filtered out of BIMElement by the category
 *  skip-list but still survives in Parquet).
 */
export async function fetchBIMElementProperties(
  modelId: string,
  revitId: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown> | null> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const resp = await fetch(
    `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/dataframe/query/`,
    {
      method: 'POST',
      headers,
      signal,
      body: JSON.stringify({
        filters: [{ column: 'id', op: '=', value: String(revitId) }],
        limit: 1,
      }),
    },
  );

  if (!resp.ok) {
    throw new Error(`Element properties fetch failed (HTTP ${resp.status})`);
  }
  const rows = (await resp.json()) as Record<string, unknown>[];
  return rows[0] ?? null;
}

/** @deprecated Use fetchGeometryBlobUrl() instead — this exposes the JWT in the URL. */
export function getGeometryUrl(modelId: string): string {
  const token = useAuthStore.getState().accessToken;
  const base = `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/geometry/`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

/** Upload BIM data (DataFrame + optional geometry file). */
export async function uploadBIMData(
  projectId: string,
  name: string,
  discipline: string,
  dataFile: File,
  geometryFile?: File | null,
  signal?: AbortSignal,
): Promise<BIMUploadResponse> {
  const formData = new FormData();
  formData.append('data_file', dataFile);
  if (geometryFile) {
    formData.append('geometry_file', geometryFile);
  }

  const params = new URLSearchParams({
    project_id: projectId,
    name,
    discipline,
  });

  const token = useAuthStore.getState().accessToken;
  const headers: HeadersInit = {
    Accept: 'application/json',
    'X-DDC-Client': 'OE/1.0',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`/api/v1/bim_hub/upload/?${params.toString()}`, {
      method: 'POST',
      headers,
      body: formData,
      signal,
    });
  } catch (networkErr) {
    // Re-throw AbortError as-is so callers can distinguish cancellation
    if (networkErr instanceof DOMException && networkErr.name === 'AbortError') throw networkErr;
    throw new Error(
      'Cannot connect to server. Please check that the backend is running and try again.',
    );
  }

  if (!response.ok) {
    let detail = `Upload failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse errors
    }
    throw new Error(detail);
  }

  return response.json();
}

/** Delete a BIM model and all its elements. */
export async function deleteBIMModel(modelId: string): Promise<void> {
  await apiDelete(`/v1/bim_hub/${encodeURIComponent(modelId)}`);
}

/* ── BIM ↔ BOQ Linking ─────────────────────────────────────────────────── */

/** A single link between a BIM element and a BOQ position. */
export interface BOQElementLink {
  id: string;
  boq_position_id: string;
  bim_element_id: string;
  link_type: 'manual' | 'auto' | 'rule_based';
  confidence: string | null;
  rule_id: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Brief embedded in the element response: the linked BOQ position's key fields. */
export interface BOQElementLinkBrief {
  id: string;
  boq_position_id: string;
  boq_position_ordinal: string | null;
  boq_position_description: string | null;
  boq_position_quantity: number | null;
  boq_position_unit: string | null;
  boq_position_unit_rate: number | null;
  boq_position_total: number | null;
  link_type: 'manual' | 'auto' | 'rule_based';
  confidence: string | null;
}

export interface BOQElementLinkListResponse {
  items: BOQElementLink[];
  total: number;
}

export interface CreateBOQElementLinkRequest {
  boq_position_id: string;
  bim_element_id: string;
  link_type?: 'manual' | 'auto' | 'rule_based';
  confidence?: string;
  rule_id?: string;
  metadata?: Record<string, unknown>;
}

/** List every BIM element link attached to a given BOQ position. */
export async function listLinks(
  boqPositionId: string,
): Promise<BOQElementLinkListResponse> {
  return apiGet<BOQElementLinkListResponse>(
    `/v1/bim_hub/links/?boq_position_id=${encodeURIComponent(boqPositionId)}`,
  );
}

/** Resolve (or lazy-create) a BIMElement DB row from a mesh_ref / stable_id.
 *
 *  When the user clicks a mesh in the 3D viewer that was NOT returned by
 *  the standard BIMElement listing (e.g. DDC's Excel extract skipped the
 *  category — tapered roofs, planting, detail lines…), the frontend holds
 *  only a client-side stub id like `_unmatched_12`.  That id will fail UUID
 *  validation on POST /links/.  Call this first to swap the stub for a
 *  real BIMElement UUID; the backend pulls the row from Parquet and persists
 *  it so future operations treat it like any other element. */
export async function ensureBIMElement(
  modelId: string,
  ref: { meshRef?: string | null; stableId?: string | null },
): Promise<{ id: string }> {
  const payload: Record<string, string> = {};
  if (ref.meshRef) payload.mesh_ref = ref.meshRef;
  if (ref.stableId) payload.stable_id = ref.stableId;
  return apiPost<{ id: string }, Record<string, string>>(
    `/v1/bim_hub/models/${encodeURIComponent(modelId)}/ensure-element/`,
    payload,
  );
}

/** Create a new BIM ↔ BOQ link. Returns the created record. */
export async function createLink(
  payload: CreateBOQElementLinkRequest,
): Promise<BOQElementLink> {
  return apiPost<BOQElementLink, CreateBOQElementLinkRequest>(
    '/v1/bim_hub/links/',
    payload,
  );
}

/** Remove a BIM ↔ BOQ link by its row id. */
export async function deleteLink(linkId: string): Promise<void> {
  await apiDelete(`/v1/bim_hub/links/${encodeURIComponent(linkId)}`);
}

/* ── Quantity Maps (rule-based bulk linking) ───────────────────────────── */

/** Optional target for a quantity-map rule. */
export interface QuantityMapTarget {
  /** Existing position to link to (preferred). */
  position_id?: string;
  /** Existing position to link to, looked up by its ordinal inside the project. */
  position_ordinal?: string;
  /** If true and no position resolves, auto-create one with the rule's name. */
  auto_create?: boolean;
  /** Classification JSON to attach to the auto-created position. */
  classification?: Record<string, string>;
  /** Default unit rate for auto-created positions.  Typically populated
   *  via the "Suggest from CWICR" button which calls
   *  `/api/v1/costs/suggest-for-element/` and inserts the top match. */
  unit_rate?: string;
  /** Cost item id this rule was matched against — kept around so the
   *  estimator can audit which CWICR row supplied the rate. */
  cost_item_id?: string;
}

export interface BIMQuantityMap {
  id: string;
  org_id: string | null;
  project_id: string | null;
  name: string;
  name_translations: Record<string, string> | null;
  element_type_filter: string;
  property_filter: Record<string, string> | null;
  quantity_source: string;
  multiplier: string;
  unit: string;
  waste_factor_pct: string | null;
  boq_target: QuantityMapTarget | null;
  is_active: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface BIMQuantityMapListResponse {
  items: BIMQuantityMap[];
  total: number;
}

export type CreateBIMQuantityMapRequest = Omit<
  BIMQuantityMap,
  'id' | 'created_at' | 'updated_at'
>;

export type PatchBIMQuantityMapRequest = Partial<CreateBIMQuantityMapRequest>;

export interface QuantityMapApplyRequest {
  model_id: string;
  dry_run: boolean;
}

export interface QuantityMapApplyResultItem {
  element_id: string;
  stable_id: string;
  element_type: string;
  rule_id: string;
  rule_name: string;
  quantity_source: string;
  raw_quantity: number;
  adjusted_quantity: number;
  unit: string;
  boq_target: QuantityMapTarget | null;
}

export interface QuantityMapApplyResult {
  matched_elements: number;
  rules_applied: number;
  links_created: number;
  positions_created: number;
  results: QuantityMapApplyResultItem[];
}

/** List every quantity-map rule visible to the current user. */
export async function listQuantityMaps(
  offset = 0,
  limit = 100,
): Promise<BIMQuantityMapListResponse> {
  return apiGet<BIMQuantityMapListResponse>(
    `/v1/bim_hub/quantity-maps/?offset=${offset}&limit=${limit}`,
  );
}

/** Create a new quantity-map rule. */
export async function createQuantityMap(
  payload: CreateBIMQuantityMapRequest,
): Promise<BIMQuantityMap> {
  return apiPost<BIMQuantityMap, CreateBIMQuantityMapRequest>(
    '/v1/bim_hub/quantity-maps/',
    payload,
  );
}

/** Patch a quantity-map rule. */
export async function patchQuantityMap(
  mapId: string,
  payload: PatchBIMQuantityMapRequest,
): Promise<BIMQuantityMap> {
  return apiPatch<BIMQuantityMap, PatchBIMQuantityMapRequest>(
    `/v1/bim_hub/quantity-maps/${encodeURIComponent(mapId)}`,
    payload,
  );
}

/** Apply every active quantity-map rule to the given model.
 *
 * When `dry_run` is true (the default), the endpoint returns a preview of
 * what would be linked without writing anything.  When false, it creates
 * real `BOQElementLink` rows (and, for rules with `auto_create: true`,
 * creates fresh BOQ positions) inside a transaction per rule.
 */
export async function applyQuantityMaps(
  modelId: string,
  dryRun = true,
): Promise<QuantityMapApplyResult> {
  return apiPost<QuantityMapApplyResult, QuantityMapApplyRequest>(
    '/v1/bim_hub/quantity-maps/apply/',
    { model_id: modelId, dry_run: dryRun },
  );
}

/* ── BIM Element Groups (saved selections) ────────────────────────────── */

/** Filter predicate for a dynamic group.  Every field is optional and
 *  multi-valued where it makes sense.  An empty filter matches every
 *  element. */
export interface BIMGroupFilterCriteria {
  element_type?: string | string[];
  category?: string | string[];
  discipline?: string | string[];
  storey?: string | string[];
  name_contains?: string;
  property_filter?: Record<string, string>;
}

export interface BIMElementGroup {
  id: string;
  project_id: string;
  model_id: string | null;
  name: string;
  description: string | null;
  is_dynamic: boolean;
  filter_criteria: BIMGroupFilterCriteria;
  element_ids: string[];
  element_count: number;
  color: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  /** Resolved member element UUIDs (computed by the backend on read for
   *  dynamic groups; equal to `element_ids` for static groups). */
  member_element_ids: string[];
}

export interface BIMElementGroupCreate {
  name: string;
  description?: string;
  model_id?: string | null;
  is_dynamic?: boolean;
  filter_criteria?: BIMGroupFilterCriteria;
  element_ids?: string[];
  color?: string;
}

export type BIMElementGroupUpdate = Partial<BIMElementGroupCreate>;

/** List every saved element group for the project, optionally scoped to one model. */
export async function listElementGroups(
  projectId: string,
  modelId?: string | null,
): Promise<BIMElementGroup[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (modelId) params.set('model_id', modelId);
  return apiGet<BIMElementGroup[]>(
    `/v1/bim_hub/element-groups/?${params.toString()}`,
  );
}

/** Create a new element group.  Returns the created record with member ids resolved. */
export async function createElementGroup(
  projectId: string,
  payload: BIMElementGroupCreate,
): Promise<BIMElementGroup> {
  return apiPost<BIMElementGroup, BIMElementGroupCreate>(
    `/v1/bim_hub/element-groups/?project_id=${encodeURIComponent(projectId)}`,
    payload,
  );
}

/** Patch an existing element group.  When filter_criteria changes the
 *  member ids are recomputed and re-cached on the backend side. */
export async function updateElementGroup(
  groupId: string,
  payload: BIMElementGroupUpdate,
): Promise<BIMElementGroup> {
  return apiPatch<BIMElementGroup, BIMElementGroupUpdate>(
    `/v1/bim_hub/element-groups/${encodeURIComponent(groupId)}`,
    payload,
  );
}

/** Delete an element group.  Existing BIMElementLink rows referencing
 *  members of the group are NOT touched — the group is just metadata. */
export async function deleteElementGroup(groupId: string): Promise<void> {
  await apiDelete(`/v1/bim_hub/element-groups/${encodeURIComponent(groupId)}`);
}

/* ── Cross-module link wrappers (Documents / Tasks / Schedule) ───────── */

/** A document ↔ BIM element link. */
export interface DocumentBIMLink {
  id: string;
  document_id: string;
  bim_element_id: string;
  link_type: 'manual' | 'auto';
  confidence: string | null;
  region_bbox: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DocumentBIMLinkListResponse {
  items: DocumentBIMLink[];
  total: number;
}

export interface CreateDocumentBIMLinkRequest {
  document_id: string;
  bim_element_id: string;
  link_type?: 'manual' | 'auto';
  confidence?: string;
  region_bbox?: Record<string, unknown>;
}

/** List documents linked to a BIM element. */
export async function listDocumentsForElement(
  elementId: string,
): Promise<DocumentBIMLinkListResponse> {
  return apiGet<DocumentBIMLinkListResponse>(
    `/v1/documents/bim-links/?element_id=${encodeURIComponent(elementId)}`,
  );
}

/** List BIM elements linked from a document. */
export async function listElementsForDocument(
  documentId: string,
): Promise<DocumentBIMLinkListResponse> {
  return apiGet<DocumentBIMLinkListResponse>(
    `/v1/documents/bim-links/?document_id=${encodeURIComponent(documentId)}`,
  );
}

/** Create a new document ↔ BIM element link. */
export async function createDocumentBIMLink(
  payload: CreateDocumentBIMLinkRequest,
): Promise<DocumentBIMLink> {
  return apiPost<DocumentBIMLink, CreateDocumentBIMLinkRequest>(
    '/v1/documents/bim-links/',
    payload,
  );
}

/** Remove a document ↔ BIM element link by id. */
export async function deleteDocumentBIMLink(linkId: string): Promise<void> {
  await apiDelete(`/v1/documents/bim-links/${encodeURIComponent(linkId)}`);
}

/* ── Tasks ↔ BIM element wrappers ────────────────────────────────────── */

export interface TaskBimLinkRequest {
  bim_element_ids: string[];
}

/** Replace the bim_element_ids list on a task. */
export async function updateTaskBIMLinks(
  taskId: string,
  bimElementIds: string[],
): Promise<unknown> {
  return apiPatch<unknown, TaskBimLinkRequest>(
    `/v1/tasks/${encodeURIComponent(taskId)}/bim-links`,
    { bim_element_ids: bimElementIds },
  );
}

/** List tasks that include the given BIM element id. */
export async function listTasksForElement(
  bimElementId: string,
  projectId?: string,
): Promise<unknown> {
  const params = new URLSearchParams({ bim_element_id: bimElementId });
  if (projectId) params.set('project_id', projectId);
  return apiGet<unknown>(`/v1/tasks/?${params.toString()}`);
}

/* ── Schedule activity ↔ BIM element wrappers ────────────────────────── */

export interface ActivityBimLinkRequest {
  bim_element_ids: string[];
}

/** Replace the bim_element_ids list on a schedule activity. */
export async function updateActivityBIMLinks(
  activityId: string,
  bimElementIds: string[],
): Promise<unknown> {
  return apiPatch<unknown, ActivityBimLinkRequest>(
    `/v1/schedule/activities/${encodeURIComponent(activityId)}/bim-links`,
    { bim_element_ids: bimElementIds },
  );
}

/** List schedule activities that include the given BIM element id. */
export async function listActivitiesForElement(
  bimElementId: string,
  projectId: string,
): Promise<unknown> {
  const params = new URLSearchParams({
    element_id: bimElementId,
    project_id: projectId,
  });
  return apiGet<unknown>(
    `/v1/schedule/activities/by-bim-element/?${params.toString()}`,
  );
}

/** Upload a raw CAD file (RVT, IFC, DWG, DGN, FBX, OBJ, 3DS) for background processing. */
export async function uploadCADFile(
  projectId: string,
  name: string,
  discipline: string,
  file: File,
  signal?: AbortSignal,
  conversionDepth?: 'standard' | 'medium' | 'complete',
): Promise<BIMCadUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const qp: Record<string, string> = { project_id: projectId, name, discipline };
  if (conversionDepth) qp.conversion_depth = conversionDepth;
  const params = new URLSearchParams(qp);

  const token = useAuthStore.getState().accessToken;
  const headers: HeadersInit = {
    Accept: 'application/json',
    'X-DDC-Client': 'OE/1.0',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`/api/v1/bim_hub/upload-cad/?${params.toString()}`, {
      method: 'POST',
      headers,
      body: formData,
      signal,
    });
  } catch (networkErr) {
    // Re-throw AbortError as-is so callers can distinguish cancellation
    if (networkErr instanceof DOMException && networkErr.name === 'AbortError') throw networkErr;
    throw new Error(
      'Cannot connect to server. Please check that the backend is running and try again.',
    );
  }

  if (!response.ok) {
    let detail = `Upload failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse errors
    }
    throw new Error(detail);
  }

  return response.json();
}

/** Trigger background generation of a single PDF that combines every
 *  sheet/view extracted from the uploaded CAD file.  The request itself
 *  is non-blocking — the backend schedules the job and returns
 *  immediately.  The resulting PDF is saved to the project's Documents
 *  module once ready. */
export async function generateBIMPDFSheets(
  modelId: string,
): Promise<{ status: string; model_id: string }> {
  return apiPost<{ status: string; model_id: string }>(
    `/v1/bim_hub/${encodeURIComponent(modelId)}/generate-pdf-sheets/`,
    {},
  );
}

/* ── BIM Requirements Import/Export ─────────────────────────────────── */

export interface BIMRequirementSetResponse {
  id: string;
  project_id: string;
  name: string;
  description: string;
  source_format: string;
  source_filename: string;
  created_by: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface BIMRequirementResponse {
  id: string;
  requirement_set_id: string;
  element_filter: Record<string, unknown>;
  property_group: string | null;
  property_name: string;
  constraint_def: Record<string, unknown>;
  context: Record<string, unknown> | null;
  source_format: string;
  source_ref: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface BIMRequirementSetDetail extends BIMRequirementSetResponse {
  requirements: BIMRequirementResponse[];
}

export interface BIMRequirementImportResult {
  requirement_set_id: string;
  name: string;
  source_format: string;
  total_requirements: number;
  errors: Array<{ row?: number; field?: string; msg?: string }>;
  warnings: Array<{ row?: number; field?: string; msg?: string }>;
  metadata: Record<string, unknown>;
}

/** Upload and import a BIM requirements file. */
export async function importBIMRequirements(
  projectId: string,
  file: File,
  name?: string,
): Promise<BIMRequirementImportResult> {
  const formData = new FormData();
  formData.append('file', file);

  let url = `/v1/bim_requirements/import/upload/?project_id=${encodeURIComponent(projectId)}`;
  if (name) {
    url += `&name=${encodeURIComponent(name)}`;
  }

  const token = useAuthStore.getState().accessToken;
  const reqHeaders: Record<string, string> = {};
  if (token) reqHeaders['Authorization'] = `Bearer ${token}`;

  const resp = await fetch(`/api${url}`, { method: 'POST', headers: reqHeaders, body: formData });
  if (!resp.ok) {
    let detail = `Import failed (HTTP ${resp.status})`;
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch {
      // ignore json parse error
    }
    throw new Error(detail);
  }
  return resp.json();
}

/** List BIM requirement sets for a project. */
export async function fetchBIMRequirementSets(
  projectId: string,
): Promise<BIMRequirementSetResponse[]> {
  return apiGet<BIMRequirementSetResponse[]>(
    `/v1/bim_requirements/sets/?project_id=${encodeURIComponent(projectId)}`,
  );
}

/** Get a BIM requirement set with all requirements. */
export async function fetchBIMRequirementSetDetail(
  setId: string,
): Promise<BIMRequirementSetDetail> {
  return apiGet<BIMRequirementSetDetail>(
    `/v1/bim_requirements/sets/${encodeURIComponent(setId)}/`,
  );
}

/** Delete a BIM requirement set. */
export async function deleteBIMRequirementSet(setId: string): Promise<void> {
  await apiDelete(`/v1/bim_requirements/sets/${encodeURIComponent(setId)}/`);
}

/** Download the BIM requirements Excel template URL. */
export function bimRequirementsTemplateUrl(): string {
  return '/api/v1/bim_requirements/template/';
}

/** Export a BIM requirement set as Excel (returns action URL for POST). */
export function bimRequirementsExportExcelUrl(setId: string, language = 'en'): string {
  return `/api/v1/bim_requirements/export/${encodeURIComponent(setId)}/excel/?language=${language}`;
}

/** Export a BIM requirement set as IDS XML (returns action URL for POST). */
export function bimRequirementsExportIdsUrl(setId: string): string {
  return `/api/v1/bim_requirements/export/${encodeURIComponent(setId)}/ids/`;
}
