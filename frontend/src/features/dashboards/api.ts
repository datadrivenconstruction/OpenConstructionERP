/**
 * API helpers for the Dashboards module (T01: snapshots).
 *
 * Backend endpoints (mounted at /api/v1/dashboards by the module loader):
 *   POST   /v1/dashboards/projects/{project_id}/snapshots   — multipart upload
 *   GET    /v1/dashboards/projects/{project_id}/snapshots   — list
 *   GET    /v1/dashboards/snapshots/{snapshot_id}            — detail
 *   DELETE /v1/dashboards/snapshots/{snapshot_id}            — remove
 *   GET    /v1/dashboards/snapshots/{snapshot_id}/manifest   — manifest.json
 */

import { apiGet, apiDelete, apiPatch, apiPost } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ──────────────────────────────────────────────────────────────── */

export interface SnapshotSourceFile {
  id: string;
  original_name: string;
  format: string;
  discipline: string | null;
  entity_count: number;
  bytes_size: number;
  converter_notes: Record<string, unknown>;
}

export interface SnapshotSummary {
  id: string;
  project_id: string;
  label: string;
  total_entities: number;
  total_categories: number;
  summary_stats: Record<string, number>;
  created_by_user_id: string;
  created_at: string;
}

export interface Snapshot extends SnapshotSummary {
  parquet_dir: string;
  parent_snapshot_id: string | null;
  source_files: SnapshotSourceFile[];
}

export interface SnapshotListResponse {
  total: number;
  items: SnapshotSummary[];
}

export interface SnapshotManifest {
  label: string;
  total_entities: number;
  total_categories: number;
  summary_stats: Record<string, number>;
  source_files: Array<Record<string, unknown>>;
  created_by_user_id: string;
  created_at: string;
}

export interface SnapshotError {
  message_key: string;
  message: string;
  details?: Record<string, unknown>;
}

/* ── Queries ────────────────────────────────────────────────────────────── */

export async function listSnapshots(
  projectId: string,
  opts?: { limit?: number; offset?: number },
): Promise<SnapshotListResponse> {
  const params = new URLSearchParams({
    limit: String(opts?.limit ?? 100),
    offset: String(opts?.offset ?? 0),
  });
  return apiGet<SnapshotListResponse>(
    `/v1/dashboards/projects/${encodeURIComponent(projectId)}/snapshots?${params.toString()}`,
  );
}

export async function getSnapshot(snapshotId: string): Promise<Snapshot> {
  return apiGet<Snapshot>(
    `/v1/dashboards/snapshots/${encodeURIComponent(snapshotId)}`,
  );
}

export async function getSnapshotManifest(
  snapshotId: string,
): Promise<SnapshotManifest> {
  return apiGet<SnapshotManifest>(
    `/v1/dashboards/snapshots/${encodeURIComponent(snapshotId)}/manifest`,
  );
}

/* ── Mutations ──────────────────────────────────────────────────────────── */

export interface CreateSnapshotInput {
  projectId: string;
  label: string;
  files: File[];
  disciplines?: Array<string | null>;
  parentSnapshotId?: string | null;
}

/**
 * Create a snapshot from uploaded CAD/BIM files.
 *
 * Uses a raw fetch (not apiPost) because the backend expects a multipart
 * body — apiPost serialises JSON. 413/422/409 responses come back as
 * a SnapshotError envelope; we re-throw with the structured message so
 * callers can key on `message_key`.
 */
