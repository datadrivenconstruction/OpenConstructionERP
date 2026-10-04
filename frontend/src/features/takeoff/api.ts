// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Takeoff Measurements API client.
 *
 * Mirrors backend endpoints at /v1/takeoff/measurements/*.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { isModuleLoaded } from '@/shared/lib/moduleProbe';

/* ── Types ────────────────────────────────────────────────────────────── */

export interface MeasurementPoint {
  x: number;
  y: number;
}

/**
 * Where a measurement's scale ratio came from. Mirrors the server's closed set
 * (``app/modules/takeoff/schemas.py``); a value outside it is rejected there.
 *
 * The set exists so a sheet found to be mis-scaled can be narrowed to the rows
 * that actually inherited the bad ratio instead of sending the whole document
 * back for a manual re-check.
 */
export type ScaleSource =
  | 'page_text'
  | 'recovered_text'
  | 'vision_read'
  | 'manual_calibration'
  | 'preset'
  | 'inherited';

export interface MeasurementCreate {
  project_id: string;
  document_id?: string | null;
  page: number;
  type: string;
  group_name?: string;
  /** Per-measurement colour override. ``null`` CLEARS it so the measurement
   *  follows its group again (issue #396) - a real stored state, matching
   *  {@link MeasurementResponse.group_color}. Omitted on create (nothing to
   *  clear); sent explicitly on update, where an omitted key would mean
   *  "leave unchanged". */
  group_color?: string | null;
  annotation?: string | null;
  points: MeasurementPoint[];
  measurement_value?: number | null;
  measurement_unit?: string;
  depth?: number | null;
  volume?: number | null;
  perimeter?: number | null;
  count_value?: number | null;
  scale_pixels_per_unit?: number | null;
  /** Where ``scale_pixels_per_unit`` came from. Omit when the client cannot
   *  attribute it: the server stores NULL, which reads as "not recorded", and
   *  that is the honest answer. Never send a plausible-looking guess here - a
   *  wrong provenance is worse than a missing one, because it is the one a
   *  re-scale would trust when deciding which rows to recompute. */
  scale_source?: ScaleSource | null;
  linked_boq_position_id?: string | null;
  /** Mark an area measurement as an opening / void; its area is subtracted
   *  from the group's gross area (net = gross - openings). Area-only. */
  is_deduction?: boolean;
  metadata?: Record<string, unknown>;
}

export interface MeasurementResponse {
  id: string;
  project_id: string;
  document_id: string | null;
  page: number;
  type: string;
  group_name: string;
  /** Per-measurement colour override; ``null`` when the user never recoloured
   *  this measurement (issue #378), read as "fall back to the group colour". */
  group_color: string | null;
  annotation: string | null;
  points: MeasurementPoint[];
  measurement_value: number | null;
  measurement_unit: string;
  depth: number | null;
  volume: number | null;
  perimeter: number | null;
  count_value: number | null;
  scale_pixels_per_unit: number | null;
  /** Where the ratio above came from, or ``null`` when it was never recorded.
   *  Typed loosely on the way in so a value added server-side ahead of this
   *  client does not fail the parse; surfaces render an unknown value as-is. */
  scale_source?: string | null;
  linked_boq_position_id: string | null;
  /** True when this area measurement is an opening / void subtracted from
   *  its group's gross area. False / absent for normal measurements. */
  is_deduction?: boolean;
  metadata: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
  /** Provenance of the measurement (issue #194). 'ai_plan_read' marks a
   *  vision-LLM proposal; 'manual' is a human-drawn measurement. */
  source?: string;
  /** AI confidence 0..1, present only on AI-sourced rows (null otherwise). */
  confidence?: number | null;
  /** Review state: 'proposed' (unconfirmed AI suggestion), 'confirmed', or
   *  'rejected'. Manual measurements default to 'confirmed'. */
  review_status?: string;
}

/* ── Tier-1 scale detection from the PDF text layer ────────────────────────
 * The deterministic, AI-free counterpart to the vision plan-reader's scale
 * proposal: reads the explicit scale note the architect typed in the title
 * block ("SCALE 1:100", '1/4" = 1\'-0"') and offers it as a one-click
 * calibration the user confirms. Nothing is persisted or auto-applied. */

