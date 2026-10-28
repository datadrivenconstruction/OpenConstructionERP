// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for ESG Site Performance.
 *
 * Tracks operational site ESG metrics (energy, water, waste, site CO2e, local
 * labour, training, safety, governance) recorded per period against targets.
 * All endpoints live under /v1/esg (apiGet/apiPost prepend /api).
 *
 * Note: `value` / `target` figures are Decimal on the backend and therefore
 * arrive as JSON strings - parse with Number() (never do arithmetic on them as
 * strings).
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';


/* ── Types ─────────────────────────────────────────────────────────────── */

export type EsgCategory = 'environmental' | 'social' | 'governance';
export type EsgDirection = 'lower_better' | 'higher_better';

export interface EsgMetricDefinition {
  key: string;
  category: EsgCategory;
  label: string;
  unit: string;
  direction: EsgDirection;
  description: string;
}

export interface EsgEntry {
  id: string;
  project_id: string;
  metric_key: string;
  period: string;
  /** Decimal serialised as a string. */
  value: string;
  /** Decimal serialised as a string, or null. */
  target: string | null;
  note: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface EsgTrendPoint {
  period: string;
  value: string;
}

export interface EsgMetricSummary {
  metric_key: string;
  category: EsgCategory;
  label: string;
  unit: string;
  direction: EsgDirection;
  latest_period: string | null;
  latest_value: string | null;
  target: string | null;
  /** True when the latest reading meets its target given the direction; null when unknown. */
  on_track: boolean | null;
  /** Signed % difference of the latest reading from its target; null when not computable. */
  delta_pct: number | null;
  entry_count: number;
  trend: EsgTrendPoint[];
}

export interface EsgSummary {
  project_id: string;
  trend_periods: number;
  latest_period: string | null;
  by_category: Record<EsgCategory, EsgMetricSummary[]>;
}

export interface CreateEsgEntryPayload {
  project_id: string;
  metric_key: string;
  period: string;
  /** Send as a string to preserve decimal precision. */
  value: string;
  target?: string;
  note?: string;
}

export interface UpdateEsgEntryPayload {
  value?: string;
  target?: string | null;
  note?: string | null;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

/** The fixed catalogue of ESG metric definitions. */
export async function fetchEsgMetrics(): Promise<EsgMetricDefinition[]> {
  return apiGet<EsgMetricDefinition[]>(`/v1/esg/metrics/`);
}

/** Per-metric KPI + short trend for a project, grouped by ESG pillar. */
export async function fetchEsgSummary(
  projectId: string,
  trendPeriods = 6,
): Promise<EsgSummary> {
  const params = new URLSearchParams({ project_id: projectId });
  if (trendPeriods) params.set('trend_periods', String(trendPeriods));
  return apiGet<EsgSummary>(`/v1/esg/summary/?${params.toString()}`);
}

/** List readings for a project, optionally filtered to a single metric. */
export async function fetchEsgEntries(
  projectId: string,
  metricKey?: string,
): Promise<EsgEntry[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (metricKey) params.set('metric', metricKey);
  return apiGet<EsgEntry[]>(`/v1/esg/entries/?${params.toString()}`);
}

export async function createEsgEntry(data: CreateEsgEntryPayload): Promise<EsgEntry> {
  return apiPost<EsgEntry>(`/v1/esg/entries/`, data);
}

export async function updateEsgEntry(
  id: string,
  data: UpdateEsgEntryPayload,
): Promise<EsgEntry> {
  return apiPatch<EsgEntry>(`/v1/esg/entries/${id}`, data);
}

export async function deleteEsgEntry(id: string): Promise<void> {
  await apiDelete<void>(`/v1/esg/entries/${id}`);
}
