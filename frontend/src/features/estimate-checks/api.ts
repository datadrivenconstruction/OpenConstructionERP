// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Estimate check API: ratings of one estimate, acceptances, workspace settings
 * and the caller's display preference. Backend: /api/v1/estimate_checks.
 */
import { apiDelete, apiGet, apiPut } from '@/shared/lib/api';

export type CheckStatus = 'normal' | 'suspect' | 'warning' | 'no_data';
export type DisplayMode = 'all' | 'issues' | 'badge' | 'off';
export type KpiGroup = 'labour' | 'equipment' | 'materials' | 'subcontractors' | 'markup' | 'data_quality';
export type KpiUnit = 'pct' | 'money' | 'ratio' | 'count';

export interface PositionRef {
  id: string;
  ordinal: string;
  description: string;
}

export interface Acceptance {
  reason: string;
  accepted_by: string;
  accepted_at: string | null;
  status_at_accept: string;
  value_at_accept: string | null;
}

export interface KpiResult {
  kpi_id: string;
  group: KpiGroup;
  unit: KpiUnit;
  unit_label: string | null;
  value: number | null;
  low: number | null;
  high: number | null;
  compared: number;
  status: CheckStatus;
  confidence: number;
  reason: string;
  positions: PositionRef[];
  position_count: number;
  accepted: Acceptance | null;
}

export interface StatusCounts {
  normal: number;
  suspect: number;
  warning: number;
  accepted: number;
}

export interface CheckResponse {
  boq_id: string;
  revision: string;
  currency: string;
  comparables_scope: string;
  comparables_pool: number;
  counts: StatusCounts;
  kpis: KpiResult[];
}

export interface KpiSetting {
  enabled: boolean;
  low?: number | null;
  high?: number | null;
}

export interface KpiCatalogEntry {
  kpi_id: string;
  group: KpiGroup;
  unit: KpiUnit;
  kind: 'historical' | 'count';
  default_low: number | null;
  default_high: number | null;
}

export interface CheckSettings {
  comparables: 'auto' | 'currency' | 'all';
  min_comparables: number;
  warning_margin: number;
  database_rate_tolerance_pct: number;
  count_warning_share_pct: number;
  kpis: Record<string, KpiSetting>;
}

export interface SettingsResponse extends CheckSettings {
  catalog: KpiCatalogEntry[];
}

const BASE = '/v1/estimate_checks';

export const estimateChecksApi = {
  check: (boqId: string) => apiGet<CheckResponse>(`${BASE}/boq/${encodeURIComponent(boqId)}`),
  accept: (boqId: string, kpiId: string, reason: string) =>
    apiPut<CheckResponse, { reason: string }>(
      `${BASE}/boq/${encodeURIComponent(boqId)}/accept/${encodeURIComponent(kpiId)}`,
      { reason },
    ),
  withdraw: (boqId: string, kpiId: string) =>
    apiDelete<CheckResponse>(`${BASE}/boq/${encodeURIComponent(boqId)}/accept/${encodeURIComponent(kpiId)}`),
  settings: () => apiGet<SettingsResponse>(`${BASE}/settings`),
  saveSettings: (body: CheckSettings) => apiPut<SettingsResponse, CheckSettings>(`${BASE}/settings`, body),
  preference: () => apiGet<{ display_mode: DisplayMode }>(`${BASE}/preference`),
  savePreference: (mode: DisplayMode) =>
    apiPut<{ display_mode: DisplayMode }, { display_mode: DisplayMode }>(`${BASE}/preference`, {
      display_mode: mode,
    }),
};
