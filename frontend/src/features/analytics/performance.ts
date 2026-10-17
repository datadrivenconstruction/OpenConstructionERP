// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cross-project performance benchmark: API, types and the pure helpers the
// Performance tab renders with. Backed by
// POST /api/v1/bi-dashboards/performance/benchmark, see
// backend/app/modules/bi_dashboards/performance.py for the semantics. The two
// that matter on screen: a value can be null (unavailable, with a reason) and
// must never be drawn as 0, and each unit or currency is its own group.

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type Decimalish = string | number | null;

export interface PerformancePreset {
  key: string;
  spec: Record<string, unknown>;
}

export interface PerformanceProjectRow {
  project_id: string;
  value: Decimalish;
  numerator: Decimalish;
  denominator: Decimalish;
  records: number;
  unavailable_reason: string | null;
  /** Units this project's rows were converted from to land in the group. */
  converted_from?: string[];
}

export interface PerformanceBenchmarkFigures {
  weighted: Decimalish;
  weighted_unavailable_reason: string | null;
  /** Arithmetic mean of the per-project values: every project counts once. */
  mean?: Decimalish;
  median: Decimalish;
  p25: Decimalish;
  p75: Decimalish;
  min: Decimalish;
  max: Decimalish;
}

/** `1 from_unit = factor to_unit`, applied to land rows in a group. */
export interface PerformanceConversion {
  from_unit: string;
  to_unit: string;
  factor: Decimalish;
}

export type BenchmarkStatistic = 'weighted' | 'mean' | 'median';

export interface PerformanceGroup {
  key: string;
  dimensions: Record<string, string | null>;
  rows: PerformanceProjectRow[];
  benchmark: PerformanceBenchmarkFigures;
  evidence: { projects_with_data: number; projects_with_value: number; records: number; records_with_value?: number };
  coverage: Decimalish;
  conversions?: PerformanceConversion[];
  /** The figure the group leads with, and which statistic it actually is. */
  headline?: Decimalish;
  headline_statistic?: BenchmarkStatistic;
  /** False when the group misses the minimum projects or records. */
  sufficient?: boolean;
  shortfall?: string[];
}

export interface PerformanceProjectLabel {
  project_id: string;
  name: string;
  currency: string;
}

export interface PerformanceBenchmarkResponse {
  kpi: string | null;
  spec: Record<string, unknown>;
  aggregation: string;
  projects_selected: number;
  projects: PerformanceProjectLabel[];
  groups: PerformanceGroup[];
}

export interface KpiRowFilter {
  field: string;
  op: string;
  value: string | number | string[] | null;
}

/** Which projects and rows a benchmark reads. Every list narrows. */
export interface BenchmarkCohort {
  project_ids: string[];
  clients: string[];
  regions: string[];
  project_types: string[];
  row_filters: KpiRowFilter[];
  period_start: string | null;
  period_end: string | null;
}

export interface BenchmarkReadingOptions {
  convert_units: boolean;
  min_projects: number;
  min_records: number;
  statistic: BenchmarkStatistic;
}

export interface PerformanceBenchmarkRequest extends BenchmarkCohort, BenchmarkReadingOptions {
  kpi: string;
}

export interface PerformanceCohortOptions {
  clients: string[];
  regions: string[];
  project_types: string[];
}

export interface BenchmarkSet extends BenchmarkReadingOptions {
  id: string;
  name: string;
  description: string;
  owner_user_id: string | null;
  scope: 'personal' | 'shared';
  kpis: string[];
  cohort: BenchmarkCohort;
  is_owner: boolean;
  created_at: string;
  updated_at: string;
}

export interface BenchmarkSetPage {
  items: BenchmarkSet[];
  total: number;
  offset: number;
  limit: number;
}

export interface BenchmarkSetWrite extends BenchmarkReadingOptions {
  name: string;
  description?: string;
  scope: 'personal' | 'shared';
  kpis: string[];
  cohort: BenchmarkCohort;
}

