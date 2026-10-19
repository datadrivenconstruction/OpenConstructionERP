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
  /** (value - headline) / headline: +0.25 is 25 % above the group's leading figure. */
  variance?: Decimalish;
  /** Currencies restated into the reporting currency, with the original value and rate. */
  converted_from_currency?: string[];
  original_value?: Decimalish;
  original_currency?: string | null;
  fx_rate?: Decimalish;
  /** How a cost index moved this project's money: series, months, factor and the value before. */
  index_series?: string | null;
  index_base_periods?: string[];
  index_target_period?: string | null;
  index_factor?: Decimalish;
  /** Months the index series has no point for; they excluded the reading. */
  index_missing_periods?: string[];
  location_region?: string | null;
  location_factor?: Decimalish;
  unadjusted_value?: Decimalish;
}

/** The month and region historical money was brought to. `applicable` is false for a KPI without money. */
export interface PerformanceCostIndex {
  series_id: string | null;
  series_name: string | null;
  target_period: string | null;
  target_region: string | null;
  target_region_factor: Decimalish;
  applicable: boolean;
}

/** Opt-in: bring historical money to a reference month and region with the price index register. */
export interface CostIndexRequest {
  index_series_id?: string | null;
  /** YYYY-MM; the series' latest month when null. */
  index_target_period?: string | null;
  location_target_region?: string | null;
}

/** The cost index part of a request, to pass on to compare and drilldown unchanged. */
export function costIndexOf(request: CostIndexRequest): CostIndexRequest {
  return {
    index_series_id: request.index_series_id ?? null,
    index_target_period: request.index_target_period ?? null,
    location_target_region: request.location_target_region ?? null,
  };
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
  /** Only from ten projects with a value; null below that. */
  p10?: Decimalish;
  p90?: Decimalish;
  /** Sample standard deviation and coefficient of variation, from two projects. */
  stddev?: Decimalish;
  cv?: Decimalish;
}

/** One currency restated into the reporting currency: `1 from = rate to`. */
export interface PerformanceCurrencyConversion {
  from_currency: string;
  to_currency: string;
  rate: Decimalish;
  as_of: string | null;
  source: string;
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
  currency_conversions?: PerformanceCurrencyConversion[];
  /** Compound unit the values are in, such as h/m2 or EUR/m2; null when it cannot be stated. */
  value_unit?: string | null;
  /** Readings left out of the statistics, counted by reason. */
  excluded?: Record<string, number>;
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
  client?: string | null;
  region?: string | null;
  status?: string | null;
  project_type?: string | null;
}

