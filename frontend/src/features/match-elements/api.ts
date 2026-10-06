// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Match-Elements API client. Surface mirrors backend
// app/modules/match_elements/schemas.py exactly — no client-side
// extrapolation, no kludges.

import { apiGet } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { withLongRunningDeadline } from '@/shared/lib/longRunningDeadline';

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

/** Names of the fields a FastAPI 422 rejected (the last part of each ``loc``). */
function rejectedFields(body: unknown): string[] {
  if (!body || typeof body !== 'object') return [];
  const d = (body as Record<string, unknown>).detail;
  if (!Array.isArray(d)) return [];
  const out: string[] = [];
  for (const item of d) {
    if (!item || typeof item !== 'object') continue;
    const loc = (item as Record<string, unknown>).loc;
    if (!Array.isArray(loc)) continue;
    const last = [...loc].reverse().find((p) => typeof p === 'string');
    if (typeof last === 'string' && last !== 'body' && !out.includes(last)) out.push(last);
  }
  return out;
}

/**
 * A failed match-elements request, with what kind of failure it was.
 *
 * ``message`` keeps the historical ``"<status> <detail>"`` text so callers
 * that show it raw are unchanged; ``kind`` / ``status`` / ``detail`` let
 * the page say what happened in the reader's language instead
 * (see ``describeMatchError``).
 */
export class MatchApiError extends Error {
  readonly kind: 'http' | 'timeout' | 'network';
  readonly status: number | null;
  readonly detail: string;
  /** Fields a 422 rejected, by name; empty for every other failure. */
  readonly fields: string[];

  constructor(
    kind: 'http' | 'timeout' | 'network',
    message: string,
    status: number | null = null,
    detail = '',
    fields: string[] = [],
  ) {
    super(message);
    this.name = 'MatchApiError';
    this.kind = kind;
    this.status = status;
    this.detail = detail;
    this.fields = fields;
  }
}

async function call<T>(path: string, init?: RequestInit & { longRunning?: boolean }): Promise<T> {
  if (init?.longRunning) {
    const { longRunning: _longRunning, ...request } = init;
    return withLongRunningDeadline((signal) => call<T>(path, { ...request, signal }), init.signal);
  }
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
      throw new MatchApiError(
        'timeout',
        'Request cancelled or timed out - the backend did not respond in time.',
      );
    }
    if (err instanceof TypeError) {
      throw new MatchApiError('network', err.message);
    }
    throw err;
  }
  if (!res.ok) {
    let detail = res.statusText;
    let fields: string[] = [];
    try {
      const body = await res.json();
      detail = formatErrorDetail(body) || res.statusText;
      fields = rejectedFields(body);
    } catch {
      // ignore
    }
    throw new MatchApiError('http', `${res.status} ${detail}`, res.status, detail, fields);
  }
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

async function uploadSession(url: string, body: FormData, callerSignal?: AbortSignal): Promise<MatchSession> {
  return withLongRunningDeadline(async (signal) => {
    const token = useAuthStore.getState().accessToken;
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), Accept: 'application/json' },
      body,
      signal,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = formatErrorDetail(await res.json()) || res.statusText; } catch { /* keep HTTP fallback */ }
      throw new Error(`${res.status} ${detail}`);
    }
    return res.json();
  }, callerSignal);
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
  /** Optional server-provided explanation for this candidate, shown as a
   *  note beside the client-built match reasons. Absent on bases that do
   *  not carry a reasoning string. */
  reasoning?: string | null;
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

/** Bulk signature -> prior-confirmed template lookup. Mirrors backend
 *  ``TemplateLookupResponse`` (match_elements/schemas.py): a map keyed by
 *  the group signature so the wizard can show a "previously matched"
 *  hint before running a fresh search. Signatures with no confirmed
 *  mapping are simply absent from ``matches``. */
export interface TemplateLookupResponse {
  matches: Record<string, MatchTemplate>;
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
  /** English prose from the backend. Legacy: kept as the fallback for a
   *  response that carries no {@link install_hint_code}, and for one whose
   *  code this build does not recognise. See
   *  {@link EmbedderInstallHintCode}. Absent on a backend older than the
   *  field itself, which is why it is optional. */
  install_hint?: string;
  /** Which sentence to show, said in a form the UI can translate. Optional
   *  by contract - see {@link EmbedderInstallHintCode}. */
  install_hint_code?: string;
  missing_packages: string[];
  extra_name: string;
}

