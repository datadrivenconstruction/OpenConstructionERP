// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Site sensors.
 *
 * Backed by /api/v1/site_sensors/ - see backend/app/modules/site_sensors/router.py.
 * Decimals are strings; sensor values are floats.
 */

import { apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import type { RuleResult } from '@/shared/lib/ruleResults';

export type SensorKind =
  | 'concrete_maturity'
  | 'noise'
  | 'dust_pm10'
  | 'vibration'
  | 'weather'
  | 'water_level';

export interface SensorDevice {
  id: string;
  project_id: string;
  code: string;
  name: string;
  kind: SensorKind;
  unit: string;
  limit_value: string | null;
  country_code: string;
  offline_after_minutes: number;
  token_prefix: string;
  active: boolean;
  last_seen_at: string | null;
  last_value: number | null;
  lat: number | null;
  lng: number | null;
  mix_id: string | null;
  pour_ref: string;
  cast_at: string | null;
  schedule_activity_id: string | null;
}

export interface SensorDeviceInput {
  project_id: string;
  code: string;
  name: string;
  kind: SensorKind;
  unit?: string;
  limit_value?: string | null;
  mix_id?: string | null;
  pour_ref?: string;
  cast_at?: string | null;
}

export interface SensorMix {
  id: string;
  project_id: string | null;
  code: string;
  name: string;
  strip_strength_mpa: string | null;
}

export interface MaturityPoint {
  t: string;
  maturity: number;
  temp: number;
}

export interface Maturity {
  device_id: string;
  mix_id: string | null;
  datum_temp_c: number;
  maturity_c_h: number;
  strength_mpa: number | null;
  target_strength_mpa: number | null;
  target_maturity_c_h?: number;
  hours_to_target: number | null;
  series: MaturityPoint[];
}

export interface SensorAlert {
  id: string;
  project_id: string;
  device_id: string;
  kind: string;
  status: string;
  raised_at: string;
  value: number | null;
  limit_value: number | null;
  limit_source: string;
  acknowledged_at: string | null;
  note: string | null;
  diary_id: string | null;
  inspection_id: string | null;
  punch_item_id: string | null;
}

export interface AlertLinks {
  diary_id: string | null;
  inspection_id: string | null;
  punch_item_id: string | null;
}

export interface FormworkStrip {
  id: string;
  project_id: string;
  device_id: string;
  element: string;
  target_strength_mpa: string;
  planned_at: string | null;
  released_at: string | null;
  struck_at: string | null;
  strength_at_strike_mpa: string | null;
  status: string;
}

export interface SensorSummary {
  devices: number;
  online: number;
  open_alerts: number;
  open_by_kind: Record<string, number>;
  pours: {
    code: string;
    pour_ref: string;
    strength_mpa: number | null;
    target_strength_mpa: number | null;
    maturity_c_h: number;
    hours_to_target: number | null;
  }[];
  latest_alerts: {
    id: string;
    kind: string;
    device_id: string;
    raised_at: string;
    value: number | null;
    limit: number | null;
  }[];
}

export interface SensorValidation {
  results: RuleResult[];
  failed: number;
}

const BASE = '/v1/site_sensors';

export const fetchSensorDevices = (projectId: string) =>
  apiGet<SensorDevice[]>(`${BASE}/devices/?project_id=${encodeURIComponent(projectId)}`);

export const createSensorDevice = (data: SensorDeviceInput) =>
  apiPost<SensorDevice, SensorDeviceInput>(`${BASE}/devices/`, data);

export const updateSensorDevice = (id: string, data: Partial<SensorDeviceInput> & { active?: boolean }) =>
  apiPatch<SensorDevice, typeof data>(`${BASE}/devices/${id}`, data);

export const addSensorReadings = (id: string, readings: { recorded_at: string; value: number }[]) =>
  apiPost<{ accepted: number; exceedances: number }, { readings: typeof readings }>(
    `${BASE}/devices/${id}/readings`,
    { readings },
  );

export const fetchMaturity = (id: string) => apiGet<Maturity>(`${BASE}/devices/${id}/maturity`);

export const fetchSensorMixes = (projectId: string) =>
  apiGet<SensorMix[]>(`${BASE}/mixes/?project_id=${encodeURIComponent(projectId)}`);

export const fetchSensorAlerts = (projectId: string) =>
  apiGet<SensorAlert[]>(`${BASE}/alerts/?project_id=${encodeURIComponent(projectId)}`);

export const acknowledgeAlert = (id: string, note: string) =>
  apiPost<SensorAlert, { note: string }>(`${BASE}/alerts/${id}/acknowledge`, { note });

export const linkAlert = (id: string, links: AlertLinks) =>
  apiPost<SensorAlert, AlertLinks>(`${BASE}/alerts/${id}/links`, links);

export const fetchStrips = (projectId: string) =>
  apiGet<FormworkStrip[]>(`${BASE}/strips/?project_id=${encodeURIComponent(projectId)}`);

export const createStrip = (data: { device_id: string; element: string; target_strength_mpa?: string }) =>
  apiPost<FormworkStrip, typeof data>(`${BASE}/strips/`, data);

export const strikeStrip = (id: string) => apiPost<FormworkStrip, Record<string, never>>(`${BASE}/strips/${id}/strike`, {});

export const fetchSensorSummary = (projectId?: string) =>
  apiGet<SensorSummary>(`${BASE}/summary/?${projectId ? `project_id=${encodeURIComponent(projectId)}` : ''}`);

export const fetchSensorValidation = (projectId: string) =>
  apiGet<SensorValidation>(`${BASE}/validation/?project_id=${encodeURIComponent(projectId)}`);