export interface PerformanceBenchmarkResponse {
  kpi: string | null;
  spec: Record<string, unknown>;
  aggregation: string;
  projects_selected: number;
  projects: PerformanceProjectLabel[];
  groups: PerformanceGroup[];
  split_by?: string | null;
  reporting_currency?: string | null;
  /** Currencies left apart because the FX register has no rate for them. */
  currencies_unconverted?: string[];
  cost_index?: PerformanceCostIndex | null;
  /** Groups past the display cap, not returned. */
  groups_omitted?: number;
  /** Selected projects with no record for this KPI at all. */
  projects_without_data?: number;
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
  statuses: string[];
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

export interface PerformanceBenchmarkRequest extends BenchmarkCohort, BenchmarkReadingOptions, CostIndexRequest {
  kpi: string;
  /** A project attribute (client, region, ...) or a row field such as classification.din276. */
  split_by?: string | null;
  /** ISO code to restate money in with the FX register; null keeps every currency apart. */
  reporting_currency?: string | null;
}

export interface PerformanceCohortOptions {
  clients: string[];
  regions: string[];
  project_types: string[];
  statuses?: string[];
  /** The project attributes a benchmark can be split by. */
  project_splits?: string[];
}

export interface BenchmarkSet extends BenchmarkReadingOptions {
  id: string;
  name: string;
  description: string;
  owner_user_id: string | null;
  scope: 'personal' | 'shared';
  kpis: string[];
  cohort: BenchmarkCohort;
  split_by?: string | null;
  reporting_currency?: string | null;
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
  /** Empty string clears it on update. */
  split_by?: string | null;
  reporting_currency?: string | null;
}

export interface PerformanceCheckRequest extends PerformanceBenchmarkRequest {
  value: string;
  unit: string | null;
  currency: string | null;
  /** With a split, the group value the estimate is compared with. */
  split_value?: string | null;
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
  cost_index?: PerformanceCostIndex | null;
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
  statuses: [],
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
    (cohort.statuses?.length ? 1 : 0) +
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

/* ── Comparison, coverage, drilldown, position context ─────────────────── */

export interface PerformanceCompareRequest extends BenchmarkCohort, CostIndexRequest {
  kpis: string[];
  convert_units: boolean;
  min_projects: number;
  min_records: number;
  statistic: BenchmarkStatistic;
  reporting_currency?: string | null;
}

/** One column of the comparison: one KPI in one unit or currency group. */
export interface PerformanceCompareColumn {
  kpi: string;
  aggregation: string;
  group: PerformanceGroup;
}

export interface PerformanceCompareResponse {
  projects_selected: number;
  projects: PerformanceProjectLabel[];
  columns: PerformanceCompareColumn[];
  groups_omitted?: Record<string, number>;
  reporting_currency?: string | null;
  currencies_unconverted?: string[];
  statistic?: BenchmarkStatistic;
}

export interface PerformanceDataQualityRequest extends BenchmarkCohort {
  classification_key?: string | null;
}

/** How much of the cohort's data can feed a position benchmark. Shares are null, not 0, when the whole is 0. */
export interface PerformanceDataQuality {
  projects: number;
  hours_total: Decimalish;
  hours_linked: Decimalish;
  hours_linked_share: Decimalish;
  positions_total: number | null;
  positions_with_progress: number | null;
  progress_share: Decimalish;
  classification_key: string | null;
  positions_classified: number | null;
  classification_share: Decimalish;
}

export interface PerformanceDrilldownRequest extends CostIndexRequest {
  kpi: string;
  project_id: string;
  row_filters: KpiRowFilter[];
  period_start: string | null;
  period_end: string | null;
  split_by?: string | null;
  /** Group dimensions to match, each with every raw value that landed in the group. */
  dimensions: Record<string, (string | null)[]>;
  target_unit?: string | null;
  reporting_currency?: string | null;
  offset: number;
  limit: number;
}

export interface PerformanceDrillRecord {
  record_id: string;
  boq_id: string | null;
  position_id: string | null;
  ref: string;
  description: string;
  dimensions: Record<string, string | null>;
  numerator: Decimalish;
  denominator: Decimalish;
  /** The figures as counted in the group, after unit or currency conversion. */
  counted_numerator: Decimalish;
  counted_denominator: Decimalish;
  /** The cost index and location factor this record's money moved by. */
  index_factor?: Decimalish;
}

export interface PerformanceDrilldownResponse {
  project_id: string;
  kpi: string | null;
  aggregation: string;
  total_records: number;
  numerator: Decimalish;
  denominator: Decimalish;
  value: Decimalish;
  unavailable_reason: string | null;
  value_unit: string | null;
  offset: number;
  limit: number;
  records: PerformanceDrillRecord[];
}

export interface PerformancePositionContextItem {
  position_id: string;
  status: string;
  classification_code: string | null;
  unit: string | null;
  currency: string | null;
  estimate: Decimalish;
  value: Decimalish;
  value_unit: string | null;
  headline: Decimalish;
  statistic: BenchmarkStatistic | null;
  median: Decimalish;
  p25: Decimalish;
  p75: Decimalish;
  variance: Decimalish;
  percentile_rank: Decimalish;
  band: RangeBand | null;
  confidence: 'low' | 'medium' | 'high' | null;
  projects: number;
  records: number;
  shortfall: string[];
}

export interface PerformancePositionContextResponse {
  kpi: string;
  classification_key: string | null;
  items: PerformancePositionContextItem[];
}

export interface PerformancePositionContextRequest {
  position_ids: string[];
  kpi?: string;
  classification_key?: string | null;
}

export function fetchPerformanceCompare(body: PerformanceCompareRequest): Promise<PerformanceCompareResponse> {
  return apiPost<PerformanceCompareResponse, PerformanceCompareRequest>('/v1/bi-dashboards/performance/compare', body);
}

export function fetchDataQuality(body: PerformanceDataQualityRequest): Promise<PerformanceDataQuality> {
  return apiPost<PerformanceDataQuality, PerformanceDataQualityRequest>(
    '/v1/bi-dashboards/performance/data-quality',
    body,
  );
}

export function fetchDrilldown(body: PerformanceDrilldownRequest): Promise<PerformanceDrilldownResponse> {
  return apiPost<PerformanceDrilldownResponse, PerformanceDrilldownRequest>(
    '/v1/bi-dashboards/performance/drilldown',
    body,
  );
}

export function fetchPositionContext(
  body: PerformancePositionContextRequest,
): Promise<PerformancePositionContextResponse> {
  return apiPost<PerformancePositionContextResponse, PerformancePositionContextRequest>(
    '/v1/bi-dashboards/performance/position-context',
    body,
  );
}

/** Values a project's rows had before they landed in this group, per dimension, for the drilldown. */
export function drillDimensions(
  group: PerformanceGroup,
  row: PerformanceProjectRow,
): Record<string, (string | null)[]> {
  const out: Record<string, (string | null)[]> = {};
  for (const [name, value] of Object.entries(group.dimensions)) {
    const raw = value === NULL_GROUP_KEY ? null : value;
    const extra =
      name === 'unit' ? (row.converted_from ?? []) : name === 'currency' ? (row.converted_from_currency ?? []) : [];
    out[name] = Array.from(new Set([raw, ...extra]));
  }
  return out;
}

export type RowSort = 'name' | 'value_asc' | 'value_desc';

/** Rows sorted by name or by value; a row with no value always goes last. */
export function sortTableRows(
  rows: PerformanceTableRow[],
  sort: RowSort,
  byName: (a: string, b: string) => number,
): PerformanceTableRow[] {
  if (sort === 'name') return [...rows].sort((a, b) => byName(a.name, b.name));
  const dir = sort === 'value_asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = toNumber(a.row?.value);
    const vb = toNumber(b.row?.value);
    if (va === null && vb === null) return byName(a.name, b.name);
    if (va === null) return 1;
    if (vb === null) return -1;
    return va === vb ? byName(a.name, b.name) : (va - vb) * dir;
  });
}

