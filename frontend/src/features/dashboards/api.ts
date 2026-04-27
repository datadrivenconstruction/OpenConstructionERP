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
  /** T09: 'synced' | 'stale' | 'needs_review'. Defaults to 'synced'. */
  sync_status?: 'synced' | 'stale' | 'needs_review';
  /** T09: ISO timestamp of the last sync-check call, null if never run. */
  last_sync_check_at?: string | null;
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

/* ── Sync Protocol (T09 / task #192) ─────────────────────────────────────── */

export type SyncStatus = 'synced' | 'stale' | 'needs_review';
export type SyncIssueKind =
  | 'column_rename'
  | 'dropped_column'
  | 'dropped_filter_value'
  | 'dtype_change';
export type SyncSeverity = 'warning' | 'error';
export type SyncSuggestedFix = 'auto_rename' | 'drop_filter' | 'manual';

export interface SyncIssue {
  kind: SyncIssueKind;
  severity: SyncSeverity;
  suggested_fix: SyncSuggestedFix;
  column: string;
  new_column: string | null;
  dropped_values: string[];
  old_dtype: string | null;
  new_dtype: string | null;
  message_key: string;
  message: string;
}

export interface SyncReport {
  preset_id: string;
  snapshot_id: string | null;
  status: SyncStatus;
  is_in_sync: boolean;
  column_renames: SyncIssue[];
  dropped_columns: SyncIssue[];
  dropped_filter_values: SyncIssue[];
  dtype_changes: SyncIssue[];
}

export interface SyncHealResponse {
  preset: DashboardPreset;
  report: SyncReport;
}

/**
 * Run the probe against the preset's current snapshot meta. Returns a
 * structured report describing column renames / drops / dtype changes /
 * dropped filter values, plus a status the badge picks up.
 */
export async function getSyncReport(presetId: string): Promise<SyncReport> {
  return apiPost<SyncReport, undefined>(
    `/v1/dashboards/presets/${encodeURIComponent(presetId)}/sync-check`,
  );
}

/**
 * Apply every safe auto-fix from the latest sync report and persist
 * the patched preset. Manual issues are returned untouched in the
 * accompanying report so the UI can prompt the user.
 */
export async function applySyncHeal(
  presetId: string,
): Promise<SyncHealResponse> {
  return apiPost<SyncHealResponse, undefined>(
    `/v1/dashboards/presets/${encodeURIComponent(presetId)}/sync-heal`,
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

/* ── Historical Snapshot Navigator (T11) ─────────────────────────────────── */

export interface SnapshotTimelineItem {
  id: string;
  project_id: string;
  label: string;
  created_at: string;
  created_by_user_id: string;
  parent_snapshot_id: string | null;
  total_entities: number;
  total_categories: number;
  source_file_count: number;
  schema_hash: string | null;
  completeness_score: number | null;
}

export interface SnapshotTimelineResponse {
  project_id: string;
  items: SnapshotTimelineItem[];
  /** ISO timestamp the caller should pass back as `before` for the
   * next page; `null` when the current page exhausted history. */
  next_before: string | null;
}

export interface GetSnapshotTimelineInput {
  projectId: string;
  /** Defaults to 50 server-side. */
  limit?: number;
  /** ISO timestamp — only return rows created strictly before this. */
  before?: string | null;
}

/**
 * Newest-first timeline of snapshots for a project. Pagination is
 * cursor-based (`before` = the oldest `created_at` already on screen)
 * to avoid drift when teammates upload concurrently.
 */
export async function getSnapshotTimeline(
  input: GetSnapshotTimelineInput,
): Promise<SnapshotTimelineResponse> {
  const params = new URLSearchParams({ project_id: input.projectId });
  if (input.limit !== undefined) params.set('limit', String(input.limit));
  if (input.before) params.set('before', input.before);
  return apiGet<SnapshotTimelineResponse>(
    `/v1/dashboards/snapshots/timeline?${params.toString()}`,
  );
}

export interface SnapshotDiffColumnChange {
  name: string;
  a_dtype: string;
  b_dtype: string;
}

export interface SnapshotDiff {
  snapshot_a_id: string;
  snapshot_b_id: string;
  a_label: string;
  b_label: string;
  a_created_at: string;
  b_created_at: string;
  columns_added: string[];
  columns_removed: string[];
  columns_changed: SnapshotDiffColumnChange[];
  a_row_count: number;
  b_row_count: number;
  rows_added: number;
  rows_removed: number;
  schema_hash_match: boolean;
  is_identical: boolean;
}

export interface DiffSnapshotsInput {
  /** Older snapshot id (left-hand side of the diff). */
  a: string;
  /** Newer snapshot id (right-hand side of the diff). */
  b: string;
}

/**
 * Column-level diff between two snapshots. Both snapshots must belong
 * to the same project — the backend enforces this and returns a 422
 * otherwise.
 */
export async function diffSnapshots(
  input: DiffSnapshotsInput,
): Promise<SnapshotDiff> {
  const params = new URLSearchParams({ a: input.a, b: input.b });
  return apiGet<SnapshotDiff>(
    `/v1/dashboards/snapshots/diff?${params.toString()}`,
  );
}
