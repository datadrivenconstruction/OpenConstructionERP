/**
 * API client for the ACAP construction timeline (Gantt) view.
 *
 * Uses the shared typed fetch helpers (@/shared/lib/api) - `apiPost`
 * already prepends the '/api' base, so paths here start at '/v1/acap' (see
 * frontend/src/acap/floorPlanApi.ts for the same convention).
 */

import { apiPost, triggerDownload, extractErrorMessageFromBody } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

const PREFIX = '/v1/acap';

export interface TimelineTask {
  element: string;
  kode: string;
  uraian: string;
  unit: string;
  stage: string;
  crew: number;
  /** Decimal encoded as a string on the wire. */
  quantity: string;
  /** Decimal encoded as a string on the wire. */
  labor_oh_per_unit: string;
  /** Decimal encoded as a string on the wire. */
  man_days: string;
  duration_days: number;
  start_day: number;
  end_day: number;
  depends_on: string[];
}

export interface TimelineStage {
  stage: string;
  start_day: number;
  end_day: number;
  duration_days: number;
  depends_on: string[];
}

export interface TimelineResponse {
  total_days: number;
  tasks: TimelineTask[];
  stages: TimelineStage[];
  not_covered: string[];
}

/** Generate (or regenerate) the construction timeline for a project. */
export function generateTimeline(projectId: string): Promise<TimelineResponse> {
  return apiPost<TimelineResponse>(`${PREFIX}/projects/${projectId}/timeline:generate`, {});
}

/**
 * Download the timeline as CSV. Fetches with the Bearer token attached
 * (an `<a download>` anchor can't carry auth headers) and triggers a
 * client-side Blob download, mirroring `exportTasks` in
 * frontend/src/features/tasks/api.ts.
 */
export async function downloadTimelineCsv(projectId: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'text/csv' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch(`/api${PREFIX}/projects/${projectId}/timeline.csv`, {
    method: 'GET',
    headers,
  });
  if (!response.ok) {
    let detail = `Export failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename = disposition?.match(/filename="?([^"]+)"?/)?.[1] || `timeline_${projectId}.csv`;
  triggerDownload(blob, filename);
}
