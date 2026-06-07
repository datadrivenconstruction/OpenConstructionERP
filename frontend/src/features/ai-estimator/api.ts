// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// AI Estimate Builder API client. Surface mirrors the authoritative
// contract docs/initiative-ai-estimator/API_CONTRACT.md (source of truth
// backend/app/modules/ai_estimator/schemas.py).
//
// Money fields are emitted as plain decimal STRINGS by the backend, so
// they are typed `string` here and never coerced through float on the
// client. `null` is an honest "no value" (e.g. no grounded rate found),
// never a fabricated number.

import { useAuthStore } from '@/stores/useAuthStore';

const PREFIX = '/api/v1/ai-estimator';

/** Render a FastAPI error payload into a readable string. */
function formatErrorDetail(body: unknown): string {
  if (body == null) return '';
  if (typeof body === 'string') return body;
  if (typeof body !== 'object') return String(body);
  const obj = body as Record<string, unknown>;
  const d = obj.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) {
    return d
      .map((item) => {
        if (item == null) return '';
        if (typeof item === 'string') return item;
        if (typeof item !== 'object') return String(item);
        const it = item as Record<string, unknown>;
        const loc = Array.isArray(it.loc) ? it.loc.join('.') : it.loc;
        const msg = it.msg ?? it.message ?? it.type ?? '';
        return loc ? `${loc}: ${msg}` : String(msg);
      })
      .filter(Boolean)
      .join('; ');
  }
  if (d && typeof d === 'object') {
    try {
      return JSON.stringify(d);
    } catch {
      return String(d);
    }
  }
  try {
    return JSON.stringify(body);
  } catch {
    return String(body);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const token = useAuthStore.getState().accessToken;
  let res: Response;
  try {
    res = await fetch(`${PREFIX}${path}`, {
      ...init,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...(init?.headers || {}),
      },
    });
  } catch (err) {
    const name = err instanceof Error ? err.name : '';
    if (name === 'AbortError' || name === 'TimeoutError') {
      throw new Error(
        'Request cancelled or timed out - the backend did not respond in time.',
      );
    }
    throw err;
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = formatErrorDetail(body) || res.statusText;
    } catch {
      // ignore
    }
    throw new Error(`${res.status} ${detail}`);
  }
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

// ── Enums / unions (mirror schemas.py) ────────────────────────────────

/** Source type. Auto-detected at stage 1, but the user picks the intake
 *  tab first. */
export type SourceType =
  | 'text'
  | 'excel'
  | 'gaeb'
  | 'bim'
  | 'dwg'
  | 'pdf'
  | 'photo'
  | 'documents';

/** Run FSM. */
export type RunStatus =
  | 'draft'
  | 'analyzing'
  | 'grouping'
  | 'matching'
  | 'review'
  | 'applied'
  | 'failed'
  | 'cancelled';

/** The four wizard steps (current_stage). */
export type StageName = 'source' | 'grouping' | 'matching' | 'assembly';

export type GroupStatus =
  | 'unmatched'
  | 'suggested'
  | 'confirmed'
  | 'overridden'
  | 'skipped'
  | 'tbd'
  | 'needs_human'
  | 'applied';

export type ConfidenceBand = 'high' | 'medium' | 'low' | 'none';

export type ValidationStatus = 'passed' | 'warnings' | 'errors' | 'skipped';

export type ValidationSeverity = 'error' | 'warning' | 'info';

export type StepRole =
  | 'thought'
  | 'tool_call'
  | 'observation'
  | 'answer'
  | 'error'
  | 'stage_complete';

export type DegradedReason = 'no_ai_key' | 'no_vectors' | 'no_catalogue';

/** 12 OmniClass construction stages (shared with match-elements). */
export type ConstructionStage =
  | '02_Demolition'
  | '03_Earthwork'
  | '04_Foundations'
  | '05_Substructure'
  | '06_Superstructure'
  | '07_Envelope'
  | '08_Interior'
  | '09_MEP'
  | '10_Finishes'
  | '11_FixedFurnishings'
  | '12_Equipment'
  | '13_Sitework';

// ── Run shapes ────────────────────────────────────────────────────────

export interface DetectedSource {
  type: string;
  confidence: number | null;
  disciplines: string[];
  summary: string | null;
}

export interface SuggestedConfig {
  catalogue_id: string | null;
  region: string | null;
  currency: string | null;
  group_by: string[];
  construction_stage: string | null;
}

