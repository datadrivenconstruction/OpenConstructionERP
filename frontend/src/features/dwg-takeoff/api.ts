/**
 * API helpers for DWG Takeoff module.
 * Endpoints prefixed with /v1/dwg_takeoff/.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type DwgScaleMode = 'preset' | 'calibrated' | 'per_annotation';

export interface DwgDrawing {
  id: string;
  project_id: string;
  name: string;
  filename: string;
  discipline: string;
  layer_count: number;
  entity_count: number;
  thumbnail_url: string | null;
  /** Persisted drawing-level scale. 1 = raw DXF units (metres). */
  scale_denominator?: number;
  /** Which scale strategy the user picked last for this drawing. */
  scale_mode?: DwgScaleMode;
  created_at: string;
  updated_at: string;
}

export interface DxfEntity {
  id: string;
  type:
    | 'LINE'
    | 'LWPOLYLINE'
    | 'ARC'
    | 'CIRCLE'
    | 'ELLIPSE'
    | 'TEXT'
    | 'POINT'
    | 'INSERT'
    | 'HATCH';
  layer: string;
  /** Hex color string (e.g. "#ff0000") or ACI number */
  color: string | number;
  /** Line start / circle center / text insertion point */
  start?: { x: number; y: number };
  /** Line end */
  end?: { x: number; y: number };
  /** Polyline / hatch boundary vertices */
  vertices?: { x: number; y: number }[];
  /** Arc / circle radius */
  radius?: number;
  /** Ellipse major radius */
  major_radius?: number;
  /** Ellipse minor radius */
  minor_radius?: number;
  /** Arc/ellipse start angle (radians) */
  start_angle?: number;
  /** Arc/ellipse end angle (radians) */
  end_angle?: number;
  /** Entity rotation (radians) */
  rotation?: number;
  /** Text content */
  text?: string;
  /** Text height */
  height?: number;
  /** Block name for INSERT entities */
  block_name?: string;
  /** Whether the polyline/hatch is closed */
  closed?: boolean;
  /** Hatch pattern name */
  pattern_name?: string;
  /** Whether hatch is solid fill */
  is_solid?: boolean;
  /** Ellipse major axis vector (ezdxf format) */
  major_axis?: { x: number; y: number };
  /** Ellipse axis ratio (ezdxf format) */
  ratio?: number;
  /** Layout name (DXF) or BlockId (DWG) the entity belongs to */
  layout?: string;
}

export interface DxfLayer {
  name: string;
  color: string | number;
  visible: boolean;
  entity_count: number;
}

export interface DwgAnnotation {
  id: string;
  drawing_id: string;
  type:
    | 'text_pin'
    | 'arrow'
    | 'rectangle'
    | 'distance'
    | 'area'
    | 'circle'
    | 'polyline'
    | 'line';
  points: { x: number; y: number }[];
  /** Extra geometry (radius for circles, etc.) sent to the backend as the
   *  `geometry` blob so the canvas can render primitives that aren't
   *  describable by `points` alone. */
  radius?: number;
  text: string | null;
  color: string;
  /** Stroke width in logical pixels. Sent to the backend as both `line_width`
   *  (legacy int) and `thickness` (new float) so the renderer can pick
   *  whichever field the backend returns. */
  thickness?: number;
  /** Legacy integer stroke width. Kept for backwards-compat with existing
   *  annotations that were saved before the `thickness` column was added. */
  line_width?: number;
  /** Virtual layer used to group user-drawn markups. Defaults to
   *  `USER_MARKUP`. The LayerPanel toggles visibility by this field for
   *  annotations (separate from DXF-entity layer toggles). */
  layer_name?: string;
  measurement_value: number | null;
  measurement_unit: string | null;
  /** Per-annotation scale denominator that overrides the drawing-level one.
   *  Used when a detail view on the same sheet has its own scale. */
  scale_override?: number | null;
  linked_boq_position_id: string | null;
  metadata?: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
}

/** Virtual layer name applied to every user-drawn primitive annotation.
 *  Exported so the page + LayerPanel can check against a single constant. */
export const USER_MARKUP_LAYER = 'USER_MARKUP';

export interface DwgPin {
  id: string;
  drawing_id: string;
  position: { x: number; y: number };
  label: string;
  color: string;
  linked_boq_position_id: string | null;
}

export interface CreateAnnotationPayload {
  /** Required by backend: the project the drawing belongs to. */
  project_id: string;
  drawing_id: string;
  /** Backend field name. The `DwgAnnotation` response still exposes `type`
   *  for backwards-compat with existing viewer code. */
  annotation_type: DwgAnnotation['type'];
  /** Backend stores all shape-specific data inside a single `geometry`
   *  JSON column; the viewer's `points` array goes in as `geometry.points`. */
  geometry: { points: { x: number; y: number }[]; [k: string]: unknown };
  text?: string;
  color?: string;
  line_width?: number;
  /** Fractional stroke width in logical pixels. Defaults to 2.0 on the
   *  backend when omitted. Coexists with `line_width` for backwards-compat. */
  thickness?: number;
  /** Virtual layer name. Defaults to `USER_MARKUP` on the backend when
   *  omitted, so user-drawn primitives are grouped and can be toggled as
   *  a single layer in the LayerPanel. */
  layer_name?: string;
  measurement_value?: number;
  measurement_unit?: string;
  /** Per-annotation scale that overrides the drawing-level one.
   *  Sent when the user draws in per-annotation mode on a detail view. */
  scale_override?: number | null;
  metadata?: Record<string, unknown>;
}