export async function createSnapshot(input: CreateSnapshotInput): Promise<Snapshot> {
  const formData = new FormData();
  formData.append('label', input.label);
  for (const file of input.files) {
    formData.append('files', file, file.name);
  }
  if (input.disciplines) {
    for (const disc of input.disciplines) {
      formData.append('disciplines', disc ?? '');
    }
  }
  if (input.parentSnapshotId) {
    formData.append('parent_snapshot_id', input.parentSnapshotId);
  }

  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'X-DDC-Client': 'OE/1.0',
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const resp = await fetch(
    `/api/v1/dashboards/projects/${encodeURIComponent(input.projectId)}/snapshots?locale=en`,
    { method: 'POST', headers, body: formData },
  );

  if (!resp.ok) {
    let err: SnapshotError = {
      message_key: 'snapshot.unknown',
      message: `Snapshot upload failed (HTTP ${resp.status})`,
    };
    try {
      const body = await resp.json();
      if (typeof body?.message_key === 'string') {
        err = body as SnapshotError;
      } else if (typeof body?.detail === 'string') {
        err.message = body.detail;
      }
    } catch {
      // fall through with default
    }
    const thrown = new Error(err.message) as Error & { snapshotError: SnapshotError };
    thrown.snapshotError = err;
    throw thrown;
  }

  return resp.json();
}

export async function deleteSnapshot(snapshotId: string): Promise<void> {
  await apiDelete(`/v1/dashboards/snapshots/${encodeURIComponent(snapshotId)}`);
}

/* ── Quick-Insight Panel (T02) ──────────────────────────────────────────── */

export type QuickInsightChartType =
  | 'histogram'
  | 'bar'
  | 'line'
  | 'scatter'
  | 'donut';

export interface QuickInsightChart {
  chart_type: QuickInsightChartType;
  title: string;
  data: Array<Record<string, unknown>>;
  x_field: string;
  y_field: string;
  agg_fn: 'mean' | 'count' | null;
  interestingness: number;
  metadata: Record<string, unknown>;
}

export interface QuickInsightsResponse {
  snapshot_id: string;
  charts: QuickInsightChart[];
  total_candidates: number;
}

/**
 * Auto-generated charts for a snapshot. The backend picks chart types
 * (histogram / bar / line / scatter / donut) using rule-based
 * heuristics — caller does not select columns.
 */
export async function getQuickInsights(
  snapshotId: string,
  opts?: { limit?: number },
): Promise<QuickInsightsResponse> {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  const qs = params.toString();
  return apiGet<QuickInsightsResponse>(
    `/v1/dashboards/snapshots/${encodeURIComponent(snapshotId)}/quick-insights${
      qs ? `?${qs}` : ''
    }`,
  );
}

/* ── Smart Value Autocomplete (T03) ─────────────────────────────────────── */

export interface SmartValue {
  value: string;
  count: number;
  score: number;
}

export interface SmartValuesResponse {
  snapshot_id: string;
  column: string;
  query: string;
  items: SmartValue[];
}

/**
 * Distinct-value autocomplete for a snapshot column. Empty `query`
 * returns the top-N values by frequency.
 */
export async function getSmartValues(
  snapshotId: string,
  column: string,
  opts?: { query?: string; limit?: number },
): Promise<SmartValuesResponse> {
  const params = new URLSearchParams({ column });
  if (opts?.query) params.set('q', opts.query);
  if (opts?.limit) params.set('limit', String(opts.limit));
  return apiGet<SmartValuesResponse>(
    `/v1/dashboards/snapshots/${encodeURIComponent(snapshotId)}/values?${params.toString()}`,
  );
}

/* ── Cascade Filter Engine (T04) ────────────────────────────────────────── */

export interface CascadeValue {
  value: string;
  count: number;
}

export interface CascadeValuesRequest {
  /** Column → allowed values. Empty arrays are dropped server-side. */
  selected: Record<string, string[]>;
  target_column: string;
  q?: string;
  limit?: number;
}

export interface CascadeValuesResponse {
  snapshot_id: string;
  target_column: string;
  q: string;
  values: CascadeValue[];
}

export interface CascadeRowCountResponse {
  snapshot_id: string;
  matched: number;
  total: number;
}

/**
 * Distinct-values cascade. Pass the *other* filters' selections in
 * `selected`; the response is the set of values for `target_column`
 * whose row-set is consistent with those constraints.
 *
 * The endpoint is POST (not GET) because the request body can be
 * arbitrarily large — multi-select chips on multiple columns blow past
 * any reasonable URL length.
 */
