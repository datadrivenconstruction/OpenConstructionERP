/**
 * API helpers for Field Reports.
 *
 * All endpoints are prefixed with /v1/fieldreports/.
 */

import { apiGet, apiPost, apiPatch, apiDelete, triggerDownload } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

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
  const res = await apiGet<FieldReport[] | { items: FieldReport[] }>(
    `/v1/fieldreports/reports?${params.toString()}`,
  );
  return Array.isArray(res) ? res : res.items ?? [];
}

export async function fetchFieldReport(id: string): Promise<FieldReport> {
  return apiGet<FieldReport>(`/v1/fieldreports/reports/${id}`);
}

export async function createFieldReport(data: CreateFieldReportPayload): Promise<FieldReport> {
  return apiPost<FieldReport>('/v1/fieldreports/reports/', data);
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
  return apiPost<FieldReport>(`/v1/fieldreports/reports/${id}/submit/`, {});
}

export async function approveFieldReport(id: string): Promise<FieldReport> {
  return apiPost<FieldReport>(`/v1/fieldreports/reports/${id}/approve/`, {});
}

export async function fetchFieldReportSummary(projectId: string): Promise<FieldReportSummary | null> {
  if (!projectId) return null;
  return apiGet<FieldReportSummary>(`/v1/fieldreports/reports/summary/?project_id=${projectId}`);
}

export async function fetchFieldReportCalendar(
  projectId: string,
  month: string,
): Promise<FieldReport[]> {
  if (!projectId) return [];
  const res = await apiGet<FieldReport[] | { items: FieldReport[] }>(
    `/v1/fieldreports/reports/calendar/?project_id=${projectId}&month=${month}`,
  );
  return Array.isArray(res) ? res : res.items ?? [];
}

export function getFieldReportPdfUrl(id: string): string {
  return `/api/v1/fieldreports/reports/${id}/export/pdf`;
}

/* ── Import / Export ────────��─────────────────────────────────────────────── */

export interface ImportResult {
  imported: number;
  skipped: number;
  errors: { row: number; error: string; data: Record<string, string> }[];
  total_rows: number;
}

export async function importFieldReportsFile(
  file: File,
  projectId: string,
): Promise<ImportResult> {
  const token = useAuthStore.getState().accessToken;
  const formData = new FormData();
  formData.append('file', file);

  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(
    `/api/v1/fieldreports/reports/import/file?project_id=${encodeURIComponent(projectId)}`,
    {
      method: 'POST',
      headers,
      body: formData,
    },
  );

  if (!response.ok) {
    let detail = 'Import failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  return response.json();
}

export async function exportFieldReports(projectId: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(
    `/api/v1/fieldreports/reports/export?project_id=${encodeURIComponent(projectId)}`,
    { method: 'GET', headers },
  );
  if (!response.ok) {
    let detail = 'Export failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename =
    disposition?.match(/filename="?(.+)"?/)?.[1] || 'field_reports_export.xlsx';
  triggerDownload(blob, filename);
}

/* ── Weather ─────────────────────────────────────────────────────────────── */

export interface WeatherData {
  available: boolean;
  temperature_c?: number | null;
  feels_like_c?: number | null;
  humidity_pct?: number | null;
  wind_speed_ms?: number | null;
  wind_direction?: string | null;
  description?: string | null;
  icon?: string | null;
  precipitation_mm?: number | null;
  error?: string;
}

export async function fetchWeather(lat: number, lon: number): Promise<WeatherData> {
  return apiGet<WeatherData>(`/v1/fieldreports/weather/?lat=${lat}&lon=${lon}`);
}

/* ── Template Download ──────────────────────────────────────────────────── */

export function downloadFieldReportsTemplate(): void {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  fetch('/api/v1/fieldreports/reports/template/', { method: 'GET', headers })
    .then((response) => {
      if (!response.ok) throw new Error('Failed to download template');
      return response.blob();
    })
    .then((blob) => {
      triggerDownload(blob, 'field_reports_import_template.xlsx');
    })
    .catch((err) => {
      if (import.meta.env.DEV) console.error('Template download error:', err);
    });
}
