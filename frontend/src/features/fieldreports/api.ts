/**
 * API helpers for Field Reports.
 *
 * All endpoints are prefixed with /v1/fieldreports/.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type ReportType = 'daily' | 'inspection' | 'safety' | 'concrete_pour';
export type ReportStatus = 'draft' | 'submitted' | 'approved';
export type WeatherCondition = 'clear' | 'cloudy' | 'rain' | 'snow' | 'fog' | 'storm';

export interface WorkforceEntry {
  trade: string;
  count: number;
  hours: number;
}

export interface FieldReport {
  id: string;
  project_id: string;
  report_date: string;
  report_type: ReportType;
  weather_condition: WeatherCondition;
  temperature_c: number | null;
  wind_speed: string | null;
  precipitation: string | null;
  humidity: number | null;
  workforce: WorkforceEntry[];
  equipment_on_site: string[];
  work_performed: string;
  delays: string | null;
  delay_hours: number;
  visitors: string | null;
  deliveries: string | null;
  safety_incidents: string | null;
  materials_used: string[];
  photos: string[];
  notes: string | null;
  signature_by: string | null;
  signature_data: string | null;
  status: ReportStatus;
  approved_by: string | null;
  approved_at: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface FieldReportSummary {
  total: number;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  total_workforce_hours: number;
  total_delay_hours: number;
}

export interface CreateFieldReportPayload {
  project_id: string;
  report_date: string;
  report_type: ReportType;
  weather_condition?: WeatherCondition;
  temperature_c?: number | null;
  wind_speed?: string | null;
  precipitation?: string | null;
  humidity?: number | null;
  workforce?: WorkforceEntry[];
  equipment_on_site?: string[];
  work_performed?: string;
  delays?: string | null;
  delay_hours?: number;
  visitors?: string | null;
  deliveries?: string | null;
  safety_incidents?: string | null;
  materials_used?: string[];
  photos?: string[];
  notes?: string | null;
  signature_by?: string | null;
  signature_data?: string | null;
}

export interface UpdateFieldReportPayload {
  report_date?: string;
  report_type?: ReportType;
  weather_condition?: WeatherCondition;
  temperature_c?: number | null;
  wind_speed?: string | null;
  precipitation?: string | null;
  humidity?: number | null;
  workforce?: WorkforceEntry[];
  equipment_on_site?: string[];
  work_performed?: string;
  delays?: string | null;
  delay_hours?: number;
  visitors?: string | null;
  deliveries?: string | null;
  safety_incidents?: string | null;
  materials_used?: string[];
  photos?: string[];
  notes?: string | null;
  signature_by?: string | null;
  signature_data?: string | null;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchFieldReports(
  projectId: string,
  filters?: {
    date_from?: string;
    date_to?: string;
    status?: ReportStatus | '';
    type?: ReportType | '';
  },
): Promise<FieldReport[]> {
  if (!projectId) return [];
  const params = new URLSearchParams({ project_id: projectId });
  if (filters?.date_from) params.set('date_from', filters.date_from);
  if (filters?.date_to) params.set('date_to', filters.date_to);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.type) params.set('type', filters.type);
  return apiGet<FieldReport[]>(`/v1/fieldreports/reports?${params.toString()}`);
}

export async function fetchFieldReport(id: string): Promise<FieldReport> {
  return apiGet<FieldReport>(`/v1/fieldreports/reports/${id}`);
}

export async function createFieldReport(data: CreateFieldReportPayload): Promise<FieldReport> {
  return apiPost<FieldReport>('/v1/fieldreports/reports', data);
}

export async function updateFieldReport(
  id: string,
  data: UpdateFieldReportPayload,
): Promise<FieldReport> {
  return apiPatch<FieldReport>(`/v1/fieldreports/reports/${id}`, data);
}

export async function deleteFieldReport(id: string): Promise<void> {
  return apiDelete(`/v1/fieldreports/reports/${id}`);
}

export async function submitFieldReport(id: string): Promise<FieldReport> {
  return apiPost<FieldReport>(`/v1/fieldreports/reports/${id}/submit`, {});
}

export async function approveFieldReport(id: string): Promise<FieldReport> {
  return apiPost<FieldReport>(`/v1/fieldreports/reports/${id}/approve`, {});
}

export async function fetchFieldReportSummary(projectId: string): Promise<FieldReportSummary> {
  return apiGet<FieldReportSummary>(`/v1/fieldreports/reports/summary?project_id=${projectId}`);
}

export async function fetchFieldReportCalendar(
  projectId: string,
  month: string,
): Promise<FieldReport[]> {
  return apiGet<FieldReport[]>(
    `/v1/fieldreports/reports/calendar?project_id=${projectId}&month=${month}`,
  );
}

export function getFieldReportPdfUrl(id: string): string {
  return `/api/v1/fieldreports/reports/${id}/export/pdf`;
}
