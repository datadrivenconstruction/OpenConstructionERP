// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { apiGet, apiPost, apiPatch, extractErrorMessageFromBody } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { withLongRunningDeadline } from '@/shared/lib/longRunningDeadline';

// ── Types ────────────────────────────────────────────────────────────────────

export type AIProvider =
  | 'anthropic'
  | 'openai'
  | 'gemini'
  | 'openrouter'
  | 'mistral'
  | 'groq'
  | 'deepseek'
  | 'together'
  | 'fireworks'
  | 'perplexity'
  | 'cohere'
  | 'ai21'
  | 'xai'
  | 'zhipu'
  | 'baidu'
  | 'yandex'
  // Final batch: a hosted Chinese provider plus three self-hosted /
  // OpenAI-compatible endpoints (two local runtimes and a hosted one).
  | 'gigachat' | 'ollama' | 'kimi' | 'vllm';

export type AIConnectionStatus = 'connected' | 'not_configured' | 'error';

/** Whether the assistant offers its tools to a self-hosted endpoint. */
export type ToolCallingMode = 'auto' | 'on' | 'off';

/** Range accepted for a per-provider AI timeout, in seconds. */
export const AI_TIMEOUT_MIN_S = 10;
export const AI_TIMEOUT_MAX_S = 1800;

export interface AISettings {
  id: string;
  user_id: string;
  anthropic_api_key_set: boolean;
  openai_api_key_set: boolean;
  gemini_api_key_set: boolean;
  openrouter_api_key_set: boolean;
  mistral_api_key_set: boolean;
  groq_api_key_set: boolean;
  deepseek_api_key_set: boolean;
  together_api_key_set: boolean;
  fireworks_api_key_set: boolean;
  perplexity_api_key_set: boolean;
  cohere_api_key_set: boolean;
  ai21_api_key_set: boolean;
  xai_api_key_set: boolean;
  zhipu_api_key_set: boolean;
  baidu_api_key_set: boolean;
  yandex_api_key_set: boolean;
  gigachat_api_key_set: boolean; kimi_api_key_set: boolean;
  // Self-hosted runtimes carry an endpoint instead of a key flag; null when unset.
  ollama_base_url: string | null; vllm_base_url: string | null;
  /** The OpenAI-compatible endpoint (id `vllm`) takes an optional key. */
  vllm_api_key_set?: boolean;
  /** Saved tool calling mode per self-hosted endpoint, and the server default. */
  tool_calling?: Record<string, ToolCallingMode>;
  tool_calling_defaults?: Record<string, ToolCallingMode>;
  /** Saved per-provider AI timeout in seconds, and the default that applies otherwise. */
  timeouts?: Record<string, number>;
  default_timeout_seconds?: number;
  /**
   * Authoritative "AI is usable" flag from the backend. True when a usable
   * cloud key is set OR a local provider (Ollama / vLLM) is configured via its
   * base_url. Prefer reading this over re-deriving readiness from key flags so
   * local-only setups are not falsely treated as unconfigured.
   */
  ai_ready: boolean;
  preferred_model: string;
  /** Per-provider model-id override the user has saved (provider -> model id). */
  model_overrides: Record<string, string>;
  /** Built-in default model id per provider (used when no override is set). */
  default_models: Record<string, string>;
  metadata_: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  // Frontend-only computed fields (not from API)
  provider?: AIProvider;
  status?: AIConnectionStatus;
  last_tested_at?: string | null;
}

export interface AISettingsUpdate {
  provider?: AIProvider;
  preferred_model?: string;
  /** Per-provider model-id override. Send a blank string to clear one. */
  model_overrides?: Record<string, string>;
  anthropic_api_key?: string | null;
  openai_api_key?: string | null;
  gemini_api_key?: string | null;
  openrouter_api_key?: string | null;
  mistral_api_key?: string | null;
  groq_api_key?: string | null;
  deepseek_api_key?: string | null;
  together_api_key?: string | null;
  fireworks_api_key?: string | null;
  perplexity_api_key?: string | null;
  cohere_api_key?: string | null;
  ai21_api_key?: string | null;
  xai_api_key?: string | null;
  zhipu_api_key?: string | null;
  baidu_api_key?: string | null;
  yandex_api_key?: string | null;
  gigachat_api_key?: string | null; kimi_api_key?: string | null;
  // Optional endpoint overrides for the self-hosted runtimes.
  ollama_base_url?: string | null; vllm_base_url?: string | null;
  /** Optional key of the OpenAI-compatible endpoint. A blank string clears it. */
  vllm_api_key?: string | null;
  /** Per self-hosted endpoint; a blank string returns it to the server default. */
  tool_calling?: Record<string, ToolCallingMode | ''>;
  /** Per-provider timeout in seconds; null clears it. */
  timeouts?: Record<string, number | null>;
}

