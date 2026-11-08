// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.
 *
 * Backed by /api/v1/site_sensors/ - see backend/app/modules/site_sensors/router.py.
 * Decimals are strings; sensor values are floats.
 */

import { API_BASE, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';
import { fetchAllPages } from '@/shared/lib/apiHelpers';
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
  noise_zone: string;
  building_class: string;
  frequency_band: string;
  effective_limit: number | null;
  limit_source: string;
  night_limit_by_ordinance: boolean;
  bim_model_id: string | null;
  bim_element_id: string | null;
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
  noise_zone?: string;
  building_class?: string;
  frequency_band?: string;
  bim_model_id?: string | null;
  bim_element_id?: string | null;
}

export type MaturityMethod = 'nurse_saul' | 'equivalent_age';

export interface SensorMix {
  id: string;
  project_id: string | null;
  code: string;
  name: string;
  datum_temp_c: string;
  method: MaturityMethod;
  activation_energy_kj_mol: string;
  reference_temp_c: string;
  curve_a: string;
  curve_b: string;
  strip_strength_mpa: string | null;
  fit_r2: number | null;
  calibrated_min: number | null;
  calibrated_max: number | null;
}

export interface SensorMixInput {
  project_id: string;
  code: string;
  name?: string;
  method: MaturityMethod;
  datum_temp_c: string;
  activation_energy_kj_mol: string;
  curve_a: string;
  curve_b: string;
  strip_strength_mpa?: string | null;
}

export interface CalibrationPoint {
  maturity_index: number;
  strength_mpa: string;
  age_hours?: number | null;
  note?: string;
}

export interface Calibration {
  mix: SensorMix;
  points: (CalibrationPoint & { id: string })[];
}

export interface SensorContext {
  country: string;
  unit_system: 'metric' | 'imperial';
  strike_ready: {
    strip_id: string;
    element: string;
    device_code: string;
    strength_mpa: number | null;
    target_strength_mpa: number;
  }[];
}

export type Sparklines = Record<string, { points: (number | null)[]; limit: number | null }>;

export interface MaturityPoint {
  t: string;
  maturity: number;
  temp: number;
}

export type StrengthStatus = 'ok' | 'below_range' | 'above_range' | 'uncalibrated' | null;

export interface Maturity {
  device_id: string;
  mix_id: string | null;
  method: MaturityMethod;
  /** `c_h` for Nurse-Saul degree-hours, `h` for equivalent age. */
  index_unit: 'c_h' | 'h';
  datum_temp_c: number;
  activation_energy_kj_mol: number | null;
  reference_temp_c: number | null;
  maturity_c_h: number;
  strength_mpa: number | null;
  strength_status: StrengthStatus;
  calibrated_min: number | null;
  calibrated_max: number | null;
  fit_r2: number | null;
  target_strength_mpa: number | null;
  target_maturity_c_h?: number;
  hours_to_target: number | null;
  hours_to_target_range: [number, number] | null;
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
  strike_reason: string | null;
  struck_by: string | null;
  status: string;
  bim_model_id: string | null;
  bim_element_id: string | null;
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


export const fetchSensorDevices = async (projectId: string) => {
  const { items } = await fetchAllPages<SensorDevice>((offset, limit) =>
    apiGet<{ items: SensorDevice[] }>(
      `/v1/site_sensors/devices/?project_id=${encodeURIComponent(projectId)}&offset=${offset}&limit=${limit}`,
    ),
  );
  return items;
};

export const createSensorDevice = (data: SensorDeviceInput) =>
  apiPost<SensorDevice, SensorDeviceInput>(`/v1/site_sensors/devices/`, data);

export const updateSensorDevice = (id: string, data: Partial<SensorDeviceInput> & { active?: boolean }) =>
  apiPatch<SensorDevice, typeof data>(`/v1/site_sensors/devices/${id}`, data);

export const addSensorReadings = (id: string, readings: { recorded_at: string; value: number }[]) =>
  apiPost<{ accepted: number; exceedances: number }, { readings: typeof readings }>(
    `/v1/site_sensors/devices/${id}/readings`,
    { readings },
  );

export const fetchMaturity = (id: string) => apiGet<Maturity>(`/v1/site_sensors/devices/${id}/maturity`);

export const fetchSensorMixes = async (projectId: string) => {
  const { items } = await fetchAllPages<SensorMix>((offset, limit) =>
    apiGet<{ items: SensorMix[] }>(
      `/v1/site_sensors/mixes/?project_id=${encodeURIComponent(projectId)}&offset=${offset}&limit=${limit}`,
    ),
  );
  return items;
};

export const fetchSensorAlerts = async (projectId: string) => {
  const { items } = await fetchAllPages<SensorAlert>((offset, limit) =>
    apiGet<{ items: SensorAlert[] }>(
      `/v1/site_sensors/alerts/?project_id=${encodeURIComponent(projectId)}&offset=${offset}&limit=${limit}`,
    ),
  );
  return items;
};

export const acknowledgeAlert = (id: string, note: string) =>
  apiPost<SensorAlert, { note: string }>(`/v1/site_sensors/alerts/${id}/acknowledge`, { note });

export const linkAlert = (id: string, links: AlertLinks) =>
  apiPost<SensorAlert, AlertLinks>(`/v1/site_sensors/alerts/${id}/links`, links);

export const fetchStrips = async (projectId: string) => {
  const { items } = await fetchAllPages<FormworkStrip>((offset, limit) =>
    apiGet<{ items: FormworkStrip[] }>(
      `/v1/site_sensors/strips/?project_id=${encodeURIComponent(projectId)}&offset=${offset}&limit=${limit}`,
    ),
  );
  return items;
};

export const createStrip = (data: { device_id: string; element: string; target_strength_mpa?: string }) =>
  apiPost<FormworkStrip, typeof data>(`/v1/site_sensors/strips/`, data);

export const strikeStrip = (id: string, reason = '') =>
  apiPost<FormworkStrip, { reason: string }>(`/v1/site_sensors/strips/${id}/strike`, { reason });

export const downloadPourRecord = (id: string, format: 'csv' | 'pdf', lang: string, name: string) =>
  downloadWithAuth(
    `${API_BASE}/v1/site_sensors/strips/${id}/record?format=${format}&lang=${encodeURIComponent(lang)}`,
    `pour-record-${name || id}.${format}`,
  );

export const createSensorMix = (data: SensorMixInput) =>
  apiPost<SensorMix, SensorMixInput>(`/v1/site_sensors/mixes/`, data);

export const fetchCalibration = (mixId: string) => apiGet<Calibration>(`/v1/site_sensors/mixes/${mixId}/calibration`);

export const saveCalibration = (mixId: string, points: CalibrationPoint[]) =>
  apiPut<Calibration, { points: CalibrationPoint[] }>(`/v1/site_sensors/mixes/${mixId}/calibration`, { points });

export const fetchSensorContext = (projectId: string) =>
  apiGet<SensorContext>(`/v1/site_sensors/context/?project_id=${encodeURIComponent(projectId)}`);

export const fetchSparklines = (projectId: string) =>
  apiGet<Sparklines>(`/v1/site_sensors/sparklines/?project_id=${encodeURIComponent(projectId)}`);

export const fetchSensorSummary = (projectId?: string) =>
  apiGet<SensorSummary>(`/v1/site_sensors/summary/?${projectId ? `project_id=${encodeURIComponent(projectId)}` : ''}`);

export const fetchSensorValidation = (projectId: string) =>
  apiGet<SensorValidation>(`/v1/site_sensors/validation/?project_id=${encodeURIComponent(projectId)}`);
