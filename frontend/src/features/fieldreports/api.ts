// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Field Reports.
 *
 * All endpoints are prefixed with /v1/fieldreports/.
 */

import { apiGet, apiPost, apiPatch, apiDelete, triggerDownload, extractErrorMessageFromBody } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

// The kinds of report the register offers, in the order every picker
// shows them. Mirrors REPORT_TYPES in
// backend/app/modules/fieldreports/schemas.py.
export const REPORT_TYPES = ['daily', 'inspection', 'safety', 'concrete_pour'] as const;
export type ReportType = (typeof REPORT_TYPES)[number];
export type ReportStatus = 'draft' | 'submitted' | 'approved';
// The weather a site report can record. The array is the list and the union
// is derived from it, so a `Record<WeatherCondition, ...>` anywhere in the
// feature stops compiling until it accounts for every word the picker
// offers. Mirrors WEATHER_CONDITIONS in
// backend/app/modules/fieldreports/schemas.py.
export const WEATHER_CONDITIONS = [
  'clear',
  'partly_cloudy',
  'cloudy',
  'overcast',
  'rain',
  'snow',
  'fog',
  'hazy',
  'storm',
] as const;
export type WeatherCondition = (typeof WEATHER_CONDITIONS)[number];

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
  metadata?: Record<string, unknown>;
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
  metadata?: Record<string, unknown>;
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
    `/v1/fieldreports/reports/?${params.toString()}`,
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

/**
 * Download a single field report as PDF.
 *
 * The endpoint is bearer-authenticated (RequirePermission('fieldreports.read')),
 * so a plain `<a href>` navigation would drop the token and 401 — and the route
 * needs its trailing slash (the app runs with redirect_slashes=False). We fetch
 * with the Authorization header and stream the blob to a download, mirroring
 * exportFieldReports below.
 */
