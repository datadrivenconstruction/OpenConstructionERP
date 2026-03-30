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
};

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
