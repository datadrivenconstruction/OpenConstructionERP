// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for equipment telematics.
 *
 * Backed by /api/v1/equipment/telematics/ - see
 * backend/app/modules/equipment/telematics_router.py. Decimals are strings.
 */

import { API_BASE, ApiError, apiGet, apiPost, fetchWithAuth, type Page } from '@/shared/lib/api';
import type { RuleResult } from '@/shared/lib/ruleResults';
import type { ImportKind } from './telematicsFormat';

export interface UtilisationMachine {
  equipment_id: string;
  code: string;
  name: string;
  worked_hours: string;
  idle_hours: string;
  off_hours: string;
  fuel_l: string;
  co2_kg: string;
  hire_cost: string;
  /** Currency of the hire cost; blank when the machine's rentals mix currencies. */
  currency: string;
  days: number;
  utilisation_pct: string;
  idle_pct: string;
  project_ids: string[];
}

export interface UtilisationTotals {
  worked_hours: string;
  idle_hours: string;
  off_hours: string;
  fuel_l: string;
  co2_kg: string;
  hire_cost: string;
  utilisation_pct: string;
  idle_pct: string;
  machines: number;
  /** Currency of the hire cost total; blank when the rentals mix currencies. */
  currency: string;
}

export interface Utilisation {
  date_from: string;
  date_to: string;
  machines: UtilisationMachine[];
  totals: UtilisationTotals;
}

export interface AllocateResult {
  allocated_days: number;
  amount: string;
  skipped_no_project: number;
}

export interface TelematicsDevice {
  id: string;
  equipment_id: string;
  label: string;
  token_prefix: string;
  active: boolean;
  last_seen_at: string | null;
  token?: string | null;
}

export interface ImportResult {
  accepted: number;
  unmatched: string[];
  days_rolled_up: number;
  parsed: number;
  rejected?: { line: number; reason: string }[];
}

export interface TelematicsValidation {
  results: RuleResult[];
  failed: number;
  machines: number;
}


function projectQuery(projectId?: string): string {
  return projectId ? `&project_id=${encodeURIComponent(projectId)}` : '';
}

export function fetchUtilisation(dateFrom: string, dateTo: string, projectId?: string): Promise<Utilisation> {
  return apiGet<Utilisation>(`/v1/equipment/telematics/utilisation/?date_from=${dateFrom}&date_to=${dateTo}${projectQuery(projectId)}`);
}

export function allocateHire(dateFrom: string, dateTo: string, projectId?: string): Promise<AllocateResult> {
  return apiPost<AllocateResult, { date_from: string; date_to: string; project_id?: string }>(`/v1/equipment/telematics/allocate/`, {
    date_from: dateFrom,
    date_to: dateTo,
    ...(projectId ? { project_id: projectId } : {}),
  });
}

export function fetchTelematicsValidation(projectId?: string): Promise<TelematicsValidation> {
  return apiGet<TelematicsValidation>(`/v1/equipment/telematics/validation/?${projectQuery(projectId).slice(1)}`);
}

export function fetchTelematicsDevices(): Promise<TelematicsDevice[]> {
  return apiGet<Page<TelematicsDevice>>(`/v1/equipment/telematics/devices/?limit=500`).then((p) => p.items);
}

export function createTelematicsDevice(equipmentId: string, label: string): Promise<TelematicsDevice> {
  return apiPost<TelematicsDevice, { equipment_id: string; label: string }>(`/v1/equipment/telematics/devices/`, {
    equipment_id: equipmentId,
    label,
  });
}

export function revokeTelematicsDevice(deviceId: string): Promise<void> {
  return apiPost<void>(`/v1/equipment/telematics/devices/${deviceId}/revoke`);
}

export async function importTelematics(kind: ImportKind, file: File): Promise<ImportResult> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetchWithAuth(`${API_BASE}/v1/equipment/telematics/import/${kind}/`, { method: 'POST', body: form });
  const payload: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, res.statusText, payload);
  return payload as ImportResult;
}