export interface PerformanceCheckRequest extends PerformanceBenchmarkRequest {
  value: string;
  unit: string | null;
  currency: string | null;
}

export interface PerformanceCheckResponse {
  kpi: string;
  status: string;
  input_value: Decimalish;
  input_unit: string | null;
  input_currency: string | null;
  value: Decimalish;
  unit_factor: Decimalish;
  group: PerformanceGroup | null;
  headline: Decimalish;
  statistic: BenchmarkStatistic | null;
  variance: Decimalish;
  percentile_rank: Decimalish;
  band: RangeBand | null;
  confidence: 'low' | 'medium' | 'high' | null;
  shortfall: string[];
}

export const EMPTY_COHORT: BenchmarkCohort = {
  project_ids: [],
  clients: [],
  regions: [],
  project_types: [],
  row_filters: [],
  period_start: null,
  period_end: null,
};

export const DEFAULT_READING: BenchmarkReadingOptions = {
  convert_units: true,
  min_projects: 3,
  min_records: 0,
  statistic: 'weighted',
};

export function fetchPerformancePresets(): Promise<PerformancePreset[]> {
  return apiGet<PerformancePreset[]>('/v1/bi-dashboards/performance/presets');
}

export function fetchPerformanceBenchmark(
  body: PerformanceBenchmarkRequest,
): Promise<PerformanceBenchmarkResponse> {
  return apiPost<PerformanceBenchmarkResponse, PerformanceBenchmarkRequest>('/v1/bi-dashboards/performance/benchmark', body);
}

export function fetchCohortOptions(): Promise<PerformanceCohortOptions> {
  return apiGet<PerformanceCohortOptions>('/v1/bi-dashboards/performance/cohort-options');
}

export function fetchBenchmarkSets(): Promise<BenchmarkSetPage> {
  return apiGet<BenchmarkSetPage>('/v1/bi-dashboards/performance/benchmark-sets?limit=500');
}

export function createBenchmarkSet(body: BenchmarkSetWrite): Promise<BenchmarkSet> {
  return apiPost<BenchmarkSet, BenchmarkSetWrite>('/v1/bi-dashboards/performance/benchmark-sets', body);
}

export function updateBenchmarkSet(id: string, body: Partial<BenchmarkSetWrite>): Promise<BenchmarkSet> {
  return apiPatch<BenchmarkSet, Partial<BenchmarkSetWrite>>(
    `/v1/bi-dashboards/performance/benchmark-sets/${encodeURIComponent(id)}`,
    body,
  );
}

export function deleteBenchmarkSet(id: string): Promise<void> {
  return apiDelete(`/v1/bi-dashboards/performance/benchmark-sets/${encodeURIComponent(id)}`);
}

export function checkAgainstCohort(body: PerformanceCheckRequest): Promise<PerformanceCheckResponse> {
  return apiPost<PerformanceCheckResponse, PerformanceCheckRequest>('/v1/bi-dashboards/performance/check', body);
}

/* ── Pure helpers ─────────────────────────────────────────────────────── */

/** The server's key for "this group had no value", see kpi_spec.NULL_GROUP_KEY. */
export const NULL_GROUP_KEY = '__null__';