/** One detected drawing-scale candidate from the document's text layer. */
export interface ScaleDetectionCandidate {
  /** The N of a 1:N paper scale (one paper unit represents N real units). */
  ratio: number;
  /** Display form, e.g. "1:100". */
  label: string;
  /** 0..1 ordering score; a "scale"-adjacent or imperial hit ranks highest. */
  confidence: number;
  /** 1-based page the scale note was found on. */
  page: number;
  /** The exact matched substring from the sheet (shown as evidence). */
  evidence: string;
  /** "ratio" | "imperial". */
  source: string;
  /** Extra notation detail (e.g. the original imperial form for the badge). */
  detail: Record<string, unknown>;
}

/** Detected scale(s) for a document; ``best`` is null when none was found. */
export interface ScaleDetectionResponse {
  best: ScaleDetectionCandidate | null;
  candidates: ScaleDetectionCandidate[];
  source: string;
}

/** One unconfirmed measurement proposed by offline vector recognition (#194). */
export interface RecognizeCandidate {
  type: 'area' | 'distance' | 'count';
  points: MeasurementPoint[];
  value: number | null;
  dimension: string;
  count?: number | null;
  confidence: number;
  reason: string;
  /** Id of the stored `proposed` row this candidate was persisted as. The
   *  detector writes the row before answering, so a review decision is a
   *  server call against this id rather than a change the reload forgets. */
  measurement_id?: string | null;
}

export interface RecognizeResult {
  candidates: RecognizeCandidate[];
  page: number;
  source: string;
  notes: string | null;
}

/** One matched symbol from a seeded "count by example" search (#194). All
 *  coordinates are in PDF points - the same space measurements are stored in. */
export interface SimilarSymbolHit {
  x: number;
  y: number;
  bbox_x0: number;
  bbox_y0: number;
  bbox_x1: number;
  bbox_y1: number;
  confidence: number;
  is_seed: boolean;
}

export interface SimilarSymbolsResult {
  hits: SimilarSymbolHit[];
  seed_found: boolean;
  page: number;
  note: string | null;
  /** Id of the single stored `count` row covering the whole hit set. */
  measurement_id?: string | null;
}

/** A review decision on one proposed measurement.
 *
 *  `points` is optional and only meaningful with `accept`: it corrects the
 *  geometry before confirming. The server always re-derives the billed value
 *  from the points it stores, so an edit cannot smuggle in a quantity the
 *  shape does not support. */
export interface MeasurementReviewRequest {
  action: 'accept' | 'reject';
  points?: MeasurementPoint[];
  note?: string;
}

/* ── Vision-LLM plan reading (issue #194) ──────────────────────────────────
 * An ADDITIONAL, higher-quality suggestion source alongside the offline
 * Recognize tool. Bring-your-own-key, cost-capped, and human-confirmed: a run
 * only produces ``proposed`` measurements; the user accepts/rejects each, and
 * the server recomputes the billed number. Nothing is auto-applied. */

export type PlanReadMode = 'scale' | 'rooms' | 'symbols' | 'full';

export interface PlanReadMeta {
  confidence_high_threshold: number;
  confidence_medium_threshold: number;
  vision_providers: string[];
  max_polygon_vertices: number;
  // Money on the wire is a Decimal-rendered string (v3 §10); coerce with
  // Number() at any display site.
  max_cost_usd: number | string;
  rolling_spend_usd: number | string;
  modes: PlanReadMode[];
  /** False when no vision-capable AI key is configured. The "Read plan with
   *  AI" action is hidden / disabled in that case; the offline Recognize tool
   *  is unaffected (graceful degradation). */
  vision_available: boolean;
  provider: string | null;
  model_used: string | null;
  /** A human-readable reason when vision_available is false. */
  reason: string | null;
}

export interface AiTakeoffRun {
  id: string;
  status: string;
  project_id: string;
  document_id: string | null;
  page: number;
  mode: string;
  provider: string | null;
  model_used: string | null;
  total_tokens: number;
  // Decimal-rendered string on the wire (v3 §10); Number() to display.
  cost_usd_estimate: number | string;
  duration_ms: number;
  proposal_count: number;
  accepted_count: number;
  validation_report: Record<string, unknown> | null;
  failure_reason: string | null;
  created_at: string | null;
}

export interface PlanReadStartRequest {
  project_id: string;
  document_id: string;
  page: number;
  scale_pixels_per_unit?: number | null;
  mode?: PlanReadMode;
  do_cost_match?: boolean;
}

