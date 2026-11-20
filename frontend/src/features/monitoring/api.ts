// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for monitoring: points, readings import (preview first, nothing
 * saved until Import), alerts with their acknowledge note, profiles and the alarm report.
 */

import { API_BASE, activeLanguageTag, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

const BASE = '/v1/monitoring';

export type Level = 'none' | 'ok' | 'alert' | 'action' | 'alarm';
export type AckState = 'none' | 'pending' | 'done';
export type PointType = 'prism' | 'settlement_pin' | 'convergence_chord' | 'inclinometer';
export type Axis = 'z' | 'horizontal' | '3d' | 'value';

export interface Thresholds {
  alert_mm: number | null;
  action_mm: number | null;
  alarm_mm: number | null;
  rate_alert: number | null;
  rate_action: number | null;
  rate_alarm: number | null;
}

export interface Profile {
  key: string;
  name: string;
  source: 'demo' | 'pack' | 'project';
  country: string;
  reference: string;
  edition?: string;
  clause?: string;
  status?: 'verified' | 'to_verify' | '';
  thresholds: Thresholds;
}

export interface Settings {
  profile_key: string;
  profile: Profile | null;
}

export interface MonitoringPoint {
  id: string;
  project_id: string;
  code: string;
  name: string;
  point_type: PointType;
  axis: Axis;
  location: string;
  epochs: number;
  baseline_at: string | null;
  latest_at: string | null;
  baseline_value: number | null;
  latest_value: number | null;
  displacement_mm: number | null;
  rate_mm_day: number | null;
  level: Level;
  ack_state: AckState;
  /** Next threshold the linear trend of the last epochs reaches, and in how many days. */
  forecast_level?: string;
  forecast_days?: number | null;
  forecast_rate_mm_day?: number | null;
  /** False when the trend is flat or runs back towards zero. */
  forecast_approaching?: boolean;
  forecast_epochs?: number;
  /** Every level with a displacement limit: reached already, or days until the trend reaches it. */
  forecast_levels?: ForecastLevel[];
}

export interface ForecastLevel {
  level: 'alert' | 'action' | 'alarm';
  limit_mm: number;
  reached: boolean;
  days: number | null;
}

export interface SeriesEntry {
  at: string;
  e: number | null;
  n: number | null;
  z: number | null;
  value: number | null;
  displacement_mm: number | null;
  rate_mm_day: number | null;
  level: Level;
  /** The risk register entry this reading's alert opened. */
  risk_id?: string | null;
}

export interface Alert {
  id: string;
  reading_id: string;
  level: 'alert' | 'action' | 'alarm';
  displacement_mm: number;
  rate_mm_day: number | null;
  observed_at: string;
  profile_label: string;
  thresholds: Thresholds;
  notified: boolean;
  risk_id: string | null;
  acknowledged_at: string | null;
  acknowledged_by_name: string;
  note: string;
}

export interface PointDetail extends MonitoringPoint {
  profile_label: string;
  thresholds: Thresholds | null;
  series: SeriesEntry[];
  alerts: Alert[];
}

export interface Summary {
  points: number;
  ok: number;
  alert: number;
  action: number;
  alarm: number;
  unacknowledged: number;
  last_epoch: string | null;
}

export interface ImportProblem {
  line: number;
  point_id: string;
  message: string;
}

export interface ReadingsPreview {
  rows_read: number;
  readings: number;
  new_points: string[];
  epochs: string[];
  already_imported: number;
  problems: ImportProblem[];
  problem_count: number;
}

export interface ReadingsResult {
  rows_read: number;
  readings_added: number;
  readings_skipped: number;
  new_points: string[];
  epochs_added: number;
  alerts: Alert[];
  problems: ImportProblem[];
  problem_count: number;
}

export interface Finding {
  rule_id: string;
  severity: string;
  message: string;
  suggestion?: string | null;
  element_ref?: string | null;
}

export interface ValidationReport {
  status: string;
  error_count: number;
  warning_count: number;
  info_count: number;
  findings: Finding[];
}

const project = (id: string) => `${BASE}/projects/${encodeURIComponent(id)}`;
const loc = (locale: string) => `locale=${encodeURIComponent(locale)}`;

export const listPoints = (projectId: string) => apiGet<{ items: MonitoringPoint[] }>(`${project(projectId)}/points`).then((r) => r.items);
export const getPoint = (id: string) => apiGet<PointDetail>(`${BASE}/points/${encodeURIComponent(id)}`);
export const getSummary = (projectId: string) => apiGet<Summary>(`${project(projectId)}/summary`);
export const getSettings = (projectId: string) => apiGet<Settings>(`${project(projectId)}/settings`);
export const listProfiles = (projectId: string) => apiGet<{ items: Profile[] }>(`${project(projectId)}/profiles`).then((r) => r.items);
export const setProfile = (projectId: string, profile_key: string) =>
  apiPut<Settings, { profile_key: string }>(`${project(projectId)}/settings`, { profile_key });
export const validateMonitoring = (projectId: string, locale: string) =>
  apiPost<ValidationReport>(`${project(projectId)}/validate?${loc(locale)}`);
export const previewReadings = (projectId: string, text: string) =>
  apiPost<ReadingsPreview, { text: string }>(`${project(projectId)}/readings/preview`, { text });
export const importReadings = (projectId: string, text: string, filename: string, locale: string) =>
  apiPost<ReadingsResult, { text: string; filename: string }>(`${project(projectId)}/readings?${loc(locale)}`, {
    text,
    filename,
  });
export const acknowledge = (pointId: string, note: string, locale: string) =>
  apiPost<PointDetail, { note: string }>(`${BASE}/points/${encodeURIComponent(pointId)}/acknowledge?${loc(locale)}`, { note });
export const loadDemo = (projectId: string) => apiPost<MonitoringPoint[]>(`${project(projectId)}/demo/riverside?epochs=3`);
export const updatePoint = (id: string, body: { name?: string; location?: string }) =>
  apiPatch<MonitoringPoint, typeof body>(`${BASE}/points/${encodeURIComponent(id)}`, body);
export const deletePoint = (id: string) => apiDelete(`${BASE}/points/${encodeURIComponent(id)}`);

export async function downloadReport(projectId: string): Promise<void> {
  const lang = activeLanguageTag();
  const query = lang ? `?${loc(lang)}` : '';
  await downloadWithAuth(`${API_BASE}${project(projectId)}/report.pdf${query}`, 'monitoring-alarm-report.pdf');
}
