import { API_BASE, apiPost, ApiError, getAuthToken } from '@/shared/lib/api';
import type { FloorPlan } from '@/acap/planTypes';

const PREFIX = '/v1/acap';

export interface ExtractResponse {
  draft_plan: FloorPlan;
  valid: boolean;
  reasons: string[];
  model: string;
}

export interface UploadResponse {
  image_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
}

export function uploadPlanImage(projectId: string, file: File, signal?: AbortSignal): Promise<UploadResponse> {
  const token = getAuthToken();
  const form = new FormData();
  form.append('file', file);

  return fetch(`${API_BASE}${PREFIX}/projects/${projectId}/plan-images`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
    signal,
  }).then(async (res) => {
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, res.statusText, body);
    }
    return res.json() as Promise<UploadResponse>;
  });
}

export function extractPlanImage(projectId: string, imageId: string): Promise<ExtractResponse> {
  return apiPost<ExtractResponse>(`${PREFIX}/projects/${projectId}/plan-images/${imageId}/extract`, {}, { longRunning: true });
}

export function isVisionNotConfiguredError(err: unknown): boolean {
  if (!(err instanceof ApiError) || err.status !== 400) return false;
  const body = err.body as { detail?: { reason?: string } } | undefined;
  return body?.detail?.reason === 'GOOGLE_API_KEY not set';
}