export interface PlanReadAcceptResult {
  confirmed: number;
  skipped: number;
  blocked: number;
  measurement_ids: string[];
}

export interface MeasurementSummary {
  total_measurements: number;
  by_type: Record<string, number>;
  by_group: Record<string, number>;
}

/** One page's drawing scale, wire shape of the frontend ``ScaleConfig``. */
export interface PageScaleConfigDTO {
  pixelsPerUnit: number;
  unitLabel: string;
}

/** Document-level per-page scale calibration (issue #334). Mirrors the
 *  frontend ``PageScales`` model: a default scale for uncalibrated pages plus
 *  per-page overrides keyed by 1-based page number (string keys over the wire). */
export interface PageScalesDTO {
  defaultScale: PageScaleConfigDTO;
  byPage: Record<string, PageScaleConfigDTO>;
}

export interface TakeoffDocumentResponse {
  id: string;
  filename: string;
  pages: number;
  size_bytes: number;
  status: string;
  uploaded_at: string | null;
  /** How many pages came back with no text layer (likely scanned drawings
   *  that need OCR). 0 / absent for a fully text-based PDF (8.2.0). */
  pages_without_text?: number;
  /** The 1-based page numbers with no text layer (8.2.0). */
  pages_without_text_list?: number[];
  /** Document-level per-page scale calibration (issue #334). The authoritative
   *  source the viewer restores on load; ``null`` when the document was never
   *  calibrated at the document level (fall back to per-measurement stamps). */
  page_scales?: PageScalesDTO | null;
  /** Owning project id. Fallback identity for measurement persistence when no
   *  project is active in the header (the document knows its own project). */
  project_id?: string | null;
}

/* ── Revision compare (Item 17) ────────────────────────────────────────── */

/** One measurement-level change between two takeoff documents. */
export interface TakeoffMeasurementDiffRow {
  change_type: 'added' | 'removed' | 'modified' | 'unchanged';
  measurement_id: string;
  type: string;
  group_name: string;
  page: number;
  label: string | null;
  old_value: number | null;
  new_value: number | null;
  measurement_unit: string | null;
  linked_boq_position_id: string | null;
  /** Signed Decimal string in the project base currency, or null when the
   *  measurement is unlinked / unpriced. */
  cost_impact: string | null;
  cost_currency: string | null;
}

export interface TakeoffCompareResponse {
  project_id: string;
  from_document_id: string;
  to_document_id: string;
  measurement_rows: TakeoffMeasurementDiffRow[];
  summary: {
    measurements: Record<'added' | 'removed' | 'modified' | 'unchanged', number>;
    net_cost_impact: string | null;
    cost_currency: string | null;
    /** How many measurements were actually compared. Below *_total when the
     *  compare hit the row ceiling. */
    from_measurement_count: number;
    to_measurement_count: number;
    /** How many measurements the document really holds. */
    from_measurement_total: number;
    to_measurement_total: number;
    /** True when the compare stopped at the row ceiling, so changes past it
     *  are absent from measurement_rows and from the tally. */
    truncated: boolean;
    /** The ceiling that was applied, or null when nothing was truncated. */
    truncation_limit: number | null;
  };
}

/** The draft variation request minted from a PDF revision-compare delta. */
export interface CreateVariationFromCompareResult {
  variation_request_id: string;
  code: string;
  estimated_cost_impact: string;
  currency: string;
}

/* ── API functions ────────────────────────────────────────────────────── */

/** Body of {@link takeoffApi.createBoqPosition}. */
export interface CreateBoqPositionFromMeasurement {
  boq_id: string;
  /** Section to place the position in; omitted / null = top level. */
  parent_id?: string | null;
  description?: string;
  /** Unit to state the position in; omitted = the measurement's own. */
  unit?: string;
  cost_item_id?: string | null;
  unit_rate?: number | null;
}

/** Result of {@link takeoffApi.createBoqPosition}. */
export interface CreateBoqPositionFromMeasurementResult {
  position_id: string;
  boq_id: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  measurement: MeasurementResponse;
}

