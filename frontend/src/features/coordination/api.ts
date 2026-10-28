// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Coordination Hub dashboard.
 *
 * Endpoints (mounted at /api/v1/coordination-hub, legacy /api/v1/coordination_hub):
 *   GET /v1/coordination_hub/projects/{pid}/dashboard
 *   GET /v1/coordination_hub/projects/{pid}/trade-matrix
 *   GET /v1/coordination_hub/projects/{pid}/timeline?days=N
 *   GET /v1/coordination_hub/projects/{pid}/thresholds
 *   PUT /v1/coordination_hub/projects/{pid}/thresholds/{metric}
 */

import { apiGet, apiPut, getAuthToken } from '@/shared/lib/api';
import type {
  CoordinationDashboard,
  CoordinationThresholdsResponse,
  CoordinationThresholdUpdate,
  CoordinationTimelineResponse,
  ThresholdRow,
  TradeMatrixResponse,
} from './types';

/** Fetch the Coordination Hub KPI rollup for one project. */
export function fetchCoordinationDashboard(
  projectId: string,
): Promise<CoordinationDashboard> {
  return apiGet<CoordinationDashboard>(
    `/v1/coordination_hub/projects/${projectId}/dashboard`,
  );
}

/** Fetch the trade-matrix payload for the heat-map. */
export function fetchTradeMatrix(
  projectId: string,
): Promise<TradeMatrixResponse> {
  return apiGet<TradeMatrixResponse>(
    `/v1/coordination_hub/projects/${projectId}/trade-matrix`,
  );
}

/** Fetch the activity timeline. */
export function fetchCoordinationTimeline(
  projectId: string,
  days = 30,
): Promise<CoordinationTimelineResponse> {
  return apiGet<CoordinationTimelineResponse>(
    `/v1/coordination_hub/projects/${projectId}/timeline?days=${days}`,
  );
}

/**
 * Fetch the project's alert thresholds together with their current
 * evaluated state (`alerts[]` = the metrics currently in breach, error
 * rows first). Drives the health banner above the KPI cards. Requires
 * `coordination.read`.
 */
export function fetchCoordinationThresholds(
  projectId: string,
): Promise<CoordinationThresholdsResponse> {
  return apiGet<CoordinationThresholdsResponse>(
    `/v1/coordination_hub/projects/${projectId}/thresholds`,
  );
}

/**
 * Download the live coordination snapshot for a project as a CSV file
 * (KPIs + threshold-alert status + cost-weighted discipline-pair
 * breakdown). Streams the attachment from the API with the bearer token,
 * then triggers a browser download. Throws on a non-2xx response so the
 * caller can surface an error toast. Requires `coordination.read`.
 */
export async function downloadCoordinationSnapshot(
  projectId: string,
): Promise<void> {
  const token = getAuthToken();
  const res = await fetch(
    `/api/v1/coordination_hub/projects/${projectId}/export.csv`,
    {
      method: 'GET',
      headers: {
        Accept: 'text/csv',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    },
  );
  if (!res.ok) {
    throw Object.assign(new Error(`Export failed (${res.status})`), {
      status: res.status,
    });
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = `coordination-${projectId}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // Revoke on the next tick so the click has a chance to start.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

/**
 * Patch one threshold's warn/error value or its `enabled` flag. Requires
 * `coordination.write`; the backend re-evaluates and returns the updated
 * row with `current_value` + `level` filled in.
 */
export function updateCoordinationThreshold(
  projectId: string,
  metric: string,
  body: CoordinationThresholdUpdate,
): Promise<ThresholdRow> {
  return apiPut<ThresholdRow, CoordinationThresholdUpdate>(
    `/v1/coordination_hub/projects/${projectId}/thresholds/${encodeURIComponent(metric)}`,
    body,
  );
}
