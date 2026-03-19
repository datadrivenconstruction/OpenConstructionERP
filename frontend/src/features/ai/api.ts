import { apiGet, apiPost, apiPatch } from '@/shared/lib/api';

// ── Types ────────────────────────────────────────────────────────────────────

export type AIProvider = 'anthropic' | 'openai' | 'gemini';

export type AIConnectionStatus = 'connected' | 'not_configured' | 'error';

export interface AISettings {
  provider: AIProvider;
  anthropic_api_key: string | null;
  openai_api_key: string | null;
  gemini_api_key: string | null;
  preferred_model: string;
  status: AIConnectionStatus;
  last_tested_at: string | null;
}

export interface AISettingsUpdate {
  provider?: AIProvider;
  anthropic_api_key?: string | null;
  openai_api_key?: string | null;
  gemini_api_key?: string | null;
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
  classification_standard?: string;
  building_type?: string;
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
  total_cost: number;
  currency: string;
  model_used: string;
  duration_ms: number;
  confidence: number;
}

export interface CreateBOQFromEstimate {
  project_id: string;
  boq_name: string;
}

// ── API functions ────────────────────────────────────────────────────────────

const TOKEN_KEY = 'oe_access_token';

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem(TOKEN_KEY);
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

  /** Upload any file (PDF, Excel, CSV, CAD) to BOQ smart import via AI. */
  fileEstimate: async (params: {
    file: File;
    boqId: string;
  }): Promise<SmartImportResult> => {
    const form = new FormData();
    form.append('file', params.file);

    const res = await fetch(`/api/v1/boq/boqs/${params.boqId}/import/smart`, {
      method: 'POST',
      headers: { ...getAuthHeaders(), Accept: 'application/json' },
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(body.detail || 'File import failed');
    }
    return res.json();
  },

  createBOQFromEstimate: (jobId: string, data: CreateBOQFromEstimate) =>
    apiPost<{ boq_id: string; project_id: string }, CreateBOQFromEstimate>(
      `/v1/ai/estimate/${jobId}/create-boq`,
      data,
    ),
};

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