export interface RunSummary {
  id: string;
  project_id: string;
  name: string | null;
  source: SourceType | null;
  status: RunStatus;
  current_stage: StageName;
  group_count: number;
  confirmed_count: number;
  applied_count: number;
  model_used: string | null;
  grand_total: string | null;
  currency: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunListResponse {
  total: number;
  runs: RunSummary[];
}

export interface ValidationResultItem {
  rule_id: string;
  status: string;
  severity: ValidationSeverity;
  message: string;
  element_ref: string | null;
}

export interface ValidationReport {
  status: ValidationStatus;
  /** Quality score in [0, 1], or null when skipped (never 1.0 on skip). */
  score: number | null;
  rule_set: string;
  passed: ValidationResultItem[];
  warnings: ValidationResultItem[];
  errors: ValidationResultItem[];
}

export interface RunRead {
  id: string;
  project_id: string;
  user_id: string;
  name: string | null;
  agent_name: string | null;
  status: RunStatus;
  current_stage: StageName;
  /** Per-stage `{accepted_at, by}`. */
  checkpoints: Record<string, { accepted_at: string | null; by: string | null }>;
  source_inputs: Record<string, unknown>;
  detected_source: DetectedSource | null;
  suggested_config: SuggestedConfig | null;
  catalogue_id: string | null;
  region: string | null;
  currency: string | null;
  group_by: string[];
  construction_stage: string | null;
  provider: string | null;
  model_used: string | null;
  total_tokens: number | null;
  /** Money field - Decimal-as-string in JSON (v3 §10). */
  cost_usd_estimate: number | string | null;
  duration_ms: number | null;
  validation_report: ValidationReport | null;
  grand_total: string | null;
  currency_subtotals: Record<string, string>;
  completeness_score: number | null;
  boq_id: string | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
}

// ── Progress + steps ──────────────────────────────────────────────────

export type StageStatus = 'pending' | 'active' | 'complete' | 'error';

export interface StageState {
  stage: StageName;
  title: string;
  status: StageStatus;
  accepted_at: string | null;
}

export interface StepOut {
  id: string;
  stage: StageName;
  step_idx: number;
  role: StepRole;
  content: unknown;
  token_count: number;
  took_ms: number | null;
  created_at: string;
}

export interface ProgressResponse {
  run_id: string;
  status: RunStatus;
  current_stage: StageName;
  stages: StageState[];
  group_count: number;
  matched_count: number;
  confirmed_count: number;
  failure_reason: string | null;
  ai_connected: boolean;
  vector_ready: boolean;
  degraded_reason: DegradedReason | null;
  provider: string | null;
  model_used: string | null;
  recent_steps: StepOut[];
}

// ── Groups ────────────────────────────────────────────────────────────

export interface ResourceOut {
  name: string;
  code: string | null;
  unit: string;
  factor: number;
  quantity: number;
  unit_rate: string;
  /** labor | material | equipment | operator | electricity | other */
  type: string;
}

export interface CandidateOut {
  candidate_id: string | null;
  code: string;
  description: string;
  unit: string;
  unit_rate: string;
  currency: string;
  score: number;
  confidence_band: ConfidenceBand;
  /** Set by the multi-pass mapping's rate-sanity pass when this candidate's
   *  per-base-unit rate sits outside the per-run benchmark band. The rate is
   *  never altered - this only flags it for human review. */
  rate_outlier?: boolean;
}

// ── Multi-pass mapping trace (design 3.3, surfaced by WP4) ────────────────

/** The pass name on the wire. The backend serialises the field under the
 *  `pass` key (a Python soft keyword on the backend side). */
export type MappingPassName = 'semantic' | 'unit_scale' | 'rate_sanity';

/** Rate-sanity benchmark band for one group's candidates. Catalogue-relative
 *  (median-derived ratio bounds), never an absolute price book. Present only
 *  on the `rate_sanity` pass. */
export interface MappingBenchmark {
  trade: string;
  unit: string;
  /** Median-relative bounds, or null when there was no usable median (a lone
   *  candidate). Real floats, never a fabricated placeholder. */
  band_low: number | null;
  band_high: number | null;
  /** How many candidates fell outside the band (flagged, never dropped). */
  outliers: number;
}

/** One named pass of the multi-pass mapping pipeline (design 4.3). */
export interface MappingPass {
  /** semantic | unit_scale | rate_sanity (string-typed defensively so an
   *  unknown future pass name still renders). */
  pass: MappingPassName | string;
  kept: number;
  dropped: number;
  notes: string;
  benchmark: MappingBenchmark | null;
}

/** The assembled multi-pass mapping log for one matched group. Read-only
 *  provenance written by the matcher into the group metadata; null until the
 *  group has been matched. */
export interface MappingTrace {
  passes: MappingPass[];
  /** How the top-1 was chosen: vector (deterministic) | unit_scale | llm
   *  (agent-reasoned) | manual (no candidate grounded). */
  final_method: string | null;
  /** Set only when every candidate was a benchmark-band outlier and the group
   *  was parked for human review. */
  needs_human_reason: string | null;
}

export type MatchMethod = 'vector' | 'lexical' | 'resources' | 'llm' | 'manual' | 'auto';

export interface GroupSummary {
  id: string;
  group_key: string;
  description: string | null;
  trade: string | null;
  signature: string | null;
  element_count: number;
  // Measurement quantities. The backend may emit these as JSON numbers or
  // (for Decimal-precision quantities) as decimal strings, so accept both
  // and always parse through `toNum` before arithmetic.
  quantities: Record<string, number | string>;
  chosen_unit: string | null;
  primary_quantity: number | string;
  chosen_code: string | null;
  unit_rate: string | null;
  currency: string | null;
  score: number | null;
  confidence: number | null;
  confidence_band: ConfidenceBand;
  match_method: MatchMethod | null;
  status: GroupStatus;
  boq_position_id: string | null;
  sort_order: number;
}

export interface GroupDetail extends GroupSummary {
  run_id: string;
  element_ids: string[];
  envelope: Record<string, unknown>;
  resources: ResourceOut[];
  candidates: CandidateOut[];
  confirmed_by: string | null;
  confirmed_at: string | null;
  notes: string | null;
  /** Where the quantity came from (e.g. "perimeter x height"). */
  derivation?: string | null;
  /** Plain-words estimation assumptions (e.g. "perimeter inferred from area"). */
  assumptions?: string[];
  /** Source of the group: dialogue | file | cad | photo. */
  source?: string | null;
  /** The three-pass mapping trace (why this rate). Null until matched. */
  mapping_trace?: MappingTrace | null;
}

export interface GroupListResponse {
  run_id: string;
  total: number;
  groups: GroupSummary[];
  summary: Record<string, number>;
  confidence_high_threshold: number;
  confidence_medium_threshold: number;
}

// ── Preview (stage 4) ─────────────────────────────────────────────────

export interface PreviewResourceRow {
  description: string;
  factor: number;
  quantity: number;
  unit: string;
  unit_rate: string;
  type: string;
}

export interface PreviewPositionRow {
  group_id: string;
  group_key: string;
  section_path: string[];
  description: string;
  unit: string;
  // Measurement quantity (not money). The backend currently emits a JSON
  // number; a Decimal-precision quantity would arrive as a string. Accept
  // both and render via `toNum` so display never shows NaN.
  quantity: number | string;
  unit_rate: string;
  currency: string;
  line_total: string;
  confidence: number | null;
  confidence_band: ConfidenceBand;
  resources: PreviewResourceRow[];
  confirmed: boolean;
}

export interface PreviewResponse {
  run_id: string;
  positions: PreviewPositionRow[];
  grand_total: string;
  currency: string | null;
  currency_subtotals: Record<string, string>;
  validation: ValidationReport | null;
  completeness_score: number | null;
  missing_items: string[];
  can_apply: boolean;
}

export interface ApplyResponse {
  run_id: string;
  boq_id: string;
  positions_created: number;
  grand_total: string;
  currency: string | null;
  currency_subtotals: Record<string, string>;
}

export interface BulkConfirmResponse {
  confirmed: number;
  skipped: number;
  group_ids: string[];
}

export interface ReadinessResponse {
  ai_connected: boolean;
  provider: string | null;
  model_used: string | null;
  vector_ready: boolean;
  vector_count: number;
  catalogues_available: number;
  message: string | null;
}

export interface CatalogueOption {
  id: string;
  label: string;
  currency: string;
  region: string;
  default_classification_standard: string | null;
}

/** Server-driven UI meta (GET /meta). The UI must drive score bands, the
 *  construction-stage menu and the match-group cap from here rather than
 *  hardcoding magic numbers. Older backends 404 - the caller falls back to
 *  the contract defaults. */
export interface EstimatorMeta {
  /** Green (>= high) / amber (>= low) score-band cutoffs in [0, 1]. */
  score_thresholds: { high: number; low: number };
  /** Allowed construction-stage values for the stage-1 select. */
  construction_stages: string[];
  /** How many groups a single match pass processes; match-all batches. */
  match_group_cap: number;
}

// ── Request bodies ────────────────────────────────────────────────────

export interface RunCreate {
  project_id: string;
  name?: string | null;
  source?: SourceType;
  agent_name?: string | null;
  text_input?: string | null;
  file_refs?: string[];
  rows?: Array<Record<string, unknown>>;
  bim_model_ids?: string[];
  document_ids?: string[];
  catalogue_id?: string | null;
  region?: string | null;
  currency?: string | null;
  construction_stage?: ConstructionStage | null;
}

export interface StageConfirmRequest {
  stage: StageName;
  edits?: {
    catalogue_id?: string | null;
    region?: string | null;
    currency?: string | null;
    group_by?: string[];
    construction_stage?: string | null;
  };
}

export interface GroupUpdate {
  chosen_unit?: string | null;
  description?: string | null;
  quantities?: Record<string, number> | null;
  /** stage-3 override; MUST be an id already in the group's candidates. */
  candidate_id?: string | null;
  status?: GroupStatus | null;
  notes?: string | null;
}

export interface RunMatchRequest {
  group_ids?: string[] | null;
  top_k?: number;
  use_reranker?: boolean;
  use_agent?: boolean;
  max_groups?: number;
}

export interface ConfirmGroupRequest {
  candidate_id?: string;
  confidence?: number;
}

export interface BulkConfirmRequest {
  threshold?: number;
  group_ids?: string[];
}

export interface ApplyRequest {
  target_boq_id?: string | null;
  boq_name?: string | null;
  append?: boolean;
  organize_by_classification?: boolean;
  group_ids?: string[] | null;
}

export interface AnalyzeRequest {
  use_ai?: boolean;
}

/** Attach more sources to a `draft` run before analysis. Shares the
 *  source-bearing fields with `RunCreate`. */
export interface AddSourcesRequest {
  source?: SourceType;
  text_input?: string | null;
  file_refs?: string[];
  rows?: Array<Record<string, unknown>>;
  bim_model_ids?: string[];
  document_ids?: string[];
}

export interface GroupMergeRequest {
  group_ids: string[];
  new_description?: string;
}

export interface GroupSplitRequest {
  element_ids: string[];
  new_description?: string;
}

// ── Source-kind tab metadata (UI helper, not from the backend) ────────

export interface SourceTabDef {
  /** UI tab id - the page maps it to a `source` + the source-bearing field. */
  id: 'text' | 'files' | 'bim_model' | 'documents';
  labelKey: string;
  labelFallback: string;
  descKey: string;
  descFallback: string;
}

export const SOURCE_TABS: SourceTabDef[] = [
  {
    id: 'text',
    labelKey: 'aiest.source.text',
    labelFallback: 'Free text',
    descKey: 'aiest.source.text_desc',
    descFallback: 'Describe the scope in plain language',
  },
  {
    id: 'files',
    labelKey: 'aiest.source.files',
    labelFallback: 'Upload files',
    descKey: 'aiest.source.files_desc',
    descFallback: 'DWG / PDF takeoff, Excel / GAEB, IFC, photos',
  },
  {
    id: 'bim_model',
    labelKey: 'aiest.source.bim',
    labelFallback: 'BIM / CAD model',
    descKey: 'aiest.source.bim_desc',
    descFallback: 'Pick a converted model already in the project',
  },
  {
    id: 'documents',
    labelKey: 'aiest.source.documents',
    labelFallback: 'Project documents',
    descKey: 'aiest.source.documents_desc',
    descFallback: 'Select drawings or specs from the project files',
  },
];

// ── Client ────────────────────────────────────────────────────────────

export const aiEstimatorApi = {
  // Runs ----------------------------------------------------------------

  /** Create a run and start stage 1 (source understanding). */
  createRun: (spec: RunCreate) =>
    call<RunRead>('/runs', { method: 'POST', body: JSON.stringify(spec) }),

  listRuns: (projectId: string, params?: { limit?: number; offset?: number }) => {
    const qs = new URLSearchParams({ project_id: projectId });
    if (params?.limit != null) qs.set('limit', String(params.limit));
    if (params?.offset != null) qs.set('offset', String(params.offset));
    return call<RunListResponse>(`/runs?${qs.toString()}`);
  },

  getRun: (id: string) => call<RunRead>(`/runs/${id}`),

  /** Attach more sources to a draft run before analysis. */
  addSources: (id: string, spec: AddSourcesRequest) =>
    call<RunRead>(`/runs/${id}/sources`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  /** Run stage 1 explicitly (normalise + AI classification). */
  analyze: (id: string, spec: AnalyzeRequest = {}) =>
    call<RunRead>(`/runs/${id}/analyze`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  getProgress: (id: string) => call<ProgressResponse>(`/runs/${id}/progress`),

  getSteps: (id: string, limit?: number) => {
    const qs = limit != null ? `?limit=${limit}` : '';
    return call<StepOut[]>(`/runs/${id}/steps${qs}`);
  },

  /** Accept a stage checkpoint, optionally editing its outputs, and advance. */
  confirmStage: (id: string, spec: StageConfirmRequest) =>
    call<RunRead>(`/runs/${id}/confirm`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  cancel: (id: string) => call<RunRead>(`/runs/${id}/cancel`, { method: 'POST' }),

  readiness: (id: string) => call<ReadinessResponse>(`/runs/${id}/readiness`),

  // Groups --------------------------------------------------------------

  listGroups: (id: string, params?: { status?: string }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    const q = qs.toString();
    return call<GroupListResponse>(`/runs/${id}/groups${q ? `?${q}` : ''}`);
  },

  getGroup: (id: string, groupId: string) =>
    call<GroupDetail>(`/runs/${id}/groups/${groupId}`),

  /** Edit a group (stage 2 quantities/unit/description) or override its
   *  match (stage 3 candidate_id / status). */
  updateGroup: (id: string, groupId: string, patch: GroupUpdate) =>
    call<GroupDetail>(`/runs/${id}/groups/${groupId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  mergeGroups: (id: string, spec: GroupMergeRequest) =>
    call<GroupListResponse>(`/runs/${id}/groups/merge`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  splitGroup: (id: string, spec: GroupSplitRequest) =>
    call<GroupListResponse>(`/runs/${id}/groups/split`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  rematchGroup: (id: string, groupId: string, spec: RunMatchRequest = {}) =>
    call<GroupDetail>(`/runs/${id}/groups/${groupId}/rematch`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  /** Confirm one group's chosen candidate as the human decision. */
  confirmGroup: (id: string, groupId: string, spec: ConfirmGroupRequest = {}) =>
    call<GroupDetail>(`/runs/${id}/groups/${groupId}/confirm`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  // Stage 3 -------------------------------------------------------------

  runMatch: (id: string, spec: RunMatchRequest = {}, opts?: { signal?: AbortSignal }) =>
    call<GroupListResponse>(`/runs/${id}/match`, {
      method: 'POST',
      body: JSON.stringify(spec),
      signal: opts?.signal,
    }),

  bulkConfirm: (id: string, spec: BulkConfirmRequest = {}) =>
    call<BulkConfirmResponse>(`/runs/${id}/bulk-confirm`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  // Stage 4 -------------------------------------------------------------

  getPreview: (id: string) => call<PreviewResponse>(`/runs/${id}/preview`),

  apply: (id: string, spec: ApplyRequest = {}) =>
    call<ApplyResponse>(`/runs/${id}/apply`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  // Reused infra surfaces ----------------------------------------------

  listCatalogues: () => call<CatalogueOption[]>('/catalogues'),

  /** Server-driven UI meta (score bands, stages, match cap). 404 on older
   *  backends - callers fall back to the contract defaults. */
  getMeta: () => call<EstimatorMeta>('/meta'),

  qdrantHealth: () => call<QdrantHealth>('/qdrant/health'),
};

// ── Qdrant health envelope (shared probe) ─────────────────────────────

export interface QdrantHealth {
  status?: string;
  reachable?: boolean;
  collections?: string[] | Record<string, unknown>;
  vector_counts?: Record<string, number>;
  url?: string | null;
  message?: string;
  [k: string]: unknown;
}
