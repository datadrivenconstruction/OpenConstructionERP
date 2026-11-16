// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the payroll hours export, backed by
 * /api/v1/field-time/payroll-export/ (backend/app/modules/field_time/payroll_router.py).
 * Hours are never money: nothing here prices or computes pay.
 */

import { API_BASE, apiDelete, apiGet, apiPost, apiPut, fetchWithAuth, triggerDownload } from '@/shared/lib/api';

export interface PayrollColumn {
  header: string;
  source: string;
  constant: string;
}

export interface PayrollProfileConfig {
  columns: PayrollColumn[];
  delimiter: string;
  decimal: string;
  date_format: string;
  encoding: string;
  grouping: 'day' | 'week';
  week_start: number;
  include_daywork: boolean;
  include_header: boolean;
  fallback_to_code: boolean;
  day_threshold: string | null;
  pay_codes: Record<string, string>;
}

export interface PayrollProfile {
  id: string;
  name: string;
  is_sample: boolean;
  config: PayrollProfileConfig;
}

export interface PayrollExample {
  key: string;
  label_key: string;
  name: string;
  config: PayrollProfileConfig;
}

export interface PayrollIssue {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  details: Record<string, unknown>;
}

export interface PayrollPreview {
  workers: number;
  rows: number;
  hours: string;
  corrections: number;
  issues: PayrollIssue[];
  blocked: boolean;
  overlapping_runs: string[];
}

export interface PayrollRun {
  id: string;
  number: number;
  profile_name: string;
  period_from: string;
  period_to: string;
  row_count: number;
  correction_count: number;
  worker_count: number;
  total_hours: string;
  filename: string;
  sha256: string;
  created_at: string;
}

const BASE = '/v1/field-time/payroll-export';

export const listPayrollProfiles = () => apiGet<PayrollProfile[]>(`${BASE}/profiles/`);
export const listPayrollExamples = () => apiGet<PayrollExample[]>(`${BASE}/examples/`);
export const listPayrollRuns = () => apiGet<PayrollRun[]>(`${BASE}/runs/`);
export const deletePayrollProfile = (id: string) => apiDelete(`${BASE}/profiles/${id}`);

export const savePayrollProfile = (name: string, config: PayrollProfileConfig, isSample = false) =>
  apiPost<PayrollProfile>(`${BASE}/profiles/`, { name, config, is_sample: isSample });

export const updatePayrollProfile = (id: string, name: string, config: PayrollProfileConfig) =>
  apiPut<PayrollProfile>(`${BASE}/profiles/${id}`, { name, config });

export function previewPayroll(profileId: string, from: string, to: string, projectIds: string[]) {
  const qs = new URLSearchParams({ profile_id: profileId, period_from: from, period_to: to });
  projectIds.forEach((p) => qs.append('project_id', p));
  return apiGet<PayrollPreview>(`${BASE}/preview/?${qs.toString()}`);
}

export const createPayrollRun = (profileId: string, from: string, to: string, projectIds: string[]) =>
  apiPost<PayrollRun>(`${BASE}/runs/`, {
    profile_id: profileId,
    period_from: from,
    period_to: to,
    project_ids: projectIds,
  });

export async function downloadPayrollRun(run: PayrollRun): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}${BASE}/runs/${run.id}/file`);
  if (!res.ok) throw new Error(res.statusText);
  triggerDownload(await res.blob(), run.filename);
}

/** The most recent completed week (Monday to Sunday) before `today`, as ISO dates. */
export function lastCompletedWeek(today: Date): { from: string; to: string } {
  const dow = (today.getDay() + 6) % 7; // Monday = 0
  const end = new Date(today);
  end.setDate(today.getDate() - dow - 1);
  const start = new Date(end);
  start.setDate(end.getDate() - 6);
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return { from: iso(start), to: iso(end) };
}