export async function exportFieldReportPdf(id: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`/api/v1/fieldreports/reports/${id}/export/pdf/`, {
    method: 'GET',
    headers,
  });
  if (!response.ok) {
    let detail = `Export failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename =
    disposition?.match(/filename="?(.+?)"?$/)?.[1] || `field_report_${id}.pdf`;
  triggerDownload(blob, filename);
}

/* ── Report Templates ──────────────────────────────────────────────────── */

// The field kinds a report template can hold, in the order the picker shows
// them. Mirrors FieldType in backend/app/modules/fieldreports/schemas.py.
export const TEMPLATE_FIELD_TYPES = [
  'text',
  'textarea',
  'number',
  'select',
  'date',
  'checkbox',
] as const;
export type TemplateFieldType = (typeof TEMPLATE_FIELD_TYPES)[number];

export interface TemplateFieldDefinition {
  key: string;
  label: string;
  type: TemplateFieldType;
  required: boolean;
  options: string[];
  placeholder: string;
  help_text: string;
}

export interface FieldReportTemplate {
  id: string;
  project_id: string | null;
  name: string;
  description: string | null;
  report_type: ReportType;
  fields: TemplateFieldDefinition[];
  is_active: boolean;
  is_builtin: boolean;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

export interface CreateTemplatePayload {
  project_id: string;
  name: string;
  description?: string | null;
  report_type?: ReportType;
  fields: Omit<TemplateFieldDefinition, never>[];
  is_active?: boolean;
}

export async function fetchFieldReportTemplates(
  projectId: string,
): Promise<FieldReportTemplate[]> {
  if (!projectId) return [];
  return apiGet<FieldReportTemplate[]>(
    `/v1/fieldreports/templates/?project_id=${encodeURIComponent(projectId)}`,
  );
}

export async function createFieldReportTemplate(
  data: CreateTemplatePayload,
): Promise<FieldReportTemplate> {
  return apiPost<FieldReportTemplate>('/v1/fieldreports/templates/', data);
}

export async function deleteFieldReportTemplate(
  id: string,
  projectId: string,
): Promise<void> {
  return apiDelete(
    `/v1/fieldreports/templates/${id}?project_id=${encodeURIComponent(projectId)}`,
  );
}

/* ── Attachments (reuses the documents module + link-documents) ─────────── */

export interface LinkedDocument {
  id: string;
  name: string;
  category: string;
  file_size: number;
  mime_type: string;
}

export async function fetchReportDocuments(
  reportId: string,
): Promise<LinkedDocument[]> {
  return apiGet<LinkedDocument[]>(
    `/v1/fieldreports/reports/${reportId}/documents/`,
  );
}

export async function linkReportDocuments(
  reportId: string,
  documentIds: string[],
): Promise<FieldReport> {
  return apiPost<FieldReport>(
    `/v1/fieldreports/reports/${reportId}/link-documents/`,
    { document_ids: documentIds },
  );
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
    `/api/v1/fieldreports/reports/import/file/?project_id=${encodeURIComponent(projectId)}`,
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
      detail = extractErrorMessageFromBody(body) ?? detail;
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
    `/api/v1/fieldreports/reports/export/?project_id=${encodeURIComponent(projectId)}`,
    { method: 'GET', headers },
  );
  if (!response.ok) {
    let detail = `Export failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
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

/**
 * Map an OpenWeatherMap free-text description / icon code onto the
 * WeatherCondition vocabulary so a fetched forecast can prefill the modal's
 * "Condition" select. Falls back to 'cloudy' for anything unrecognised.
 *
 * The cloud icons carry the distinction the words do: 02 is a few clouds and
 * 03 scattered, both partly cloudy, while 04 is broken to full overcast. The
 * atmosphere group all shares icon 50, so an icon with no description still
 * reads as fog and only an explicit haze, smoke or dust says 'hazy'.
 */
export function weatherConditionFromDescription(
  description?: string | null,
  icon?: string | null,
): WeatherCondition {
  const d = (description ?? '').toLowerCase();
  const ic = (icon ?? '').toLowerCase();
  if (d.includes('thunder') || d.includes('storm') || ic.startsWith('11')) return 'storm';
  if (d.includes('snow') || d.includes('sleet') || ic.startsWith('13')) return 'snow';
  if (
    d.includes('rain') ||
    d.includes('drizzle') ||
    d.includes('shower') ||
    ic.startsWith('09') ||
    ic.startsWith('10')
  )
    return 'rain';
  if (d.includes('haze') || d.includes('smoke') || d.includes('dust') || d.includes('sand'))
    return 'hazy';
  if (d.includes('fog') || d.includes('mist') || ic.startsWith('50')) return 'fog';
  if (d.includes('overcast') || d.includes('broken cloud') || ic.startsWith('04'))
    return 'overcast';
  if (
    d.includes('partly') ||
    d.includes('few cloud') ||
    d.includes('scattered') ||
    ic.startsWith('02') ||
    ic.startsWith('03')
  )
    return 'partly_cloudy';
  if (d.includes('cloud')) return 'cloudy';
  if (d.includes('clear') || d.includes('sun') || ic.startsWith('01')) return 'clear';
  return 'cloudy';
}

/* ── Site Workforce / Equipment logs (structured, per-report) ───────────── */

export interface SiteWorkforceLog {
  id: string;
  field_report_id: string;
  worker_type: string;
  company: string | null;
  headcount: number;
  hours_worked: string;
  overtime_hours: string;
  wbs_id: string | null;
  cost_category: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SiteWorkforceLogPayload {
  field_report_id: string;
  worker_type: string;
  company?: string | null;
  headcount?: number;
  hours_worked?: string;
  overtime_hours?: string;
  wbs_id?: string | null;
  cost_category?: string | null;
}

export interface SiteEquipmentLog {
  id: string;
  field_report_id: string;
  equipment_description: string;
  equipment_type: string | null;
  hours_operational: string;
  hours_standby: string;
  hours_breakdown: string;
  operator_name: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SiteEquipmentLogPayload {
  field_report_id: string;
  equipment_description: string;
  equipment_type?: string | null;
  hours_operational?: string;
  hours_standby?: string;
  hours_breakdown?: string;
  operator_name?: string | null;
}

export async function fetchWorkforceLogs(reportId: string): Promise<SiteWorkforceLog[]> {
  return apiGet<SiteWorkforceLog[]>(`/v1/fieldreports/reports/${reportId}/workforce/`);
}

export async function createWorkforceLog(
  reportId: string,
  data: SiteWorkforceLogPayload,
): Promise<SiteWorkforceLog> {
  return apiPost<SiteWorkforceLog>(`/v1/fieldreports/reports/${reportId}/workforce/`, data);
}

export async function deleteWorkforceLog(entryId: string): Promise<void> {
  return apiDelete(`/v1/fieldreports/workforce/${entryId}`);
}

export async function fetchEquipmentLogs(reportId: string): Promise<SiteEquipmentLog[]> {
  return apiGet<SiteEquipmentLog[]>(`/v1/fieldreports/reports/${reportId}/equipment/`);
}

export async function createEquipmentLog(
  reportId: string,
  data: SiteEquipmentLogPayload,
): Promise<SiteEquipmentLog> {
  return apiPost<SiteEquipmentLog>(`/v1/fieldreports/reports/${reportId}/equipment/`, data);
}

export async function deleteEquipmentLog(entryId: string): Promise<void> {
  return apiDelete(`/v1/fieldreports/equipment/${entryId}`);
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
