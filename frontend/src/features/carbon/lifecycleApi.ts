// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * API helpers for life-cycle carbon (A4, A5, hotspots, budget, checks) and
 * company climate reporting (ESRS E1, SECR, US state templates).
 * Backed by backend/app/modules/carbon/lifecycle_router.py.
 */

import { apiGet, apiPost, downloadWithAuth, fetchWithAuth, getErrorMessage } from '@/shared/lib/api';

export type DataQuality = 'measured' | 'calculated' | 'estimated';
export type ClassificationSystem = 'din276' | 'nrm' | 'masterformat';
export type ReportTemplate = 'esrs_e1' | 'uk_secr' | 'us_state';
export type ExportFormat = 'xlsx' | 'pdf' | 'xbrl_csv';

export interface Hotspot {
  group: string;
  carbon_kg: string;
  share_pct: number;
}

export interface CarbonBudget {
  actual_kg: string;
  budget_kg: string;
  remaining_kg: string;
  used_pct: number;
  over_budget: boolean;
  target_id: string | null;
  inventory_id: string | null;
}

export interface CarbonChecks {
  inventory_id: string | null;
  no_factor: string[];
  outdated_factor_set: string[];
  expired_epd: string[];
  unit_mismatch: string[];
  budget: CarbonBudget;
}

export interface E1Datapoint {
  label: string;
  unit: string;
  value: string;
  xbrl_element: string;
  data_quality: DataQuality;
  source_count: number;
}

export interface CompanyReport {
  id: string;
  reporting_year: number;
  template: ReportTemplate;
  company_name: string;
  net_revenue: string;
  currency: string;
  status: string;
  datapoints: Record<string, E1Datapoint>;
  audit: Record<string, Array<Record<string, unknown>>>;
}

export interface EpdImportResult {
  format: string;
  imported: string[];
  errors: string[];
}

export function getHotspots(inventoryId: string, system: ClassificationSystem): Promise<Hotspot[]> {
  return apiGet<Hotspot[]>(`/v1/carbon/inventories/${inventoryId}/hotspots?system=${system}`);
}

export function getBudget(projectId: string): Promise<CarbonBudget> {
  return apiGet<CarbonBudget>(`/v1/carbon/projects/${projectId}/budget`);
}

export function getChecks(projectId: string): Promise<CarbonChecks> {
  return apiGet<CarbonChecks>(`/v1/carbon/projects/${projectId}/checks`);
}

export function addTransportA4(
  inventoryId: string,
  body: { mass_kg: string; distance_km: string; mode: string; supplier?: string },
): Promise<unknown> {
  return apiPost(`/v1/carbon/inventories/${inventoryId}/a4-transport`, body);
}

export function addSiteEnergyA5(
  inventoryId: string,
  body: { fuel_litres: Record<string, string>; electricity_kwh: string },
): Promise<unknown> {
  return apiPost(`/v1/carbon/inventories/${inventoryId}/a5-site-energy`, body);
}

export async function importEpdFile(file: File, materialClass = 'other'): Promise<EpdImportResult> {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('material_class', materialClass);
  const res = await fetchWithAuth('/api/v1/carbon/epd/import', { method: 'POST', body: fd });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(getErrorMessage(body?.detail ?? res.statusText));
  return body as EpdImportResult;
}

export function listCompanyReports(): Promise<CompanyReport[]> {
  return apiGet<CompanyReport[]>('/v1/carbon/company/reports');
}

export function generateCompanyReport(body: {
  reporting_year: number;
  template: ReportTemplate;
  company_name: string;
  net_revenue: string;
  currency: string;
}): Promise<CompanyReport> {
  return apiPost<CompanyReport>('/v1/carbon/company/reports', body);
}

export function exportCompanyReport(report: CompanyReport, fmt: ExportFormat): Promise<void> {
  const ext = fmt === 'xbrl_csv' ? 'csv' : fmt;
  return downloadWithAuth(
    `/api/v1/carbon/company/reports/${report.id}/export?fmt=${fmt}`,
    `${report.template}_${report.reporting_year}.${ext}`,
  );
}

export interface BidCarbonLine {
  ref: string;
  carbon_kg: string | null;
  status: 'ok' | 'no_factor' | 'unit_mismatch';
}

export function getBidCarbon(
  lines: Array<{ ref: string; position_id?: string | null; quantity: number; unit?: string }>,
): Promise<{ lines: BidCarbonLine[]; total_kg: string }> {
  return apiPost('/v1/carbon/bid-carbon', { lines });
}

export interface CarbonWidget {
  budget: CarbonBudget;
  system: ClassificationSystem;
  top_hotspot: Hotspot | null;
}

export function getCarbonWidget(projectId: string): Promise<CarbonWidget> {
  return apiGet<CarbonWidget>(`/v1/carbon/projects/${projectId}/widget`);
}
