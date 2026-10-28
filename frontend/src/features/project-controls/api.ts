// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Project Controls module.
 *
 * Backed by /api/v1/project-controls/ — see
 * backend/app/modules/project_controls/router.py. The snapshot joins the
 * cost + schedule + quality + safety + risk + change spine into one
 * round-trip, status-banded, with cross-module drill-down deep links.
 */

import { useQuery } from '@tanstack/react-query';

import { apiGet } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type ControlsStatus = 'green' | 'amber' | 'red';

export interface ControlsKPI {
  code: string;
  label: string;
  value: string;
  unit: string;
  status: ControlsStatus;
  source_record_count: number;
  breakdown: Record<string, unknown>;
  drill_url: string;
}

export interface ControlsGroup {
  domain: string;
  label: string;
  kpis: ControlsKPI[];
}

export interface ControlsAlert {
  kpi_code: string;
  severity: 'warning' | 'critical';
  message: string;
}

export interface ControlsSnapshot {
  project_id: string | null;
  currency: string;
  multi_currency: boolean;
  generated_at: string;
  groups: ControlsGroup[];
  alerts: ControlsAlert[];
}

export interface ControlsDrillRecord {
  fields: Record<string, unknown>;
  deep_link: string | null;
}

export interface ControlsDrillResponse {
  kpi_code: string;
  project_id: string | null;
  record_count: number;
  records: ControlsDrillRecord[];
}

export interface ControlsPeriod {
  period_start?: string | null;
  period_end?: string | null;
}

const BASE = '/v1/project-controls';

/* ── Endpoints ─────────────────────────────────────────────────────────── */

export function getControlsSnapshot(
  projectId: string | null,
  period?: ControlsPeriod,
): Promise<ControlsSnapshot> {
  const qs = new URLSearchParams();
  if (projectId) qs.set('project_id', projectId);
  if (period?.period_start) qs.set('period_start', period.period_start);
  if (period?.period_end) qs.set('period_end', period.period_end);
  const q = qs.toString();
  return apiGet<ControlsSnapshot>(`${BASE}/snapshot${q ? `?${q}` : ''}`);
}

export function getControlsDrill(
  kpiCode: string,
  projectId: string | null,
  limit = 100,
): Promise<ControlsDrillResponse> {
  const qs = new URLSearchParams();
  if (projectId) qs.set('project_id', projectId);
  qs.set('limit', String(limit));
  return apiGet<ControlsDrillResponse>(
    `${BASE}/drill/${encodeURIComponent(kpiCode)}?${qs.toString()}`,
  );
}

/* ── React Query hooks ─────────────────────────────────────────────────── */

export function useControlsSnapshot(
  projectId: string | null,
  period?: ControlsPeriod,
) {
  return useQuery({
    queryKey: ['project-controls', 'snapshot', projectId, period],
    queryFn: () => getControlsSnapshot(projectId, period),
    // Match the snapshot dashboard's short stale time — the spine is heavy to
    // recompute so we cache briefly rather than refetching on every focus.
    staleTime: 30_000,
  });
}

export function useControlsDrill(
  kpiCode: string | null,
  projectId: string | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ['project-controls', 'drill', kpiCode, projectId],
    queryFn: () => getControlsDrill(kpiCode as string, projectId),
    enabled: enabled && !!kpiCode,
  });
}
