// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the BI Dashboards module.
 *
 * Backed by /api/v1/bi-dashboards/ — see backend/app/modules/bi_dashboards/router.py
 */

import {
  apiGet,
  apiPost,
  apiPatch,
  apiDelete,
  getAuthToken,
  triggerDownload,
} from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type DashboardScope = 'personal' | 'role' | 'global' | 'project';
export type ReportScope = 'personal' | 'role' | 'global';
export type WidgetType =
  | 'kpi_card'
  | 'line_chart'
  | 'bar_chart'
  | 'pie'
  | 'table'
  | 'heatmap'
  | 'gauge'
  | 'timeline';
export type ReportFrequency = 'daily' | 'weekly' | 'monthly' | 'quarterly';
export type OutputFormat = 'pdf' | 'xlsx' | 'csv' | 'json';
export type AlertCondition =
  | 'above'
  | 'below'
  | 'equals'
  | 'not_equals'
  | 'changed_by_more_than';
export type AlertSeverity = 'info' | 'warning' | 'critical';
export type KpiCategory =
  | 'financial'
  | 'schedule'
  | 'quality'
  | 'safety'
  | 'sustainability'
  | 'operational';

export interface KpiDefinition {
  id: string;
  code: string;
  name: string;
  description: string;
  formula_ref: string;
  source_modules: string[];
  unit: string;
  target_default: number | string | null;
  aggregation: string;
  category: KpiCategory | string;
  is_system: boolean;
  /** Null means the definition is company-wide and shows on every project. */
  project_id: string | null;
  /**
   * What one value of this KPI is a value OF.
   *
   * `project` is what every definition registered before this field existed
   * means, and stays the default. `estimate` says the KPI is only readable
   * one bill at a time, which is the honest reading for anything normalised:
   * a project holding several separately quoted estimates has one figure per
   * estimate and no meaningful average of them.
   */
  scope: KpiScope;
  created_at: string;
  updated_at: string;
}

export type KpiScope = 'project' | 'estimate';

export interface KpiHistoryPoint {
  period_start: string;
  period_end: string;
  value: number | string;
  unit: string;
  source_record_count: number;
}

export interface KpiHistoryResponse {
  kpi_code: string;
  history: KpiHistoryPoint[];
}

export interface KpiComputeResponse {
  kpi_code: string;
  value: number | string;
  unit: string;
  source_record_count: number;
  computed_at: string;
  breakdown: Record<string, unknown>;
  trend: Array<Record<string, unknown>>;
  benchmark?: {
    value?: string;
    median?: string;
    percentile?: string;
    portfolio_size?: number;
  };
}

export interface DrillDownResponse {
  kpi_code: string;
  records: Array<Record<string, unknown>>;
  record_count: number;
  aggregate_value: number | string | null;
  aggregate_unit: string | null;
}