export type MatrixCell = string | number | null;

export interface CompareMatrixLabels {
  project: string;
  client: string;
  region: string;
  status: string;
  /** Header text for one column. */
  column: (column: PerformanceCompareColumn) => string;
  /** First cell of the benchmark line. */
  benchmark: string;
}

/**
 * The comparison as a plain matrix: header, one line per project, then the
 * benchmark line. Values stay numbers (null when unavailable, never 0) so CSV
 * and Excel read them as numbers in any locale.
 */
export function buildCompareMatrix(data: PerformanceCompareResponse, labels: CompareMatrixLabels): MatrixCell[][] {
  const header: MatrixCell[] = [
    labels.project,
    labels.client,
    labels.region,
    labels.status,
    ...data.columns.map(labels.column),
  ];
  const byColumn = data.columns.map((c) => new Map(c.group.rows.map((r) => [r.project_id, toNumber(r.value)])));
  const lines: MatrixCell[][] = [header];
  for (const p of data.projects) {
    lines.push([
      p.name,
      p.client ?? '',
      p.region ?? '',
      p.status ?? '',
      ...byColumn.map((m) => m.get(p.project_id) ?? null),
    ]);
  }
  lines.push([
    labels.benchmark,
    '',
    '',
    '',
    ...data.columns.map((c) => toNumber(c.group.headline ?? c.group.benchmark.weighted)),
  ]);
  return lines;
}

export function matrixToCsv(matrix: MatrixCell[][]): string {
  return matrix.map((line) => line.map((cell) => csvCell(cell)).join(',')).join('\r\n');
}

/** The matrix as an .xlsx file. exceljs loads only on click, so it never weighs on the page. */
export async function downloadMatrixXlsx(matrix: MatrixCell[][], filename: string, sheetName: string): Promise<void> {
  const mod = await import('exceljs');
  const Ctor = (mod.Workbook ?? mod.default.Workbook) as typeof import('exceljs').Workbook;
  const wb = new Ctor();
  wb.creator = 'OpenConstructionERP';
  wb.created = new Date();
  const ws = wb.addWorksheet(sheetName.slice(0, 31) || 'Sheet1');
  for (const line of matrix) {
    // Text a spreadsheet would run as a formula is written as literal text.
    ws.addRow(line.map((cell) => (typeof cell === 'string' && /^[=+\-@\t\r\n]/.test(cell) ? `'${cell}` : cell)));
  }
  ws.getRow(1).font = { bold: true };
  ws.views = [{ state: 'frozen', xSplit: 1, ySplit: 1 }];
  ws.columns.forEach((col, i) => {
    col.width = i === 0 ? 36 : 16;
  });
  const buffer = await wb.xlsx.writeBuffer();
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
