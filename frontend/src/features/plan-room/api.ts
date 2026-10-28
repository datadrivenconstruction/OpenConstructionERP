// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Plan Room API client.
 *
 * Talks to the backend module mounted at /v1/plan-room/. That module composites
 * every overlay on one document page (punch pins, plan pins, drawing markups,
 * takeoff measurements and project photos) into a single read-only payload, and
 * owns create / delete for the positioned photo / note "plan" pins.
 *
 *   GET    /v1/plan-room/{document_id}/pages/{page}/overlays  (plan_room.read)
 *   POST   /v1/plan-room/{document_id}/pages/{page}/pins        (plan_room.write)
 *   DELETE /v1/plan-room/pins/{pin_id}                          (plan_room.write)
 *
 * Pin x / y are NORMALISED page fractions in [0, 1] (validated at the backend
 * edge), so they position by percentage over the rendered page and stay correct
 * at any zoom - the same convention the punch pin board uses. Markup and
 * measurement geometry live in their own source coordinate spaces (see
 * PlanRoomViewer for how each is projected onto the canvas).
 */

import { apiGet, apiPost, apiDelete, type Page } from '@/shared/lib/api';

/* ── Overlay composite (read) ──────────────────────────────────────────── */

/** A positioned pin. `kind` is `punch` (a punch-list defect pin) or `plan`
 *  (a Plan Room photo / note pin owned by this module). Fields not relevant to
 *  a given kind are null. */
export type OverlayPinKind = 'punch' | 'plan';

export interface OverlayPin {
  kind: OverlayPinKind;
  id: string;
  /** Normalised page fraction in [0, 1]. */
  x: number;
  /** Normalised page fraction in [0, 1]. */
  y: number;
  title: string | null;
  note: string | null;
  status: string | null;
  priority: string | null;
  assigned_to: string | null;
  photo_ref: string | null;
  file_version_id: string | null;
}

/** A single 2-D point after normalisation (see {@link parseOverlayPoints}). */
export interface OverlayPoint {
  x: number;
  y: number;
}

export interface OverlayMarkup {
  id: string;
  page: number;
  type: string;
  /** Free-form geometry from the markups module: usually
   *  `{ points: {x,y}[], tool, coord_space: 'pdf' | 'canvas', ... }`. */
  geometry: Record<string, unknown>;
  color: string | null;
  line_width: number | null;
  opacity: number | null;
  text: string | null;
  label: string | null;
  layer: string | null;
  status: string | null;
  /** Rendered as a string on the read path so no binary-float drift creeps in. */
  measurement_value: string | null;
  measurement_unit: string | null;
  file_version_id: string | null;
}

export interface OverlayMeasurement {
  id: string;
  type: string;
  /** Raw points (either `{x,y}` objects or `[x,y]` pairs); normalise with
   *  {@link parseOverlayPoints}. In takeoff scale-1 viewport units. */
  points: unknown[];
  measurement_value: string | null;
  measurement_unit: string | null;
  group_name: string | null;
  group_color: string | null;
  annotation: string | null;
}

/** A project photo attached to the document. Photos carry no page or (x, y) on
 *  their source row, so the backend surfaces them at the document level for
 *  every page - we render them as a side gallery, not on the sheet. */
export interface OverlayPhoto {
  id: string;
  document_id: string | null;
  filename: string;
  thumbnail_path: string | null;
  caption: string | null;
  taken_at: string | null;
}

/** The document revision the overlay was composited against. */
export interface OverlayVersion {
  document_id: string;
  revision_code: string | null;
  is_current_revision: boolean | null;
}

export interface OverlaysResponse {
  document_id: string;
  page: number;
  version: OverlayVersion;
  pins: OverlayPin[];
  markups: OverlayMarkup[];
  measurements: OverlayMeasurement[];
  photos: OverlayPhoto[];
}

/* ── Plan pin (create / delete) ────────────────────────────────────────── */

export interface PlanPinCreate {
  /** 1-based page; must match the page in the request URL. */
  page: number;
  /** Normalised page coordinates in [0, 1]. */
  x: number;
  y: number;
  note?: string | null;
  photo_ref?: string | null;
  file_version_id?: string | null;
  metadata?: Record<string, unknown>;
}

export interface PlanPinResponse {
  id: string;
  project_id: string;
  document_id: string;
  page: number;
  x: number;
  y: number;
  note: string | null;
  photo_ref: string | null;
  file_version_id: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/* ── API functions ─────────────────────────────────────────────────────── */

const BASE = '/v1/plan-room';

/** Read the overlay composite for one document page. */
export async function fetchOverlays(documentId: string, page: number): Promise<OverlaysResponse> {
  return apiGet<OverlaysResponse>(`${BASE}/${documentId}/pages/${page}/overlays`);
}

/** Drop a positioned photo / note pin on a document page. */
export async function createPlanPin(
  documentId: string,
  page: number,
  payload: PlanPinCreate,
): Promise<PlanPinResponse> {
  return apiPost<PlanPinResponse, PlanPinCreate>(`${BASE}/${documentId}/pages/${page}/pins`, payload);
}

/** Remove a positioned plan pin. */
export async function deletePlanPin(pinId: string): Promise<void> {
  return apiDelete(`${BASE}/pins/${pinId}`);
}

/** A drawing / document option for the document picker. */
export interface PlanRoomDrawing {
  id: string;
  filename: string;
}

/** The slice of a documents-list row the drawing filter reads. */
interface DocumentRow {
  id: string;
  filename?: string;
  name?: string;
  mime_type?: string | null;
}

/**
 * Whether a project document can be opened as a drawing sheet. The viewer
 * renders with pdf.js, so only PDFs qualify: a spreadsheet, an IFC model or a
 * photo in the list would only open to "could not be shown as a drawing".
 * Rows stored without a MIME type fall back to the file extension.
 */
export function isDrawingDocument(row: { filename?: string; name?: string; mime_type?: string | null }): boolean {
  const mime = (row.mime_type ?? '').trim().toLowerCase();
  if (mime) return mime === 'application/pdf' || mime === 'application/x-pdf';
  const name = (row.filename ?? row.name ?? '').trim().toLowerCase();
  return name.endsWith('.pdf');
}

/**
 * List the project documents that can be opened in the Plan Room: the PDFs
 * among the project documents (see {@link isDrawingDocument}).
 */
export async function fetchPlanRoomDrawings(projectId: string): Promise<PlanRoomDrawing[]> {
  if (!projectId) return [];
  const page = await apiGet<Page<DocumentRow>>(`/v1/documents/?project_id=${projectId}&limit=500`);
  return page.items.filter(isDrawingDocument).map((r) => ({
    id: r.id,
    filename: r.filename ?? r.name ?? '',
  }));
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

/**
 * Coerce a raw overlay point list into `{x, y}` points, tolerating both the
 * `{x, y}` object shape (takeoff / markups) and the `[x, y]` pair shape. Any
 * entry that is neither is skipped, so a malformed row degrades to a shorter
 * polyline rather than throwing.
 */
export function parseOverlayPoints(raw: unknown[]): OverlayPoint[] {
  const out: OverlayPoint[] = [];
  for (const p of raw) {
    if (Array.isArray(p) && typeof p[0] === 'number' && typeof p[1] === 'number') {
      out.push({ x: p[0], y: p[1] });
    } else if (p && typeof p === 'object') {
      const o = p as { x?: unknown; y?: unknown };
      if (typeof o.x === 'number' && typeof o.y === 'number') {
        out.push({ x: o.x, y: o.y });
      }
    }
  }
  return out;
}