export interface AITestResult {
  success: boolean;
  message: string;
  latency_ms?: number;
  /** Effective model id the test call used (override or built-in default). */
  model?: string;
}

export interface QuickEstimateRequest {
  description: string;
  location?: string;
  currency?: string;
  standard?: string;
  project_type?: string;
  area_m2?: number;
}

export interface EstimateItem {
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
  classification: Record<string, string>;
  category?: string;
}

export interface EstimateJobResponse {
  id: string;
  status: string;
  items: EstimateItem[];
  grand_total: number;
  currency?: string;
  model_used: string;
  duration_ms: number;
  confidence?: number;
  /** Number of tokens the AI call consumed (0 when unknown). */
  tokens_used?: number;
  /** Estimated USD spend for the run (Decimal-as-string on the wire). */
  cost_usd_estimate?: number | string;
  error_message?: string | null;
  input_type?: string;
}

export interface CreateBOQFromEstimate {
  project_id: string;
  boq_name: string;
  /** When true, persist the best same-currency CWICR rate per line. */
  apply_enriched?: boolean;
  /** Region for the cost-DB lookup when apply_enriched is set. */
  region?: string;
}

/** Lightweight summary of a past estimate job (history list). */
export interface EstimateJobSummary {
  id: string;
  project_id?: string | null;
  input_type: string;
  input_text?: string | null;
  input_filename?: string | null;
  status: string;
  items_count: number;
  currency: string;
  grand_total: number | string;
  model_used?: string | null;
  tokens_used: number;
  cost_usd_estimate: number | string;
  duration_ms: number;
  error_message?: string | null;
  created_at: string;
}

export interface EstimateJobList {
  items: EstimateJobSummary[];
  total: number;
  limit: number;
  offset: number;
}

/** Per-region item counts from the cost database (drives the enrich dropdown). */
export interface CostRegionStat {
  region: string;
  count: number;
}

export interface CostMatch {
  code: string;
  description: string;
  unit: string;
  rate: number;
  /** ISO currency of the matched cost-DB rate. May be empty for legacy rows. */
  currency?: string;
  region: string;
  score: number;
}

export interface EnrichedItem {
  index: number;
  description: string;
  unit: string;
  ai_rate: number;
  matches: CostMatch[];
  best_match: CostMatch | null;
}

export interface EnrichResult {
  items: EnrichedItem[];
  region: string;
  total_matched: number;
  total_items: number;
}

// ── API functions ────────────────────────────────────────────────────────────