export async function getCascadeValues(
  snapshotId: string,
  body: CascadeValuesRequest,
): Promise<CascadeValuesResponse> {
  const payload: CascadeValuesRequest = {
    selected: body.selected ?? {},
    target_column: body.target_column,
    q: body.q ?? '',
    limit: body.limit ?? 50,
  };
  return apiPost<CascadeValuesResponse, CascadeValuesRequest>(
    `/v1/dashboards/snapshots/${encodeURIComponent(snapshotId)}/cascade-values`,
    payload,
  );
}

/**
 * Live "X of Y rows match" counter for the cascade panel header.
 *
 * The selection is JSON-serialised into a single `selected` query
 * param — keeps the GET request flat and cacheable. The backend
 * decodes it before validating column names.
 */
export async function getCascadeRowCount(
  snapshotId: string,
  selected: Record<string, string[]>,
): Promise<CascadeRowCountResponse> {
  const params = new URLSearchParams({ selected: JSON.stringify(selected ?? {}) });
  return apiGet<CascadeRowCountResponse>(
    `/v1/dashboards/snapshots/${encodeURIComponent(snapshotId)}/row-count?${params.toString()}`,
  );
}

/* ── Dashboard Presets & Collections (T05) ───────────────────────────────── */

export type DashboardPresetKind = 'preset' | 'collection';

export interface DashboardPreset {
  id: string;
  tenant_id: string | null;
  project_id: string | null;
  owner_id: string;
  name: string;
  description: string | null;
  kind: DashboardPresetKind;
  config_json: Record<string, unknown>;
  shared_with_project: boolean;
  created_at: string;
  updated_at: string;
}

export interface DashboardPresetListResponse {
  total: number;
  items: DashboardPreset[];
}

export interface CreateDashboardPresetInput {
  name: string;
  description?: string | null;
  kind?: DashboardPresetKind;
  project_id?: string | null;
  config_json?: Record<string, unknown>;
  shared_with_project?: boolean;
}

export interface UpdateDashboardPresetInput {
  name?: string;
  description?: string | null;
  kind?: DashboardPresetKind;
  config_json?: Record<string, unknown>;
  shared_with_project?: boolean;
}

export async function listDashboardPresets(opts?: {
  projectId?: string | null;
  kind?: DashboardPresetKind;
  limit?: number;
  offset?: number;
}): Promise<DashboardPresetListResponse> {
  const params = new URLSearchParams();
  if (opts?.projectId) params.set('project_id', opts.projectId);
  if (opts?.kind) params.set('kind', opts.kind);
  if (opts?.limit) params.set('limit', String(opts.limit));
  if (opts?.offset) params.set('offset', String(opts.offset));
  const qs = params.toString();
  return apiGet<DashboardPresetListResponse>(
    `/v1/dashboards/presets${qs ? `?${qs}` : ''}`,
  );
}

export async function getDashboardPreset(
  presetId: string,
): Promise<DashboardPreset> {
  return apiGet<DashboardPreset>(
    `/v1/dashboards/presets/${encodeURIComponent(presetId)}`,
  );
}

export async function createDashboardPreset(
  input: CreateDashboardPresetInput,
): Promise<DashboardPreset> {
  return apiPost<DashboardPreset, CreateDashboardPresetInput>(
    `/v1/dashboards/presets`,
    input,
  );
}

export async function updateDashboardPreset(
  presetId: string,
  input: UpdateDashboardPresetInput,
): Promise<DashboardPreset> {
  return apiPatch<DashboardPreset, UpdateDashboardPresetInput>(
    `/v1/dashboards/presets/${encodeURIComponent(presetId)}`,
    input,
  );
}

export async function deleteDashboardPreset(presetId: string): Promise<void> {
  await apiDelete(`/v1/dashboards/presets/${encodeURIComponent(presetId)}`);
}

export async function shareDashboardPreset(
  presetId: string,
): Promise<DashboardPreset> {
  return apiPost<DashboardPreset, undefined>(
    `/v1/dashboards/presets/${encodeURIComponent(presetId)}/share`,
  );
}