/** A Decimal string as a number, or null when there is no value. Never 0 for absent. */
export function toNumber(value: Decimalish | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export type RangeBand = 'below' | 'within' | 'above';

/** Where one project's value sits against the cohort's P25-P75 range. */
export function rangeBand(
  value: Decimalish | undefined,
  p25: Decimalish | undefined,
  p75: Decimalish | undefined,
): RangeBand | null {
  const v = toNumber(value);
  const lo = toNumber(p25);
  const hi = toNumber(p75);
  if (v === null || lo === null || hi === null) return null;
  if (v < lo) return 'below';
  if (v > hi) return 'above';
  return 'within';
}

/** One table row per selected project; a project with no reading is a row too. */
export interface PerformanceTableRow {
  projectId: string;
  name: string;
  row: PerformanceProjectRow | null;
}

export function tableRows(
  group: PerformanceGroup,
  projects: PerformanceProjectLabel[],
): PerformanceTableRow[] {
  const byId = new Map(group.rows.map((r) => [r.project_id, r]));
  return projects.map((p) => ({ projectId: p.project_id, name: p.name, row: byId.get(p.project_id) ?? null }));
}

type CsvCell = string | number | null | undefined;

/** RFC 4180 quoting, plus a leading quote on a cell a spreadsheet would run as a formula. */
export function csvCell(value: CsvCell): string {
  let s = value == null ? '' : String(value);
  if (/^[=+\-@\t\r]/.test(s) && !/^-?\d/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export interface PerformanceCsvLabels {
  group: string;
  project: string;
  value: string;
  numerator: string;
  denominator: string;
  records: string;
  status: string;
  weighted: string;
  median: string;
  p25: string;
  p75: string;
  /** Text for a reading with no value, given its reason code. */
  unavailable: (reason: string | null) => string;
  /** Text for a group key. */
  groupLabel: (group: PerformanceGroup) => string;
}

/**
 * The benchmark as CSV: one line per group and selected project, with the
 * cohort figures repeated on every line so a filtered spreadsheet keeps them.
 * Values are written as the server sent them, with a dot decimal, so a
 * spreadsheet reads them as numbers in any locale it is opened in.
 */
export function buildPerformanceCsv(
  data: PerformanceBenchmarkResponse,
  labels: PerformanceCsvLabels,
): string {
  const header = [
    labels.group,
    labels.project,
    labels.value,
    labels.numerator,
    labels.denominator,
    labels.records,
    labels.status,
    labels.weighted,
    labels.median,
    labels.p25,
    labels.p75,
  ];
  const lines = [header.map(csvCell).join(',')];
  for (const group of data.groups) {
    for (const { name, row } of tableRows(group, data.projects)) {
      const value = toNumber(row?.value);
      lines.push(
        [
          labels.groupLabel(group),
          name,
          value === null ? '' : String(row?.value),
          row?.numerator ?? '',
          row?.denominator ?? '',
          row?.records ?? 0,
          value === null ? labels.unavailable(row?.unavailable_reason ?? 'no_data') : '',
          group.benchmark.weighted ?? '',
          group.benchmark.median ?? '',
          group.benchmark.p25 ?? '',
          group.benchmark.p75 ?? '',
        ]
          .map(csvCell)
          .join(','),
      );
    }
  }
  return lines.join('\r\n');
}

/** The KPI a set or a screen reads, kept to what the set offers. */
export function pickKpi(current: string, offered: string[]): string {
  return offered.includes(current) ? current : (offered[0] ?? current);
}

/**
 * The classification filter a cohort carries, as the `{key, code}` pair the
 * screen edits: only the first `classification.<key> eq <code>` filter is
 * read, because that is the only shape the screen writes.
 */
export function classificationFilter(cohort: BenchmarkCohort): { key: string; code: string } {
  for (const f of cohort.row_filters) {
    if (f.op === 'eq' && f.field.startsWith('classification.') && typeof f.value === 'string') {
      return { key: f.field.slice('classification.'.length), code: f.value };
    }
  }
  return { key: '', code: '' };
}

/** The row filters for a classification key and code; none when either is blank. */
export function classificationRowFilters(key: string, code: string): KpiRowFilter[] {
  const k = key.trim();
  const c = code.trim();
  if (!k || !c) return [];
  return [{ field: `classification.${k}`, op: 'eq', value: c }];
}

/** How many cohort filters beyond the project list are active, for the "More filters" badge. */
export function activeFilterCount(cohort: BenchmarkCohort): number {
  return (
    (cohort.clients.length ? 1 : 0) +
    (cohort.regions.length ? 1 : 0) +
    (cohort.project_types.length ? 1 : 0) +
    (cohort.row_filters.length ? 1 : 0) +
    (cohort.period_start || cohort.period_end ? 1 : 0)
  );
}

/** Save CSV text as a file: the Blob + object-URL download the analytics page uses. */
export function downloadCsv(csv: string, filename: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