function getAuthHeaders(): Record<string, string> {
  const token = useAuthStore.getState().accessToken;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export const aiApi = {
  getSettings: () => apiGet<AISettings>('/v1/ai/settings/'),

  updateSettings: (data: AISettingsUpdate) =>
    apiPatch<AISettings, AISettingsUpdate>('/v1/ai/settings/', data),

  testConnection: (provider: AIProvider) =>
    apiPost<AITestResult, { provider: AIProvider }>('/v1/ai/settings/test/', { provider }),

  /**
   * Generate a BOQ estimate from a text description.
   *
   * Accepts an optional `signal` so callers can wire a Cancel button via
   * `AbortController` - aborting rejects the promise with a DOMException
   * whose `name === 'AbortError'`. The hook layer (useQuickEstimateHistory)
   * uses that signal to distinguish user-cancelled runs (status: 'cancelled')
   * from real failures (status: 'error').
   */
  quickEstimate: (data: QuickEstimateRequest, opts?: { signal?: AbortSignal }) => {
    const send = (signal?: AbortSignal) => apiPost<EstimateJobResponse, QuickEstimateRequest>(
      '/v1/ai/quick-estimate/', data, { longRunning: true, signal },
    );
    // The shared client defers to a supplied signal; keep both Cancel and
    // the heavy-request budget when this screen owns the controller.
    return opts?.signal ? withLongRunningDeadline(send, opts.signal) : send();
  },

  /** Upload a photo and get an AI estimate via Vision model. */
  photoEstimate: async (params: {
    file: File;
    location?: string;
    currency?: string;
    standard?: string;
    signal?: AbortSignal;
  }): Promise<EstimateJobResponse> => {
    const form = new FormData();
    form.append('file', params.file);
    if (params.location) form.append('location', params.location);
    if (params.currency) form.append('currency', params.currency);
    if (params.standard) form.append('standard', params.standard);

    return withLongRunningDeadline(async (signal) => {
      const res = await fetch('/api/v1/ai/photo-estimate/', {
        method: 'POST',
        headers: { ...getAuthHeaders(), Accept: 'application/json' },
        body: form,
        signal,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(extractErrorMessageFromBody(body) ?? 'Photo estimate failed');
      }
      return res.json();
    }, params.signal);
  },

  /** Upload any file (PDF, Excel, CSV, CAD, image) for standalone AI estimate. */
  fileEstimate: async (params: {
    file: File;
    location?: string;
    currency?: string;
    standard?: string;
    signal?: AbortSignal;
  }): Promise<EstimateJobResponse> => {
    const form = new FormData();
    form.append('file', params.file);
    if (params.location) form.append('location', params.location);
    if (params.currency) form.append('currency', params.currency);
    if (params.standard) form.append('standard', params.standard);

    return withLongRunningDeadline(async (signal) => {
      const res = await fetch('/api/v1/ai/file-estimate/', {
        method: 'POST',
        headers: { ...getAuthHeaders(), Accept: 'application/json' },
        body: form,
        signal,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(extractErrorMessageFromBody(body) ?? 'File estimate failed');
      }
      return res.json();
    }, params.signal);
  },

  createBOQFromEstimate: (jobId: string, data: CreateBOQFromEstimate) =>
    apiPost<
      { boq_id: string; project_id: string; positions_created: number; positions_enriched?: number },
      CreateBOQFromEstimate
    >(`/v1/ai/estimate/${jobId}/create-boq/`, data),

  /** List the current user's past estimate jobs (server-side history). */
  listEstimates: (params?: { limit?: number; offset?: number; status?: string }) => {
    const q = new URLSearchParams();
    if (params?.limit != null) q.set('limit', String(params.limit));
    if (params?.offset != null) q.set('offset', String(params.offset));
    if (params?.status) q.set('status_filter', params.status);
    const qs = q.toString();
    return apiGet<EstimateJobList>(`/v1/ai/estimates/${qs ? `?${qs}` : ''}`);
  },

  /** Fetch a single estimate job (used to reopen a history entry). */
  getEstimate: (jobId: string) => apiGet<EstimateJobResponse>(`/v1/ai/estimate/${jobId}`),

  /** Distinct regions present in the cost DB, with item counts (best-first). */
  costRegions: () => apiGet<CostRegionStat[]>('/v1/costs/regions/stats/'),

  enrichEstimate: (jobId: string, region: string, currency: string) =>
    apiPost<EnrichResult>(`/v1/ai/estimate/${jobId}/enrich/`, { region, currency }),

  /** Extract grouped quantity tables from a CAD/BIM file (no AI needed). */
  cadExtract: async (file: File): Promise<CadExtractResponse> => {
    const form = new FormData();
    form.append('file', file);

    const res = await fetch('/api/v1/takeoff/cad-extract/', {
      method: 'POST',
      headers: { ...getAuthHeaders(), Accept: 'application/json' },
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(extractErrorMessageFromBody(body) ?? 'CAD extraction failed');
    }
    return res.json();
  },

  /** Upload a CAD file and get available columns for interactive grouping. */
  cadColumns: async (file: File): Promise<CadColumnsResponse> => {
    const form = new FormData();
    form.append('file', file);

    const res = await fetch('/api/v1/takeoff/cad-columns/', {
      method: 'POST',
      headers: { ...getAuthHeaders(), Accept: 'application/json' },
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(extractErrorMessageFromBody(body) ?? 'CAD column extraction failed');
    }
    return res.json();
  },

  /** Group CAD elements by selected columns and sum quantities. */
  cadGroup: (data: CadGroupRequest) =>
    apiPost<CadGroupResponse, CadGroupRequest>('/v1/takeoff/cad-group/', data),

  /** Get individual elements for a specific group. */
  cadGroupElements: (data: CadGroupElementsRequest) =>
    apiPost<CadGroupElementsResponse, CadGroupElementsRequest>('/v1/takeoff/cad-group/elements/', data),

  /** Create a BOQ directly from grouped CAD QTO data. */
  createBOQFromCadQTO: (data: CreateBOQFromCadQTORequest) =>
    apiPost<CreateBOQFromCadQTOResponse, CreateBOQFromCadQTORequest>(
      '/v1/takeoff/cad-group/create-boq/',
      data,
    ),

  /** Export grouped CAD QTO results as Excel. */
  exportCadGroupExcel: async (params: {
    session_id: string;
    group_by: string[];
    sum_columns: string[];
    /**
     * The user's display measurement system. Sent so the server can render the
     * exported quantities in the same units the user sees in the app. The
     * backend may currently ignore this; storage stays metric-canonical and the
     * FE never converts anything client-side for this path.
     */
    measurementSystem?: 'metric' | 'imperial';
  }): Promise<void> => {
    const query = new URLSearchParams({
      session_id: params.session_id,
      group_by: params.group_by.join(','),
      sum_columns: params.sum_columns.join(','),
      format: 'xlsx',
      measurementSystem: params.measurementSystem ?? 'metric',
    });
    const res = await fetch(`/api/v1/takeoff/cad-group/export/?${query.toString()}`, {
      method: 'GET',
      headers: { ...getAuthHeaders() },
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(extractErrorMessageFromBody(body) ?? 'Export failed');
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const disposition = res.headers.get('Content-Disposition') || '';
    const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
    a.download = filenameMatch?.[1] || `cad-qto-export.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  },
};

// ── CAD BOQ creation types ────────────────────────────────────────────────────

export interface CreateBOQFromCadQTORequest {
  session_id: string;
  project_id: string;
  boq_name: string;
  group_by: string[];
  sum_columns: string[];
}

export interface CreateBOQFromCadQTOResponse {
  boq_id: string;
  project_id: string;
  position_count: number;
  boq_name: string;
}

// ── CAD quantity extraction types ───────────────────────────────────────────

export interface CadQuantityItem {
  type: string;
  material: string;
  count: number;
  volume_m3: number;
  area_m2: number;
  length_m: number;
}

export interface QuantityTotals {
  count: number;
  volume_m3: number;
  area_m2: number;
  length_m: number;
}

export interface CadQuantityGroup {
  category: string;
  items: CadQuantityItem[];
  totals: QuantityTotals;
}

export interface CadExtractResponse {
  filename: string;
  format: string;
  total_elements: number;
  duration_ms: number;
  groups: CadQuantityGroup[];
  grand_totals: QuantityTotals;
}

// ── CAD interactive grouping types ──────────────────────────────────────────

export interface CadColumnsResponse {
  filename: string;
  format: string;
  total_elements: number;
  columns: {
    grouping: string[];
    quantity: string[];
    text: string[];
  };
  suggested_grouping: string[];
  suggested_quantities: string[];
  preview: Record<string, any>[];
  session_id: string;
  duration_ms: number;
  presets: Record<string, {
    label: string;
    description: string;
    group_by: string[];
    sum_columns: string[];
  }>;
  unit_labels: Record<string, string>;
  confidence: Record<string, number>;
}

export interface CadGroupRequest {
  session_id: string;
  group_by: string[];
  sum_columns: string[];
}

export interface CadDynamicGroup {
  key: string;
  key_parts: Record<string, string>;
  count: number;
  sums: Record<string, number>;
}

export interface CadGroupResponse {
  total_elements: number;
  group_by: string[];
  sum_columns: string[];
  groups: CadDynamicGroup[];
  grand_totals: Record<string, number>;
}

export interface CadGroupElementsRequest {
  session_id: string;
  group_key: Record<string, string>;
}

export interface CadGroupElementsResponse {
  group_key: Record<string, string>;
  total_elements: number;
  columns: string[];
  elements: Record<string, any>[];
  totals: Record<string, number>;
  truncated: boolean;
}

/** Result returned by the BOQ smart import endpoint. */
export interface SmartImportResult {
  imported: number;
  skipped?: number;
  errors: { row?: number; item?: string; error: string; data?: Record<string, string> }[];
  total_rows?: number;
  total_items?: number;
  method?: 'direct' | 'ai' | 'cad_ai';
  model_used?: string | null;
  cad_format?: string;
  cad_elements?: number;
}