/**
 * Why the install sentence is what it is, as a value rather than as prose.
 *
 * `install_hint` is written by the backend in English and rendered verbatim,
 * so on the path where it is shown the card drops out of the user's language
 * and into English for every one of the 41 other locales. A reason code moves
 * the sentence into the locale files, where it can be translated once and read
 * in any language.
 *
 * The two values are the two things that are actually true of a reader:
 *
 * - `pip` - there is a package manager here and a command to run. The command
 *   itself still travels in `pip_command`; the code only chooses the sentence.
 * - `frozen_no_extra` - a frozen desktop bundle that ships a fixed set of
 *   packages and has no pip, so the model cannot be added where the reader is
 *   standing. This is the case that has no command, and the case the English
 *   prose was invented for.
 *
 * DELIBERATELY TYPED AS `string`, not as this union, on the wire. The field is
 * optional and open: a backend older than the field sends nothing, and a newer
 * one may send a value this build has never heard of. Neither may render an
 * empty card, so the UI resolves the sentence through a fallback chain and
 * must never switch on this exhaustively. See `installSentence` in
 * `EmbedderStatusCard.tsx` for the chain.
 */
export type EmbedderInstallHintCode = 'pip' | 'frozen_no_extra';

/**
 * GET /api/v1/costs/embedder/status/ — see EmbedderStatus above.
 *
 * Through the shared transport rather than a raw fetch, for the one thing a
 * raw fetch here cannot do: a 401 on this path is almost always an access
 * token that expired while the page sat open, and the wrapper exchanges the
 * refresh token and replays the request. Raw, that 401 was thrown, the card
 * rendered nothing, and it stayed blank until some unrelated request happened
 * to refresh the token.
 *
 * `suppressTimeoutToast` because this probe's failure is a designed
 * non-event: the card returns `null` on error and the page works without it,
 * so the global banner would announce the absence of an optional component to
 * a user who was not waiting for it. The query also polls every 60s, so it
 * would announce it again, and again, which is how a toast stops being read.
 */
export async function fetchEmbedderStatus(): Promise<EmbedderStatus> {
  return apiGet<EmbedderStatus>('/v1/costs/embedder/status/', {
    suppressTimeoutToast: true,
  });
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
      signal?: AbortSignal;
      name?: string;
      catalogue_id?: string | null;
      construction_stage?: ConstructionStage | null;
    },
  ): Promise<MatchSession> => {
    const fd = new FormData();
    fd.append('project_id', spec.project_id);
    fd.append('file', spec.file);
    if (spec.name) fd.append('name', spec.name);
    if (spec.catalogue_id) fd.append('catalogue_id', spec.catalogue_id);
    if (spec.construction_stage)
      fd.append('construction_stage', spec.construction_stage);
    return uploadSession(`${PREFIX}/sessions/from-excel`, fd, spec.signal);
  },

  /** Upload a tender PDF and create a 'pdf' source session in one call.
   *  The backend extracts one line item per table row (or text line) via
   *  the shared PDF parser; see backend pdf_import for the strategy. */
  createSessionFromPdf: async (
    spec: {
      project_id: string;
      file: File;
      signal?: AbortSignal;
      name?: string;
      catalogue_id?: string | null;
      construction_stage?: ConstructionStage | null;
    },
  ): Promise<MatchSession> => {
    const fd = new FormData();
    fd.append('project_id', spec.project_id);
    fd.append('file', spec.file);
    if (spec.name) fd.append('name', spec.name);
    if (spec.catalogue_id) fd.append('catalogue_id', spec.catalogue_id);
    if (spec.construction_stage)
      fd.append('construction_stage', spec.construction_stage);
    return uploadSession(`${PREFIX}/sessions/from-pdf`, fd, spec.signal);
  },

  /** §3.1/§4.1.4 — upload a single photo or drawing snapshot and create
   *  an 'image' source session in one call. The backend binds the saved
   *  file to the session and a vision-LLM enumerates the visible
   *  construction elements with rough quantity estimates. Extraction is
   *  a suggestion the user reviews; the session is usable (empty) even
   *  when no AI provider is configured. Accepts PNG / JPG / WebP up to
   *  10 MB. */
  createSessionFromImage: async (
    spec: {
      project_id: string;
      file: File;
      signal?: AbortSignal;
      name?: string;
      catalogue_id?: string | null;
      construction_stage?: ConstructionStage | null;
    },
  ): Promise<MatchSession> => {
    const fd = new FormData();
    fd.append('project_id', spec.project_id);
    fd.append('image', spec.file);
    if (spec.name) fd.append('name', spec.name);
    if (spec.catalogue_id) fd.append('catalogue_id', spec.catalogue_id);
    if (spec.construction_stage)
      fd.append('construction_stage', spec.construction_stage);
    return uploadSession(`${PREFIX}/sessions/from-image`, fd, spec.signal);
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
      // Optional model/provider hint for the method="llm" re-rank, e.g.
      // "gpt-4o". The key is resolved server-side from the user's own AI
      // settings; only the model hint travels from the client.
      llm_model?: string;
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
      longRunning: true,
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

  /** Bulk lookup of prior-confirmed mappings for a set of group
   *  signatures. Powers the "previously matched" hint: the wizard can
   *  ask, before running a search, which groups the team already
   *  confirmed a code for. Ownership-scoped server-side, so a user only
   *  ever sees their own library. */
  lookupTemplates: (signatures: string[]) =>
    call<TemplateLookupResponse>('/templates/lookup', {
      method: 'POST',
      body: JSON.stringify({ signatures }),
    }),

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
      save_to_my_catalogue?: boolean;
      rfq_supplier_ids?: string[];
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
      { method: 'POST', body: JSON.stringify(body), longRunning: true },
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

  /** Item #18 — deterministic symbol-signature recogniser. Ranks a
   *  structured descriptor (category + geometry quantities + properties)
   *  against the built-in symbol library and returns ranked suggestions
   *  with honest confidence (0..1). NOT computer vision: raster CV symbol
   *  detection is the separate cv-pipeline service. SUGGESTS only; the
   *  human confirms via the existing confirm/apply path. */
  suggestSymbols: (spec: SymbolSuggestRequest) =>
    call<SymbolSuggestResponse>('/suggest-symbols', {
      method: 'POST',
      body: JSON.stringify(spec),
    }),
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
  /** Whether the backend can import a client for the vector database.
   *  A server that is up but has no client is still unusable, and it is the
   *  state that used to report as healthy. Optional so a response from an
   *  older backend is read as "yes" rather than as a missing client. */
  client_installed?: boolean;
}

