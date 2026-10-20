// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for DWG Takeoff module.
 * Endpoints prefixed with /v1/dwg_takeoff/.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { isModuleLoaded } from '@/shared/lib/moduleProbe';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type DwgScaleMode = 'preset' | 'calibrated' | 'per_annotation';

/** Lifecycle states the backend reports for a drawing.
 *  - `uploaded`: file persisted, conversion not yet started.
 *  - `processing`: DXF parser or the DDC DWG converter is running. This is the
 *    long step — a medium DWG can stay here for 3–8 minutes.
 *  - `ready`: entities + thumbnail are available. The viewer can render.
 *  - `empty`: file parsed cleanly but produced 0 entities.
 *  - `needs_conversion`: a `.dwg` with no parsed entities and no converter
 *    available on this server. Definitive (not a spinner) — the UI shows a
 *    one-click "Convert with cad2data" / install CTA instead of waiting
 *    forever for a transition that will never come.
 *  - `error`: conversion failed. `error_message` carries the reason. */
export type DwgDrawingStatus =
  | 'uploaded'
  | 'processing'
  | 'ready'
  | 'empty'
  | 'needs_conversion'
  | 'error';

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
  /** DXF $INSUNITS name: "mm", "cm", "m", "inches", "feet", "unitless", ... */
  units?: string | null;
  /** Backend conversion lifecycle (see {@link DwgDrawingStatus}). Polled
   *  by the DWG takeoff page while the user waits — uploading a .dwg
   *  immediately returns a row with ``status="processing"`` while the
   *  actual DDC conversion runs in the background for several minutes. */
  status?: DwgDrawingStatus;
  /** Human-readable reason when ``status === 'error'`` or ``'empty'``. */
  error_message?: string | null;
  /** Server-side extras. ``error_code`` is the stable failure code the page
   *  translates instead of showing the English ``error_message``. */
  metadata?: { error_code?: string | null } & Record<string, unknown>;
  /** Latest parsed version. Only present on the single-drawing fetch
   *  ({@link fetchDrawing}); the LIST endpoint omits it. Carries the
   *  resolved/backfilled ``units`` the LIST response does not expose, so
   *  the page can apply the mm→m factor. */
  latest_version?: DwgDrawingVersion | null;
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
  /** DXF text style name (the STYLE table entry the TEXT/MTEXT references). */
  style?: string;
  /** Resolved SHX font file for the text style (e.g. "romans.shx"); may be
   *  empty when the backend could not resolve it. The renderer maps it to a
   *  CSS font family so annotation text looks like the source drawing instead
   *  of always rendering in monospace. */
  font?: string;
  /** Block name for INSERT entities: which definition this reference places. */
  block_name?: string;
  /** INSERT x/y scale factors, a negative value meaning the block is mirrored
   *  on that axis. Together with `rotation` and `start` they are the reference's
   *  full transform, which `expandBlockReferences` composes onto the members of
   *  `block_name` to put the definition's geometry in the world. */
  x_scale?: number;
  y_scale?: number;
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
  /** Block definition this entity is a member of. An entity carries either
   *  `layout` or `block`, never both: `layout` means it is placed on a sheet,
   *  `block` means it is part of a definition and its coordinates are in that
   *  block's own space. A member is therefore never drawn or fitted where it
   *  lies - only through the INSERTs that place it. */
  block?: string;
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
    | 'line'
    | 'count';
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
  // /documents page lists drawings even when oe_dwg_takeoff is disabled —
  // return empty instead of 404-logging on every project switch.
  if (!(await isModuleLoaded('oe_dwg_takeoff'))) return [];
  return apiGet<DwgDrawing[]>(`/v1/dwg_takeoff/drawings/?project_id=${projectId}`);
}

/** Fetch a single drawing — used to poll conversion status while the
 *  user watches the honest progress UI on /dwg-takeoff. The backend
 *  flips `status` from `processing` → `ready` (or `error` / `empty`)
 *  once the DDC pipeline finishes. */