/* ── Tabular Data I/O (T06) ──────────────────────────────────────────────── */

export interface SnapshotRowsResponse {
  snapshot_id: string;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  total: number;
  limit: number;
  offset: number;
}

export type ExportFormat = 'csv' | 'xlsx' | 'parquet';

export interface SnapshotRowsQuery {
  columns?: string[];
  filters?: Record<string, string[]>;
  orderBy?: string; // "col:asc" | "col:desc"
  limit?: number;
  offset?: number;
}

function _rowsQueryParams(opts?: SnapshotRowsQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (opts?.columns && opts.columns.length > 0) {
    params.set('columns', opts.columns.join(','));
  }
  if (opts?.filters && Object.keys(opts.filters).length > 0) {
    params.set('filters', JSON.stringify(opts.filters));
  }
  if (opts?.orderBy) params.set('order_by', opts.orderBy);
  if (opts?.limit !== undefined) params.set('limit', String(opts.limit));
  if (opts?.offset !== undefined) params.set('offset', String(opts.offset));
  return params;
}

export async function getSnapshotRows(
  snapshotId: string,
  opts?: SnapshotRowsQuery,
): Promise<SnapshotRowsResponse> {
  const params = _rowsQueryParams(opts);
  const qs = params.toString();
  return apiGet<SnapshotRowsResponse>(
    `/v1/dashboards/snapshots/${encodeURIComponent(snapshotId)}/rows${
      qs ? `?${qs}` : ''
    }`,
  );
}

/**
 * Trigger a download of the snapshot in the requested tabular format.
 * Resolves to the URL we navigated to (handy for tests).
 */
export function buildSnapshotExportUrl(
  snapshotId: string,
  format: ExportFormat,
  opts?: SnapshotRowsQuery,
): string {
  const params = _rowsQueryParams(opts);
  params.set('format', format);
  return `/api/v1/dashboards/snapshots/${encodeURIComponent(
    snapshotId,
  )}/export?${params.toString()}`;
}

/* ── Dataset Integrity Overview (T07) ────────────────────────────────────── */

export type IntegrityIssueCode =
  | 'all_null'
  | 'high_null_pct'
  | 'constant'
  | 'dtype_mismatch'
  | 'outliers_present'
  | 'high_zero_pct'
  | 'low_cardinality_string'
  | 'uuid_like';

export type IntegrityInferredType =
  | 'numeric'
  | 'datetime'
  | 'boolean'
  | 'string'
  | 'empty';

export interface IntegritySampleValue {
  value: string;
  count: number;
}

export interface IntegrityColumn {
  name: string;
  dtype: string;
  inferred_type: IntegrityInferredType;
  row_count: number;
  null_count: number;
  null_pct: number;
  unique_count: number;
  completeness: number;
  sample_values: IntegritySampleValue[];
  zero_pct: number | null;
  outlier_count: number | null;
  min_value: number | null;
  max_value: number | null;
  mean_value: number | null;
  issues: IntegrityIssueCode[];
}

export interface IntegrityReport {
  snapshot_id: string;
  project_id: string;
  row_count: number;
  column_count: number;
  completeness_score: number;
  schema_hash: string;
  columns: IntegrityColumn[];
  issue_summary: Record<string, number>;
}

export interface GetIntegrityReportInput {
  snapshotId: string;
  projectId: string;
}

/**
 * Fetch the dataset-integrity report for a snapshot.
 *
 * The endpoint is POST (not GET) because the body carries both the
 * snapshot id and the project id — the server cross-checks them so a
 * caller can't request integrity for a snapshot in a project they
 * don't own.
 */
export async function getIntegrityReport(
  input: GetIntegrityReportInput,
): Promise<IntegrityReport> {
  return apiPost<IntegrityReport, { snapshot_id: string; project_id: string }>(
    `/v1/dashboards/integrity-report`,
    {
      snapshot_id: input.snapshotId,
      project_id: input.projectId,
    },
  );
}