export interface Dashboard {
  id: string;
  name: string;
  description: string;
  owner_user_id: string | null;
  scope: DashboardScope;
  role_ref: string | null;
  project_id: string | null;
  layout_json: Record<string, unknown>;
  is_default: boolean;
  refresh_interval_seconds: number;
  /**
   * Wave 4 / T11 — opt-in flag. When true the dashboard's evaluate endpoint
   * propagates click-driven filters into every widget. False (the default)
   * keeps the v3.x static-render behaviour.
   */
  cross_filter_enabled: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Describes how a click on a widget propagates a filter to the rest of the
 * dashboard. ``filter_value_from`` is a lightweight expression — currently
 * either a literal value or ``"row.<field>"`` to pull a per-row value out
 * of the clicked table/chart record.
 */
export interface DrillPath {
  filter_field: string;
  filter_value_from?: string;
}

export interface WidgetEvaluateResult {
  id: string;
  kpi_code: string | null;
  widget_type: WidgetType | string;
  value: number | string | null;
  unit: string | null;
  series: Array<Record<string, unknown>>;
  drill_path: DrillPath | null;
  breakdown: Record<string, unknown>;
}

export interface DashboardEvaluateResponse {
  dashboard_id: string;
  cross_filter_enabled: boolean;
  applied_filters: Record<string, unknown>;
  widgets: WidgetEvaluateResult[];
  evaluated_at: string;
}

export interface WidgetRead {
  id: string;
  dashboard_id: string;
  widget_type: WidgetType;
  kpi_code: string | null;
  config_json: Record<string, unknown>;
  position_x: number;
  position_y: number;
  width: number;
  height: number;
  order_seq: number;
  drill_path: DrillPath | null;
  created_at: string;
  updated_at: string;
}

export interface WidgetRenderResult {
  widget: WidgetRead;
  value: number | string | null;
  unit: string | null;
  breakdown: Record<string, unknown>;
  from_cache: boolean;
}

export interface DashboardRenderResponse {
  dashboard: Dashboard;
  widgets: WidgetRenderResult[];
  rendered_at: string;
}

export interface ReportDefinition {
  id: string;
  code: string;
  name: string;
  description: string;
  owner_user_id: string | null;
  source_modules: string[];
  query_spec_json: Record<string, unknown>;
  output_format: OutputFormat;
  template_ref: string | null;
  scope: ReportScope;
  /** Null means the report is company-wide and shows on every project. */
  project_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReportRunResponse {
  report_id: string;
  file_url: string | null;
  rows: Array<Record<string, unknown>>;
  row_count: number;
  output_format: OutputFormat;
  generated_at: string;
}

export interface ReportSchedule {
  id: string;
  report_definition_id: string;
  frequency: ReportFrequency;
  day_of_week: number | null;
  day_of_month: number | null;
  time_of_day: string;
  timezone: string;
  recipients_json: Array<Record<string, unknown>>;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  filter_overrides_json: Record<string, unknown>;
  /** Null means the schedule follows its parent report's audience. */
  project_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertRule {
  id: string;
  name: string;
  kpi_code: string;
  condition: AlertCondition;
  threshold_value: number | string;
  threshold_unit: string | null;
  severity: AlertSeverity;
  scope_project_id: string | null;
  recipients_json: Array<Record<string, unknown>>;
  channels_json: string[];
  throttle_seconds: number;
  last_triggered_at: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateDashboardPayload {
  name: string;
  description?: string;
  scope?: DashboardScope;
  role_ref?: string | null;
  project_id?: string | null;
  refresh_interval_seconds?: number;
  cross_filter_enabled?: boolean;
}

export interface CreateReportPayload {
  code: string;
  name: string;
  description?: string;
  source_modules?: string[];
  output_format?: OutputFormat;
  scope?: ReportScope;
  /** Pin the report to one project; omit to leave it company-wide. */
  project_id?: string | null;
}

export interface CreateAlertPayload {
  name: string;
  kpi_code: string;
  condition: AlertCondition;
  threshold_value: number;
  severity?: AlertSeverity;
  scope_project_id?: string | null;
  expression_json?: Record<string, unknown>;
}

const BASE = '/v1/bi-dashboards';

/* ── KPI ───────────────────────────────────────────────────────────────── */

/**
 * List the KPI library.
 *
 * `project_id` is the project named in the address bar on the
 * `/projects/:projectId/bi-dashboards` route. The backend answers with that
 * project's own definitions plus the company-wide ones (`project_id` NULL);
 * omitting it keeps the whole library, which is what the plain module route
 * wants.
 */
export function listKpis(params?: {
  category?: string;
  project_id?: string;
}): Promise<KpiDefinition[]> {
  const qs = new URLSearchParams();
  if (params?.category) qs.set('category', params.category);
  if (params?.project_id) qs.set('project_id', params.project_id);
  const q = qs.toString();
  return apiGet<KpiDefinition[]>(`${BASE}/kpis${q ? `?${q}` : ''}`);
}

export function getKpiHistory(
  code: string,
  params?: { project_id?: string; boq_id?: string; limit?: number },
): Promise<KpiHistoryResponse> {
  const qs = new URLSearchParams();
  if (params?.project_id) qs.set('project_id', params.project_id);
  // Narrows the trend to one estimate. Omitting it is the project-level
  // series, which is what every stored point was before estimates existed -
  // the server reads the absence as `boq_id IS NULL` rather than as "any".
  if (params?.boq_id) qs.set('boq_id', params.boq_id);
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return apiGet<KpiHistoryResponse>(
    `${BASE}/kpis/${encodeURIComponent(code)}/history${q ? `?${q}` : ''}`,
  );
}

export function computeKpi(
  code: string,
  payload: {
    project_id?: string | null;
    /**
     * Read one estimate rather than the whole project.
     *
     * The server resolves it to the project that owns it and checks access
     * against that, so passing it alone is enough and passing a `project_id`
     * that disagrees with it is refused rather than silently resolved.
     * A KPI that cannot be read per estimate answers 422 instead of
     * returning the project figure under the estimate's name.
     */
    boq_id?: string | null;
    period_start?: string | null;
    period_end?: string | null;
    filters?: Record<string, unknown>;
    persist?: boolean;
  },
): Promise<KpiComputeResponse> {
  return apiPost<KpiComputeResponse>(
    `${BASE}/kpis/${encodeURIComponent(code)}/compute`,
    payload,
  );
}

/* ── Custom KPI (issue #441) ──────────────────────────────────────────── */

/** A field kind decides which aggregations and filter operators it accepts. */
export type KpiSpecFieldKind = 'numeric' | 'text' | 'uuid' | 'bool';

export interface KpiSpecField {
  name: string;
  kind: KpiSpecFieldKind;
}

export interface KpiSpecJsonPathField {
  name: string;
  kind: KpiSpecFieldKind;
  /** The shape to show, e.g. `classification.<key>`. */
  example: string;
}

/** One entity a custom KPI may aggregate over, as the catalog describes it. */
export interface KpiSpecEntity {
  name: string;
  source_module: string;
  description: string;
  fields: KpiSpecField[];
  /** Fields that can be measured. */
  numeric_fields: string[];
  /** Fields a breakdown can be keyed by, or a group labelled with. */
  groupable_fields: string[];
  /**
   * Id field -> the field that names it.
   *
   * Grouping by an id gives a breakdown keyed by identifiers, and the
   * server fills the label in from this map when the spec leaves it out.
   * The form reads the same map so what it shows is what will be stored.
   */
  display_name_for: Record<string, string>;
  /**
   * JSON columns a `<column>.<key>` path may be built on.
   *
   * There is no finite list of paths to offer - the keys live in the data,
   * because these columns hold classification schemes - so the picker offers
   * the column and prompts for the key.
   */
  json_path_fields: KpiSpecJsonPathField[];
  /**
   * Whether one row of this entity belongs to exactly one estimate.
   *
   * False for `project`, whose one row per building is what makes its floor
   * area worth measuring, and for `cost_item_usage`, whose ledger records
   * which project a rate was applied to and not which bill. Offering
   * estimate scope on those would be offering the project's number under an
   * estimate's label.
   */
  narrows_to_estimate: boolean;
}

/**
 * The whole vocabulary a spec may be written in, served by the backend.
 *
 * The form is built from this rather than from a copy kept here: the
 * whitelist is the server's to define, and a picker offering a field the
 * server has since dropped would only be refused on submit.
 */
export interface KpiSpecCatalog {
  entities: KpiSpecEntity[];
  aggregations: string[];
  filter_operators: string[];
  max_breakdown_groups: number;
}

export interface KpiSpecFilter {
  field: string;
  op: string;
  /** `is_null` / `not_null` carry none; `in` carries a list. */
  value?: unknown;
}

export interface KpiSpec {
  entity: string;
  aggregation: string;
  /** Every aggregation but `count` needs a numeric field. */
  field?: string;
  /** `weighted_avg` only. */
  weight_field?: string;
  denominator_field?: string;
  /** Keys the breakdown. */
  group_by?: string;
  /** Names each group of the breakdown, so ids read as words. */
  label_field?: string;
  filters?: KpiSpecFilter[];
}

export interface CreateKpiPayload {
  code: string;
  name: string;
  description?: string;
  unit?: string;
  target_default?: number | string | null;
  /** How stored values roll up over time - not what the KPI measures. */
  aggregation?: string;
  category?: KpiCategory;
  project_id?: string | null;
  /**
   * Defaults to `project`. `estimate` is refused at creation when the spec's
   * entity has no estimate of its own, rather than accepted and found
   * unanswerable once it is on a dashboard.
   */
  scope?: KpiScope;
  spec: KpiSpec;
}

export function getKpiSpecCatalog(): Promise<KpiSpecCatalog> {
  return apiGet<KpiSpecCatalog>(`${BASE}/kpis/spec-catalog`);
}

/**
 * Register a custom KPI.
 *
 * A 422 carries `{path, value, allowed, message}` naming the part of the
 * spec that was refused; `getErrorMessage` surfaces the message, which
 * already starts with that path.
 */
export function createKpi(payload: CreateKpiPayload): Promise<KpiDefinition> {
  return apiPost<KpiDefinition>(`${BASE}/kpis`, payload);
}

/** Delete a custom KPI. Refused with 409 while anything still reads it. */
export function deleteKpi(code: string): Promise<void> {
  return apiDelete<void>(`${BASE}/kpis/${encodeURIComponent(code)}`);
}

/* ── Dashboards ───────────────────────────────────────────────────────── */

export interface StarterPackResult {
  kpi_definitions: number;
  dashboards: number;
  reports: number;
  schedules: number;
  alerts: number;
  kpi_history_rows: number;
}

/** Idempotent fresh-install bootstrap. Materialises 5 role-based
 *  dashboards + their widgets + system KPIs + reports + schedules +
 *  alert rules so a brand-new tenant sees actual charts on /bi-dashboards
 *  instead of an empty grid. Re-running is safe — only missing rows are
 *  inserted. v3.12.1 / Wave 1. */
export function installStarterPack(): Promise<StarterPackResult> {
  return apiPost<StarterPackResult>(`${BASE}/install-starter-pack`, {});
}

/** List dashboards; `projectId` scopes to that project plus company-wide. */
export function listDashboards(projectId?: string): Promise<Dashboard[]> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return apiGet<Dashboard[]>(`${BASE}/dashboards${qs}`);
}

export function createDashboard(data: CreateDashboardPayload): Promise<Dashboard> {
  return apiPost<Dashboard>(`${BASE}/dashboards`, data);
}

export function updateDashboard(
  id: string,
  data: Partial<CreateDashboardPayload>,
): Promise<Dashboard> {
  return apiPatch<Dashboard>(`${BASE}/dashboards/${id}`, data);
}

export function deleteDashboard(id: string): Promise<void> {
  return apiDelete(`${BASE}/dashboards/${id}`);
}

export function renderDashboard(id: string): Promise<DashboardRenderResponse> {
  return apiGet<DashboardRenderResponse>(`${BASE}/dashboards/${id}/render`);
}

/**
 * Cross-filter evaluate (Wave 4 / T11).
 *
 * Re-evaluates every widget on the dashboard against the supplied filter
 * dict. When the dashboard's ``cross_filter_enabled`` flag is false the
 * filters are dropped server-side and each widget returns its static
 * aggregate — safe to call either way.
 */
export function evaluateDashboard(
  id: string,
  filters: Record<string, unknown> = {},
): Promise<DashboardEvaluateResponse> {
  return apiPost<DashboardEvaluateResponse>(
    `${BASE}/dashboards/${id}/evaluate`,
    { filters },
  );
}

/* ── Widgets ──────────────────────────────────────────────────────────── */

export interface CreateWidgetPayload {
  dashboard_id: string;
  widget_type?: WidgetType;
  kpi_code?: string | null;
  config_json?: Record<string, unknown>;
  position_x?: number;
  position_y?: number;
  width?: number;
  height?: number;
  order_seq?: number;
  drill_path?: DrillPath | null;
}

export function createWidget(data: CreateWidgetPayload): Promise<WidgetRead> {
  return apiPost<WidgetRead>(`${BASE}/widgets`, data);
}

export function deleteWidget(id: string): Promise<void> {
  return apiDelete(`${BASE}/widgets/${id}`);
}

/* ── Reports ──────────────────────────────────────────────────────────── */

/** List reports; `projectId` scopes to that project plus company-wide. */
export function listReports(projectId?: string): Promise<ReportDefinition[]> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return apiGet<ReportDefinition[]>(`${BASE}/reports${qs}`);
}

export function createReport(data: CreateReportPayload): Promise<ReportDefinition> {
  return apiPost<ReportDefinition>(`${BASE}/reports`, data);
}

export function runReport(id: string): Promise<ReportRunResponse> {
  return apiPost<ReportRunResponse>(`${BASE}/reports/${id}/run`, {});
}

/* ── Schedules ────────────────────────────────────────────────────────── */

/** List schedules; `projectId` scopes to that project plus company-wide. */
export function listSchedules(projectId?: string): Promise<ReportSchedule[]> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return apiGet<ReportSchedule[]>(`${BASE}/report-schedules${qs}`);
}

export function createSchedule(data: {
  report_definition_id: string;
  frequency: ReportFrequency;
  time_of_day?: string;
  timezone?: string;
  enabled?: boolean;
  project_id?: string | null;
}): Promise<ReportSchedule> {
  return apiPost<ReportSchedule>(`${BASE}/report-schedules`, data);
}

export function updateSchedule(
  id: string,
  data: Partial<{ enabled: boolean; frequency: ReportFrequency }>,
): Promise<ReportSchedule> {
  return apiPatch<ReportSchedule>(`${BASE}/report-schedules/${id}`, data);
}

export function runScheduleNow(id: string): Promise<ReportRunResponse> {
  return apiPost<ReportRunResponse>(`${BASE}/report-schedules/${id}/run-now`, {});
}

/* ── Alerts ───────────────────────────────────────────────────────────── */

export function listAlerts(): Promise<AlertRule[]> {
  return apiGet<AlertRule[]>(`${BASE}/alerts`);
}

export function createAlert(data: CreateAlertPayload): Promise<AlertRule> {
  return apiPost<AlertRule>(`${BASE}/alerts`, data);
}

export function toggleAlert(id: string, enabled: boolean): Promise<AlertRule> {
  return apiPatch<AlertRule>(
    `${BASE}/alerts/${id}/toggle?enabled=${enabled ? 'true' : 'false'}`,
    {},
  );
}

/** Run every enabled alert rule immediately. Returns the count that fired. */
export function evaluateAlertsNow(): Promise<{ fired: number }> {
  return apiPost<{ fired: number }>(`${BASE}/alerts/evaluate-now`, {});
}

/* ── Drill-down ───────────────────────────────────────────────────────── */

export function drillDownKpi(
  code: string,
  payload: {
    project_id?: string | null;
    period_start?: string | null;
    period_end?: string | null;
    filters?: Record<string, unknown>;
    depth?: number;
    limit?: number;
  },
): Promise<DrillDownResponse> {
  return apiPost<DrillDownResponse>(
    `${BASE}/kpis/${encodeURIComponent(code)}/drill-down`,
    payload,
  );
}

/* ── Saved filter sharing ─────────────────────────────────────────────── */

export interface SavedFilter {
  id: string;
  name: string;
  owner_user_id: string | null;
  scope: string;
  module: string;
  filter_json: Record<string, unknown>;
  is_default: boolean;
  shared_with_user_ids_json: string[];
  /** Null means the filter is company-wide and shows on every project. */
  project_id: string | null;
  created_at: string;
}

/** List saved filters; `projectId` scopes to that project plus company-wide. */
export function listSavedFilters(
  module?: string,
  projectId?: string,
): Promise<SavedFilter[]> {
  const qs = new URLSearchParams();
  if (module) qs.set('module', module);
  if (projectId) qs.set('project_id', projectId);
  const q = qs.toString();
  return apiGet<SavedFilter[]>(`${BASE}/saved-filters${q ? `?${q}` : ''}`);
}

export function createSavedFilter(data: {
  name: string;
  module: string;
  scope?: string;
  filter_json?: Record<string, unknown>;
  is_default?: boolean;
  shared_with_user_ids?: string[];
  project_id?: string | null;
}): Promise<SavedFilter> {
  return apiPost<SavedFilter>(`${BASE}/saved-filters`, data);
}

export function shareSavedFilter(
  id: string,
  userIds: string[],
): Promise<SavedFilter> {
  return apiPost<SavedFilter>(`${BASE}/saved-filters/${id}/share`, {
    user_ids: userIds,
  });
}

/* ── Report file download ─────────────────────────────────────────────── */

export function reportRunDownloadUrl(runId: string): string {
  return `/api/v1/bi-dashboards/report-runs/${runId}/file`;
}

/* ── Widget export ────────────────────────────────────────────────────── */

export function widgetExportUrl(
  widgetId: string,
  format: 'csv' | 'svg' = 'csv',
): string {
  return `/api/v1/bi-dashboards/widgets/${widgetId}/export?format=${format}`;
}

/**
 * Fetch an authenticated file path and hand the resulting blob to the
 * browser's download flow. The BI download/export endpoints are gated by
 * a JWT Bearer header, so a bare ``<a href>`` would 401 — we must fetch
 * with the auth header and stream the body into a blob. ``fallbackName``
 * is used when the server doesn't send a Content-Disposition filename.
 */
async function downloadAuthedFile(
  url: string,
  fallbackName: string,
): Promise<void> {
  const token = getAuthToken();
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) {
    throw new Error(`Download failed (${res.status})`);
  }
  // Prefer the server-provided filename when present.
  let filename = fallbackName;
  const disp = res.headers.get('Content-Disposition');
  if (disp) {
    const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disp);
    if (match?.[1]) filename = decodeURIComponent(match[1]);
  }
  const blob = await res.blob();
  triggerDownload(blob, filename);
}

/** Download the rendered report file for a completed run. */
export function downloadReportRun(
  runId: string,
  fallbackName = 'report',
): Promise<void> {
  return downloadAuthedFile(reportRunDownloadUrl(runId), fallbackName);
}

/** Download a widget's data/chart export (CSV or SVG). */
export function downloadWidgetExport(
  widgetId: string,
  format: 'csv' | 'svg' = 'csv',
): Promise<void> {
  return downloadAuthedFile(
    widgetExportUrl(widgetId, format),
    `widget-${widgetId}.${format}`,
  );
}