export const takeoffApi = {
  /** List ALL measurements for a project, optionally filtered by document.
   *  /markups page calls this on mount; returns empty when oe_takeoff
   *  is disabled so the request never 404-logs to the network panel.
   *
   *  The endpoint is paginated (default/max page size 500) and the client
   *  used to fetch a single page, so a document past the page size silently
   *  lost its oldest rows on reload and the hydrate path then erased their
   *  local copies (issue #377). This pages to exhaustion - looping
   *  ``offset += limit`` until a short page arrives - and concatenates, so
   *  every consumer (takeoff hydrate, quantity summary, unified markups)
   *  sees the complete set. The result is de-duplicated by ``id`` because a
   *  row created mid-fetch can shift later pages and repeat across a page
   *  boundary. It is all-or-nothing: any page request that fails rejects the
   *  whole call rather than returning a partial set, because the hydrate path
   *  treats the returned list as the complete server state. */
  list: async (projectId: string, documentId?: string): Promise<MeasurementResponse[]> => {
    if (!(await isModuleLoaded('oe_takeoff'))) return [];
    const base = `/v1/takeoff/measurements/?project_id=${projectId}`
      + (documentId ? `&document_id=${encodeURIComponent(documentId)}` : '');
    // ``le=500`` is the endpoint's hard cap; a large page keeps the
    // mid-fetch shift window (a row deleted between pages) small.
    const pageSize = 500;
    const seen = new Set<string>();
    const all: MeasurementResponse[] = [];
    for (let offset = 0; ; offset += pageSize) {
      const page = await apiGet<MeasurementResponse[]>(
        `${base}&limit=${pageSize}&offset=${offset}`,
      );
      for (const row of page) {
        if (seen.has(row.id)) continue;
        seen.add(row.id);
        all.push(row);
      }
      // A page shorter than the requested size is the last one (the endpoint
      // returns a bare list with no total, so a short page is the only
      // termination signal; an exact multiple just costs one empty request).
      if (page.length < pageSize) break;
    }
    return all;
  },

  /** Create a single measurement. */
  create: (data: MeasurementCreate) =>
    apiPost<MeasurementResponse>('/v1/takeoff/measurements/', data),

  /** Bulk create measurements (up to 500). */
  bulkCreate: (measurements: MeasurementCreate[]) =>
    apiPost<MeasurementResponse[]>('/v1/takeoff/measurements/bulk/', { measurements }),

  /** Update a measurement. */
  update: (id: string, data: Partial<MeasurementCreate>) =>
    apiPatch<MeasurementResponse>(`/v1/takeoff/measurements/${id}`, data),

  /** Delete a measurement. */
  delete: (id: string) =>
    apiDelete(`/v1/takeoff/measurements/${id}`),

  /** Link a measurement to a BOQ position.
   *
   *  ``pushQuantity: true`` opts into the backend ``push_quantity`` flag:
   *  the server copies the measurement's (server-recomputed) value into
   *  the position's quantity and recomputes the total through the
   *  canonical BOQ recompute path. The push is dimension-guarded server
   *  side (an area measurement never overwrites an m3 quantity) and a
   *  measurement with no usable value is a no-op. Default false keeps
   *  link-only callers backward-compatible. */
  linkToBoq: (id: string, boqPositionId: string, options?: { pushQuantity?: boolean }) =>
    apiPost<MeasurementResponse>(`/v1/takeoff/measurements/${id}/link-to-boq/`, {
      boq_position_id: boqPositionId,
      push_quantity: options?.pushQuantity ?? false,
    }),

  /** Create a NEW BOQ position from a measurement and link the two in one
   *  server transaction. The server computes the quantity (wall area with
   *  openings, slope, wastage, multiplier) so the bill carries the ledger's
   *  figure; ``unit`` restates it (e.g. ``ft2`` for an imperial bill). */
  createBoqPosition: (id: string, body: CreateBoqPositionFromMeasurement) =>
    apiPost<CreateBoqPositionFromMeasurementResult>(
      `/v1/takeoff/measurements/${id}/create-boq-position/`,
      body,
    ),

  /** Recognize candidate measurements from a page's vector layer (offline,
   *  issue #194). Returns confidence-scored area/length/count candidates that
   *  the user confirms on the canvas. Each candidate is also stored as a
   *  `proposed` row and carries its `measurement_id`, so a decision survives a
   *  reload and a colleague opening the same sheet sees it. Nothing counts as
   *  a quantity until it is accepted. Needs `takeoff.create`, not read: the
   *  call writes rows. */
  recognize: (docId: string, page: number, scalePixelsPerUnit?: number) => {
    const sp = scalePixelsPerUnit && scalePixelsPerUnit > 0 ? scalePixelsPerUnit : 0;
    return apiPost<RecognizeResult>(
      `/v1/takeoff/documents/${encodeURIComponent(docId)}/recognize/?page=${page}&scale_pixels_per_unit=${sp}`,
      {},
    );
  },

  /** Seeded "count by example": the user clicks one symbol on a vector page
   *  and the backend returns the centroids of every near-identical symbol so
   *  they can be confirmed as a single count measurement. Coordinates are in
   *  PDF points. The whole hit set is stored as ONE `proposed` count row whose
   *  id comes back as `measurement_id`; its confidence is the weakest match in
   *  the set, not the average, so one poor hit cannot hide behind good ones.
   *  Needs `takeoff.create`, not read: the call writes a row. */
  similarSymbols: (docId: string, page: number, seedX: number, seedY: number) =>
    apiPost<SimilarSymbolsResult>(
      `/v1/takeoff/documents/${encodeURIComponent(docId)}/similar-symbols/?page=${page}&seed_x=${seedX}&seed_y=${seedY}`,
      {},
    ),

  /** Accept or reject one proposed measurement.
   *
   *  Accepting flips the stored row to `confirmed`, which is what brings it
   *  into totals, exports and the estimator; rejecting flips it to `rejected`
   *  and keeps it, because the record of what a human turned down is the point
   *  of the queue. Reviewing an already-reviewed row answers 409 rather than
   *  silently overwriting a colleague's decision. */
  reviewMeasurement: (measurementId: string, body: MeasurementReviewRequest) =>
    apiPost<MeasurementResponse>(
      `/v1/takeoff/measurements/${encodeURIComponent(measurementId)}/review/`,
      body,
    ),

  /** Detect an explicit drawing scale from the document's text layer (tier-1,
   *  AI-free). Reads the scale note the architect typed in the title block and
   *  returns the best candidate (plus ranked alternatives) so the calibration
   *  dialog can offer a one-click "Use this". Returns null when the optional
   *  `oe_takeoff` module is disabled so the caller can degrade silently;
   *  `best` is null in the payload when no explicit scale was found. */
  detectScale: async (docId: string): Promise<ScaleDetectionResponse | null> => {
    if (!(await isModuleLoaded('oe_takeoff'))) return null;
    return apiGet<ScaleDetectionResponse>(
      `/v1/takeoff/documents/${encodeURIComponent(docId)}/detect-scale/`,
    );
  },

  /* ── Vision-LLM plan reading (issue #194) ─────────────────────────────── */
  planRead: {
    /** Thresholds, vision availability, caps, and rolling spend. Returns a
     *  graceful "vision_available: false" payload (never throws) when the
     *  module is disabled so the viewer can hide the action without errors. */
    meta: async (): Promise<PlanReadMeta | null> => {
      if (!(await isModuleLoaded('oe_takeoff'))) return null;
      return apiGet<PlanReadMeta>('/v1/takeoff/plan-read/meta');
    },

    /** Start a vision plan-read run for one page. 400 when no vision key is
     *  configured, the model is text-only, or the cost cap would be exceeded. */
    start: (body: PlanReadStartRequest) =>
      apiPost<AiTakeoffRun>('/v1/takeoff/plan-read/', body),

    /** Poll a run's FSM state. */
    getRun: (runId: string) =>
      apiGet<AiTakeoffRun>(`/v1/takeoff/plan-read/runs/${encodeURIComponent(runId)}`),

    /** List the unconfirmed (proposed) measurements minted by a run. */
    proposals: (runId: string) =>
      apiGet<MeasurementResponse[]>(
        `/v1/takeoff/plan-read/runs/${encodeURIComponent(runId)}/proposals`,
      ),

    /** Confirm selected / above-threshold proposals into billed measurements.
     *  A self-intersecting proposal is blocked (redraw first). */
    accept: (
      runId: string,
      body: { measurement_ids?: string[] | null; min_confidence?: number | null },
    ) =>
      apiPost<PlanReadAcceptResult>(
        `/v1/takeoff/plan-read/runs/${encodeURIComponent(runId)}/accept`,
        body,
      ),
  },

  /** Get measurement summary stats for a project. */
  summary: (projectId: string) =>
    apiGet<MeasurementSummary>(`/v1/takeoff/measurements/summary/?project_id=${projectId}`),

  /** Export measurements as CSV or JSON. */
  export: (projectId: string, format: 'csv' | 'json' = 'json') =>
    apiGet<unknown>(`/v1/takeoff/measurements/export/?project_id=${projectId}&format=${format}`),

  /** List uploaded takeoff documents for a project.
   *  Returns empty when the optional `oe_takeoff` module is disabled. */
  listDocuments: async (projectId?: string): Promise<TakeoffDocumentResponse[]> => {
    if (!(await isModuleLoaded('oe_takeoff'))) return [];
    const url = projectId
      ? `/v1/takeoff/documents/?project_id=${encodeURIComponent(projectId)}`
      : '/v1/takeoff/documents/';
    return apiGet<TakeoffDocumentResponse[]>(url);
  },

  /** Fetch a single takeoff document's metadata (status + the per-page
   *  text-layer audit). Returns null when the optional `oe_takeoff` module is
   *  disabled so the caller can degrade silently. Used by the viewer to flag
   *  pages with no text layer that likely need OCR. */
  getDocument: async (docId: string): Promise<TakeoffDocumentResponse | null> => {
    if (!(await isModuleLoaded('oe_takeoff'))) return null;
    return apiGet<TakeoffDocumentResponse>(
      `/v1/takeoff/documents/${encodeURIComponent(docId)}`,
    );
  },

  /** Persist the document-level per-page scale calibration (issue #334).
   *  This is the authoritative, durable store of each sheet's drawing scale
   *  (the browser localStorage copy is only an offline cache and the
   *  per-measurement ``scale_pixels_per_unit`` stamp is capture provenance).
   *  Called whenever the user calibrates a page so a reload / a second device
   *  restores the exact per-sheet scales instead of losing them. ``pageScales``
   *  is sent verbatim in the frontend ``PageScales`` shape. */
  saveDocumentScales: (docId: string, pageScales: unknown) =>
    apiPatch<{ id: string; page_scales: PageScalesDTO | null }>(
      `/v1/takeoff/documents/${encodeURIComponent(docId)}/page-scales/`,
      { page_scales: pageScales },
    ),

  /** Delete an uploaded takeoff document. */
  deleteDocument: (docId: string) =>
    apiDelete(`/v1/takeoff/documents/${docId}`),

  /** Compare the measurements of two takeoff documents (revision compare).
   *  ``fromDocumentId`` is the baseline ('before'); ``toDocumentId`` the
   *  target ('after'). Returns added / removed / modified / unchanged rows
   *  plus a money cost impact for linked-to-BOQ measurements that changed. */
  compare: (projectId: string, fromDocumentId: string, toDocumentId: string) =>
    apiPost<TakeoffCompareResponse>(
      `/v1/takeoff/measurements/compare/?project_id=${encodeURIComponent(projectId)}`
        + `&from_document_id=${encodeURIComponent(fromDocumentId)}`
        + `&to_document_id=${encodeURIComponent(toDocumentId)}`,
    ),

  /** Turn a PDF revision-compare delta into a DRAFT variation request.
   *  The backend recomputes the deterministic compare and shapes its net
   *  cost impact into a draft VariationRequest (never submitted - a human
   *  confirms it in the variations module). Requires both ``takeoff.read``
   *  and ``variations.create`` permissions. */
  createVariation: (
    projectId: string,
    fromDocumentId: string,
    toDocumentId: string,
    title?: string,
  ) =>
    apiPost<CreateVariationFromCompareResult>(
      '/v1/takeoff/measurements/create-variation',
      {
        project_id: projectId,
        from_document_id: fromDocumentId,
        to_document_id: toDocumentId,
        ...(title ? { title } : {}),
      },
    ),

  /** Save a CAD takeoff session to a project as a BIM model. */
  saveToProject: (
    sessionId: string,
    projectId: string,
    modelName: string = 'Imported from Takeoff',
  ) =>
    apiPost<{ model_id: string; element_count: number; model_name: string; project_id: string }>(
      `/v1/takeoff/sessions/${sessionId}/save-to-project/?project_id=${encodeURIComponent(projectId)}`,
      { model_name: modelName },
    ),
};