/** Why matching can or cannot work for a project, before any upload.
 *  Mirrors backend ``MatchReadiness`` (match_elements/schemas.py). */
export type MatchReadinessCode =
  | 'demo_mode'
  | 'search_client_missing'
  | 'search_unreachable'
  | 'search_not_configured'
  | 'no_catalogue_installed'
  | 'embedder_missing'
  | 'no_catalogue_for_language'
  | 'region_language_unknown'
  | 'region_unknown'
  | 'binding_language_differs';

export interface MatchReadinessItem {
  code: MatchReadinessCode;
  params: Record<string, string>;
}

export interface MatchReadiness {
  can_match: boolean;
  blockers: MatchReadinessItem[];
  warnings: MatchReadinessItem[];
  project_region: string;
  /** The backend's reading of the project's region; the same reading
   *  auto-bind uses, so the wizard never re-derives it. */
  project_language: string | null;
  project_country: string | null;
  installed_languages: string[];
  recommended_catalogue: {
    region: string;
    language: string;
    country_iso: string;
    installed: boolean;
  } | null;
  bound_catalogue: string | null;
  /** Owner or admin: may change the project's match settings. */
  can_change_catalogue: boolean;
}

export async function fetchMatchReadiness(projectId: string): Promise<MatchReadiness> {
  return call<MatchReadiness>(`/readiness?project_id=${encodeURIComponent(projectId)}`, {
    method: 'GET',
  });
}

export async function installQdrantNative(): Promise<QdrantHealth> {
  return call<QdrantHealth>('/qdrant/install', { method: 'POST' });
}

// ── Symbol-signature suggestions (item #18) ───────────────────────────
// Shapes mirror backend match_elements/schemas.py exactly.

export interface SymbolSuggestRequest {
  /** Inline descriptor (canonical-format element shape). */
  category?: string | null;
  quantities?: Record<string, number>;
  properties?: Record<string, unknown>;
  /** OR reference an existing stored group (authorised server-side). */
  session_id?: string | null;
  group_key?: string | null;
  top_k?: number;
  min_confidence?: number;
}

export interface SymbolFactor {
  name: string;
  weight: number;
  contribution: number;
  detail: string;
}

export interface SymbolSuggestion {
  symbol: string;
  /** Honest confidence in [0, 1] — blend of category, geometry, keywords. */
  confidence: number;
  confidence_band: 'high' | 'medium' | 'low';
  factors: SymbolFactor[];
  rank: number;
}

export interface SymbolSignatureOut {
  category: string;
  ratios: Record<string, number>;
  property_fingerprint: string[];
  raw_dimensions: Record<string, number>;
}

export interface SymbolSuggestResponse {
  signature: SymbolSignatureOut;
  suggestions: SymbolSuggestion[];
  /** Provenance: deterministic heuristic, not CV/ML pixel detection. */
  note: string;
}
