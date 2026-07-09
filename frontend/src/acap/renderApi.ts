/**
 * API client for the ACAP visual render viewer (floor plan -> image via
 * GeminiGen).
 *
 * Uses the shared typed fetch helpers (@/shared/lib/api) - `apiPost`/`apiGet`
 * already prepend the '/api' base, so paths here start at '/v1/acap' (see
 * frontend/src/acap/timelineApi.ts for the same convention).
 */

import { apiGet, apiPost, ApiError } from '@/shared/lib/api';

const PREFIX = '/v1/acap';

export interface RenderResponse {
  render_id: string;
  floor_plan_version: number;
  status: 'completed' | 'failed' | 'pending' | string;
  prompt: string;
  storage_key: string | null;
  source_url: string | null;
  error_message: string | null;
}

/**
 * Generate (or regenerate) a visual render for a project's latest floor
 * plan. Slow — the backend blocks on image generation + polling (up to ~7
 * min); callers should show a loading state that makes that clear.
 *
 * Throws `ApiError(404)` when the project has no floor plan yet, and
 * `ApiError(400)` when the render service isn't configured (see
 * `isNotConfiguredError`).
 */
export function generateRender(projectId: string): Promise<RenderResponse> {
  return apiPost<RenderResponse>(`${PREFIX}/projects/${projectId}/render:generate`, {});
}

/** List a project's renders, newest first. */
export function listRenders(projectId: string): Promise<RenderResponse[]> {
  return apiGet<RenderResponse[]>(`${PREFIX}/projects/${projectId}/renders`);
}

/**
 * True when `err` is the key-gated 400 the backend returns if
 * `GEMINIGEN_API_KEY` isn't set — i.e. the render service is simply not
 * configured yet, not a real failure. Callers should show a calm info
 * banner instead of an error toast.
 */
export function isNotConfiguredError(err: unknown): boolean {
  if (!(err instanceof ApiError) || err.status !== 400) return false;
  const body = err.body as { detail?: { reason?: string; detail?: string } } | undefined;
  return body?.detail?.reason === 'GEMINIGEN_API_KEY not set';
}
