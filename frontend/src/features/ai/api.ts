import { apiGet, apiPost, apiPatch } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

// ── Types ────────────────────────────────────────────────────────────────────

export type AIProvider = 'anthropic' | 'openai' | 'gemini' | 'openrouter' | 'mistral' | 'groq' | 'deepseek';

export type AIConnectionStatus = 'connected' | 'not_configured' | 'error';

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
  preferred_model: string;
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
  anthropic_api_key?: string | null;
  openai_api_key?: string | null;
  gemini_api_key?: string | null;
  openrouter_api_key?: string | null;
  mistral_api_key?: string | null;
  groq_api_key?: string | null;
  deepseek_api_key?: string | null;
}

export interface AITestResult {
  success: boolean;
  message: string;
  latency_ms?: number;
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
  error_message?: string | null;
  input_type?: string;
}

export interface CreateBOQFromEstimate {
  project_id: string;
  boq_name: string;
}

export interface CostMatch {
  code: string;
  description: string;
  unit: string;
  rate: number;
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
  getSettings: () => apiGet<AISettings>('/v1/ai/settings'),

  updateSettings: (data: AISettingsUpdate) =>
    apiPatch<AISettings, AISettingsUpdate>('/v1/ai/settings', data),

  testConnection: (provider: AIProvider) =>
    apiPost<AITestResult, { provider: AIProvider }>('/v1/ai/settings/test', { provider }),

  quickEstimate: (data: QuickEstimateRequest) =>
    apiPost<EstimateJobResponse, QuickEstimateRequest>('/v1/ai/quick-estimate', data),

  /** Upload a photo and get an AI estimate via Vision model. */
  photoEstimate: async (params: {
    file: File;
    location?: string;
    currency?: string;
    standard?: string;
  }): Promise<EstimateJobResponse> => {
    const form = new FormData();
    form.append('file', params.file);
    if (params.location) form.append('location', params.location);
    if (params.currency) form.append('currency', params.currency);
    if (params.standard) form.append('standard', params.standard);

    const res = await fetch('/api/v1/ai/photo-estimate', {
      method: 'POST',
      headers: { ...getAuthHeaders(), Accept: 'application/json' },
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(body.detail || 'Photo estimate failed');
    }
    return res.json();
  },

  /** Upload any file (PDF, Excel, CSV, CAD, image) for standalone AI estimate. */
  fileEstimate: async (params: {
    file: File;
    location?: string;
    currency?: string;
    standard?: string;
  }): Promise<EstimateJobResponse> => {
    const form = new FormData();
    form.append('file', params.file);
    if (params.location) form.append('location', params.location);
    if (params.currency) form.append('currency', params.currency);
    if (params.standard) form.append('standard', params.standard);

    const res = await fetch('/api/v1/ai/file-estimate', {
      method: 'POST',
      headers: { ...getAuthHeaders(), Accept: 'application/json' },
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(body.detail || 'File estimate failed');
    }
    return res.json();
  },

  createBOQFromEstimate: (jobId: string, data: CreateBOQFromEstimate) =>
    apiPost<{ boq_id: string; project_id: string }, CreateBOQFromEstimate>(
      `/v1/ai/estimate/${jobId}/create-boq`,
      data,
    ),

  enrichEstimate: (jobId: string, region: string, currency: string) =>
    apiPost<EnrichResult>(`/v1/ai/estimate/${jobId}/enrich`, { region, currency }),

  /** Extract grouped quantity tables from a CAD/BIM file (no AI needed). */
  cadExtract: async (file: File): Promise<CadExtractResponse> => {
    const form = new FormData();
    form.append('file', file);

    const res = await fetch('/api/v1/takeoff/cad-extract', {
      method: 'POST',
      headers: { ...getAuthHeaders(), Accept: 'application/json' },
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(body.detail || 'CAD extraction failed');
    }
    return res.json();
  },

  /** Upload a CAD file and get available columns for interactive grouping. */
  cadColumns: async (file: File): Promise<CadColumnsResponse> => {
    const form = new FormData();
    form.append('file', file);

    const res = await fetch('/api/v1/takeoff/cad-columns', {
      method: 'POST',
      headers: { ...getAuthHeaders(), Accept: 'application/json' },
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(body.detail || 'CAD column extraction failed');
    }
    return res.json();
  },

  /** Group CAD elements by selected columns and sum quantities. */
  cadGroup: (data: CadGroupRequest) =>
    apiPost<CadGroupResponse, CadGroupRequest>('/v1/takeoff/cad-group', data),

  /** Get individual elements for a specific group. */
  cadGroupElements: (data: CadGroupElementsRequest) =>
    apiPost<CadGroupElementsResponse, CadGroupElementsRequest>('/v1/takeoff/cad-group/elements', data),

  /** Create a BOQ directly from grouped CAD QTO data. */
  createBOQFromCadQTO: (data: CreateBOQFromCadQTORequest) =>
    apiPost<CreateBOQFromCadQTOResponse, CreateBOQFromCadQTORequest>(
      '/v1/takeoff/cad-group/create-boq',
      data,
    ),

  /** Export grouped CAD QTO results as Excel. */
  exportCadGroupExcel: async (params: {
    session_id: string;
    group_by: string[];
    sum_columns: string[];
  }): Promise<void> => {
    const query = new URLSearchParams({
      session_id: params.session_id,
      group_by: params.group_by.join(','),
      sum_columns: params.sum_columns.join(','),
      format: 'xlsx',
    });
    const res = await fetch(`/api/v1/takeoff/cad-group/export?${query.toString()}`, {
      method: 'GET',
      headers: { ...getAuthHeaders() },
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(body.detail || 'Export failed');
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
