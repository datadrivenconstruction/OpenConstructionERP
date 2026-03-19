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

export const aiApi = {
  getSettings: () => apiGet<AISettings>('/v1/ai/settings'),

  updateSettings: (data: AISettingsUpdate) =>
    apiPatch<AISettings, AISettingsUpdate>('/v1/ai/settings', data),

  testConnection: (provider: AIProvider) =>
    apiPost<AITestResult, { provider: AIProvider }>('/v1/ai/settings/test', { provider }),

  quickEstimate: (data: QuickEstimateRequest) =>
    apiPost<EstimateJobResponse, QuickEstimateRequest>('/v1/ai/quick-estimate', data),

  createBOQFromEstimate: (jobId: string, data: CreateBOQFromEstimate) =>
    apiPost<{ boq_id: string; project_id: string }, CreateBOQFromEstimate>(
      `/v1/ai/estimate/${jobId}/create-boq`,
      data,
    ),
};
