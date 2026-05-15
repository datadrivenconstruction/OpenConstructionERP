// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Match-Elements API client. Surface mirrors backend
// app/modules/match_elements/schemas.py exactly — no client-side
// extrapolation, no kludges.

import { useAuthStore } from '@/stores/useAuthStore';

const PREFIX = '/api/v1/match_elements';

/**
 * Render a FastAPI error payload (``{detail: ...}``) into a human-readable
 * string. The framework's 422 shape is a list of dicts like
 * ``[{type, loc, msg, input, ctx}]``; older 4xx/5xx send a plain
 * ``{detail: "string"}``. Without this normaliser the React toast renders
 * the list as ``[object Object]`` (the symptom Artem flagged on
 * /match-elements Step 4).
 */
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
    try { return JSON.stringify(d); } catch { return String(d); }
  }
  try { return JSON.stringify(body); } catch { return String(body); }
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
    // ``fetch`` rejects with AbortError when the caller-supplied signal
    // fires (timeout or user cancel) and with a generic TypeError on
    // network failures. Surface a stable, user-readable message either
    // way so the caller's toast / progress card doesn't render
    // ``[object Object]`` or a silent "still running" spinner.
    const name = err instanceof Error ? err.name : '';
    if (name === 'AbortError' || name === 'TimeoutError') {
      throw new Error(
        'Request cancelled or timed out — the backend did not respond in time.',
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

export type SourceName = 'bim' | 'dwg' | 'boq' | 'text' | 'pdf' | 'photo' | 'image';

/** A single BoQ row for the 'boq' source (MAPPING_PROCESS.md §4.1.5).
 *  Either pre-parse client-side and post via createSession, or upload an
 *  xlsx via createSessionFromExcel and let the backend parse it. */
export interface BoqRow {
  description: string;
  qty?: number;
  unit?: string;
  /** Exact CWICR rate code — when present, the matcher short-circuits
   *  Qdrant fan-out and fetches the rate directly from parquet. */
  code?: string;
  category?: string;
  source_lang?: string;
  /** Pass-through: any extra columns are preserved in attributes. */
  [k: string]: unknown;
}

/** A single text input for the 'text' source (MAPPING_PROCESS.md §4.1.6).
 *  Plain string is fine for the simple case; the dict shape lets the
 *  caller pin per-line ``project_country`` / ``stage`` overrides. */
export type TextInput =
  | string
  | {
      raw_text: string;
      project_country?: string;
      stage?: string;
      category?: string;
    };
export type MatcherName = 'vector' | 'lexical' | 'resources' | 'llm';
export type ConfirmMethod = 'vector' | 'lexical' | 'llm' | 'manual' | 'auto';
export type GroupStatus =
  | 'unmatched'
  | 'suggested'
  | 'confirmed'
  | 'overridden'
  | 'skipped'
  | 'tbd'
  | 'applied';
export type ConfidenceBand = 'high' | 'medium' | 'low' | 'none';
export type TradeBucket =
  | 'architectural'
  | 'structural'
  | 'mep'
  | 'civil'
  | 'spatial'
  | 'subtractive'
  | 'annotation'
  | 'other';

export interface MatchSession {
  id: string;
  project_id: string;
  bim_model_id: string | null;
  source: SourceName;
  name: string | null;
  group_by: string[];
  filters: Record<string, unknown[]>;
  excluded_categories: string[];
  auto_confirm_threshold: number;
  use_net_quantities: boolean;
  catalogue_id: string | null;
  is_archived: boolean;
  /**
   * v3-P10b: User-picked construction stage from the dropdown. When set,
   * the SearchPlan stamps it as a hard filter so the catalogue search
   * only surfaces rates from the chosen phase. Null = no stage pin.
   */
  construction_stage: ConstructionStage | null;
  last_active_at: string | null;
  created_at: string;
  updated_at: string;
}

/** 12 OmniClass-aligned construction stages from MAPPING_PROCESS.md v3 §4.2. */
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

export const CONSTRUCTION_STAGES: ConstructionStage[] = [
  '02_Demolition',
  '03_Earthwork',
  '04_Foundations',
  '05_Substructure',
  '06_Superstructure',
  '07_Envelope',
  '08_Interior',
  '09_MEP',
  '10_Finishes',
  '11_FixedFurnishings',
  '12_Equipment',
  '13_Sitework',
];

export interface SessionSummary {
  id: string;
  project_id: string;
  bim_model_id: string | null;
  name: string | null;
  source: SourceName;
  last_active_at: string | null;
  created_at: string;
  is_archived: boolean;
  group_count: number;
  confirmed_count: number;
  applied_count: number;
  total_value: number;
  currency: string | null;
}

export interface MatchCandidate {
  /** Real CostItem.id (or CatalogResource.id for method=resources). */
  id: string | null;
  code: string;
  description: string;
  unit: string;
  unit_rate: number;
  currency: string;
  score: number;
  vector_score: number;
  boosts_applied: Record<string, number>;
  confidence_band: ConfidenceBand;
  region_code: string;
  source: string;
  classification: Record<string, string>;
}

export interface GroupSummary {
  id: string;
  group_key: string;
  display_label: string;
  trade: TradeBucket;
  is_subtractive: boolean;
  signature: string | null;
  element_count: number;
  quantities: Record<string, number>;
  chosen_unit: string | null;
  primary_quantity: number;
  gross_quantity: number | null;
  net_quantity: number | null;
  opening_warning: boolean;
  chosen_method: string | null;
  confidence: string | null;
  confidence_band: ConfidenceBand;
  status: GroupStatus;
  boq_position_id: string | null;
  suggested_code: string | null;
  suggested_description: string | null;
  suggested_unit_rate: number | null;
  suggested_currency: string | null;
  sample_names: string[];
}

export interface GroupListResponse {
  session_id: string;
  total: number;
  groups: GroupSummary[];
  summary: Record<string, number>;
  confidence_high_threshold: number;
  confidence_medium_threshold: number;
}

export interface GroupDetail extends GroupSummary {
  session_id: string;
  element_ids: string[];
  methods: Record<string, MatchCandidate[]>;
  chosen_candidate_id: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
  notes: string | null;
}

export interface AttributeKey {
  key: string;
  sample_values: string[];
}

export interface CategoryCount {
  category: string;
  display_label: string;
  trade: TradeBucket;
  is_subtractive: boolean;
  count: number;
}

/** Live progress snapshot for a running match. See
 *  ``MatchService.run_match`` for stage definitions and the
 *  ``/sessions/{id}/progress`` endpoint for the poll contract. */
export type MatchStage =
  | 'idle'
  | 'init'
  | 'elements'
  | 'ranking'
  | 'save'
  | 'done'
  | 'error';

export type MatchProgressStatus = 'idle' | 'running' | 'done' | 'error';

export interface MatchProgress {
  stage: MatchStage;
  stage_idx: number;
  total_stages: number;
  groups_done: number;
  groups_total: number;
  status: MatchProgressStatus;
  started_at: string | null;
  updated_at: string | null;
  error: string | null;
}

export interface BIMModelOption {
  id: string;
  name: string;
  model_format: string | null;
  element_count: number;
  storey_count: number;
  status: string;
  created_at: string | null;
}

export interface ApplyResourcePreview {
  description: string;
  factor: number;
  quantity: number;
  unit: string;
  unit_rate: number;
}

export interface ApplyPositionPreview {
  group_key: string;
  section_path: string[];
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  currency: string;
  line_total: number;
  resources: ApplyResourcePreview[];
}

export interface ApplyToBoqResponse {
  dry_run: boolean;
  boq_id: string | null;
  positions_created: number;
  positions: ApplyPositionPreview[];
  grand_total: number;
  currency: string | null;
}

export interface MatchTemplate {
  id: string;
  tenant_id: string | null;
  signature: string;
  label: string | null;
  cwicr_position_id: string;
  source_fields: string[];
  use_count: number;
  last_used_at: string | null;
  created_at: string;
}

/** Vector DB readiness for the project's language. Surfaced on the page
 *  so the user can see whether the cwicr_<lang>_v3 collection is loaded
 *  and which collection a match query will hit. */
export type VectorReadinessBand =
  | 'ready'        // collection exists, points_count > 0
  | 'empty'        // collection exists but is empty
  | 'missing'      // Qdrant connected but no collection of this name
  | 'disconnected' // Qdrant unreachable (or any backend error)
  | 'no_country'   // engine reachable but caller didn't pass a country
  | 'non_qdrant';  // backend is LanceDB / other — v3 layout doesn't apply

/** Cross-language binding diagnostic. Returned when ``project_id`` is
 *  passed to /vector/v3-status/. Lets the UI surface a "wrong catalogue"
 *  warning when the bound CWICR catalogue speaks a different language
 *  than the project's region. */
export type LanguageMismatchStatus =
  | 'unknown'   // project not found, region missing, or probe failed
  | 'unbound'   // project has no cost_database_id yet
  | 'ok'        // project language matches catalogue language
  | 'mismatch'; // project language ≠ catalogue language → render warning

export interface LanguageMismatch {
  status: LanguageMismatchStatus;
  project_region: string;
  project_language: string;
  bound_catalogue: string;
  bound_language: string;
}

export interface VectorReadiness {
  engine: string;
  connected: boolean;
  country: string;
  language: string;
  collection: string;
  exists: boolean;
  points_count: number;
  status_band: VectorReadinessBand;
  error?: string;
  language_mismatch?: LanguageMismatch;
}

/** Free / open-source language-model readiness for /match-elements.
 *  Mirrors backend ``GET /api/v1/costs/embedder/status/`` exactly
 *  (costs/router.py:embedder_status). The endpoint always returns 200 —
 *  the UI distinguishes installed/loaded/missing from the JSON payload. */
export interface EmbedderStatus {
  installed: boolean;
  model_loaded: boolean;
  model_name: string;
  model_id_runtime: string;
  license: string;
  open_source: boolean;
  homepage: string;
  languages_supported: number;
  size_mb_int8: number;
  size_mb_fp32: number;
  int8_mode: boolean;
  pip_command: string;
  missing_packages: string[];
  extra_name: string;
}

/** GET /api/v1/costs/embedder/status/ — see EmbedderStatus above. */
export async function fetchEmbedderStatus(): Promise<EmbedderStatus> {
  const token = useAuthStore.getState().accessToken;
  const res = await fetch('/api/v1/costs/embedder/status/', {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      Accept: 'application/json',
    },
  });
  if (!res.ok) {
    throw new Error(`embedder/status ${res.status}`);
  }
  return (await res.json()) as EmbedderStatus;
}

/** GET /api/v1/costs/vector/v3-status/?country=...&project_id=...
 *  Returns the per-language CWICR v3 collection state for the active
 *  project. When ``projectId`` is passed, the response also includes
 *  ``language_mismatch`` diagnostics. */
export async function fetchVectorReadiness(
  country: string,
  projectId?: string | null,
): Promise<VectorReadiness> {
  const token = useAuthStore.getState().accessToken;
  const qs = new URLSearchParams();
  if (country) qs.set('country', country);
  if (projectId) qs.set('project_id', projectId);
  const res = await fetch(`/api/v1/costs/vector/v3-status/?${qs.toString()}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      Accept: 'application/json',
    },
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return (await res.json()) as VectorReadiness;
}

export const matchElementsApi = {
  // ── Sessions ─────────────────────────────────────────────────────────

  createSession: (spec: {
    project_id: string;
    bim_model_id?: string | null;
    source?: SourceName;
    name?: string;
    group_by?: string[];
    filters?: Record<string, unknown[]>;
    /** null = use server-side defaults (subtractive set). [] = show everything. */
    excluded_categories?: string[] | null;
    auto_confirm_threshold?: number;
    use_net_quantities?: boolean;
    catalogue_id?: string | null;
    construction_stage?: ConstructionStage | null;
    /** §4.1.6 — only honoured when source = 'text'. */
    text_inputs?: TextInput[];
    /** §4.1.5 — only honoured when source = 'boq'. */
    boq_rows?: BoqRow[];
  }) =>
    call<MatchSession>('/sessions', {
      method: 'POST',
      body: JSON.stringify({
        source: 'bim',
        ...spec,
      }),
    }),

  /** §4.1.5 — convenience path: upload an xlsx file and let the backend
   *  parse it (multi-language column detection: EN/DE/RU/ES/PT/CJK/...).
   *  Returns the created session — the caller then drives the regular
   *  match flow. */
  createSessionFromExcel: async (
    spec: {
      project_id: string;
      file: File;
      name?: string;
      catalogue_id?: string | null;
      construction_stage?: ConstructionStage | null;
    },
  ): Promise<MatchSession> => {
    const token = useAuthStore.getState().accessToken;
    const fd = new FormData();
    fd.append('project_id', spec.project_id);
    fd.append('file', spec.file);
    if (spec.name) fd.append('name', spec.name);
    if (spec.catalogue_id) fd.append('catalogue_id', spec.catalogue_id);
    if (spec.construction_stage)
      fd.append('construction_stage', spec.construction_stage);
    const res = await fetch(`${PREFIX}/sessions/from-excel`, {
      method: 'POST',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        Accept: 'application/json',
      },
      body: fd,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = formatErrorDetail(body) || res.statusText;
      } catch {
        /* ignore */
      }
      throw new Error(`${res.status} ${detail}`);
    }
    return (await res.json()) as MatchSession;
  },

  listSessions: (
    projectId: string,
    params?: { include_archived?: boolean; limit?: number },
  ) => {
    const qs = new URLSearchParams({ project_id: projectId });
    if (params?.include_archived) qs.set('include_archived', 'true');
    if (params?.limit) qs.set('limit', String(params.limit));
    return call<SessionSummary[]>(`/sessions?${qs.toString()}`);
  },

  getSession: (id: string) => call<MatchSession>(`/sessions/${id}`),

  updateSession: (
    id: string,
    patch: Partial<{
      name: string;
      bim_model_id: string | null;
      group_by: string[];
      filters: Record<string, unknown[]>;
      excluded_categories: string[];
      auto_confirm_threshold: number;
      use_net_quantities: boolean;
      catalogue_id: string | null;
      construction_stage: ConstructionStage | null;
      is_archived: boolean;
    }>,
  ) =>
    call<MatchSession>(`/sessions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  touchSession: (id: string) =>
    call<void>(`/sessions/${id}/touch`, { method: 'POST' }),

  /** Read the latest run-match progress snapshot for the session. The
   *  wizard's MatchProgressCard polls this every ~800ms while a match
   *  is running and stops as soon as ``status`` flips to ``done`` /
   *  ``error``. The endpoint always returns 200 — idle sessions
   *  surface ``stage: "idle"`` / ``status: "idle"``. Older backends
   *  that predate the progress column will 404 here; the FE should
   *  fall back to the existing spinner. */
  getProgress: (id: string) =>
    call<MatchProgress>(`/sessions/${id}/progress`),

  // ── BIM models ────────────────────────────────────────────────────────

  listBIMModels: (projectId: string) =>
    call<BIMModelOption[]>(`/projects/${projectId}/bim-models`),

  // ── Groups ────────────────────────────────────────────────────────────

  listGroups: (
    sessionId: string,
    params?: { status?: string; limit?: number; offset?: number },
  ) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    const q = qs.toString();
    return call<GroupListResponse>(
      `/sessions/${sessionId}/groups${q ? `?${q}` : ''}`,
    );
  },

  getGroup: (sessionId: string, groupKey: string) =>
    call<GroupDetail>(
      `/sessions/${sessionId}/group?group_key=${encodeURIComponent(groupKey)}`,
    ),

  runMatch: (
    sessionId: string,
    spec: {
      method: MatcherName;
      group_keys?: string[];
      max_groups?: number;
      top_k?: number;
    },
    opts?: { signal?: AbortSignal },
  ) =>
    // Long-running endpoint: BGE-M3 encode + Qdrant + per-group ranking
    // can take 30–300s on real projects. The caller's AbortSignal
    // (from MatchProgressCard's Cancel button or a 5-minute safety
    // timeout) lets the request be cancelled so the UI never wedges
    // forever — the symptom that previously read as "stuck on
    // Currency normalization" because the wall-clock progress
    // heuristic had run out of stages but the synchronous POST hadn't
    // returned.
    call<GroupSummary[]>(`/sessions/${sessionId}/match`, {
      method: 'POST',
      body: JSON.stringify(spec),
      signal: opts?.signal,
    }),

  confirm: (
    sessionId: string,
    spec: {
      group_key: string;
      /** null = manual override with custom rate/description. */
      candidate_id: string | null;
      method?: ConfirmMethod;
      confidence?: number;
      save_to_template_library?: boolean;
    },
  ) =>
    call<GroupDetail>(`/sessions/${sessionId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({
        method: 'manual',
        save_to_template_library: true,
        ...spec,
      }),
    }),

  bulkConfirm: (
    sessionId: string,
    spec: { threshold?: number; group_keys?: string[] },
  ) =>
    call<{ confirmed_count: number }>(`/sessions/${sessionId}/bulk-confirm`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  apply: (
    sessionId: string,
    spec: { dry_run?: boolean; target_boq_id?: string; group_keys?: string[] },
  ) =>
    call<ApplyToBoqResponse>(`/sessions/${sessionId}/apply`, {
      method: 'POST',
      body: JSON.stringify({
        dry_run: true,
        organize_by_classification: true,
        ...spec,
      }),
    }),

  listAttributes: (sessionId: string) =>
    call<AttributeKey[]>(`/sessions/${sessionId}/attributes`),

  listCategories: (sessionId: string) =>
    call<CategoryCount[]>(`/sessions/${sessionId}/categories`),

  // ── Templates ────────────────────────────────────────────────────────

  listTemplates: () => call<MatchTemplate[]>('/templates'),

  deleteTemplate: (id: string) =>
    call<void>(`/templates/${id}`, { method: 'DELETE' }),

  noMatch: (
    sessionId: string,
    spec: {
      group_key: string;
      action: 'custom' | 'rfq' | 'tbd';
      custom_description?: string;
      custom_unit?: string;
      custom_rate?: number;
    },
  ) =>
    call<GroupDetail>(`/sessions/${sessionId}/no-match`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  skip: (sessionId: string, groupKey: string) =>
    call<GroupDetail>(`/sessions/${sessionId}/no-match`, {
      method: 'POST',
      body: JSON.stringify({ group_key: groupKey, action: 'tbd' }),
    }),

  /** §10 dashboard. Aggregate match-quality metrics over the requested
   *  window. ``project_id`` scopes to one project (auth-checked); omit
   *  for tenant-wide rollup. ``catalog_id`` further narrows the
   *  window when diagnosing a single catalogue. */
  getAnalytics: (
    params: { days?: number; project_id?: string | null; catalog_id?: string | null } = {},
  ) => {
    const qs = new URLSearchParams();
    qs.set('days', String(params.days ?? 7));
    if (params.project_id) qs.set('project_id', params.project_id);
    if (params.catalog_id) qs.set('catalog_id', params.catalog_id);
    return call<MatchAnalyticsResponse>(`/analytics?${qs.toString()}`);
  },

  // ── Visible pipeline (v3034 — 7-stage wizard) ─────────────────────────

  /** Read the seven pipeline stages for a session in canonical order.
   *  Stages that have never run come back ``pending`` with empty
   *  inputs/output so the timeline always renders fully. */
  listStages: (sessionId: string) =>
    call<StageListResponse>(`/sessions/${sessionId}/stages`),

  /** Execute one stage. Empty body re-runs with stored knobs; pass
   *  ``inputs`` / ``prompt_template_id`` / ``llm_provider`` to tune.
   *  Downstream done-stages flip to ``stale`` so the UI flags them. */
  runStage: (
    sessionId: string,
    stageName: StageName,
    body: RunStageRequest = {},
  ) =>
    call<RunStageResponse>(
      `/sessions/${sessionId}/stages/${stageName}/run`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  /** List system + own prompt templates, optionally filtered by stage
   *  key (``schema.header_aggregation`` etc.). */
  listPromptTemplates: (key?: string) => {
    const qs = key ? `?key=${encodeURIComponent(key)}` : '';
    return call<PromptTemplate[]>(`/prompt-templates${qs}`);
  },

  getPromptTemplate: (id: string) =>
    call<PromptTemplate>(`/prompt-templates/${id}`),

  /** Fork a system prompt (or type a new one) into a user-owned,
   *  editable row. ``forked_from_id`` records provenance. */
  createPromptTemplate: (spec: PromptTemplateCreate) =>
    call<PromptTemplate>('/prompt-templates', {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  updatePromptTemplate: (id: string, patch: PromptTemplateUpdate) =>
    call<PromptTemplate>(`/prompt-templates/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  deletePromptTemplate: (id: string) =>
    call<void>(`/prompt-templates/${id}`, { method: 'DELETE' }),
};

// ── Visible pipeline types (mirror match_elements/schemas.py) ─────────

export type StageName =
  | 'convert'
  | 'load'
  | 'schema'
  | 'filter'
  | 'group'
  | 'match'
  | 'rollup';

export type StageStatus =
  | 'pending'
  | 'running'
  | 'done'
  | 'error'
  | 'stale'
  | 'skipped';

export interface StageState {
  stage_name: StageName;
  title: string;
  subtitle: string;
  explainer: string;
  uses_llm: boolean;
  prompt_key: string | null;
  status: StageStatus;
  inputs: Record<string, unknown>;
  output: Record<string, unknown>;
  error: string | null;
  took_ms: number | null;
  prompt_template_id: string | null;
  llm_provider: string | null;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
}

export interface StageListResponse {
  session_id: string;
  stages: StageState[];
}

export interface RunStageRequest {
  inputs?: Record<string, unknown>;
  prompt_template_id?: string | null;
  llm_provider?: string | null;
}

export interface RunStageResponse {
  stage_name: StageName;
  status: StageStatus;
  output: Record<string, unknown>;
  error: string | null;
  took_ms: number | null;
}

export interface PromptTemplate {
  id: string;
  key: string;
  name: string;
  description: string | null;
  system_prompt: string;
  user_template: string;
  allowed_providers: string | null;
  version: number;
  is_system: boolean;
  created_by: string | null;
  forked_from_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PromptTemplateCreate {
  key: string;
  name: string;
  description?: string | null;
  system_prompt?: string;
  user_template: string;
  allowed_providers?: string | null;
  forked_from_id?: string | null;
}

export interface PromptTemplateUpdate {
  name?: string;
  description?: string | null;
  system_prompt?: string;
  user_template?: string;
  allowed_providers?: string | null;
}

/** LLM providers the Adjust sheet offers. The backend treats the
 *  provider string as opaque (``vendor/model``); this list is the UI
 *  default — a deploy can offer more by typing a custom value. */
export const LLM_PROVIDERS: { id: string; label: string }[] = [
  { id: 'anthropic/claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { id: 'anthropic/claude-opus-4-7', label: 'Claude Opus 4.7' },
  { id: 'openai/gpt-4o', label: 'OpenAI GPT-4o' },
  { id: 'openai/gpt-4o-mini', label: 'OpenAI GPT-4o mini' },
  { id: 'local/ollama', label: 'Local (Ollama)' },
];

// ── §10 analytics (MAPPING_PROCESS.md) ────────────────────────────────

export type AnalyticsAlertSeverity = 'info' | 'warning' | 'critical';

export interface AnalyticsAlert {
  id: string;
  severity: AnalyticsAlertSeverity;
  title: string;
  detail: string;
  metric: number;
  threshold: number;
  spec_ref: string;
}

export interface AnalyticsBreakdown {
  key: string;
  searches: number;
  mean_score: number | null;
  pick_rate: number | null;
}

export interface MatchAnalyticsResponse {
  window_days: number;
  project_id: string | null;
  catalog_id: string | null;
  generated_at: string;
  total_searches: number;
  total_with_pick: number;
  pick_rate: number;
  mean_top_score: number | null;
  p95_top_score: number | null;
  low_score_pct: number;
  zero_hit_pct: number;
  relax_tier_distribution: Record<string, number>;
  confidence_band_distribution: Record<string, number>;
  bge_rerank_pct: number;
  llm_rerank_pct: number;
  mean_took_ms: number | null;
  p95_took_ms: number | null;
  mean_picked_rank: number | null;
  p95_picked_rank: number | null;
  high_picked_rank_pct: number;
  by_country: AnalyticsBreakdown[];
  by_source_type: AnalyticsBreakdown[];
  by_ifc_class: AnalyticsBreakdown[];
  alerts: AnalyticsAlert[];
}

// ── Qdrant supervisor (native binary, no Docker) ─────────────────────
// Shape locked to backend dataclass
// ``app.modules.match_elements.qdrant_supervisor.QdrantHealth``.

export interface QdrantHealth {
  reachable: boolean;
  url: string | null;
  installed: boolean;
  binary_path: string | null;
  storage_dir: string;
  spawn_attempted: boolean;
  message: string;
  install_hint: string;
  download_url: string | null;
}

export async function fetchQdrantHealth(): Promise<QdrantHealth> {
  return call<QdrantHealth>('/qdrant/health', { method: 'GET' });
}

export async function installQdrantNative(): Promise<QdrantHealth> {
  return call<QdrantHealth>('/qdrant/install', { method: 'POST' });
}
