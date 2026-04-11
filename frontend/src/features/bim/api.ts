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
  model_id: string;
  name: string;
  format: string;
  file_size: number;
  status: string;
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
 * Default limit is 50000 because the 3D viewer needs every element loaded
 * at once to match COLLADA mesh nodes by stable_id — pagination would mean
 * missing geometry references.
 */
export async function fetchBIMElements(
  modelId: string,
  limit = 50000,
  offset = 0,
): Promise<BIMElementsResponse> {
  return apiGet<BIMElementsResponse>(
    `/v1/bim_hub/models/${encodeURIComponent(modelId)}/elements/?limit=${limit}&offset=${offset}`,
  );
}

/** Get the geometry file URL for a BIM model.
 *
 * Includes the JWT access token as a query param because Three.js
 * ColladaLoader cannot set custom headers — without this the geometry
 * fetch would 401.
 */
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
    });
  } catch (networkErr) {
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
): Promise<BIMCadUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

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
    response = await fetch(`/api/v1/bim_hub/upload-cad/?${params.toString()}`, {
      method: 'POST',
      headers,
      body: formData,
    });
  } catch (networkErr) {
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