export async function fetchDrawing(drawingId: string): Promise<DwgDrawing> {
  return apiGet<DwgDrawing>(`/v1/dwg_takeoff/drawings/${drawingId}`);
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

/**
 * Upload a NEW REVISION of an existing drawing.
 *
 * Unlike {@link uploadDrawing}, which creates a SEPARATE drawing, this appends
 * a new parsed version (v N+1) to the SAME drawing, so the revision history and
 * the revision-compare flow both work off one drawing id. The multipart field
 * name is `file`, matching the backend ``POST /drawings/{drawing_id}/revisions/``
 * handler; it returns the same drawing with ``latest_version`` bumped to the
 * new revision.
 */
export async function uploadDrawingRevision(
  drawingId: string,
  file: File,
): Promise<DwgDrawing> {
  const token = useAuthStore.getState().accessToken;
  const form = new FormData();
  form.append('file', file);

  const res = await fetch(`/api/v1/dwg_takeoff/drawings/${drawingId}/revisions/`, {
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

/**
 * Create (or reuse) a DWG/DXF drawing from an existing project Document.
 *
 * Powers the Documents / File Manager "Open in DWG Takeoff" action: a CAD
 * file that lives only as a Document has no drawing to render, so opening it
 * used to land on a blank page. The backend materialises the drawing on
 * demand (status ``uploaded`` → ``processing`` → ``ready``) and is idempotent
 * per document, so re-opening returns the same drawing. The caller then polls
 * /drawings/{id} via the normal status-polling path while it converts.
 */
export async function importDrawingFromDocument(
  documentId: string,
  name?: string,
): Promise<DwgDrawing> {
  return apiPost<DwgDrawing>('/v1/dwg_takeoff/drawings/from-document/', {
    document_id: documentId,
    ...(name ? { name } : {}),
  });
}

/* ── Entities & Layers ─────────────────────────────────────────────────── */

/**
 * Fetch parsed entities for a drawing.
 *
 * When `visibleLayers` is a non-empty list, only those layers are requested
 * so the backend filters the (potentially large) entity set BEFORE
 * serialising it — a medium DWG can carry 50k+ entities, and the canvas
 * only ever renders the layers the user has toggled on. Omitting the
 * parameter (or passing an empty list) returns every layer, which is the
 * correct behaviour on first load when the full layer list is not yet known.
 */
export async function fetchEntities(
  drawingId: string,
  visibleLayers?: string[],
): Promise<DxfEntity[]> {
  let url = `/v1/dwg_takeoff/drawings/${drawingId}/entities/`;
  if (visibleLayers && visibleLayers.length > 0) {
    const layers = visibleLayers.map((l) => encodeURIComponent(l)).join(',');
    url += `?layers=${layers}`;
  }
  return apiGet<DxfEntity[]>(url);
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

/** Backend response shape. The API stores `annotation_type` + `geometry`
 *  (with `points` + primitive-specific extras like `radius`) in separate
 *  columns; the frontend renderer expects a flattened `{type, points, radius}`.
 *  ``normaliseAnnotation`` bridges the two. Without it, `AnnotationOverlay`
 *  reads `ann.type`/`ann.points` as undefined and every user-drawn mark is
 *  silently invisible on the canvas even though the side panel lists it. */
interface RawAnnotation {
  id: string;
  drawing_id: string;
  annotation_type?: string;
  type?: string;
  geometry?: { points?: { x: number; y: number }[]; radius?: number; [k: string]: unknown };
  points?: { x: number; y: number }[];
  radius?: number;
  text: string | null;
  color: string;
  line_width?: number;
  thickness?: number;
  layer_name?: string;
  measurement_value: number | null;
  measurement_unit: string | null;
  scale_override?: number | null;
  linked_boq_position_id: string | null;
  metadata?: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
}

function normaliseAnnotation(raw: RawAnnotation): DwgAnnotation {
  const type = (raw.type ?? raw.annotation_type ?? 'text_pin') as DwgAnnotation['type'];
  const geom = raw.geometry ?? {};
  const points = raw.points ?? geom.points ?? [];
  const radius = raw.radius ?? (typeof geom.radius === 'number' ? geom.radius : undefined);
  return {
    ...raw,
    type,
    points,
    radius,
  } as DwgAnnotation;
}

export async function fetchAnnotations(drawingId: string): Promise<DwgAnnotation[]> {
  const raw = await apiGet<RawAnnotation[]>(
    `/v1/dwg_takeoff/annotations/?drawing_id=${encodeURIComponent(drawingId)}&limit=500`,
  );
  return raw.map(normaliseAnnotation);
}

export async function createAnnotation(data: CreateAnnotationPayload): Promise<DwgAnnotation> {
  const raw = await apiPost<RawAnnotation>('/v1/dwg_takeoff/annotations/', data);
  return normaliseAnnotation(raw);
}

export async function updateAnnotation(
  id: string,
  data: UpdateAnnotationPayload,
): Promise<DwgAnnotation> {
  const raw = await apiPatch<RawAnnotation>(`/v1/dwg_takeoff/annotations/${id}`, data);
  return normaliseAnnotation(raw);
}

export async function deleteAnnotation(id: string): Promise<void> {
  return apiDelete(`/v1/dwg_takeoff/annotations/${id}`);
}

export async function linkAnnotationToBoq(
  annotId: string,
  boqPositionId: string,
): Promise<DwgAnnotation> {
  const raw = await apiPost<RawAnnotation>(`/v1/dwg_takeoff/annotations/${annotId}/link-boq/`, {
    position_id: boqPositionId,
  });
  return normaliseAnnotation(raw);
}

/* ── Pins ──────────────────────────────────────────────────────────────── */

export async function fetchPins(drawingId: string): Promise<DwgPin[]> {
  return apiGet<DwgPin[]>(`/v1/dwg-takeoff/pins/?drawing_id=${encodeURIComponent(drawingId)}`);
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

/* ── Revision compare (Item 17) ────────────────────────────────────────── */

/** An external reference (xref) or an undefined block the drawing needs. */
export interface DwgUnresolvedXref {
  name: string;
  path: string | null;
}

/** A parsed version of a drawing — the unit a revision compare diffs. */
export interface DwgDrawingVersion {
  id: string;
  drawing_id: string;
  version_number: number;
  entity_count: number;
  units: string | null;
  status: string;
  /** ``xrefs``: external references the converted drawing could not resolve. */
  metadata?: { xrefs?: DwgUnresolvedXref[] } & Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** One layer-level entity change between two drawing versions. */
export interface DwgEntityDiffRow {
  change_type: 'added' | 'removed' | 'modified' | 'unchanged';
  entity_id: string;
  entity_type: string;
  layer: string;
  old_count: number;
  new_count: number;
  delta: number;
}

/** One annotation-level change between two drawing versions. */
export interface DwgAnnotationDiffRow {
  change_type: 'added' | 'removed' | 'modified' | 'unchanged';
  annotation_id: string;
  annotation_type: string;
  label: string | null;
  layer_name: string;
  old_measurement: number | null;
  new_measurement: number | null;
  measurement_unit: string | null;
  linked_boq_position_id: string | null;
  /** Signed Decimal string in the project base currency, or null when the
   *  annotation is unlinked / unpriced. */
  cost_impact: string | null;
  cost_currency: string | null;
}

export interface DwgDrawingDiffResponse {
  drawing_id: string;
  /** Present only on a drawing-vs-drawing compare (two independent drawings):
   *  identifies each side so the UI can label both. Absent on the
   *  version-vs-version compare of a single drawing. */
  from_drawing_id?: string | null;
  to_drawing_id?: string | null;
  from_version_id: string;
  from_version_number: number;
  to_version_id: string;
  to_version_number: number;
  entity_rows: DwgEntityDiffRow[];
  annotation_rows: DwgAnnotationDiffRow[];
  summary: {
    entities: Record<'added' | 'removed' | 'modified' | 'unchanged', number>;
    annotations: Record<'added' | 'removed' | 'modified' | 'unchanged', number>;
    net_cost_impact: string | null;
    cost_currency: string | null;
    from_entity_count: number;
    to_entity_count: number;
  };
}

/** List every parsed version of a drawing (newest first) for the compare picker. */
export async function fetchDrawingVersions(
  drawingId: string,
): Promise<DwgDrawingVersion[]> {
  return apiGet<DwgDrawingVersion[]>(
    `/v1/dwg_takeoff/drawings/${drawingId}/versions/`,
  );
}

/** Compare two versions of a drawing. ``fromVersionId`` is the baseline
 *  ('before'); ``toVersionId`` is the target ('after'). */
export async function compareDrawings(
  drawingId: string,
  fromVersionId: string,
  toVersionId: string,
): Promise<DwgDrawingDiffResponse> {
  return apiPost<DwgDrawingDiffResponse>(
    `/v1/dwg_takeoff/drawings/${drawingId}/compare/${toVersionId}?from_version_id=${encodeURIComponent(fromVersionId)}`,
  );
}

/** Compare two INDEPENDENT drawings in a project (drawing-vs-drawing).
 *
 * Unlike {@link compareDrawings} (two versions of ONE drawing), this diffs
 * the latest version of two separately uploaded drawings - the user picks
 * (or uploads) a second drawing as the comparison target. ``fromDrawingId``
 * is the baseline ('before'); ``toDrawingId`` is the target ('after').
 * Mirrors the PDF module's two-document compare. */
export async function compareDrawingPair(
  projectId: string,
  fromDrawingId: string,
  toDrawingId: string,
): Promise<DwgDrawingDiffResponse> {
  const params = new URLSearchParams({
    project_id: projectId,
    from_drawing_id: fromDrawingId,
    to_drawing_id: toDrawingId,
  });
  return apiPost<DwgDrawingDiffResponse>(
    `/v1/dwg_takeoff/drawings/compare/?${params.toString()}`,
  );
}

/** The draft variation request minted from a revision-compare delta. */
export interface CreateVariationFromDiffResult {
  variation_request_id: string;
  code: string;
  estimated_cost_impact: string;
  currency: string;
}

/** Turn a drawing revision delta into a DRAFT variation request.
 *
 * The backend recomputes the deterministic compare for the two version
 * ids and shapes its net cost impact into a draft VariationRequest (never
 * submitted - a human confirms it in the variations module). Requires both
 * ``dwg_takeoff.read`` and ``variations.create`` permissions. */
export async function createVariationFromDiff(
  drawingId: string,
  fromVersionId: string,
  toVersionId: string,
  title?: string,
): Promise<CreateVariationFromDiffResult> {
  return apiPost<CreateVariationFromDiffResult>(
    `/v1/dwg_takeoff/drawings/${drawingId}/compare/create-variation`,
    {
      from_version_id: fromVersionId,
      to_version_id: toVersionId,
      ...(title ? { title } : {}),
    },
  );
}

/** Turn a drawing-vs-drawing delta into a DRAFT variation request.
 *
 * Mirrors {@link createVariationFromDiff} for the drawing-pair path: the
 * backend recomputes the deterministic pair-compare and shapes its net cost
 * impact into a draft VariationRequest (never submitted - a human confirms
 * it). Requires both ``dwg_takeoff.read`` and ``variations.create``. */
export async function createVariationFromDrawingPair(
  projectId: string,
  fromDrawingId: string,
  toDrawingId: string,
  title?: string,
): Promise<CreateVariationFromDiffResult> {
  return apiPost<CreateVariationFromDiffResult>(
    '/v1/dwg_takeoff/drawings/compare/create-variation',
    {
      project_id: projectId,
      from_drawing_id: fromDrawingId,
      to_drawing_id: toDrawingId,
      ...(title ? { title } : {}),
    },
  );
}

/* ── Offline Readiness (R3 #9) ─────────────────────────────────────────── */

export interface DwgOfflineReadiness {
  ready: boolean;
  converter_available: boolean;
  version: string | null;
  message: string;
  /** True only when the browser and the backend run on the same machine
   *  (loopback request + non-production server). Drives whether the UI may
   *  show the strong "your files never leave your computer" claim or the
   *  honest "processed on your OpenConstructionERP server" copy. Optional so
   *  older backends that don't yet send it are treated as NOT local-only. */
  local_only?: boolean;
}

export async function fetchOfflineReadiness(): Promise<DwgOfflineReadiness> {
  if (!(await isModuleLoaded('oe_dwg_takeoff'))) {
    return {
      ready: false,
      converter_available: false,
      version: null,
      message: 'DWG takeoff module is disabled',
      local_only: false,
    };
  }
  return apiGet<DwgOfflineReadiness>('/v1/dwg_takeoff/offline-readiness/');
}
