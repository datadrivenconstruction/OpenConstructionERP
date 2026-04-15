/**
 * API helpers for DWG Takeoff module.
 * Endpoints prefixed with /v1/dwg_takeoff/.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

export interface DwgDrawing {
  id: string;
  project_id: string;
  name: string;
  filename: string;
  discipline: string;
  layer_count: number;
  entity_count: number;
  thumbnail_url: string | null;
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
  type: 'text_pin' | 'arrow' | 'rectangle' | 'distance' | 'area';
  points: { x: number; y: number }[];
  text: string | null;
  color: string;
  measurement_value: number | null;
  measurement_unit: string | null;
  linked_boq_position_id: string | null;
  metadata?: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface DwgPin {
  id: string;
  drawing_id: string;
  position: { x: number; y: number };
  label: string;
  color: string;
  linked_boq_position_id: string | null;
}

export interface CreateAnnotationPayload {
  drawing_id: string;
  type: DwgAnnotation['type'];
  points: { x: number; y: number }[];
  text?: string;
  color?: string;
  measurement_value?: number;
  measurement_unit?: string;
  metadata?: Record<string, unknown>;
}

export interface UpdateAnnotationPayload {
  text?: string;
  color?: string;
  measurement_value?: number;
  measurement_unit?: string;
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

/* ── Annotations CRUD ──────────────────────────────────────────────────── */

export async function fetchAnnotations(drawingId: string): Promise<DwgAnnotation[]> {
  return apiGet<DwgAnnotation[]>(`/v1/dwg_takeoff/drawings/${drawingId}/annotations`);
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