export interface UpdateAnnotationPayload {
  text?: string;
  color?: string;
  measurement_value?: number;
  measurement_unit?: string;
  scale_override?: number | null;
}

/* ── Drawings CRUD ─────────────────────────────────────────────────────── */

export async function fetchDrawings(projectId: string): Promise<DwgDrawing[]> {
  if (!projectId) return [];
  return apiGet<DwgDrawing[]>(`/v1/dwg_takeoff/drawings/?project_id=${projectId}`);
}

export async function uploadDrawing(
  projectId: string,
  file: File,
  name: string,
  discipline: string,
): Promise<DwgDrawing> {
  const token = useAuthStore.getState().accessToken;
  const form = new FormData();
  form.append('file', file);

  const params = new URLSearchParams({
    project_id: projectId,
    ...(name ? { name } : {}),
    ...(discipline ? { discipline } : {}),
  });

  const res = await fetch(`/api/v1/dwg_takeoff/drawings/upload/?${params.toString()}`, {
    method: 'POST',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-DDC-Client': 'OE/1.0',
    },
    body: form,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || res.statusText);
  }
  return res.json();
}

export async function deleteDrawing(id: string): Promise<void> {
  return apiDelete(`/v1/dwg_takeoff/drawings/${id}`);
}

/* ── Entities & Layers ─────────────────────────────────────────────────── */

export async function fetchEntities(drawingId: string): Promise<DxfEntity[]> {
  return apiGet<DxfEntity[]>(`/v1/dwg_takeoff/drawings/${drawingId}/entities/`);
}

export async function fetchThumbnail(drawingId: string): Promise<string> {
  return apiGet<string>(`/v1/dwg_takeoff/drawings/${drawingId}/thumbnail/`);
}

export async function updateLayers(drawingId: string, layers: DxfLayer[]): Promise<void> {
  return apiPatch(`/v1/dwg_takeoff/drawings/${drawingId}/layers`, { layers });
}

export async function updateDrawingScale(
  drawingId: string,
  payload: { scale_denominator: number; scale_mode: DwgScaleMode },
): Promise<DwgDrawing> {
  return apiPatch<DwgDrawing>(
    `/v1/dwg_takeoff/drawings/${drawingId}/scale/`,
    payload,
  );
}

/* ── Annotations CRUD ──────────────────────────────────────────────────── */

export async function fetchAnnotations(drawingId: string): Promise<DwgAnnotation[]> {
  return apiGet<DwgAnnotation[]>(
    `/v1/dwg_takeoff/annotations/?drawing_id=${encodeURIComponent(drawingId)}&limit=500`,
  );
}

export async function createAnnotation(data: CreateAnnotationPayload): Promise<DwgAnnotation> {
  return apiPost<DwgAnnotation>('/v1/dwg_takeoff/annotations/', data);
}

export async function updateAnnotation(
  id: string,
  data: UpdateAnnotationPayload,
): Promise<DwgAnnotation> {
  return apiPatch<DwgAnnotation>(`/v1/dwg_takeoff/annotations/${id}`, data);
}

export async function deleteAnnotation(id: string): Promise<void> {
  return apiDelete(`/v1/dwg_takeoff/annotations/${id}`);
}

export async function linkAnnotationToBoq(
  annotId: string,
  boqPositionId: string,
): Promise<DwgAnnotation> {
  return apiPost<DwgAnnotation>(`/v1/dwg_takeoff/annotations/${annotId}/link-boq/`, {
    position_id: boqPositionId,
  });
}

/* ── Pins ──────────────────────────────────────────────────────────────── */

export async function fetchPins(drawingId: string): Promise<DwgPin[]> {
  return apiGet<DwgPin[]>(`/v1/dwg_takeoff/drawings/${drawingId}/pins`);
}

/* ── Entity Groups (RFC 11) ───────────────────────────────────────────── */

export interface DwgEntityGroup {
  id: string;
  drawing_id: string;
  entity_ids: string[];
  name: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CreateEntityGroupPayload {
  drawing_id: string;
  entity_ids: string[];
  name: string;
  metadata?: Record<string, unknown>;
}

export async function createEntityGroup(
  data: CreateEntityGroupPayload,
): Promise<DwgEntityGroup> {
  return apiPost<DwgEntityGroup>('/v1/dwg_takeoff/groups/', data);
}

export async function fetchEntityGroups(drawingId: string): Promise<DwgEntityGroup[]> {
  return apiGet<DwgEntityGroup[]>(`/v1/dwg_takeoff/groups/?drawing_id=${drawingId}`);
}

export async function deleteEntityGroup(groupId: string): Promise<void> {
  return apiDelete(`/v1/dwg_takeoff/groups/${groupId}`);
}

/* ── Offline Readiness (R3 #9) ─────────────────────────────────────────── */

export interface DwgOfflineReadiness {
  ready: boolean;
  converter_available: boolean;
  version: string | null;
  message: string;
}

export async function fetchOfflineReadiness(): Promise<DwgOfflineReadiness> {
  return apiGet<DwgOfflineReadiness>('/v1/dwg_takeoff/offline-readiness/');
}
